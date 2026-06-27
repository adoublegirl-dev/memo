"""嵌入模型包装 —— 本地 BGE-small，首次运行自动下载。"""

import numpy as np
from sentence_transformers import SentenceTransformer

from memo.core.config import config
from memo.utils.logger import logger


class EmbeddingModel:
    """单例嵌入模型，懒加载。"""

    _instance: "EmbeddingModel | None" = None
    _model: SentenceTransformer | None = None

    def __new__(cls) -> "EmbeddingModel":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info(f"加载嵌入模型: {config.embedding_model_name}")
            self._model = SentenceTransformer(config.embedding_model_name)
            try:
                actual_dim = self._model.get_embedding_dimension()
            except (AttributeError, TypeError):
                actual_dim = getattr(self._model, 'get_sentence_embedding_dimension', self._model.get_embedding_dimension)()
            logger.info(f"嵌入模型就绪，维度={actual_dim}")
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
