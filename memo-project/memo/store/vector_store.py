"""向量存储 —— 基于内存 numpy 数组的简单向量索引。

对于小规模（<10万条），内存索引完全够用，避免了 pgvector 的外部依赖。
后续可迁移到 pgvector / Qdrant / FAISS。
"""

from typing import Any

import numpy as np

from memo.store.database import blob_decode, blob_encode, db
from memo.utils.embedding import embedding_model
from memo.utils.logger import logger


class VectorStore:
    """内存向量索引 + SQLite BLOB 存储。

    写入：编码 → 存 BLOB → 更新内存索引
    检索：编码 query → cosine 相似度 → top-K
    """

    def __init__(self):
        self._index: dict[str, np.ndarray] = {}  # memory_id → embedding
        self._dirty_ids: set[str] = set()  # 待写回磁盘的 ID

    def load_all(self) -> None:
        """从数据库加载所有嵌入向量到内存索引。"""
        rows = db.fetchall("SELECT id, embedding FROM memory_units WHERE embedding IS NOT NULL")
        for row in rows:
            if row["embedding"]:
                self._index[row["id"]] = blob_decode(row["embedding"])
        rows = db.fetchall("SELECT id, embedding FROM feature_tags WHERE embedding IS NOT NULL")
        for row in rows:
            if row["embedding"]:
                self._index[f"tag:{row['id']}"] = blob_decode(row["embedding"])
        logger.info(f"向量索引已加载: {len(self._index)} 条")

    def add_memory(self, memory_id: str, text: str) -> np.ndarray:
        """编码并存储记忆单元的嵌入。"""
        emb = embedding_model.encode(text)
        db.execute(
            "UPDATE memory_units SET embedding = ? WHERE id = ?",
            (blob_encode(emb), memory_id),
        )
        db.commit()
        self._index[memory_id] = emb
        return emb

    def add_tag(self, tag_id: str, text: str) -> np.ndarray:
        """编码并存储特征词的嵌入。"""
        emb = embedding_model.encode(text)
        db.execute(
            "UPDATE feature_tags SET embedding = ? WHERE id = ?",
            (blob_encode(emb), tag_id),
        )
        db.commit()
        self._index[f"tag:{tag_id}"] = emb
        return emb

    def search(
        self,
        query: str,
        top_k: int = 20,
        search_tags: bool = False,
    ) -> list[tuple[str, float]]:
        """向量语义检索，返回 (id, cosine_similarity) 列表。

        Args:
            query: 查询文本
            top_k: 返回数量
            search_tags: 是否同时搜索特征词
        """
        query_emb = embedding_model.encode(query)
        scores: list[tuple[str, float]] = []

        for mem_id, emb in self._index.items():
            if not search_tags and mem_id.startswith("tag:"):
                continue
            sim = float(np.dot(query_emb, emb))
            scores.append((mem_id, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def search_among(
        self,
        query: str,
        candidate_ids: list[str],
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        """在指定候选集中检索（用于图扩散后的语义过滤）。"""
        if not candidate_ids:
            return []

        query_emb = embedding_model.encode(query)
        scores: list[tuple[str, float]] = []

        for mem_id in candidate_ids:
            if mem_id in self._index:
                sim = float(np.dot(query_emb, self._index[mem_id]))
                scores.append((mem_id, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    @property
    def size(self) -> int:
        return len(self._index)


# 全局单例
vector_store = VectorStore()
