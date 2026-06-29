"""RRF 融合 + 可选 LLM 重排。"""

from collections import defaultdict

from memo.core.config import config
from memo.utils.logger import logger


def rrf_fuse(
    vec: dict[str, float],
    bm25: dict[str, float],
    graph: dict[str, float],
    top_k: int = 5,
    k: int | None = None,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion 融合三个通道的结果。

    公式：RRF(doc) = Σ 1 / (k + rank(doc))
    k 默认为 60（经典参数）。

    Args:
        vec: {memory_id: score} 向量通道
        bm25: {memory_id: score} BM25 通道
        graph: {memory_id: score} 图扩散通道
        top_k: 返回数量
        k: RRF 参数

    Returns:
        [(memory_id, fused_score), ...] 按融合分数降序
    """
    k = k or config.rrf_k

    # 按分数排序得到每个通道的排名
    vec_ranked = sorted(vec.items(), key=lambda x: x[1], reverse=True)
    bm25_ranked = sorted(bm25.items(), key=lambda x: x[1], reverse=True)
    graph_ranked = sorted(graph.items(), key=lambda x: x[1], reverse=True)

    # 建立排名映射
    def build_rank_map(ranked: list[tuple[str, float]]) -> dict[str, int]:
        return {doc_id: rank + 1 for rank, (doc_id, _) in enumerate(ranked)}

    vec_ranks = build_rank_map(vec_ranked)
    bm25_ranks = build_rank_map(bm25_ranked)
    graph_ranks = build_rank_map(graph_ranked)

    # 收集所有出现过的文档
    all_docs = set(vec_ranks.keys()) | set(bm25_ranks.keys()) | set(graph_ranks.keys())

    # 计算 RRF 分数
    scores: dict[str, float] = {}
    for doc_id in all_docs:
        score = 0.0
        if doc_id in vec_ranks:
            score += 1.0 / (k + vec_ranks[doc_id])
        if doc_id in bm25_ranks:
            score += 1.0 / (k + bm25_ranks[doc_id])
        if doc_id in graph_ranks:
            score += 1.0 / (k + graph_ranks[doc_id])
        scores[doc_id] = score

    # 排序
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    logger.debug(
        f"RRF 融合: vec={len(vec)} bm25={len(bm25)} graph={len(graph)} → {len(scores)} 个文档"
    )

    return sorted_scores[:top_k]
