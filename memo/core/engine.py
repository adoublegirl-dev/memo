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

    def start_session(self, title: str = "", agent_id: str = "ASH") -> Session:
        """开始新会话。"""
        self._ensure_init()
        return memory_store.create_session(agent_id=agent_id, title=title)

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

        # 写入记忆单元（手动模式 signal_level=L2）
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
        }

    # ── 记忆检索（核心） ──

    def recall(
        self,
        query: str,
        top_k: int | None = None,
        current_session_id: str | None = None,
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
        graph_results = self._channel_graph(query, top_k=20, current_session_id=current_session_id)

        # RRF 融合
        fused = self._rrf_fuse(vec_results, bm25_results, graph_results, top_k=top_k)

        # 补充记忆单元详情
        enriched = []
        for mem_id, score in fused:
            mem = memory_store.get_memory(mem_id)
            if mem and not mem.is_superseded:
                # ESA 信号加权
                signal_multiplier = {0: 0.7, 1: 1.0, 2: 1.5}
                adjusted_score = score * signal_multiplier.get(mem.signal_level, 1.0)
                # 获取关联特征词
                tags = graph_store.get_memory_tags(mem_id)
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
                    "feature_tags": [t.name for t in tags],
                    "session_id": mem.session_id,
                    "from_current_session": (
                        mem.session_id == current_session_id
                        if current_session_id
                        else False
                    ),
                    "valid_from": mem.valid_from,
                })

        return enriched

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

    def _channel_graph(self, query: str, top_k: int = 20, current_session_id: str | None = None) -> dict[str, float]:
        """通道③：图扩散激活检索。"""
        from memo.retrieval.graph_search import graph_search

        return graph_search.spreading_activation(query, top_k=top_k, current_session_id=current_session_id)

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
