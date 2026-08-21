"""嵌入模型包装 —— 本地 BGE-small，首次运行自动下载。

设置 HF_HUB_OFFLINE=1 和 TRANSFORMERS_OFFLINE=1 避免网络超时。
模型已缓存时零网络请求。

延迟加载：sentence-transformers（及其传递依赖 torch/transformers）只在
首次访问 model 或首次 encode 时才导入，避免任何入口 import 本模块
（例如 memo.core.engine）时付出 3~10 秒的重型依赖冷启动开销。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np

from memo.core.config import config
from memo.utils.logger import logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class EmbeddingModel:
    """单例嵌入模型，懒加载。"""

    _instance: EmbeddingModel | None = None
    _model: SentenceTransformer | None = None

    def __new__(cls) -> EmbeddingModel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def _load_model() -> SentenceTransformer:
        """首次需要模型时才导入 sentence-transformers 并加载模型。"""
        from sentence_transformers import SentenceTransformer

        logger.info(f"加载嵌入模型: {config.embedding_model_name}")
        model = SentenceTransformer(config.embedding_model_name)
        try:
            actual_dim = model.get_embedding_dimension()
        except (AttributeError, TypeError):
            actual_dim = getattr(model, "get_sentence_embedding_dimension", model.get_embedding_dimension)()
        logger.info(f"嵌入模型就绪，维度={actual_dim}")
        return model

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = self._load_model()
        return self._model

    def encode(self, text: str | list[str]) -> np.ndarray:
        """编码文本为嵌入向量，返回 float32 数组。"""
        return self.model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    def encode_batch(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """批量编码。"""
        return self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=batch_size,
        )

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """两个归一化向量的余弦相似度（即点积）。"""
        return float(np.dot(a, b))


# 全局单例
embedding_model = EmbeddingModel()
