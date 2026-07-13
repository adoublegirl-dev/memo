"""图存储层 —— 基于 SQLite 邻接表实现特征关系图谱。

核心操作：
- 添加/更新特征关系（赫布权重）
- 获取邻居节点
- 获取特征词的关联记忆单元
"""

from datetime import datetime
from typing import Any

import numpy as np

from memo.models import (
    FeatureRelation,
    FeatureTag,
    MemoryUnit,
    RelationType,
    RELATION_TYPE_FACTOR,
    TagMention,
)
from memo.store.database import (
    Database,
    blob_decode,
    blob_encode,
    db,
    json_decode,
    json_encode,
    new_id,
)
from memo.utils.logger import logger


class GraphStore:
    """特征关系图谱存储层。"""

    def __init__(self, database: Database = db):
        self.db = database

    # ── 特征词 ──

    def get_or_create_tag(
        self,
        name: str,
        category: str = "CONCEPT",
        embedding: np.ndarray | None = None,
    ) -> FeatureTag:
        """查找已有特征词，不存在则创建。自动标准化 category 为大写。"""
        # 标准化 category
        category = category.upper()
        valid = {'PERSON', 'OBJECT', 'LOCATION', 'EVENT', 'ORGANIZATION', 'CONCEPT'}
        if category not in valid:
            category = 'CONCEPT'
        row = self.db.fetchone(
            "SELECT * FROM feature_tags WHERE name = ?", (name,)
        )
        if row:
            return self._row_to_tag(row)

        now = datetime.now().isoformat()
        tag_id = new_id()
        emb_blob = blob_encode(embedding) if embedding is not None else None
        self.db.execute(
            """INSERT INTO feature_tags (id, name, category, first_seen_at, embedding)
               VALUES (?, ?, ?, ?, ?)""",
            (tag_id, name, category, now, emb_blob),
        )
        self.db.commit()
        logger.debug(f"新建特征词: {name} ({tag_id[:8]})")
        return FeatureTag(
            id=tag_id,
            name=name,
            category=category,
            first_seen_at=now,
            embedding=embedding,
        )

    def get_tag(self, tag_id: str) -> FeatureTag | None:
        row = self.db.fetchone("SELECT * FROM feature_tags WHERE id = ?", (tag_id,))
        return self._row_to_tag(row) if row else None

    def get_tags_by_name(self, names: list[str]) -> list[FeatureTag]:
        """批量按名称查找。"""
        placeholders = ",".join("?" * len(names))
        rows = self.db.fetchall(
            f"SELECT * FROM feature_tags WHERE name IN ({placeholders})", names
        )
        return [self._row_to_tag(r) for r in rows]

    def get_hot_tags(self, limit: int = 50) -> list[FeatureTag]:
        """获取权重最高的特征词（L0 热记忆体）。"""
        rows = self.db.fetchall(
            """SELECT * FROM feature_tags
               WHERE is_dormant = 0
               ORDER BY (storage_strength * retrieval_strength) DESC
               LIMIT ?""",
            (limit,),
        )
        return [self._row_to_tag(r) for r in rows]

    def activate_tag(self, tag_id: str, increment: float = 0.01) -> None:
        """激活特征词：增加存储强度 + 重置检索强度 + 更新激活时间。"""
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE feature_tags
               SET storage_strength = MIN(storage_strength + ?, 1.0),
                   retrieval_strength = MIN(retrieval_strength + (1.0 - retrieval_strength) * 0.1, 1.0),
                   total_activations = total_activations + 1,
                   last_activated_at = ?,
                   cooldown_days = 0.0,
                   is_dormant = 0
               WHERE id = ?""",
            (increment, now, tag_id),
        )
        self.db.commit()

    def _row_to_tag(self, row) -> FeatureTag:
        emb = blob_decode(row["embedding"]) if row["embedding"] else None
        return FeatureTag(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            storage_strength=row["storage_strength"],
            retrieval_strength=row["retrieval_strength"],
            total_activations=row["total_activations"],
            last_activated_at=row["last_activated_at"] or "",
            cooldown_days=row["cooldown_days"] or 0.0,
            first_seen_at=row["first_seen_at"] or "",
            created_by=row["created_by"],
            embedding=emb,
            is_dormant=bool(row["is_dormant"]),
        )

    # ── 特征关系 ──

    def upsert_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType = RelationType.CO_OCCUR,
        semantic_similarity: float = 0.0,
        context: str | None = None,
        session_id: str = "",
    ) -> FeatureRelation:
        """创建或更新特征关系（赫布权重更新 + SCB 会话加成）。

        Args:
            session_id: 当前会话 ID，用于 SCB 会话凝聚力加成。
                       同会话内多次共现获得额外权重。
        """
        from memo.core.config import config as cfg
        now = datetime.now().isoformat()

        existing = self.db.fetchone(
            """SELECT * FROM feature_relations
               WHERE source_tag_id = ? AND target_tag_id = ? AND relation_type = ?""",
            (source_id, target_id, relation_type.value),
        )

        if existing:
            # 更新：赫布权重增长
            old_weight = existing["hebbian_weight"]
            count = existing["co_activation_count"] + 1
            boost = min(count / 10, 2.0)  # 共现加成，上限 2x

            # SCB 会话加成：同一 session 内多次共现额外加权
            session_boost = 1.0
            if session_id and (existing["last_session_id"] if "last_session_id" in existing.keys() else "") == session_id:
                # 同会话内已共现过，根据配置计算加成
                session_alpha = getattr(cfg, "session_boost_alpha", 0.5)
                session_co_count = min(count / 5, 1.0)
                session_boost = 1.0 + session_alpha * session_co_count

            new_weight = old_weight + 0.05 * (1.0 - old_weight) * max(semantic_similarity, 0.1) * boost * session_boost
            new_weight = min(new_weight, 1.0)

            # 更新上下文（追加，最多 3 条）
            contexts = json_decode(existing["contexts"] or "[]")
            if context and len(contexts) < 3:
                contexts.append(context)

            self.db.execute(
                """UPDATE feature_relations
                   SET hebbian_weight = ?, co_activation_count = ?,
                       last_co_activated_at = ?, contexts = ?, last_session_id = ?
                   WHERE id = ?""",
                (new_weight, count, now, json_encode(contexts), session_id or "", existing["id"]),
            )
            self.db.commit()
            return FeatureRelation(
                id=existing["id"],
                source_tag_id=source_id,
                target_tag_id=target_id,
                relation_type=relation_type,
                hebbian_weight=new_weight,
                co_activation_count=count,
                last_co_activated_at=now,
                first_observed_at=existing["first_observed_at"],
                contexts=contexts,
                last_session_id=session_id or "",
            )
        else:
            # 新建
            rel_id = new_id()
            initial_weight = 0.05 * max(semantic_similarity, 0.1)
            contexts = [context] if context else []
            self.db.execute(
                """INSERT INTO feature_relations
                   (id, source_tag_id, target_tag_id, relation_type, hebbian_weight,
                    co_activation_count, last_co_activated_at, first_observed_at, contexts, last_session_id)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                (rel_id, source_id, target_id, relation_type.value, initial_weight,
                 now, now, json_encode(contexts), session_id or ""),
            )
            self.db.commit()
            return FeatureRelation(
                id=rel_id,
                source_tag_id=source_id,
                target_tag_id=target_id,
                relation_type=relation_type,
                hebbian_weight=initial_weight,
                co_activation_count=1,
                last_co_activated_at=now,
                first_observed_at=now,
                contexts=contexts,
                last_session_id=session_id or "",
            )

    def get_neighbors(
        self, tag_id: str, min_weight: float = 0.05
    ) -> list[tuple[FeatureTag, FeatureRelation, bool]]:
        """获取特征词的所有邻居，返回 (邻居词, 关系, 是否出边)。

        双向查找：同时查 source→target 和 target→source。
        """
        neighbors = []

        # 作为 source（出边）
        out_rows = self.db.fetchall(
            """SELECT fr.*, ft.* FROM feature_relations fr
               JOIN feature_tags ft ON fr.target_tag_id = ft.id
               WHERE fr.source_tag_id = ? AND fr.hebbian_weight >= ? AND ft.is_dormant = 0""",
            (tag_id, min_weight),
        )
        for row in out_rows:
            tag = self._row_to_tag(row)
            rel = FeatureRelation(
                id=row["id"],
                source_tag_id=row["source_tag_id"],
                target_tag_id=row["target_tag_id"],
                relation_type=row["relation_type"],
                hebbian_weight=row["hebbian_weight"],
                co_activation_count=row["co_activation_count"],
                last_co_activated_at=row["last_co_activated_at"] or "",
                first_observed_at=row["first_observed_at"] or "",
                contexts=json_decode(row["contexts"] or "[]"),
            )
            neighbors.append((tag, rel, True))

        # 作为 target（入边）
        in_rows = self.db.fetchall(
            """SELECT fr.*, ft.* FROM feature_relations fr
               JOIN feature_tags ft ON fr.source_tag_id = ft.id
               WHERE fr.target_tag_id = ? AND fr.hebbian_weight >= ? AND ft.is_dormant = 0""",
            (tag_id, min_weight),
        )
        for row in in_rows:
            tag = self._row_to_tag(row)
            rel = FeatureRelation(
                id=row["id"],
                source_tag_id=row["source_tag_id"],
                target_tag_id=row["target_tag_id"],
                relation_type=row["relation_type"],
                hebbian_weight=row["hebbian_weight"],
                co_activation_count=row["co_activation_count"],
                last_co_activated_at=row["last_co_activated_at"] or "",
                first_observed_at=row["first_observed_at"] or "",
                contexts=json_decode(row["contexts"] or "[]"),
            )
            neighbors.append((tag, rel, False))

        return neighbors

    # ── 特征词↔记忆单元关联 ──

    def create_mention(
        self,
        tag_id: str,
        memory_unit_id: str,
        mention_type: str = "DIRECT",
        relevance_score: float = 0.5,
    ) -> TagMention:
        mention_id = new_id()
        self.db.execute(
            """INSERT INTO tag_mentions (id, tag_id, memory_unit_id, mention_type, relevance_score)
               VALUES (?, ?, ?, ?, ?)""",
            (mention_id, tag_id, memory_unit_id, mention_type, relevance_score),
        )
        self.db.commit()
        return TagMention(
            id=mention_id,
            tag_id=tag_id,
            memory_unit_id=memory_unit_id,
            mention_type=mention_type,
            relevance_score=relevance_score,
        )

    def get_tag_mentions(self, tag_id: str) -> list[TagMention]:
        """获取特征词关联的所有记忆单元。"""
        rows = self.db.fetchall(
            "SELECT * FROM tag_mentions WHERE tag_id = ?", (tag_id,)
        )
        return [
            TagMention(
                id=r["id"],
                tag_id=r["tag_id"],
                memory_unit_id=r["memory_unit_id"],
                mention_type=r["mention_type"],
                relevance_score=r["relevance_score"],
                position_index=r["position_index"],
            )
            for r in rows
        ]

    def get_memory_tags(self, memory_unit_id: str) -> list[FeatureTag]:
        """获取记忆单元关联的所有特征词。"""
        rows = self.db.fetchall(
            """SELECT ft.* FROM feature_tags ft
               JOIN tag_mentions tm ON ft.id = tm.tag_id
               WHERE tm.memory_unit_id = ?""",
            (memory_unit_id,),
        )
        return [self._row_to_tag(r) for r in rows]


# 全局单例
graph_store = GraphStore()
