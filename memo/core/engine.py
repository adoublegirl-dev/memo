"""记忆引擎总入口 —— 对外提供统一的记忆读写接口。

所有外部调用通过 Engine 进行，不直接访问底层 store。
"""

import json
import threading
import uuid
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from memo.core.config import config
from memo.models import (
    FeatureTag,
    MemoryType,
    MemoryUnit,
    RelationType,
    Session,
)
from memo.store.database import db
from memo.store.graph_store import graph_store
from memo.store.memory_store import memory_store
from memo.store.vector_store import vector_store
from memo.utils.embedding import embedding_model
from memo.utils.llm import llm_client
from memo.utils.logger import logger


class Engine:
    """Memo 记忆引擎。

    用法：
        engine = Engine()
        engine.init()  # 首次运行

        # 写入
        session = engine.start_session(title="排位赛开发")
        engine.remember(session_id=session.id, raw_text="...")

        # 检索
        results = engine.recall("ELO 算法怎么设计的？")

        # 生命周期
        engine.run_lifecycle()
    """

    def __init__(self):
        self._initialized = False
        self._history_worker_lock = threading.Lock()
        self._history_worker_thread: threading.Thread | None = None

    def init(self) -> None:
        """初始化：执行数据库迁移、加载向量索引。"""
        if self._initialized:
            return

        db.init()
        vector_store.load_all()
        self._initialized = True
        logger.info("Memo 引擎初始化完成")

    # ── 会话 ──

    def start_session(
        self,
        title: str = "",
        agent_id: str = "ASH",
        space_id: str | None = None,
    ) -> Session:
        """开始新会话。"""
        self._ensure_init()
        return memory_store.create_session(agent_id=agent_id, title=title, space_id=space_id)

    def end_session(self, session_id: str) -> None:
        """结束会话。"""
        memory_store.end_session(session_id)

    # ── 记忆写入（核心） ──

    def remember(
        self,
        session_id: str,
        raw_text: str,
        title: str = "",
        summary: str = "",
        summary_detail: str = "",
        memory_type: MemoryType = MemoryType.FACT,
        confidence: float = 0.8,
        feature_tags: list[str] | None = None,
        tag_relations: list[dict[str, str]] | None = None,
        space_id: str | None = None,
    ) -> str:
        """写入一条记忆。

        自动完成：向量编码、特征词创建/激活、关系建立。

        Args:
            session_id: 会话 ID
            raw_text: 原文
            title: 标题（不提供则自动生成）
            summary: 一级摘要
            summary_detail: 二级摘要
            memory_type: 记忆类型
            confidence: 置信度
            feature_tags: 手动指定特征词列表
            tag_relations: 手动指定特征词关系 [{"from": "A", "to": "B", "type": "CO_OCCUR"}, ...]

        Returns:
            记忆单元 ID
        """
        self._ensure_init()

        # 自动生成标题
        if not title:
            title = self._auto_title(raw_text)

        # 写入记忆单元（手动模式 signal_level=L2）。显式手动记忆不自动跳过，但记录指纹供后续去重。
        memory_id = memory_store.add_memory(
            session_id=session_id,
            title=title,
            summary=summary,
            summary_detail=summary_detail,
            raw_text=raw_text,
            memory_type=memory_type,
            confidence=confidence,
            signal_level=2,  # 显式手动
        )

        # 编码向量
        text_for_embedding = f"{title} {summary} {raw_text[:500]}"
        vector_store.add_memory(memory_id, text_for_embedding)

        # 处理特征词：创建 + 激活 + 建立关联
        tag_ids: list[str] = []
        if feature_tags:
            for tag_name in feature_tags:
                emb = embedding_model.encode(tag_name)
                tag = graph_store.get_or_create_tag(name=tag_name, embedding=emb)
                tag_ids.append(tag.id)
                graph_store.activate_tag(tag.id, increment=0.02)  # L2 显式记忆额外加成
                graph_store.create_mention(
                    tag_id=tag.id,
                    memory_unit_id=memory_id,
                    mention_type="DIRECT",
                    relevance_score=0.8,
                )

        # 建立特征词间关系（赫布权重更新）
        if tag_relations:
            self._process_tag_relations(tag_relations, session_id=session_id)

        # 同一条记忆中出现的特征词默认建立 CO_OCCUR 关系
        for i in range(len(tag_ids)):
            for j in range(i + 1, len(tag_ids)):
                a, b = tag_ids[i], tag_ids[j]
                sim = embedding_model.cosine_similarity(
                    embedding_model.encode(graph_store.get_tag(a).name),
                    embedding_model.encode(graph_store.get_tag(b).name),
                ) if graph_store.get_tag(a) and graph_store.get_tag(b) else 0.2
                graph_store.upsert_relation(
                    source_id=a,
                    target_id=b,
                    relation_type=RelationType.CO_OCCUR,
                    semantic_similarity=sim,
                    session_id=session_id,
                )

        try:
            from memo.dedupe import record_created
            record_created(memory_id, raw_text, title, summary, session_id=session_id)
        except Exception as e:
            logger.debug(f"手动记忆去重指纹记录失败: {e}")

        if space_id:
            self.space_bind_memory(
                space_id=space_id,
                memory_id=memory_id,
                relation_type="related",
                relevance=0.9,
                created_by="manual",
            )

        logger.info(f"记忆已写入: {title[:30]} ({memory_id[:8]})")
        return memory_id

    def _process_tag_relations(self, relations: list[dict[str, str]], session_id: str = "") -> None:
        """处理手动指定的特征词关系。"""
        for rel in relations:
            source_tag = graph_store.get_or_create_tag(name=rel["from"])
            target_tag = graph_store.get_or_create_tag(name=rel["to"])
            rel_type = RelationType(rel.get("type", "CO_OCCUR"))
            sim = 0.5
            if source_tag.embedding is not None and target_tag.embedding is not None:
                sim = embedding_model.cosine_similarity(
                    source_tag.embedding, target_tag.embedding
                )
            graph_store.upsert_relation(
                source_id=source_tag.id,
                target_id=target_tag.id,
                relation_type=rel_type,
                semantic_similarity=sim,
                                session_id=session_id,
                )

    def _auto_title(self, raw_text: str) -> str:
        """自动生成标题：取第一句话或前 50 个字符。"""
        text = raw_text.strip()
        # 取第一句（遇到句号、换行截断）
        for sep in ["。", "\n", ". "]:
            if sep in text:
                text = text.split(sep)[0]
                break
        return text[:80] + ("..." if len(text) > 80 else "")

    # ── 对话记忆自动写入（Phase 1 核心） ──

    def remember_conversation(
        self,
        session_id: str,
        conversation: str,
        auto_extract: bool = True,
        context_rounds: int = 3,
        skip_gating: bool = False,
        skip_cas: bool = False,
        space_id: str | None = None,
    ) -> dict[str, Any]:
        """从一段对话中自动提取并写入记忆。

        完整管道：对话 → [MVG 门控] → 上下文回顾 → LLM 提取（或 jieba 降级）
                → 特征词创建/激活 → 关系建立 → 冲突检测 → 向量编码 → 写入

        Args:
            session_id: 会话 ID
            conversation: 对话文本（可用 "User: ...\\nAssistant: ..." 格式）
            auto_extract: 是否自动调用 LLM 提取（False 则仅做 jieba 提取）
            context_rounds: 回顾同会话最近 N 轮对话原文，供 LLM 判断关联（默认 3）
            skip_gating: 是否跳过 MVG 门控（手动调用时设为 True，避免额外开销）

        Returns:
            {
                "memory_id": str | None,  # 被门控跳过时为 None
                "title": str,
                "feature_tags": [str, ...],
                "conflicts_found": [str, ...],
                "extraction_method": "llm" | "jieba",
                "gating_result": dict | None,
            }
        """
        self._ensure_init()

        source_agent = ""
        if session_id:
            row = db.fetchone("SELECT agent_id FROM sessions WHERE id = ?", (session_id,))
            source_agent = row["agent_id"] if row else ""

        # Step -2: ingestion 事件闸门，避免 watcher/import/MCP 重试重复处理同一输入。
        try:
            from memo.dedupe import check_ingestion, record_ingestion
            ingestion = check_ingestion(
                conversation,
                source_type="memo_remember",
                source_agent=source_agent,
                source_session_id=session_id,
            )
            if ingestion.get("duplicate"):
                record_ingestion(
                    conversation,
                    source_type="memo_remember",
                    source_agent=source_agent,
                    source_session_id=session_id,
                    processed_memory_id=ingestion.get("processed_memory_id"),
                    status="skipped",
                    reason=ingestion.get("reason", "ingestion_duplicate"),
                    metadata=ingestion,
                )
                logger.info(f"ingestion 去重跳过: {ingestion.get('reason')}")
                return {
                    "memory_id": None,
                    "title": "",
                    "feature_tags": [],
                    "conflicts_found": [],
                    "extraction_method": "ingestion_skipped",
                    "gating_result": {"reason": ingestion.get("reason", "ingestion_duplicate"), "verdict": "skip", "total_score": 0},
                    "dedupe_result": ingestion,
                }
        except Exception as e:
            logger.debug(f"ingestion 去重检查失败，继续写入: {e}")

        # Step -1: 入库前 exact / structured 去重，尽量避免无意义 LLM 调用。
        try:
            from memo.dedupe import check_before_extract, record_skipped
            pre_dedupe = check_before_extract(conversation, session_id=session_id, source_agent=source_agent)
            if pre_dedupe.should_skip:
                record_skipped(pre_dedupe, session_id=session_id, source_agent=source_agent)
                logger.info(f"去重跳过: {pre_dedupe.reason} -> {pre_dedupe.existing_memory_id}")
                return {
                    "memory_id": None,
                    "title": "",
                    "feature_tags": [],
                    "conflicts_found": [],
                    "extraction_method": "dedupe_skipped",
                    "gating_result": {"reason": pre_dedupe.reason, "verdict": "skip", "total_score": 0},
                    "dedupe_result": pre_dedupe.as_dict(),
                }
        except Exception as e:
            logger.debug(f"入库前去重检查失败，继续写入: {e}")

        # Step 0: MVG 记忆价值门控
        gating_result = None
        if not skip_gating:
            from memo.extraction.gating import evaluate_importance
            gating_result = evaluate_importance(conversation)
            if gating_result["verdict"] == "skip":
                logger.info(
                    f"MVG 跳过: {gating_result['reason']} "
                    f"(score={gating_result['total_score']})"
                )
                return {
                    "memory_id": None,
                    "title": "",
                    "feature_tags": [],
                    "conflicts_found": [],
                    "extraction_method": "skipped",
                    "gating_result": gating_result,
                }

        # Step 0: 回顾上下文（同会话最近的记忆原文）
        context_texts: list[str] = []
        if context_rounds > 0 and session_id:
            recent_memories = memory_store.get_session_memories(session_id)
            recent_memories.sort(key=lambda m: m.created_at, reverse=True)
            context_texts = [m.raw_text for m in recent_memories[:context_rounds]]
            context_texts.reverse()  # 时间正序

        # Step 1: 提取
        from memo.extraction.extractor import (
            extract_from_conversation,
            extract_conflicts_with_llm,
        )

        # 获取已有特征词作为上下文
        hot_tags = graph_store.get_hot_tags(limit=30)
        existing_tag_names = [t.name for t in hot_tags]

        if auto_extract:
            extracted = extract_from_conversation(
                conversation, existing_tag_names, context_texts
            )
            extraction_method = "llm" if llm_client.available else "jieba"
        else:
            extracted = extract_from_conversation.__wrapped__ if hasattr(
                extract_from_conversation, "__wrapped__"
            ) else None
            if extracted is None:
                from memo.extraction.extractor import _jieba_extract
                extracted = _jieba_extract(conversation)
            extraction_method = "jieba"

        # Step 1.5: 提取后按事实 key / title-summary 做近重复检查。
        try:
            from memo.dedupe import check_after_extract, record_skipped
            post_dedupe = check_after_extract(
                conversation,
                extracted.get("title", ""),
                extracted.get("summary", ""),
                extracted.get("memory_type", ""),
            )
            if post_dedupe.should_skip:
                record_skipped(post_dedupe, session_id=session_id, source_agent=source_agent)
                logger.info(f"去重跳过: {post_dedupe.reason} -> {post_dedupe.existing_memory_id}")
                return {
                    "memory_id": None,
                    "title": extracted.get("title", ""),
                    "feature_tags": [],
                    "conflicts_found": [],
                    "extraction_method": "dedupe_skipped",
                    "gating_result": {"reason": post_dedupe.reason, "verdict": "skip", "total_score": 0},
                    "dedupe_result": post_dedupe.as_dict(),
                }
        except Exception as e:
            logger.debug(f"提取后去重检查失败，继续写入: {e}")

        # Step 2: 写入记忆单元（灰色地带降低置信度，MVG 高分提升 signal_level）
        mem_confidence = 0.5 if (gating_result and gating_result["verdict"] == "gray") else 0.85
        mem_signal = 0  # L0 普通自动
        if gating_result:
            if gating_result["total_score"] >= 4.0:
                mem_signal = 1  # L1 高价值自动
        memory_id = memory_store.add_memory(
            session_id=session_id,
            title=extracted["title"],
            summary=extracted["summary"],
            summary_detail=extracted["summary_detail"],
            raw_text=conversation,
            memory_type=MemoryType(extracted.get("memory_type", "FACT")),
            confidence=mem_confidence,
            signal_level=mem_signal,
        )

        try:
            from memo.dedupe import record_created, record_ingestion
            record_created(
                memory_id,
                conversation,
                extracted.get("title", ""),
                extracted.get("summary", ""),
                session_id=session_id,
                source_agent=source_agent,
            )
            record_ingestion(
                conversation,
                source_type="memo_remember",
                source_agent=source_agent,
                source_session_id=session_id,
                processed_memory_id=memory_id,
                status="processed",
                reason="created",
            )
        except Exception as e:
            logger.debug(f"记忆去重/ingestion 指纹记录失败: {e}")

        # Step 3: 向量编码
        text_for_embedding = f"{extracted['title']} {extracted['summary']} {conversation[:500]}"
        vector_store.add_memory(memory_id, text_for_embedding)

        # Step 4: 特征词处理
        tag_ids: list[str] = []
        tag_names: list[str] = []
        for tag_info in extracted.get("feature_tags", []):
            name = tag_info["name"]
            category = tag_info.get("category", "CONCEPT")
            if not name or len(name) < 2:
                continue
            emb = embedding_model.encode(name)
            tag = graph_store.get_or_create_tag(name=name, category=category, embedding=emb)
            tag_ids.append(tag.id)
            tag_names.append(name)
            graph_store.activate_tag(tag.id)
            graph_store.create_mention(
                tag_id=tag.id,
                memory_unit_id=memory_id,
                mention_type="DIRECT",
                relevance_score=0.85,
            )

        # Step 5: 建立特征词关系
        for rel in extracted.get("relations", []):
            from_name = rel.get("from", "")
            to_name = rel.get("to", "")
            rel_type = RelationType(rel.get("type", "CO_OCCUR"))
            if from_name in tag_names and to_name in tag_names:
                from_idx = tag_names.index(from_name)
                to_idx = tag_names.index(to_name)
                a, b = tag_ids[from_idx], tag_ids[to_idx]
                tag_a = graph_store.get_tag(a)
                tag_b = graph_store.get_tag(b)
                sim = 0.5
                if tag_a and tag_b and tag_a.embedding is not None and tag_b.embedding is not None:
                    sim = embedding_model.cosine_similarity(tag_a.embedding, tag_b.embedding)
                graph_store.upsert_relation(
                    source_id=a, target_id=b,
                    relation_type=rel_type,
                    semantic_similarity=sim,
                                    session_id=session_id,
                )

        # 同记忆内所有特征词建立 CO_OCCUR 关系
        for i in range(len(tag_ids)):
            for j in range(i + 1, len(tag_ids)):
                a, b = tag_ids[i], tag_ids[j]
                tag_a = graph_store.get_tag(a)
                tag_b = graph_store.get_tag(b)
                sim = 0.3
                if tag_a and tag_b and tag_a.embedding is not None and tag_b.embedding is not None:
                    sim = embedding_model.cosine_similarity(tag_a.embedding, tag_b.embedding)
                graph_store.upsert_relation(
                    source_id=a, target_id=b,
                    relation_type=RelationType.CO_OCCUR,
                    semantic_similarity=sim,
                                    session_id=session_id,
                )

        # Step 6: CAS 变更检测（导入批量可跳过，后续统一扫描更高效）
        conflicts: list[str] = []
        if not skip_cas:
            from memo.extraction.change_detector import detect_change, apply_changes

            changes = detect_change(
                new_memory_id=memory_id,
                new_title=extracted["title"],
                new_summary=extracted["summary"],
            )
            if changes["superseded"] or changes["refined"]:
                apply_result = apply_changes(memory_id, changes)
                conflicts = changes["superseded"]

        # 兼容旧 is_update_of 机制：如果 LLM 提取阶段就识别了显式推翻
        is_update = extracted.get("is_update_of")
        if is_update and not conflicts:
            similar = self.recall(" ".join(is_update), top_k=5)
            existing = [
                {"id": m["id"], "title": m["title"], "summary": m["summary"]}
                for m in similar
            ]
            conflicts = extract_conflicts_with_llm(
                extracted["summary"], existing
            )
            for old_id in conflicts:
                memory_store.supersede_memory(old_id, memory_id)
                logger.info(f"冲突解决（is_update_of）: 旧记忆 {old_id[:8]} 被 {memory_id[:8]} 替代")

        bound_spaces: list[dict[str, Any]] = []
        try:
            if space_id:
                bound_spaces.append(self.space_bind_memory(
                    space_id=space_id,
                    memory_id=memory_id,
                    relation_type=extracted.get("memory_type", "related").lower(),
                    relevance=0.9,
                    created_by="explicit",
                ))
                db.execute(
                    "UPDATE sessions SET space_id = COALESCE(space_id, ?) WHERE id = ?",
                    (space_id, session_id),
                )
                db.commit()
            else:
                for candidate in self.space_detect(conversation, top_k=2):
                    if candidate.get("confidence", 0) >= 0.8:
                        bound_spaces.append(self.space_bind_memory(
                            space_id=candidate["space_id"],
                            memory_id=memory_id,
                            relation_type=extracted.get("memory_type", "related").lower(),
                            relevance=candidate.get("confidence", 0.8),
                            created_by="auto",
                        ))
        except Exception as e:
            logger.warning(f"Space 自动绑定失败: {e}")

        logger.info(
            f"对话记忆已写入: {extracted['title'][:30]} ({memory_id[:8]}), "
            f"{len(tag_names)} 特征词, {len(conflicts)} 冲突"
        )

        return {
            "memory_id": memory_id,
            "title": extracted["title"],
            "feature_tags": tag_names,
            "conflicts_found": conflicts,
            "extraction_method": extraction_method,
            "context_rounds_used": len(context_texts),
            "gating_result": gating_result,
            "bound_spaces": bound_spaces,
        }

    # ── 记忆检索（核心） ──

    def recall(
        self,
        query: str,
        top_k: int | None = None,
        current_session_id: str | None = None,
        space_id: str | None = None,
        space_mode: str = "boost",
    ) -> list[dict[str, Any]]:
        """三通道混合检索。

        通道① 向量语义 → 通道② BM25 全文 → 通道③ 图扩散 → RRF 融合 → Top-K

        Args:
            query: 查询文本
            top_k: 返回数量（默认 config.top_k_retrieval）
            current_session_id: 当前会话 ID（结果中会标记是否来自当前会话）

        Returns:
            [{"id": ..., "title": ..., "summary": ..., "score": ..., "source": "vector|bm25|graph|fused", ...}, ...]
        """
        self._ensure_init()
        top_k = top_k or config.top_k_retrieval

        # 通道①
        vec_results = self._channel_vector(query, top_k=20)
        # 通道②
        bm25_results = self._channel_bm25(query, top_k=20)
        # 通道③
        graph_results = self._channel_graph(query, top_k=20, current_session_id=current_session_id, space_id=space_id)

        # RRF 融合。Space within/boost 需要更大的候选池，避免先截断导致空间内结果被丢弃。
        fused_limit = max(top_k * 5, 30) if space_id else top_k
        fused = self._rrf_fuse(vec_results, bm25_results, graph_results, top_k=fused_limit)

        space_memory_ids: set[str] = set()
        if space_id:
            resolved_space = self.space_get(space_id)
            if resolved_space:
                space_id = resolved_space["id"]
                rows = db.fetchall("SELECT memory_id FROM space_memories WHERE space_id = ?", (space_id,))
                space_memory_ids = {r["memory_id"] for r in rows}

        # 补充记忆单元详情
        enriched = []
        for mem_id, score in fused:
            if space_mode == "within" and space_id and mem_id not in space_memory_ids:
                continue
            mem = memory_store.get_memory(mem_id)
            if mem and not mem.is_superseded and getattr(mem, "status", "active") not in {"wrong", "muted", "deleted"}:
                # ESA 信号加权 + 用户治理权重
                signal_multiplier = {0: 0.7, 1: 1.0, 2: 1.5}
                status_multiplier = {"active": 1.0, "expired": 0.25}.get(getattr(mem, "status", "active"), 1.0)
                adjusted_score = score * signal_multiplier.get(mem.signal_level, 1.0) * getattr(mem, "user_weight", 1.0) * status_multiplier
                if getattr(mem, "pinned", False):
                    adjusted_score *= 1.25
                from_current_space = bool(space_id and mem_id in space_memory_ids)
                if from_current_space and space_mode == "boost":
                    adjusted_score *= 1.25
                    if mem.memory_type == "DECISION":
                        adjusted_score *= 1.08
                # 获取关联特征词
                tags = graph_store.get_memory_tags(mem_id)
                explanation_reasons = []
                if tags:
                    explanation_reasons.append("和当前问题相关的关键词包括：" + "、".join([t.name for t in tags[:5]]))
                if mem.signal_level >= 2:
                    explanation_reasons.append("这是一条被明确沉淀过的重要记忆，所以更容易被想起")
                elif mem.signal_level == 1:
                    explanation_reasons.append("这条记忆有一定稳定性，可作为当前上下文参考")
                else:
                    explanation_reasons.append("这条记忆来自自动捕捉，排序时会更谨慎")
                if getattr(mem, "pinned", False):
                    explanation_reasons.append("你已经把它标为重要，因此会优先保留")
                if getattr(mem, "status", "active") == "expired":
                    explanation_reasons.append("它已被标记为过期，只会低权重参考")
                quality_gate = self._memory_quality_gate(mem_id)
                if not quality_gate["participates"]:
                    continue
                adjusted_score *= quality_gate["score_multiplier"]
                explanation_reasons.extend(quality_gate["reasons"])
                if from_current_space:
                    explanation_reasons.append("它属于当前 Space，和当前工作场景更接近")
                if current_session_id and mem.session_id == current_session_id:
                    explanation_reasons.append("它来自当前会话，时间和语境都更近")
                user_weight = getattr(mem, "user_weight", 1.0)
                if user_weight > 1.0:
                    explanation_reasons.append("你提高过这条记忆的权重")
                elif user_weight < 1.0:
                    explanation_reasons.append("你降低过这条记忆的权重")

                enriched.append({
                    "id": mem.id,
                    "title": mem.title,
                    "summary": mem.summary,
                    "summary_detail": mem.summary_detail,
                    "raw_text": mem.raw_text,
                    "score": round(adjusted_score, 4),
                    "raw_score": round(score, 4),
                    "memory_type": mem.memory_type if isinstance(mem.memory_type, str) else mem.memory_type.value,
                    "confidence": mem.confidence,
                    "signal_level": mem.signal_level,
                    "status": getattr(mem, "status", "active"),
                    "user_weight": getattr(mem, "user_weight", 1.0),
                    "pinned": getattr(mem, "pinned", False),
                    "user_note": getattr(mem, "user_note", ""),
                    "feature_tags": [t.name for t in tags],
                    "session_id": mem.session_id,
                    "from_current_session": (
                        mem.session_id == current_session_id
                        if current_session_id
                        else False
                    ),
                    "from_current_space": from_current_space,
                    "space_id": space_id if from_current_space else "",
                    "valid_from": mem.valid_from,
                    "explanation": {
                        "summary": "这条记忆和当前问题的语义、关键词或所在空间有关，因此被优先想起。",
                        "reasons": explanation_reasons,
                        "participates": True,
                        "raw_score": round(score, 4),
                        "final_score": round(adjusted_score, 4),
                        "signal_level": mem.signal_level,
                        "status_multiplier": status_multiplier,
                        "user_weight": user_weight,
                        "pinned": getattr(mem, "pinned", False),
                        "from_current_space": from_current_space,
                        "from_current_session": mem.session_id == current_session_id if current_session_id else False,
                        "quality_review": quality_gate.get("review"),
                    },
                })

        enriched.sort(key=lambda x: x["score"], reverse=True)
        return enriched[:top_k]

    def _memory_quality_gate(self, memory_id: str) -> dict[str, Any]:
        """规则质量处理的召回闸门。只影响排序/默认参与，不删除原始记忆。"""
        try:
            row = db.fetchone("SELECT review_status, retention_class, recall_policy, quality_score, auto_flags_json FROM memory_quality_reviews WHERE memory_id=?", (memory_id,))
        except Exception:
            row = None
        if not row:
            return {"participates": True, "score_multiplier": 1.0, "reasons": [], "review": None}
        review = dict(row)
        policy = review.get("recall_policy") or "include"
        retention = review.get("retention_class") or "candidate"
        if policy in {"exclude", "exclude_default"}:
            return {
                "participates": False,
                "score_multiplier": 0.0,
                "reasons": [f"这条记忆已被规则处理标记为 {retention}，默认不参与召回"],
                "review": review,
            }
        multiplier = 1.0
        reasons: list[str] = []
        if policy == "downrank":
            multiplier *= 0.45
            reasons.append("这条记忆被规则标记为候选重复或需复核，召回时会降权")
        score = float(review.get("quality_score") or 0.5)
        multiplier *= max(0.25, min(1.2, 0.5 + score))
        if retention == "long_term":
            reasons.append("这条记忆已通过规则处理，暂定为可进入长期召回")
        return {"participates": True, "score_multiplier": multiplier, "reasons": reasons, "review": review}

    def _channel_vector(self, query: str, top_k: int = 20) -> dict[str, float]:
        """通道①：向量语义检索。"""
        results = vector_store.search(query, top_k=top_k)
        # 过滤掉特征词结果，只保留记忆单元
        return {mem_id: score for mem_id, score in results if not mem_id.startswith("tag:")}

    def _channel_bm25(self, query: str, top_k: int = 20) -> dict[str, float]:
        """通道②：BM25 全文检索（SQLite FTS5）。"""
        try:
            # FTS5 简单查询
            rows = db.fetchall(
                """SELECT mu.id, memory_fts.rank AS score
                   FROM memory_fts
                   JOIN memory_units mu ON mu.rowid = memory_fts.rowid
                   WHERE memory_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, top_k),
            )
            # FTS5 rank 是越小越好，转换为分数
            max_rank = max((r["score"] for r in rows), default=1)
            return {
                r["id"]: 1.0 - (r["score"] / (max_rank * 2 + 1))
                for r in rows
                if not memory_store.get_memory(r["id"]) or not memory_store.get_memory(r["id"]).is_superseded
            }
        except Exception as e:
            logger.debug(f"BM25 检索异常（可能是 FTS5 语法问题）: {e}")
            return {}

    def _channel_graph(self, query: str, top_k: int = 20, current_session_id: str | None = None, space_id: str | None = None) -> dict[str, float]:
        """通道③：图扩散激活检索。Space 存在时，在扩散入口和记忆落点都加入软偏置。"""
        from memo.retrieval.graph_search import graph_search

        return graph_search.spreading_activation(query, top_k=top_k, current_session_id=current_session_id, space_id=space_id)

    def _rrf_fuse(
        self,
        vec: dict[str, float],
        bm25: dict[str, float],
        graph: dict[str, float],
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """RRF 融合三个通道的结果。"""
        from memo.retrieval.fusion import rrf_fuse

        return rrf_fuse(vec, bm25, graph, top_k=top_k)

    # ── 生命周期 ──

    def run_lifecycle(self) -> dict[str, Any]:
        """执行一次完整的生命周期维护。

        包含：遗忘衰减 + 固化检查 + CAS 扫描 + 快照检查 + 人格增量更新。
        """
        self._ensure_init()
        report = {}

        # 1. 遗忘衰减
        report["forgetting"] = self._run_forgetting()

        # 2. 固化检查
        report["consolidation"] = self._run_consolidation_check()

        # 3. CAS L2 变更扫描
        from memo.extraction.change_detector import scan_conflicts_batch
        report["change_scan"] = scan_conflicts_batch(
            min_similarity=config.change_similarity_threshold,
        )

        # 4. 快照检查
        report["snapshot"] = self._run_snapshot_check()

        # 5. 人格增量更新
        report["persona"] = self._run_persona_incremental()

        logger.info(f"生命周期完成: {report}")
        return report

    # ── 人格引擎 ──

    def build_persona_baseline(self, reset_existing: bool = False) -> dict[str, Any]:
        """批量建人格基线。

        采样 L2+L1+高价值 L0 记忆 → 10 维逐维提炼 → 初始断言。
        reset_existing=True 时用于 Dashboard 的“重建人格基线”：先生成新断言，成功后归档旧系统断言。
        """
        self._ensure_init()
        from memo.persona.extractor import build_persona_baseline as _build
        return _build(reset_existing=reset_existing)

    def update_persona(self) -> dict[str, Any]:
        """增量更新人格断言。"""
        self._ensure_init()
        from memo.persona.extractor import update_persona_incremental
        return update_persona_incremental()

    def persona_ask(self, question: str) -> dict[str, Any]:
        """人格路由问答。

        自动判断问题走人格通道/混合通道/经验通道，返回人格化回复。
        """
        self._ensure_init()
        from memo.persona.router import route, build_persona_reply
        route_result = route(question)
        reply = build_persona_reply(question, route_result)
        return reply

    def persona_profile(self, dimension: str | None = None) -> list[dict]:
        """获取人格画像。"""
        self._ensure_init()
        from memo.persona.extractor import get_active_assertions
        return get_active_assertions(dimension)

    def persona_assertion_action(self, assertion_id: str, action: str, **kwargs) -> dict[str, Any]:
        """人格断言治理操作：编辑、锁定、删除、恢复。"""
        self._ensure_init()
        from memo.persona.extractor import persona_assertion_action
        return persona_assertion_action(assertion_id, action, **kwargs)

    def persona_audit(self, assertion_id: str = "", limit: int = 50) -> list[dict]:
        """获取人格断言审计日志。"""
        self._ensure_init()
        from memo.persona.extractor import get_persona_audit
        return get_persona_audit(assertion_id, limit=limit)

    def _run_persona_incremental(self) -> dict[str, Any]:
        """生命周期内的人格增量更新。"""
        try:
            from memo.persona.extractor import update_persona_incremental, get_persona_settings
            settings = get_persona_settings()
            last = settings.get("last_incremental_at", "")
            if not last:
                # 还没有基线，检查是否应该建基线
                total = db.fetchone("SELECT COUNT(*) as cnt FROM memory_units WHERE is_superseded = 0")
                if total["cnt"] >= 10:
                    return self.build_persona_baseline()
                return {"status": "skipped", "reason": "记忆数不足，暂不建基线"}
            return update_persona_incremental()
        except Exception as e:
            logger.warning(f"人格增量更新异常: {e}")
            return {"status": "error", "reason": str(e)}

    def _run_forgetting(self) -> dict[str, Any]:
        """执行遗忘衰减。"""
        from memo.lifecycle.forgetting import run_forgetting

        return run_forgetting()

    def _run_consolidation_check(self) -> dict[str, Any]:
        """检查是否需要固化。"""
        from memo.lifecycle.consolidation import check_and_consolidate

        return check_and_consolidate()

    def _run_snapshot_check(self) -> dict[str, Any]:
        """检查是否需要生成快照。"""
        from memo.lifecycle.snapshot import check_and_snapshot

        return check_and_snapshot()

    # ── 辅助 ──

    def _ensure_init(self) -> None:
        if not self._initialized:
            self.init()

    # ── Context Space ──

    def space_create(self, **kwargs) -> dict:
        """创建上下文空间。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        return space_manager.create(**kwargs)

    def space_list(self, include_archived: bool = False, type: str = "") -> list[dict]:
        """列出上下文空间。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        return space_manager.list(include_archived=include_archived, type=type)

    def space_get(self, space_id: str) -> dict | None:
        """按 id/name/alias 获取上下文空间。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        return space_manager.resolve(space_id)

    def space_update(self, space_id: str, **kwargs) -> dict:
        """更新上下文空间。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        return space_manager.update(space_id, **kwargs)

    def space_detect(self, conversation: str, top_k: int = 3) -> list[dict]:
        """检测对话可能所属的上下文空间。"""
        self._ensure_init()
        from memo.space.detector import space_detector
        return space_detector.detect(conversation, top_k=top_k)

    def space_bind_memory(
        self,
        space_id: str,
        memory_id: str,
        relation_type: str = "related",
        relevance: float = 0.8,
        created_by: str = "auto",
    ) -> dict:
        """绑定记忆到上下文空间。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        return space_manager.bind_memory(space_id, memory_id, relation_type, relevance, created_by)

    def space_unbind_memory(self, space_id: str, memory_id: str) -> dict:
        """从上下文空间解绑记忆。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        return space_manager.unbind_memory(space_id, memory_id)

    def space_archive(self, space_id: str) -> dict:
        """归档上下文空间。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        return space_manager.archive(space_id)

    def space_restore(self, space_id: str) -> dict:
        """恢复已归档上下文空间。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        return space_manager.restore(space_id)

    def space_aliases(self, space_id: str) -> list[str]:
        """列出 Space 别名。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        return space_manager.aliases(space_id)

    def space_add_alias(self, space_id: str, alias: str) -> dict:
        """新增 Space 别名。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        space = space_manager.resolve(space_id)
        if not space:
            return {"error": "space not found"}
        space_manager.add_alias(space["id"], alias)
        return {"space_id": space["id"], "alias": alias, "added": True}

    def space_remove_alias(self, space_id: str, alias: str) -> dict:
        """删除 Space 别名。"""
        self._ensure_init()
        from memo.space.manager import space_manager
        return space_manager.remove_alias(space_id, alias)

    def space_profile(self, space_id: str, mode: str = "brief", persist: bool = False) -> dict:
        """获取空间简报。"""
        self._ensure_init()
        from memo.space.summarizer import space_summarizer
        return space_summarizer.summarize(space_id, mode=mode, persist=persist)

    def space_recall(self, space_id: str, query: str, top_k: int | None = None, mode: str = "boost") -> list[dict]:
        """在空间语境下检索记忆。"""
        self._ensure_init()
        return self.recall(query=query, top_k=top_k, space_id=space_id, space_mode=mode)

    def space_candidate_scan(self, limit: int = 80, min_memories: int = 1, use_llm: bool = False) -> dict:
        """从历史会话扫描候选 Space。只生成候选，不自动创建正式 Space。"""
        self._ensure_init()
        from memo.space.candidates import space_candidate_manager
        return space_candidate_manager.scan(limit=limit, min_memories=min_memories, use_llm=use_llm)

    def space_candidate_list(self, status: str = "pending", limit: int = 50) -> list[dict]:
        """列出候选 Space。"""
        self._ensure_init()
        from memo.space.candidates import space_candidate_manager
        return space_candidate_manager.list(status=status, limit=limit)

    def space_candidate_get(self, candidate_id: str) -> dict | None:
        """获取候选 Space 详情与来源证据。"""
        self._ensure_init()
        from memo.space.candidates import space_candidate_manager
        return space_candidate_manager.get(candidate_id)

    def space_candidate_accept(self, candidate_id: str, **kwargs) -> dict:
        """手动确认候选为新 Space。"""
        self._ensure_init()
        from memo.space.candidates import space_candidate_manager
        return space_candidate_manager.accept(candidate_id, **kwargs)

    def space_candidate_merge_to_space(self, candidate_id: str, space_id: str, actor: str = "dashboard") -> dict:
        """手动将候选合并到已有 Space。"""
        self._ensure_init()
        from memo.space.candidates import space_candidate_manager
        return space_candidate_manager.merge_to_space(candidate_id, space_id=space_id, actor=actor)

    def space_candidate_merge_many(self, candidate_ids: list[str], name: str, type: str = "project", description: str = "", actor: str = "dashboard") -> dict:
        """手动将多个候选合并为一个新 Space。"""
        self._ensure_init()
        from memo.space.candidates import space_candidate_manager
        return space_candidate_manager.merge_many(candidate_ids=candidate_ids, name=name, type=type, description=description, actor=actor)

    def space_candidate_ignore(self, candidate_id: str, note: str = "", actor: str = "dashboard") -> dict:
        """忽略候选 Space。"""
        self._ensure_init()
        from memo.space.candidates import space_candidate_manager
        return space_candidate_manager.ignore(candidate_id, note=note, actor=actor)

    def space_candidate_refresh_display_titles(self, limit: int = 500) -> dict:
        """刷新候选项目里的来源会话展示名，不修改记忆本体。"""
        self._ensure_init()
        from memo.space.candidates import space_candidate_manager
        return space_candidate_manager.refresh_display_titles(limit=limit)

    # ── 来源会话层 ──

    def source_session_backfill(self, limit: int = 200) -> dict:
        """渐进式为既有 memo.sessions 建立 source_sessions 来源索引。"""
        self._ensure_init()
        from memo.space.source_sessions import source_session_manager
        return source_session_manager.backfill_from_sessions(limit=limit)

    def source_session_list(self, limit: int = 50, source_type: str = "", source_agent: str = "") -> list[dict]:
        """列出来源会话。"""
        self._ensure_init()
        from memo.space.source_sessions import source_session_manager
        return source_session_manager.list(limit=limit, source_type=source_type, source_agent=source_agent)

    def source_session_get(self, source_session_id: str) -> dict | None:
        """查看来源会话详情。"""
        self._ensure_init()
        from memo.space.source_sessions import source_session_manager
        return source_session_manager.get(source_session_id)

    def source_session_stats(self) -> dict:
        """来源会话统计。"""
        self._ensure_init()
        from memo.space.source_sessions import source_session_manager
        return source_session_manager.stats()

    # ── 历史会话处理任务 ──

    def _history_processing_schema_ready(self) -> bool:
        try:
            cols = {r[1] for r in db.fetchall("PRAGMA table_info(history_processing_jobs)")}
        except Exception:
            return False
        return {"id", "status", "current_step", "selected_sources_json", "detect_report_json", "model_config_json", "progress_json"}.issubset(cols)

    def _history_job_event(self, job_id: str, event_type: str, message: str = "", payload: dict[str, Any] | None = None) -> None:
        db.execute(
            """INSERT INTO history_processing_job_events (id, job_id, event_type, message, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("hp_evt_" + uuid.uuid4().hex[:16], job_id, event_type, message or "", json.dumps(payload or {}, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )

    def _history_job_row(self, row) -> dict[str, Any]:
        if not row:
            return {}
        data = dict(row)
        for key in ["selected_sources_json", "detect_report_json", "model_config_json", "progress_json"]:
            out_key = key[:-5] if key.endswith("_json") else key
            try:
                data[out_key] = json.loads(data.get(key) or "{}")
            except Exception:
                data[out_key] = {} if key != "selected_sources_json" else []
        model = data.get("model_config") or {}
        if model.get("api_key"):
            model = dict(model)
            model["api_key"] = "***"
            data["model_config"] = model
        return data

    def _history_latest_job(self):
        return db.fetchone("SELECT * FROM history_processing_jobs ORDER BY datetime(updated_at) DESC, datetime(created_at) DESC LIMIT 1")

    def _history_progress_summary(self, job: dict[str, Any]) -> dict[str, Any]:
        steps = ["detect", "source_import", "memory_extract", "quality_rules", "llm_enhance", "done"]
        labels = {
            "detect": "检测历史源",
            "source_import": "导入原始会话/轮次",
            "memory_extract": "保守抽取记忆",
            "quality_rules": "规则质量处理",
            "llm_enhance": "LLM 增强（最后一步）",
            "done": "完成",
        }
        step = job.get("current_step") or "detect"
        status = job.get("status") or "draft"
        idx = steps.index(step) if step in steps else 0
        denominator = max(1, len(steps) - 1)
        completed = denominator if step == "done" or status == "done" else max(0, min(idx, denominator))
        # Fixed stage bands keep the displayed progress monotonic and understandable.
        # The last step (LLM enhance) owns 80%..100%; batch_size is internal throughput,
        # not a user-visible need to click one batch at a time.
        stage_floor = {
            "detect": 0,
            "source_import": 15,
            "memory_extract": 35,
            "quality_rules": 60,
            "llm_enhance": 80,
            "done": 100,
        }
        percent = stage_floor.get(step, 0)
        if status == "done" or step == "done":
            percent = 100
        progress_json = job.get("progress") or {}
        llm_progress = progress_json.get("llm_enhance") or {}
        if step == "llm_enhance":
            total = float(llm_progress.get("total") or 0)
            if total > 0:
                llm_ratio = min(1.0, max(0.0, float(llm_progress.get("processed") or 0) / max(1.0, total)))
                percent = int(round(80 + llm_ratio * 20))
            else:
                percent = 80
        blocking_reason = ""
        if step == "llm_enhance" and llm_progress.get("status") == "blocked":
            blocking_reason = "LLM 增强执行器尚未接入；基础处理已可用，当前不会真实调用模型。"
        return {
            "steps": steps,
            "labels": labels,
            "current_step": step,
            "current_label": labels.get(step, step),
            "status": status,
            "completed_steps": completed,
            "total_steps": denominator,
            "percent": percent,
            "is_running": status == "running",
            "blocking_reason": blocking_reason,
        }

    def history_processing_overview(self) -> dict[str, Any]:
        """历史 Agent 会话处理中心状态。"""
        self._ensure_init()
        ready = self._history_processing_schema_ready()
        job = self._history_job_row(self._history_latest_job()) if ready else {}
        events = []
        if job.get("id"):
            events = [dict(r) for r in db.fetchall(
                "SELECT event_type, message, payload_json, created_at FROM history_processing_job_events WHERE job_id=? ORDER BY datetime(created_at) DESC LIMIT 30",
                (job["id"],),
            )]
        progress_summary = self._history_progress_summary(job) if job else self._history_progress_summary({})
        return {
            "schema_ready": ready,
            "job": job,
            "job_progress": progress_summary,
            "events": events,
            "supported_sources": [
                {"id": "hanaagent", "label": "HanaAgent"},
                {"id": "workbuddy", "label": "WorkBuddy"},
                {"id": "codex", "label": "Codex"},
            ],
            "steps": ["detect", "source_import", "memory_extract", "quality_rules", "llm_enhance", "done"],
            "step_labels": {
                "detect": "检测历史源",
                "source_import": "导入原始会话/轮次",
                "memory_extract": "保守抽取记忆",
                "quality_rules": "规则质量处理",
                "llm_enhance": "LLM 增强（最后一步）",
                "done": "完成",
            },
            "llm_note": "LLM 增强永远在规则质量处理之后执行；已接入 OpenAI 兼容执行器。点击继续后会在后台按批次自动处理到完成或暂停，并实时落库进度。暂不支持 Anthropic/Gemini/Ollama 的真实调用。"
        }

    def _history_normalize_model_config(self, model_config: dict[str, Any] | None, current_row=None) -> dict[str, Any]:
        model_config = dict(model_config or {})
        allowed_providers = {"openai-compatible", "anthropic-compatible", "gemini-compatible", "ollama"}
        provider = model_config.get("provider") or "openai-compatible"
        if provider not in allowed_providers:
            provider = "openai-compatible"
        old_model: dict[str, Any] = {}
        if current_row:
            try:
                old_model = json.loads(current_row["model_config_json"] or "{}")
            except Exception:
                old_model = {}
        api_key = model_config.get("api_key")
        if api_key == "***":
            api_key = old_model.get("api_key", "")
        return {
            "provider": provider,
            "base_url": str(model_config.get("base_url") or "").strip(),
            "api_key": str(api_key or "").strip(),
            "model": str(model_config.get("model") or "").strip(),
            "concurrency": max(1, min(int(model_config.get("concurrency") or 1), 8)),
            "batch_size": max(1, min(int(model_config.get("batch_size") or 20), 100)),
        }

    def _history_llm_call_openai_compatible(self, model: dict[str, Any], messages: list[dict[str, str]]) -> str:
        base_url = (model.get("base_url") or "").rstrip("/")
        api_key = model.get("api_key") or ""
        model_name = model.get("model") or ""
        if not base_url or not api_key or not model_name:
            raise ValueError("LLM 模型配置不完整：需要 base_url / api_key / model")
        url = f"{base_url}/v1/chat/completions"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")[:500]
            raise RuntimeError(f"LLM HTTP {exc.code}: {body}") from exc
        return data["choices"][0]["message"]["content"]

    def _history_llm_enhance_batch(self, model: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        provider = model.get("provider") or "openai-compatible"
        if provider != "openai-compatible":
            raise ValueError(f"当前仅已接入 OpenAI 兼容执行器，暂不支持 {provider}")
        items = [
            {
                "id": r["id"],
                "title": r.get("title") or "",
                "summary": r.get("summary") or "",
                "summary_detail": r.get("summary_detail") or "",
                "memory_type": r.get("memory_type") or "FACT",
                "retention_class": r.get("retention_class") or "",
                "recall_policy": r.get("recall_policy") or "",
                "flags": r.get("auto_flags_json") or "{}",
            }
            for r in rows
        ]
        system = (
            "你是 Memo 记忆系统的长期记忆质量增强器。只处理给定 JSON，必须返回严格 JSON。"
            "目标：把粗糙的小颗粒 memory 改写成适合长期检索的标题和摘要；不要编造未给出的事实。"
            "memory_type 只能使用 FACT / DECISION / PREFERENCE / EVENT / REASONING。"
            "recall_policy 只能使用 include / downrank / exclude_default / exclude。"
        )
        user = {
            "task": "enhance_memory_units",
            "requirements": [
                "返回对象包含 key: results，值为数组。",
                "每个 result 必须包含 id,title,summary,summary_detail,memory_type,recall_policy,quality_score,note。",
                "title 使用中文，简洁具体，不超过 32 字。",
                "summary 使用中文，概括稳定事实，不超过 140 字。",
                "summary_detail 可更完整但仍要克制，不超过 500 字。",
                "对临时命令、工具噪音、一次性调试过程，recall_policy 应为 exclude 或 exclude_default。",
                "对项目状态、产品决策、用户偏好、长期事实，recall_policy 应为 include 或 downrank。",
                "quality_score 为 0 到 1。",
            ],
            "items": items,
        }
        content = self._history_llm_call_openai_compatible(
            model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
        )
        try:
            parsed = json.loads(content)
        except Exception as exc:
            raise RuntimeError(f"LLM 返回不是 JSON: {content[:300]}") from exc
        results = parsed.get("results") if isinstance(parsed, dict) else None
        if not isinstance(results, list):
            raise RuntimeError(f"LLM 返回缺少 results 数组: {content[:300]}")
        return [r for r in results if isinstance(r, dict) and r.get("id")]

    def _history_run_llm_enhance(self, job_id: str, progress: dict[str, Any], limit: int = 100000, keep_running: bool = False) -> dict[str, Any]:
        row = db.fetchone("SELECT model_config_json FROM history_processing_jobs WHERE id=?", (job_id,))
        model = json.loads(row["model_config_json"] or "{}") if row else {}
        batch_size = max(1, min(int(model.get("batch_size") or 20), 100))
        existing = progress.get("llm_enhance") or {}
        processed_ids = set(existing.get("processed_ids") or [])
        rows = [dict(r) for r in db.fetchall(
            """SELECT mu.id, mu.title, mu.summary, mu.summary_detail, mu.memory_type,
                      mqr.retention_class, mqr.recall_policy, mqr.auto_flags_json
                 FROM memory_units mu
                 JOIN memory_quality_reviews mqr ON mqr.memory_id = mu.id
                 WHERE COALESCE(mqr.needs_llm,0)=1
                 ORDER BY mu.created_at ASC
                 LIMIT ?""",
            (int(limit or 100000),),
        )]
        pending = [r for r in rows if r["id"] not in processed_ids]
        total = int(existing.get("total") or len(rows))
        done_before = len(processed_ids)
        if not pending:
            progress["llm_enhance"] = {**existing, "status": "done", "total": total, "processed": done_before, "failed": int(existing.get("failed") or 0)}
            db.execute(
                "UPDATE history_processing_jobs SET progress_json=?, current_step='done', status='done', finished_at=?, updated_at=?, last_error='' WHERE id=?",
                (json.dumps(progress, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"), job_id),
            )
            self._history_job_event(job_id, "llm_enhance", "LLM 增强完成", progress["llm_enhance"])
            return progress["llm_enhance"]
        batch = pending[:batch_size]
        enhanced = self._history_llm_enhance_batch(model, batch)
        allowed_types = {"FACT", "DECISION", "PREFERENCE", "EVENT", "REASONING"}
        allowed_policies = {"include", "downrank", "exclude_default", "exclude"}
        by_id = {r["id"]: r for r in batch}
        success = 0
        now = datetime.now().isoformat(timespec="seconds")
        attempted_ids = {str(r["id"]) for r in batch}
        for item in enhanced:
            mid = str(item.get("id") or "")
            if mid not in by_id:
                continue
            title = str(item.get("title") or by_id[mid].get("title") or "")[:120]
            summary = str(item.get("summary") or by_id[mid].get("summary") or "")[:1000]
            detail = str(item.get("summary_detail") or summary)[:3000]
            memory_type = str(item.get("memory_type") or by_id[mid].get("memory_type") or "FACT").upper()
            if memory_type not in allowed_types:
                memory_type = "FACT"
            policy = str(item.get("recall_policy") or by_id[mid].get("recall_policy") or "include")
            if policy not in allowed_policies:
                policy = "include"
            try:
                quality = max(0.0, min(float(item.get("quality_score", 0.75)), 1.0))
            except Exception:
                quality = 0.75
            note = str(item.get("note") or "LLM enhanced")[:1000]
            db.execute(
                """UPDATE memory_units
                   SET title=?, summary=?, summary_detail=?, memory_type=?, confidence=MAX(COALESCE(confidence,0), ?), updated_at=?
                   WHERE id=?""",
                (title, summary, detail, memory_type, quality, now, mid),
            )
            db.execute(
                """UPDATE memory_quality_reviews
                   SET recall_policy=?, quality_score=?, needs_llm=0,
                       processor_version='llm_enhance_v1', note=?, updated_at=?, reviewed_at=?
                   WHERE memory_id=?""",
                (policy, quality, note, now, now, mid),
            )
            processed_ids.add(mid)
            success += 1
        processed_ids.update(attempted_ids)
        failed = int(existing.get("failed") or 0) + max(0, len(batch) - success)
        final = len(processed_ids) >= total
        next_status = "done" if final else ("running" if keep_running else "ready")
        progress["llm_enhance"] = {
            "status": next_status,
            "total": total,
            "processed": len(processed_ids),
            "failed": failed,
            "batch_size": batch_size,
            "processed_ids": sorted(processed_ids),
            "last_batch_at": now,
            "pause_requested": bool(existing.get("pause_requested")),
        }
        db.execute(
            "UPDATE history_processing_jobs SET progress_json=?, current_step=?, status=?, finished_at=CASE WHEN ? THEN ? ELSE finished_at END, updated_at=?, last_error='' WHERE id=?",
            (json.dumps(progress, ensure_ascii=False), "done" if final else "llm_enhance", next_status, 1 if final else 0, now, now, job_id),
        )
        self._history_job_event(job_id, "llm_enhance", f"LLM 增强批次完成：{len(processed_ids)}/{total}", {k: v for k, v in progress["llm_enhance"].items() if k != "processed_ids"})
        return progress["llm_enhance"]

    def _history_create_or_update_job(self, selected_sources: list[str] | None = None, detect_report: dict[str, Any] | None = None, model_config: dict[str, Any] | None = None) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        row = self._history_latest_job()
        job_id = row["id"] if row else "hp_job_" + uuid.uuid4().hex[:12]
        allowed = {"hanaagent", "workbuddy", "codex"}
        selected = [s for s in (selected_sources or []) if s in allowed]
        if row:
            updates = ["updated_at=?"]
            params: list[Any] = [now]
            if selected_sources is not None:
                updates.append("selected_sources_json=?")
                params.append(json.dumps(selected, ensure_ascii=False))
            if detect_report is not None:
                updates.append("detect_report_json=?")
                params.append(json.dumps(detect_report, ensure_ascii=False))
            if model_config is not None:
                updates.append("model_config_json=?")
                params.append(json.dumps(self._history_normalize_model_config(model_config, row), ensure_ascii=False))
            params.append(job_id)
            db.execute(f"UPDATE history_processing_jobs SET {', '.join(updates)} WHERE id=?", tuple(params))
        else:
            db.execute(
                """INSERT INTO history_processing_jobs
                   (id, status, current_step, selected_sources_json, detect_report_json, model_config_json, progress_json, created_at, updated_at)
                   VALUES (?, 'draft', 'detect', ?, ?, ?, '{}', ?, ?)""",
                (job_id, json.dumps(selected, ensure_ascii=False), json.dumps(detect_report or {}, ensure_ascii=False), json.dumps(self._history_normalize_model_config(model_config), ensure_ascii=False), now, now),
            )
        db.commit()
        return job_id

    def _history_detect_sources(self) -> dict[str, Any]:
        from scripts.detect_agent_sources import build_report
        report = build_report([])
        source_map = {"HanaAgent": "hanaagent", "WorkBuddy": "workbuddy", "Codex": "codex"}
        detected_sources = []
        for item in report.get("agents", []):
            sid = source_map.get(item.get("agent"))
            if sid and item.get("detected") and int(item.get("session_count") or 0) > 0:
                detected_sources.append(sid)
        report["detected_supported_sources"] = detected_sources
        report["pending_import"] = self._history_detect_pending_imports(detected_sources)
        return report

    def _history_detect_pending_imports(self, sources: list[str], limit: int = 100000) -> dict[str, Any]:
        """Read-only incremental scan for source sessions that are new or changed.

        Detection compares the source-aware session id and content_hash against the
        current DB. It does not write source_sessions/source_turns/episodes.
        """
        try:
            from scripts.source_aware_import import adapter_for, stable_hash
        except Exception as exc:
            return {"status": "error", "message": str(exc), "sources": {}, "total_pending": 0}
        by_source: dict[str, Any] = {}
        total_pending = 0
        allowed = {"hanaagent", "workbuddy", "codex"}
        for source in [s for s in (sources or []) if s in allowed]:
            info = {"scanned": 0, "pending": 0, "new": 0, "changed": 0, "unchanged": 0, "errors": 0}
            try:
                adapter = adapter_for(source)
                paths = adapter.list_sessions(limit=limit)
                for source_path in paths:
                    try:
                        session = adapter.load_session(source_path)
                        source_id = "ss_" + stable_hash(f"{session.source_agent}|{session.agent_session_id}|{session.source_path}")[:24]
                        row = db.fetchone("SELECT content_hash FROM source_sessions WHERE id=?", (source_id,))
                        info["scanned"] += 1
                        if not row:
                            info["new"] += 1
                            info["pending"] += 1
                        elif (row["content_hash"] or "") != (session.content_hash or ""):
                            info["changed"] += 1
                            info["pending"] += 1
                        else:
                            info["unchanged"] += 1
                    except Exception:
                        info["errors"] += 1
            except Exception as exc:
                info["error"] = str(exc)
            total_pending += int(info.get("pending") or 0)
            by_source[source] = info
        return {
            "status": "has_pending" if total_pending > 0 else "up_to_date",
            "total_pending": total_pending,
            "sources": by_source,
        }

    def _history_llm_worker_is_running(self) -> bool:
        with self._history_worker_lock:
            return bool(self._history_worker_thread and self._history_worker_thread.is_alive())

    def _history_start_llm_enhance_worker(self, job_id: str, limit: int = 100000) -> bool:
        with self._history_worker_lock:
            if self._history_worker_thread and self._history_worker_thread.is_alive():
                return False
            thread = threading.Thread(
                target=self._history_llm_enhance_worker,
                args=(job_id, int(limit or 100000)),
                name="memo-history-llm-enhance",
                daemon=True,
            )
            self._history_worker_thread = thread
            thread.start()
            return True

    def _history_llm_enhance_worker(self, job_id: str, limit: int = 100000) -> None:
        """Run LLM enhancement batches until completion, pause, or failure.

        The HTTP action only starts this worker and returns quickly. Batch size remains
        the internal LLM payload size; users should not need to click once per batch.
        """
        try:
            self._ensure_init()
            self._history_job_event(job_id, "llm_enhance", "LLM 增强后台任务已启动")
            db.commit()
            while True:
                row = db.fetchone("SELECT * FROM history_processing_jobs WHERE id=?", (job_id,))
                if not row:
                    return
                progress = json.loads(row["progress_json"] or "{}")
                llm_progress = progress.get("llm_enhance") or {}
                if bool(progress.get("pause_requested")) or bool(llm_progress.get("pause_requested")):
                    now = datetime.now().isoformat(timespec="seconds")
                    progress.pop("pause_requested", None)
                    progress["llm_enhance"] = {**llm_progress, "status": "paused", "pause_requested": False}
                    db.execute(
                        "UPDATE history_processing_jobs SET progress_json=?, status='paused', current_step='llm_enhance', updated_at=? WHERE id=?",
                        (json.dumps(progress, ensure_ascii=False), now, job_id),
                    )
                    self._history_job_event(job_id, "pause", "LLM 增强已在当前批次后暂停")
                    db.commit()
                    return
                if row["status"] not in {"running", "ready"}:
                    return
                result = self._history_run_llm_enhance(job_id, progress, limit=limit, keep_running=True)
                db.commit()
                if result.get("status") == "done":
                    return
        except Exception as exc:
            now = datetime.now().isoformat(timespec="seconds")
            db.execute(
                "UPDATE history_processing_jobs SET status='failed', last_error=?, updated_at=? WHERE id=?",
                (str(exc), now, job_id),
            )
            self._history_job_event(job_id, "error", str(exc))
            db.commit()
            logger.exception("历史 LLM 增强后台任务失败")
        finally:
            with self._history_worker_lock:
                if self._history_worker_thread is threading.current_thread():
                    self._history_worker_thread = None

    def history_processing_action(self, action: str, **kwargs) -> dict[str, Any]:
        """历史会话处理动作。同步执行单步，状态落库，可中断后继续。"""
        self._ensure_init()
        if not self._history_processing_schema_ready():
            return {"error": "history processing schema not ready; restart Memo to run migrations"}
        action = action or "overview"
        row = self._history_latest_job()
        if row and row["status"] == "running" and action not in {"pause"}:
            stale_llm_worker = row["current_step"] == "llm_enhance" and not self._history_llm_worker_is_running()
            if not (stale_llm_worker and action in {"start", "continue", "run_next"}):
                return self.history_processing_overview()
        if action == "scan":
            report = self._history_detect_sources()
            selected_sources = report.get("detected_supported_sources", [])
            pending = report.get("pending_import") or {}
            job_id = self._history_create_or_update_job(selected_sources=selected_sources, detect_report=report)
            now = datetime.now().isoformat(timespec="seconds")
            scan_progress = {"scan": pending}
            if int(pending.get("total_pending") or 0) <= 0:
                self._history_job_event(job_id, "scan", "没有发现新的历史会话，当前已是最新", {"sources": selected_sources, "pending_import": pending})
                db.execute(
                    "UPDATE history_processing_jobs SET progress_json=?, status='ready', current_step='detect', updated_at=?, last_error='' WHERE id=?",
                    (json.dumps(scan_progress, ensure_ascii=False), now, job_id),
                )
            else:
                self._history_job_event(job_id, "scan", "历史源检测完成，发现新的或已变化的历史会话", {"sources": selected_sources, "pending_import": pending})
                db.execute(
                    "UPDATE history_processing_jobs SET progress_json=?, status='ready', current_step='source_import', updated_at=?, last_error='' WHERE id=?",
                    (json.dumps(scan_progress, ensure_ascii=False), now, job_id),
                )
            db.commit()
            return self.history_processing_overview()
        if action == "save_config":
            job_id = self._history_create_or_update_job(selected_sources=kwargs.get("selected_sources"), model_config=kwargs.get("model_config") or {})
            self._history_job_event(job_id, "config", "已保存历史处理配置", {"selected_sources": kwargs.get("selected_sources") or []})
            db.commit()
            return self.history_processing_overview()
        if action == "pause":
            row = self._history_latest_job()
            if not row:
                return {"error": "no job"}
            now = datetime.now().isoformat(timespec="seconds")
            if row["status"] == "running" and row["current_step"] == "llm_enhance":
                progress = json.loads(row["progress_json"] or "{}")
                llm_progress = progress.get("llm_enhance") or {}
                progress["llm_enhance"] = {**llm_progress, "pause_requested": True}
                db.execute(
                    "UPDATE history_processing_jobs SET progress_json=?, updated_at=? WHERE id=?",
                    (json.dumps(progress, ensure_ascii=False), now, row["id"]),
                )
                self._history_job_event(row["id"], "pause", "已请求暂停；当前 LLM 批次完成后停止")
            else:
                db.execute("UPDATE history_processing_jobs SET status='paused', updated_at=? WHERE id=?", (now, row["id"]))
                self._history_job_event(row["id"], "pause", "任务已暂停")
            db.commit()
            return self.history_processing_overview()
        if action in {"start", "continue", "run_next"}:
            return self._history_run_next_step(limit=int(kwargs.get("limit") or 100000))
        return {"error": f"unknown action: {action}"}

    def _history_run_next_step(self, limit: int = 100000) -> dict[str, Any]:
        row = self._history_latest_job()
        if not row:
            report = self._history_detect_sources()
            job_id = self._history_create_or_update_job(selected_sources=report.get("detected_supported_sources", []), detect_report=report)
            row = db.fetchone("SELECT * FROM history_processing_jobs WHERE id=?", (job_id,))
        job_id = row["id"]
        status = row["status"]
        step = row["current_step"]
        selected = json.loads(row["selected_sources_json"] or "[]")
        if status == "running":
            stale_llm_worker = step == "llm_enhance" and not self._history_llm_worker_is_running()
            if not stale_llm_worker:
                return {"error": "history processing job is already running; duplicate continue is blocked", **self.history_processing_overview()}
        if status == "done" or step == "done":
            return self.history_processing_overview()
        if not selected and step != "detect":
            return {"error": "no selected sources; run scan or choose sources first"}
        progress = json.loads(row["progress_json"] or "{}")
        scan_progress = progress.get("scan") or {}
        if step == "detect" and scan_progress.get("status") == "up_to_date":
            return {"message": "没有发现新的历史会话，当前已是最新", **self.history_processing_overview()}
        if step == "source_import" and scan_progress.get("status") == "up_to_date":
            return {"message": "没有发现新的历史会话，当前已是最新", **self.history_processing_overview()}
        if step == "source_import" and scan_progress and int(scan_progress.get("total_pending") or 0) <= 0:
            return {"message": "没有发现新的历史会话，当前已是最新", **self.history_processing_overview()}
        
        now = datetime.now().isoformat(timespec="seconds")
        db.execute("UPDATE history_processing_jobs SET status='running', started_at=COALESCE(started_at, ?), updated_at=?, last_error='' WHERE id=?", (now, now, job_id))
        db.commit()
        try:
            if step == "detect":
                report = self._history_detect_sources()
                selected = report.get("detected_supported_sources", [])
                db.execute(
                    "UPDATE history_processing_jobs SET detect_report_json=?, selected_sources_json=?, current_step='source_import', status='ready', updated_at=? WHERE id=?",
                    (json.dumps(report, ensure_ascii=False), json.dumps(selected, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), job_id),
                )
                self._history_job_event(job_id, "detect", "检测完成", {"sources": selected})
            elif step == "source_import":
                from scripts.source_aware_import import apply_to_production_source_only
                results = {}
                for source in selected:
                    results[source] = apply_to_production_source_only(source, limit=limit)
                progress["source_import"] = results
                db.execute("UPDATE history_processing_jobs SET progress_json=?, current_step='memory_extract', status='ready', updated_at=? WHERE id=?", (json.dumps(progress, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), job_id))
                self._history_job_event(job_id, "source_import", "source-only 导入完成", {"sources": selected})
            elif step == "memory_extract":
                from scripts.source_aware_import import extract_memory_units_from_source_sessions
                source_agent = {"hanaagent": "HanaAgent", "workbuddy": "WorkBuddy", "codex": "Codex"}
                db_path = Path(config.db_path).resolve()
                results = {}
                for source in selected:
                    results[source] = extract_memory_units_from_source_sessions(db_path, source_agent=source_agent[source], limit=limit)
                progress["memory_extract"] = results
                db.execute("UPDATE history_processing_jobs SET progress_json=?, current_step='quality_rules', status='ready', updated_at=? WHERE id=?", (json.dumps(progress, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), job_id))
                self._history_job_event(job_id, "memory_extract", "保守记忆抽取完成", {"sources": selected})
            elif step == "quality_rules":
                result = self.apply_source_aware_quality_rules(dry_run=False)
                progress["quality_rules"] = result
                db.execute("UPDATE history_processing_jobs SET progress_json=?, current_step='llm_enhance', status='ready', updated_at=? WHERE id=?", (json.dumps(progress, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), job_id))
                self._history_job_event(job_id, "quality_rules", "规则质量处理完成；LLM 增强是最后一步，等待执行", result)
            elif step == "llm_enhance":
                llm_progress = progress.get("llm_enhance") or {}
                progress.pop("pause_requested", None)
                progress["llm_enhance"] = {**llm_progress, "status": "running", "pause_requested": False}
                db.execute(
                    "UPDATE history_processing_jobs SET progress_json=?, current_step='llm_enhance', status='running', updated_at=?, last_error='' WHERE id=?",
                    (json.dumps(progress, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), job_id),
                )
                self._history_job_event(job_id, "llm_enhance", "LLM 增强自动批处理已启动；将按批次持续处理到完成或暂停")
                db.commit()
                self._history_start_llm_enhance_worker(job_id, limit=limit)
                return self.history_processing_overview()
            db.commit()
        except Exception as exc:
            db.execute("UPDATE history_processing_jobs SET status='failed', last_error=?, updated_at=? WHERE id=?", (str(exc), datetime.now().isoformat(timespec="seconds"), job_id))
            self._history_job_event(job_id, "error", str(exc))
            db.commit()
            return {"error": str(exc), **self.history_processing_overview()}
        return self.history_processing_overview()

    # ── Source-aware Dashboard ──

    def source_aware_dashboard(self, page: int = 1, page_size: int = 30, q: str = "", mode: str = "sessions") -> dict[str, Any]:
        """Source-aware 审计工作台：source_sessions / missing titles / evidence counts。只读，不返回原文。"""
        self._ensure_init()
        page_size = max(1, min(int(page_size or 30), 100))
        page = max(1, int(page or 1))
        offset = (page - 1) * page_size
        q = (q or "").strip()
        mode = mode or "sessions"
        schema_status = self._source_aware_schema_status()
        if not schema_status["ready"]:
            return {
                "page": page,
                "page_size": page_size,
                "mode": mode,
                "q": q,
                "total": 0,
                "schema_status": schema_status,
                "stats": self._source_aware_empty_stats(),
                "sessions": [],
            }
        where, params = self._source_aware_session_where(q=q, mode=mode)
        total_row = db.fetchone(f"SELECT COUNT(*) AS c FROM source_sessions ss{where}", params)
        total = int(total_row["c"] if total_row else 0)
        rows = db.fetchall(
            f"""WITH turn_counts AS (
                    SELECT source_session_id,
                           COUNT(*) AS turn_count,
                           SUM(CASE WHEN is_tool_call=1 THEN 1 ELSE 0 END) AS tool_call_count,
                           SUM(CASE WHEN is_tool_result=1 THEN 1 ELSE 0 END) AS tool_result_count
                    FROM source_turns
                    GROUP BY source_session_id
                ), episode_counts AS (
                    SELECT source_session_id, COUNT(*) AS episode_count
                    FROM episodes
                    GROUP BY source_session_id
                ), memory_counts AS (
                    SELECT source_session_id, COUNT(*) AS memory_count
                    FROM memory_units
                    WHERE source_session_id IS NOT NULL
                    GROUP BY source_session_id
                ), evidence_counts AS (
                    SELECT mu.source_session_id,
                           COUNT(DISTINCT mts.memory_id || ':' || mts.turn_id || ':' || mts.evidence_role) AS evidence_count
                    FROM memory_units mu
                    JOIN memory_turn_sources mts ON mts.memory_id=mu.id
                    WHERE mu.source_session_id IS NOT NULL
                    GROUP BY mu.source_session_id
                ), quality_counts AS (
                    SELECT mu.source_session_id,
                           SUM(CASE WHEN mqr.retention_class='long_term' THEN 1 ELSE 0 END) AS long_term_count,
                           SUM(CASE WHEN mqr.retention_class='temporary_task' THEN 1 ELSE 0 END) AS temporary_task_count,
                           SUM(CASE WHEN mqr.retention_class='noise' THEN 1 ELSE 0 END) AS noise_count,
                           SUM(CASE WHEN mqr.retention_class='project_state' THEN 1 ELSE 0 END) AS project_state_count,
                           SUM(CASE WHEN mqr.needs_llm=1 THEN 1 ELSE 0 END) AS needs_llm_count,
                           COUNT(mqr.memory_id) AS quality_reviewed_count
                    FROM memory_units mu
                    LEFT JOIN memory_quality_reviews mqr ON mqr.memory_id=mu.id
                    WHERE mu.source_session_id IS NOT NULL
                    GROUP BY mu.source_session_id
                )
                SELECT ss.id, ss.source_agent, ss.agent_session_id, ss.source_path, ss.source_hash,
                       ss.original_title, ss.title_source, ss.display_title, ss.display_title_source,
                       ss.started_at, ss.updated_at, ss.imported_at, ss.message_count, ss.status,
                       COALESCE(tc.turn_count, 0) AS turn_count,
                       COALESCE(ec.episode_count, 0) AS episode_count,
                       COALESCE(mc.memory_count, 0) AS memory_count,
                       COALESCE(evc.evidence_count, 0) AS evidence_count,
                       COALESCE(tc.tool_call_count, 0) AS tool_call_count,
                       COALESCE(tc.tool_result_count, 0) AS tool_result_count,
                       COALESCE(qc.long_term_count, 0) AS long_term_count,
                       COALESCE(qc.temporary_task_count, 0) AS temporary_task_count,
                       COALESCE(qc.noise_count, 0) AS noise_count,
                       COALESCE(qc.project_state_count, 0) AS project_state_count,
                       COALESCE(qc.needs_llm_count, 0) AS needs_llm_count,
                       COALESCE(qc.quality_reviewed_count, 0) AS quality_reviewed_count,
                       COALESCE(srs.review_status, '') AS session_review_status,
                       COALESCE(srs.review_note, '') AS session_review_note,
                       COALESCE(srs.manual_done_count, 0) AS manual_done_count,
                       COALESCE(srs.manual_progress_count, 0) AS manual_progress_count,
                       COALESCE(srs.postponed_until, '') AS postponed_until,
                       COALESCE(srs.reviewed_at, '') AS session_reviewed_at,
                       COALESCE(srs.updated_at, '') AS session_review_updated_at
                FROM source_sessions ss
                LEFT JOIN turn_counts tc ON tc.source_session_id=ss.id
                LEFT JOIN episode_counts ec ON ec.source_session_id=ss.id
                LEFT JOIN memory_counts mc ON mc.source_session_id=ss.id
                LEFT JOIN evidence_counts evc ON evc.source_session_id=ss.id
                LEFT JOIN quality_counts qc ON qc.source_session_id=ss.id
                LEFT JOIN source_session_review_states srs ON srs.source_session_id=ss.id
                {where}
                ORDER BY COALESCE(ss.updated_at, ss.imported_at, ss.created_at) DESC
                LIMIT ? OFFSET ?""",
            params + (page_size, offset),
        )
        stats = self._source_aware_stats()
        return {
            "page": page,
            "page_size": page_size,
            "mode": mode,
            "q": q,
            "total": total,
            "schema_status": schema_status,
            "stats": stats,
            "sessions": [self._source_aware_session_row(r) for r in rows],
        }

    def apply_source_aware_quality_rules(self, dry_run: bool = True, limit: int | None = None) -> dict[str, Any]:
        """对 source-aware memory 执行规则自动处理。

        dry_run=True 只返回计划；dry_run=False 写入 memory_quality_reviews。
        不删除、不合并、不改写原始 memory 内容。
        """
        self._ensure_init()
        schema_status = self._source_aware_schema_status()
        quality_ready = self._memory_quality_schema_ready()
        if not schema_status["ready"] or not quality_ready:
            return {"dry_run": dry_run, "applied": 0, "error": "schema not ready", "source_schema": schema_status, "quality_schema_ready": quality_ready}
        rows = [dict(r) for r in db.fetchall(
            """SELECT mu.id, mu.title, mu.summary, mu.source_session_id, mu.episode_id,
                      COUNT(mts.turn_id) AS evidence_count
               FROM memory_units mu
               LEFT JOIN memory_turn_sources mts ON mts.memory_id=mu.id
               WHERE mu.source_session_id IS NOT NULL
               GROUP BY mu.id
               ORDER BY mu.created_at DESC"""
        )]
        if limit:
            rows = rows[: max(1, int(limit))]
        duplicate_counts = self._source_aware_duplicate_counts()
        now = datetime.now().isoformat()
        plans = []
        summary = defaultdict(int)
        for row in rows:
            plan = self._quality_rule_plan(row, duplicate_counts)
            plans.append(plan)
            summary[plan["review_status"]] += 1
            summary[plan["retention_class"]] += 1
            summary[plan["recall_policy"]] += 1
            if not dry_run:
                db.execute(
                    """INSERT INTO memory_quality_reviews
                       (memory_id, review_status, retention_class, recall_policy, quality_score, auto_flags_json,
                        duplicate_group_key, duplicate_count, needs_llm, processor_version, note, reviewed_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'rules-v1', ?, ?, ?)
                       ON CONFLICT(memory_id) DO UPDATE SET
                         review_status=excluded.review_status,
                         retention_class=excluded.retention_class,
                         recall_policy=excluded.recall_policy,
                         quality_score=excluded.quality_score,
                         auto_flags_json=excluded.auto_flags_json,
                         duplicate_group_key=excluded.duplicate_group_key,
                         duplicate_count=excluded.duplicate_count,
                         needs_llm=excluded.needs_llm,
                         processor_version=excluded.processor_version,
                         note=excluded.note,
                         reviewed_at=excluded.reviewed_at,
                         updated_at=excluded.updated_at""",
                    (
                        plan["memory_id"], plan["review_status"], plan["retention_class"], plan["recall_policy"],
                        plan["quality_score"], json.dumps(plan["flags"], ensure_ascii=False), plan["duplicate_group_key"],
                        plan["duplicate_count"], int(plan["needs_llm"]), plan["note"], now, now,
                    ),
                )
        if not dry_run:
            db.commit()
        return {"dry_run": dry_run, "processed": len(plans), "applied": 0 if dry_run else len(plans), "summary": dict(summary), "samples": plans[:20]}

    def _memory_quality_schema_ready(self) -> bool:
        try:
            cols = {r[1] for r in db.fetchall("PRAGMA table_info(memory_quality_reviews)")}
        except Exception:
            return False
        return {"memory_id", "review_status", "retention_class", "recall_policy", "quality_score", "auto_flags_json"}.issubset(cols)

    def _source_aware_duplicate_counts(self) -> dict[str, int]:
        rows = db.fetchall("SELECT id, title FROM memory_units WHERE source_session_id IS NOT NULL")
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            key = self._quality_normalize_title(row["title"] or "")
            if key:
                counts[key] += 1
        return counts

    def _quality_normalize_title(self, text: str) -> str:
        return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")[:80]

    def _quality_rule_plan(self, row: dict[str, Any], duplicate_counts: dict[str, int]) -> dict[str, Any]:
        text = f"{row.get('title') or ''}\n{row.get('summary') or ''}".lower()
        pollution_tokens = ("<system-reminder", "<command-name>", "<local-command-", "[hana_reminder", "[use skill:", "[sessionfile]", "c:\\users\\pc>", "tool_call", "tool_result", "command-caveat", "user-context", "secret key", "api key", "sk-", "successfully updated", "<environment_context", "<recommended_plugins", "the following is the codex agent history")
        temporary_tokens = ("帮我安装", "打开", "访问", "检查一下", "跑一下", "修一下", "这个路径", "这个文件", "当前这个项目")
        flags: list[str] = []
        flags.extend([f"pollution:{t}" for t in pollution_tokens if t in text])
        flags.extend([f"temporary:{t}" for t in temporary_tokens if t in text])
        evidence_count = int(row.get("evidence_count") or 0)
        if evidence_count <= 0:
            flags.append("low_evidence")
        duplicate_key = self._quality_normalize_title(row.get("title") or "")
        duplicate_count = duplicate_counts.get(duplicate_key, 1) if duplicate_key else 1
        if duplicate_count > 1:
            flags.append("duplicate_candidate")

        if any(f.startswith("pollution:") for f in flags):
            review_status, retention_class, recall_policy, score, needs_llm = "auto_rejected", "noise", "exclude", 0.05, False
            note = "规则命中系统/工具污染，默认排除召回。"
        elif any(f.startswith("temporary:") for f in flags):
            review_status, retention_class, recall_policy, score, needs_llm = "auto_muted", "temporary_task", "exclude_default", 0.25, False
            note = "规则命中临时执行任务，默认不进入长期召回。"
        elif "low_evidence" in flags:
            review_status, retention_class, recall_policy, score, needs_llm = "auto_flagged", "candidate", "downrank", 0.35, True
            note = "证据链不足，需要复核。"
        elif "duplicate_candidate" in flags:
            review_status, retention_class, recall_policy, score, needs_llm = "auto_flagged", "project_state", "downrank", 0.55, True
            note = "疑似重复记忆，等待 LLM 或人工合并建议。"
        else:
            review_status, retention_class, recall_policy, score, needs_llm = "auto_accepted", "long_term", "include", 0.82, True
            note = "规则未发现污染/临时任务/证据缺失，暂定长期候选；后续可由 LLM 优化摘要和类型。"
        return {
            "memory_id": row["id"],
            "title": row.get("title"),
            "review_status": review_status,
            "retention_class": retention_class,
            "recall_policy": recall_policy,
            "quality_score": score,
            "flags": flags,
            "duplicate_group_key": duplicate_key if duplicate_count > 1 else "",
            "duplicate_count": duplicate_count,
            "needs_llm": needs_llm,
            "note": note,
        }

    def source_aware_memory_quality(self, limit: int = 20) -> dict[str, Any]:
        """Source-aware memory 质量审计：只读返回候选风险，不修改数据库。"""
        self._ensure_init()
        limit = max(1, min(int(limit or 20), 100))
        schema_status = self._source_aware_schema_status()
        if not schema_status["ready"]:
            return {"schema_status": schema_status, "counts": {}, "flags": {}, "samples": {}}

        rows = [dict(r) for r in db.fetchall(
            """SELECT mu.id, mu.title, mu.summary, mu.source_session_id, mu.episode_id,
                      mu.memory_type, mu.memory_granularity, mu.speaker_scope, mu.source_confidence,
                      ss.source_agent, ss.display_title, ss.title_source, ss.display_title_source,
                      COUNT(mts.turn_id) AS evidence_count
               FROM memory_units mu
               JOIN source_sessions ss ON ss.id=mu.source_session_id
               LEFT JOIN memory_turn_sources mts ON mts.memory_id=mu.id
               WHERE mu.source_session_id IS NOT NULL
               GROUP BY mu.id
               ORDER BY mu.created_at DESC"""
        )]
        pollution_tokens = (
            "<system-reminder", "<command-name>", "<local-command-", "[hana_reminder",
            "[use skill:", "[sessionfile]", "c:\\users\\pc>", "tool_call", "tool_result",
            "command-caveat", "user-context", "secret key", "api key", "sk-", "successfully updated",
            "<environment_context", "<recommended_plugins", "the following is the codex agent history",
        )
        temporary_tokens = (
            "帮我安装", "打开", "访问", "检查一下", "跑一下", "修一下",
            "这个路径", "这个文件", "当前这个项目",
        )

        def compact(row: dict[str, Any], matched: list[str] | None = None) -> dict[str, Any]:
            data = {
                "id": row.get("id"),
                "title": row.get("title"),
                "summary": row.get("summary"),
                "source_agent": row.get("source_agent"),
                "source_session_id": row.get("source_session_id"),
                "episode_id": row.get("episode_id"),
                "display_title": row.get("display_title"),
                "title_source": row.get("title_source"),
                "display_title_source": row.get("display_title_source"),
                "evidence_count": int(row.get("evidence_count") or 0),
            }
            if matched:
                data["matched"] = matched
            return data

        def normalize_title(text: str) -> str:
            normalized = "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
            return normalized[:80]

        pollution_hits: list[dict[str, Any]] = []
        temporary_hits: list[dict[str, Any]] = []
        low_evidence: list[dict[str, Any]] = []
        duplicate_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            text = f"{row.get('title') or ''}\n{row.get('summary') or ''}".lower()
            p_hits = [token for token in pollution_tokens if token in text]
            t_hits = [token for token in temporary_tokens if token in text]
            if p_hits:
                pollution_hits.append(compact(row, p_hits))
            if t_hits:
                temporary_hits.append(compact(row, t_hits))
            if int(row.get("evidence_count") or 0) <= 0:
                low_evidence.append(compact(row))
            key = normalize_title(row.get("title") or "")
            if key:
                duplicate_map[key].append(row)

        duplicate_groups = [
            {"normalized_title": key, "count": len(items), "items": [compact(item) for item in items[:limit]]}
            for key, items in duplicate_map.items()
            if len(items) > 1
        ]
        duplicate_groups.sort(key=lambda item: item["count"], reverse=True)
        missing_titles = [dict(r) for r in db.fetchall(
            """SELECT id, source_agent, agent_session_id, display_title, title_source, display_title_source, source_path
               FROM source_sessions
               WHERE COALESCE(title_source,'')='missing'
               ORDER BY COALESCE(updated_at, imported_at, created_at) DESC
               LIMIT ?""",
            (limit,),
        )]
        counts = {
            "source_aware_memories": len(rows),
            "memories_with_evidence": int(db.fetchone("SELECT COUNT(DISTINCT memory_id) AS c FROM memory_turn_sources")["c"]),
            "source_sessions": int(db.fetchone("SELECT COUNT(*) AS c FROM source_sessions")["c"]),
            "missing_original_titles": int(db.fetchone("SELECT COUNT(*) AS c FROM source_sessions WHERE COALESCE(title_source,'')='missing'")["c"]),
        }
        review_summary: dict[str, Any] = {"ready": self._memory_quality_schema_ready(), "by_status": [], "by_retention": [], "by_recall_policy": []}
        if review_summary["ready"]:
            review_summary["by_status"] = [dict(r) for r in db.fetchall("SELECT review_status, COUNT(*) AS c FROM memory_quality_reviews GROUP BY review_status ORDER BY c DESC")]
            review_summary["by_retention"] = [dict(r) for r in db.fetchall("SELECT retention_class, COUNT(*) AS c FROM memory_quality_reviews GROUP BY retention_class ORDER BY c DESC")]
            review_summary["by_recall_policy"] = [dict(r) for r in db.fetchall("SELECT recall_policy, COUNT(*) AS c FROM memory_quality_reviews GROUP BY recall_policy ORDER BY c DESC")]
            counts["quality_reviewed"] = int(db.fetchone("SELECT COUNT(*) AS c FROM memory_quality_reviews")["c"])
        flags = {
            "pollution_pattern_hits": len(pollution_hits),
            "temporary_task_like_hits": len(temporary_hits),
            "duplicate_title_groups": len(duplicate_groups),
            "low_evidence_hits": len(low_evidence),
            "missing_original_titles": counts["missing_original_titles"],
        }
        return {
            "schema_status": schema_status,
            "counts": counts,
            "flags": flags,
            "review_summary": review_summary,
            "samples": {
                "pollution_pattern_hits": pollution_hits[:limit],
                "temporary_task_like_hits": temporary_hits[:limit],
                "duplicate_title_groups": duplicate_groups[:limit],
                "low_evidence_hits": low_evidence[:limit],
                "missing_original_titles": missing_titles,
            },
        }

    def source_aware_session_detail(self, source_session_id: str) -> dict[str, Any] | None:
        """Source Session 详情：元信息 + turn/episode/memory 证据概览，不返回 raw content。"""
        self._ensure_init()
        if not self._source_aware_schema_status()["ready"]:
            return None
        row = db.fetchone("SELECT * FROM source_sessions WHERE id=?", (source_session_id,))
        if not row:
            return None
        turns = [dict(r) for r in db.fetchall(
            """SELECT id, agent_turn_id, parent_turn_id, role, content_hash,
                      COALESCE(CAST(json_extract(metadata_json, '$.content_length') AS INTEGER), length(content), 0) AS content_length,
                      timestamp, turn_index, is_final_answer, is_tool_call, is_tool_result, tool_name, source_event_type
               FROM source_turns WHERE source_session_id=? ORDER BY turn_index LIMIT 300""",
            (source_session_id,),
        )]
        episodes = [dict(r) for r in db.fetchall(
            """SELECT e.id, e.title, e.user_intent, e.start_turn_index, e.end_turn_index, e.status, e.confidence,
                      COUNT(et.turn_id) AS turn_count,
                      COUNT(mu.id) AS memory_count
               FROM episodes e
               LEFT JOIN episode_turns et ON et.episode_id=e.id
               LEFT JOIN memory_units mu ON mu.episode_id=e.id
               WHERE e.source_session_id=?
               GROUP BY e.id
               ORDER BY e.start_turn_index, e.created_at""",
            (source_session_id,),
        )]
        memories = [dict(r) for r in db.fetchall(
            """SELECT mu.id, mu.title, mu.summary, mu.memory_type, mu.memory_granularity, mu.speaker_scope,
                      mu.source_confidence, mu.is_canonical, mu.created_at, mu.updated_at,
                      COUNT(mts.turn_id) AS evidence_count
               FROM memory_units mu
               LEFT JOIN memory_turn_sources mts ON mts.memory_id=mu.id
               WHERE mu.source_session_id=?
               GROUP BY mu.id
               ORDER BY mu.created_at DESC
               LIMIT 100""",
            (source_session_id,),
        )]
        return {"session": self._source_aware_session_row(row), "turns": turns, "episodes": episodes, "memory_units": memories}

    def source_aware_memory_evidence(self, memory_id: str) -> dict[str, Any] | None:
        """Memory → evidence chain：memory_turn_sources → source_turns → source_session。只返回 turn 元信息。"""
        self._ensure_init()
        if not self._source_aware_schema_status()["ready"]:
            return None
        memory = db.fetchone(
            """SELECT id, title, summary, memory_type, source_session_id, episode_id, memory_granularity,
                      speaker_scope, source_confidence, is_canonical, created_at, updated_at
               FROM memory_units WHERE id=?""",
            (memory_id,),
        )
        if not memory:
            return None
        evidence = [dict(r) for r in db.fetchall(
            """SELECT mts.evidence_role, mts.weight, mts.created_at,
                      st.id AS turn_id, st.role, st.content_hash,
                      COALESCE(CAST(json_extract(st.metadata_json, '$.content_length') AS INTEGER), length(st.content), 0) AS content_length,
                      st.timestamp, st.turn_index, st.is_final_answer, st.is_tool_call, st.is_tool_result,
                      st.tool_name, st.source_event_type,
                      ss.id AS source_session_id, ss.source_agent, ss.agent_session_id,
                      ss.original_title, ss.title_source, ss.display_title, ss.display_title_source
               FROM memory_turn_sources mts
               JOIN source_turns st ON st.id=mts.turn_id
               JOIN source_sessions ss ON ss.id=st.source_session_id
               WHERE mts.memory_id=?
               ORDER BY st.turn_index, mts.evidence_role""",
            (memory_id,),
        )]
        session = None
        if memory["source_session_id"]:
            srow = db.fetchone("SELECT * FROM source_sessions WHERE id=?", (memory["source_session_id"],))
            session = self._source_aware_session_row(srow) if srow else None
        episode = None
        if memory["episode_id"]:
            erow = db.fetchone("SELECT id, title, user_intent, start_turn_index, end_turn_index, status, confidence FROM episodes WHERE id=?", (memory["episode_id"],))
            episode = dict(erow) if erow else None
        return {"memory": dict(memory), "source_session": session, "episode": episode, "evidence": evidence}

    def _source_aware_schema_status(self) -> dict[str, Any]:
        required = {
            "source_sessions": {"agent_session_id", "source_hash", "original_title", "title_source", "display_title", "display_title_source"},
            "source_turns": {"source_session_id", "content", "content_hash", "metadata_json", "turn_index"},
            "episodes": {"source_session_id", "start_turn_id", "end_turn_id"},
            "memory_turn_sources": {"memory_id", "turn_id", "evidence_role"},
            "source_session_review_states": {"source_session_id", "review_status", "review_note", "manual_done_count", "manual_progress_count"},
        }
        missing: dict[str, list[str]] = {}
        for table, cols in required.items():
            found = {r[1] for r in db.fetchall(f"PRAGMA table_info({table})")}
            if not found:
                missing[table] = ["<table>"]
            else:
                absent = sorted(cols - found)
                if absent:
                    missing[table] = absent
        return {"ready": not missing, "missing": missing, "message": "ready" if not missing else "source-aware schema incomplete; run guarded migration/repair before production import"}

    def _source_aware_empty_stats(self) -> dict[str, Any]:
        return {
            "source_sessions": 0,
            "missing_original_titles": 0,
            "memories_with_evidence": 0,
            "tool_turn_ratio": 0,
            "by_agent": [],
            "by_title_source": [],
            "by_display_title_source": [],
        }

    def _source_aware_session_where(self, q: str = "", mode: str = "sessions") -> tuple[str, tuple]:
        where: list[str] = []
        params: list[Any] = []
        if mode == "missing_titles":
            where.append("(COALESCE(ss.title_source,'')='missing' OR COALESCE(ss.display_title_source,'')!='agent_original')")
        if q:
            where.append("(COALESCE(ss.display_title,'') LIKE ? OR COALESCE(ss.original_title,'') LIKE ? OR COALESCE(ss.source_agent,'') LIKE ? OR COALESCE(ss.agent_session_id,'') LIKE ?)")
            params.extend([f"%{q}%"] * 4)
        return (" WHERE " + " AND ".join(where) if where else "", tuple(params))

    def _source_aware_stats(self) -> dict[str, Any]:
        total = db.fetchone("SELECT COUNT(*) AS c FROM source_sessions")
        missing = db.fetchone("SELECT COUNT(*) AS c FROM source_sessions WHERE COALESCE(title_source,'')='missing'")
        evidence = db.fetchone("SELECT COUNT(DISTINCT memory_id) AS c FROM memory_turn_sources")
        turns = db.fetchone("SELECT COUNT(*) AS total, SUM(CASE WHEN is_tool_call=1 OR is_tool_result=1 THEN 1 ELSE 0 END) AS toolish FROM source_turns")
        by_agent = db.fetchall("SELECT source_agent, COUNT(*) AS c FROM source_sessions GROUP BY source_agent ORDER BY c DESC LIMIT 12")
        by_title_source = db.fetchall("SELECT title_source, COUNT(*) AS c FROM source_sessions GROUP BY title_source ORDER BY c DESC")
        by_display_title_source = db.fetchall("SELECT display_title_source, COUNT(*) AS c FROM source_sessions GROUP BY display_title_source ORDER BY c DESC")
        total_turns = int(turns["total"] if turns and turns["total"] is not None else 0)
        toolish = int(turns["toolish"] if turns and turns["toolish"] is not None else 0)
        return {
            "source_sessions": int(total["c"] if total else 0),
            "missing_original_titles": int(missing["c"] if missing else 0),
            "memories_with_evidence": int(evidence["c"] if evidence else 0),
            "tool_turn_ratio": (toolish / total_turns) if total_turns else 0,
            "by_agent": [dict(r) for r in by_agent],
            "by_title_source": [dict(r) for r in by_title_source],
            "by_display_title_source": [dict(r) for r in by_display_title_source],
        }

    def source_session_review_update(self, source_session_id: str, review_status: str, note: str = "", postponed_until: str = "") -> dict[str, Any]:
        """更新来源会话处理队列状态。只写处理状态，不改原始 source/memory。"""
        self._ensure_init()
        allowed = {"new", "rule_processed", "needs_review", "needs_llm", "in_review", "done", "postponed", "has_issue"}
        if review_status not in allowed:
            return {"error": f"invalid review_status: {review_status}"}
        existing = db.fetchone("SELECT id FROM source_sessions WHERE id=?", (source_session_id,))
        if not existing:
            return {"error": "source session not found"}
        now = datetime.now().isoformat()
        db.execute(
            """INSERT INTO source_session_review_states
               (source_session_id, review_status, review_note, postponed_until, reviewed_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_session_id) DO UPDATE SET
                 review_status=excluded.review_status,
                 review_note=excluded.review_note,
                 postponed_until=excluded.postponed_until,
                 reviewed_at=excluded.reviewed_at,
                 updated_at=excluded.updated_at""",
            (source_session_id, review_status, note or "", postponed_until or None, now, now),
        )
        db.commit()
        row = db.fetchone("SELECT * FROM source_session_review_states WHERE source_session_id=?", (source_session_id,))
        return {"updated": True, "state": dict(row) if row else {}}

    def _infer_source_session_review_status(self, data: dict[str, Any]) -> str:
        if data.get("session_review_status"):
            return data["session_review_status"]
        memory_count = int(data.get("memory_count") or 0)
        if memory_count <= 0:
            return "rule_processed"
        if int(data.get("needs_llm_count") or 0) > 0:
            return "needs_llm"
        if int(data.get("noise_count") or 0) or int(data.get("temporary_task_count") or 0) or int(data.get("project_state_count") or 0):
            return "needs_review"
        return "rule_processed"

    def _source_aware_session_row(self, row) -> dict[str, Any]:
        data = dict(row)
        data["effective_review_status"] = self._infer_source_session_review_status(data)
        if data.get("source_path"):
            try:
                home = str(Path.home())
                if str(data["source_path"]).lower().startswith(home.lower()):
                    data["source_path"] = "~" + str(data["source_path"])[len(home):]
            except Exception:
                pass
        data["has_original_title"] = bool(data.get("original_title"))
        data["is_missing_title"] = data.get("title_source") == "missing" or data.get("display_title_source") != "agent_original"
        return data

    # ── 记忆治理 ──

    def memory_govern(self, memory_id: str, action: str, **kwargs) -> dict:
        """标记记忆状态、置顶、权重、备注等用户治理动作。"""
        self._ensure_init()
        return memory_store.govern_memory(memory_id=memory_id, action=action, **kwargs)

    def memory_audit(self, memory_id: str, limit: int = 50) -> list[dict]:
        """查看单条记忆治理审计日志。"""
        self._ensure_init()
        return memory_store.get_memory_audit(memory_id, limit=limit)

    def memory_link(
        self,
        source_memory_id: str,
        target_memory_id: str,
        relation_type: str = "MERGED_INTO",
        confidence: float = 0.8,
        reason: str = "",
        created_by: str = "engine",
    ) -> dict:
        """建立记忆治理关系。"""
        self._ensure_init()
        return memory_store.link_memories(source_memory_id, target_memory_id, relation_type, confidence, reason, created_by)

    def memory_links(self, memory_id: str, limit: int = 50) -> list[dict]:
        """获取记忆关系链。"""
        self._ensure_init()
        return memory_store.get_memory_links(memory_id, limit=limit)

    def governance_overview(self, limit: int = 50, page: int = 1, page_size: int = 50, q: str = "", tab: str = "all") -> dict[str, Any]:
        """记忆治理分页视图：去重、导入事件、合并链、同源组。"""
        self._ensure_init()
        page_size = max(1, min(int(page_size or limit or 50), 200))
        page = max(1, int(page or 1))
        offset = (page - 1) * page_size
        q = (q or "").strip()
        tab = tab or "source_groups"

        total_counts = {
            "source_groups": self._governance_source_groups_count(q=""),
            "dedupe_records": self._governance_table_count("memory_dedupe_records", q="", fields=["source_agent", "fact_key", "action_key", "entity_key", "decision", "reason"]),
            "memory_links": self._governance_table_count("memory_links", q="", fields=["source_memory_id", "target_memory_id", "relation_type", "reason", "created_by"]),
            "ingestion_events": self._governance_table_count("ingestion_events", q="", fields=["source_type", "source_agent", "source_session_id", "status", "reason"]),
            "governed_memories": self._governance_table_count("memory_units", q="", fields=["title", "summary", "memory_type", "status"], extra_where="status IN ('wrong','expired','muted','deleted')"),
        }
        filtered_counts = {
            "source_groups": self._governance_source_groups_count(q=q),
            "dedupe_records": self._governance_table_count("memory_dedupe_records", q=q, fields=["source_agent", "fact_key", "action_key", "entity_key", "decision", "reason"]),
            "memory_links": self._governance_table_count("memory_links", q=q, fields=["source_memory_id", "target_memory_id", "relation_type", "reason", "created_by"]),
            "ingestion_events": self._governance_table_count("ingestion_events", q=q, fields=["source_type", "source_agent", "source_session_id", "status", "reason"]),
            "governed_memories": self._governance_table_count("memory_units", q=q, fields=["title", "summary", "memory_type", "status"], extra_where="status IN ('wrong','expired','muted','deleted')"),
        }
        result = {
            "page": page,
            "page_size": page_size,
            "q": q,
            "tab": tab,
            "counts": total_counts,
            "filtered_counts": filtered_counts,
            "dedupe_records": [],
            "ingestion_events": [],
            "memory_links": [],
            "governed_memories": [],
            "source_groups": [],
        }
        if tab == "all":
            result["source_groups"] = self._governance_source_groups(limit=limit, offset=0, q=q)
            result["dedupe_records"] = self._governance_table_page("memory_dedupe_records", q=q, fields=["source_agent", "fact_key", "action_key", "entity_key", "decision", "reason"], order_by="created_at DESC", limit=limit, offset=0)
            result["memory_links"] = self._governance_table_page("memory_links", q=q, fields=["source_memory_id", "target_memory_id", "relation_type", "reason", "created_by"], order_by="created_at DESC", limit=limit, offset=0)
            result["ingestion_events"] = self._governance_table_page("ingestion_events", q=q, fields=["source_type", "source_agent", "source_session_id", "status", "reason"], order_by="created_at DESC", limit=limit, offset=0)
            result["governed_memories"] = self._governance_table_page("memory_units", q=q, fields=["title", "summary", "memory_type", "status"], extra_where="status IN ('wrong','expired','muted','deleted')", columns="id,title,status,memory_type,summary,updated_at", order_by="updated_at DESC", limit=limit, offset=0)
        elif tab == "dedupe_records":
            result["dedupe_records"] = self._governance_table_page("memory_dedupe_records", q=q, fields=["source_agent", "fact_key", "action_key", "entity_key", "decision", "reason"], order_by="created_at DESC", limit=page_size, offset=offset)
        elif tab == "memory_links":
            result["memory_links"] = self._governance_table_page("memory_links", q=q, fields=["source_memory_id", "target_memory_id", "relation_type", "reason", "created_by"], order_by="created_at DESC", limit=page_size, offset=offset)
        elif tab == "ingestion_events":
            result["ingestion_events"] = self._governance_table_page("ingestion_events", q=q, fields=["source_type", "source_agent", "source_session_id", "status", "reason"], order_by="created_at DESC", limit=page_size, offset=offset)
        elif tab == "governed_memories":
            result["governed_memories"] = self._governance_table_page("memory_units", q=q, fields=["title", "summary", "memory_type", "status"], extra_where="status IN ('wrong','expired','muted','deleted')", columns="id,title,status,memory_type,summary,updated_at", order_by="updated_at DESC", limit=page_size, offset=offset)
        else:
            result["tab"] = "source_groups"
            result["source_groups"] = self._governance_source_groups(limit=page_size, offset=offset, q=q)
        return result

    def _governance_where(self, q: str = "", fields: list[str] | None = None, extra_where: str = "") -> tuple[str, tuple]:
        where = []
        params: list[Any] = []
        if extra_where:
            where.append(f"({extra_where})")
        if q and fields:
            where.append("(" + " OR ".join([f"COALESCE({f}, '') LIKE ?" for f in fields]) + ")")
            params.extend([f"%{q}%"] * len(fields))
        return (" WHERE " + " AND ".join(where) if where else "", tuple(params))

    def _governance_table_count(self, table: str, q: str = "", fields: list[str] | None = None, extra_where: str = "") -> int:
        where, params = self._governance_where(q=q, fields=fields, extra_where=extra_where)
        row = db.fetchone(f"SELECT COUNT(*) AS c FROM {table}{where}", params)
        return int(row["c"] if row else 0)

    def _governance_table_page(self, table: str, q: str = "", fields: list[str] | None = None, extra_where: str = "", columns: str = "*", order_by: str = "created_at DESC", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        where, params = self._governance_where(q=q, fields=fields, extra_where=extra_where)
        rows = db.fetchall(f"SELECT {columns} FROM {table}{where} ORDER BY {order_by} LIMIT ? OFFSET ?", params + (limit, offset))
        return [dict(r) for r in rows]

    def _governance_source_groups_count(self, q: str = "") -> int:
        return len(self._governance_source_groups(limit=1_000_000, offset=0, q=q))

    def _governance_source_groups(self, limit: int = 50, offset: int = 0, q: str = "") -> list[dict[str, Any]]:
        """按同源输入聚合记忆，用于治理页避免 raw_text 相同的多条记忆平铺。"""
        from memo.dedupe.normalizer import normalize_conversation, stable_hash

        rows = db.fetchall(
            """SELECT id,title,summary,memory_type,status,confidence,created_at,updated_at,raw_text
               FROM memory_units
               WHERE raw_text IS NOT NULL AND trim(raw_text) != '' AND COALESCE(status,'active') != 'deleted'
               ORDER BY created_at DESC
               LIMIT 20000"""
        )
        groups: dict[str, dict[str, Any]] = {}
        for r in rows:
            raw = r["raw_text"] or ""
            normalized = normalize_conversation(raw)
            if not normalized:
                continue
            key = stable_hash(normalized)
            g = groups.setdefault(key, {"source_hash": key, "normalized_preview": normalized[:220], "members": []})
            member = {k: r[k] for k in r.keys() if k != "raw_text"}
            member["raw_length"] = len(raw)
            g["members"].append(member)

        result = []
        type_rank = {"DECISION": 0, "PREFERENCE": 1, "FACT": 2, "REASONING": 3, "EVENT": 4}
        for g in groups.values():
            members = g["members"]
            if len(members) <= 1:
                continue
            canonical = sorted(
                members,
                key=lambda m: (
                    0 if m.get("status", "active") == "active" else 1,
                    type_rank.get(str(m.get("memory_type", "FACT")).upper(), 9),
                    -float(m.get("confidence") or 0),
                    m.get("created_at") or "",
                ),
            )[0]
            g["count"] = len(members)
            g["canonical_id"] = canonical["id"]
            g["canonical_title"] = canonical.get("title", "")
            g["memory_types"] = sorted({str(m.get("memory_type", "")) for m in members if m.get("memory_type")})
            g["statuses"] = sorted({str(m.get("status", "active")) for m in members})
            g["created_at_min"] = min((m.get("created_at") or "") for m in members)
            g["created_at_max"] = max((m.get("created_at") or "") for m in members)
            result.append(g)

        if q:
            q_lower = q.lower()
            result = [
                g for g in result
                if q_lower in (g.get("canonical_title") or "").lower()
                or q_lower in (g.get("normalized_preview") or "").lower()
                or any(q_lower in (m.get("title") or "").lower() or q_lower in (m.get("summary") or "").lower() for m in g.get("members", []))
            ]
        result.sort(key=lambda g: (g["count"], g["created_at_max"]), reverse=True)
        return result[offset:offset + limit]

    # ── 待办管理 ──

    def todo_add(self, title: str, **kwargs) -> dict:
        """创建待办。"""
        self._ensure_init()
        from memo.todo.manager import add_todo
        return add_todo(title=title, **kwargs)

    def todo_search(self, **kwargs) -> list[dict]:
        """搜索待办。"""
        self._ensure_init()
        from memo.todo.manager import search_todos
        return search_todos(**kwargs)

    def todo_list(self, **kwargs) -> list[dict]:
        """列出待办。"""
        self._ensure_init()
        from memo.todo.manager import list_todos
        return list_todos(**kwargs)

    def todo_close(self, ids: list[str], **kwargs) -> list[dict]:
        """批量关闭待办。"""
        self._ensure_init()
        from memo.todo.manager import close_todos
        results = close_todos(ids, **kwargs)
        # 完成的待办写入记忆
        for r in results:
            if r.get("closed"):
                try:
                    session = self.start_session(title=f"待办完成")
                    self.remember_conversation(
                        session_id=session.id,
                        conversation=f"完成待办: {r['title']}",
                        auto_extract=True,
                    )
                    self.end_session(session.id)
                except Exception as e:
                    logger.debug(f"待办完成记忆写入失败: {e}")
        return results

    def todo_reopen(self, ids: list[str], **kwargs) -> list[dict]:
        """重新开启待办。"""
        self._ensure_init()
        from memo.todo.manager import reopen_todos
        return reopen_todos(ids, **kwargs)

    def todo_update(self, todo_id: str, **kwargs) -> dict:
        """更新待办。"""
        self._ensure_init()
        from memo.todo.manager import update_todo
        return update_todo(todo_id, **kwargs)

    def todo_check_risk(self) -> dict:
        """检测待办风险。"""
        self._ensure_init()
        from memo.todo.manager import check_risk
        return check_risk()

    def todo_stats(self) -> dict:
        """待办统计。"""
        self._ensure_init()
        from memo.todo.manager import get_todo_stats
        return get_todo_stats()

    def stats(self) -> dict[str, Any]:
        """获取记忆统计信息。"""
        self._ensure_init()
        sessions = db.fetchone("SELECT COUNT(*) as c FROM sessions")
        memories = db.fetchone("SELECT COUNT(*) as c FROM memory_units")
        tags = db.fetchone("SELECT COUNT(*) as c FROM feature_tags")
        relations = db.fetchone("SELECT COUNT(*) as c FROM feature_relations")
        hot_tags = graph_store.get_hot_tags(limit=10)

        return {
            "sessions": sessions["c"] if sessions else 0,
            "memories": memories["c"] if memories else 0,
            "feature_tags": tags["c"] if tags else 0,
            "relations": relations["c"] if relations else 0,
            "vector_index_size": vector_store.size,
            "top_tags": [t.name for t in hot_tags],
        }


# 全局单例
engine = Engine()
