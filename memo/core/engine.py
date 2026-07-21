"""记忆引擎总入口 —— 对外提供统一的记忆读写接口。

所有外部调用通过 Engine 进行，不直接访问底层 store。
"""

from datetime import datetime
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
                    },
                })

        enriched.sort(key=lambda x: x["score"], reverse=True)
        return enriched[:top_k]

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

    def build_persona_baseline(self) -> dict[str, Any]:
        """批量建人格基线（首次运行）。

        采样 L2+L1+高价值 L0 记忆 → 10 维逐维提炼 → 初始断言。
        仅需运行一次，后续用 run_lifecycle() 做增量更新。
        """
        self._ensure_init()
        from memo.persona.extractor import build_persona_baseline as _build
        return _build()

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
