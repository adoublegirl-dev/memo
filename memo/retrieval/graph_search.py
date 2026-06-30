"""图扩散激活检索 —— 通道③的核心算法。

实现赫布扩散激活（Hebbian Spreading Activation）：
  1. 从 query 提取特征词作为种子节点
  2. BFS 扩散，每跳衰减 0.5
  3. 从激活的特征词着陆到关联的记忆单元
"""

from collections import defaultdict

from memo.core.config import config
from memo.models import RELATION_TYPE_FACTOR
from memo.store.graph_store import graph_store
from memo.store.vector_store import vector_store
from memo.utils.embedding import embedding_model
from memo.utils.logger import logger


class GraphSearch:
    """图扩散激活检索器。"""

    def spreading_activation(
        self,
        query: str,
        top_k: int = 20,
        max_hops: int | None = None,
        decay_rate: float | None = None,
    ) -> dict[str, float]:
        """执行扩散激活检索。

        Args:
            query: 用户查询
            top_k: 返回数量
            max_hops: 最大扩散跳数
            decay_rate: 每跳衰减率

        Returns:
            {memory_unit_id: activation_score, ...}
        """
        max_hops = max_hops or config.spreading_max_hops
        decay_rate = decay_rate or config.spreading_decay_rate

        # Step 1: 入口节点定位
        seed_tags = self._find_seed_tags(query)
        if not seed_tags:
            logger.debug("图扩散激活: 未找到入口特征词")
            return {}

        activation_map: dict[str, float] = {tid: 1.0 for tid in seed_tags}
        visited: set[str] = set(seed_tags)

        # Step 2: BFS 扩散激活
        for hop in range(max_hops):
            new_activations: dict[str, float] = defaultdict(float)
            current_ids = list(activation_map.keys())

            for tag_id in current_ids:
                current_activation = activation_map[tag_id]
                neighbors = graph_store.get_neighbors(tag_id, min_weight=0.05)

                for neighbor_tag, relation, is_outgoing in neighbors:
                    if neighbor_tag.id in visited:
                        # 已在激活图中，累加分数（多条路径）
                        factor = RELATION_TYPE_FACTOR.get(relation.relation_type, 1.0)
                        propagation = (
                            current_activation
                            * decay_rate
                            * relation.hebbian_weight
                            * factor
                        )
                        activation_map[neighbor_tag.id] = max(
                            activation_map.get(neighbor_tag.id, 0),
                            activation_map[neighbor_tag.id] + propagation * 0.3,  # 附加贡献
                        )
                        continue

                    factor = RELATION_TYPE_FACTOR.get(relation.relation_type, 1.0)
                    # 矛盾关系：负向激活（减少关联）
                    if factor < 0:
                        continue

                    propagation = (
                        current_activation
                        * decay_rate
                        * relation.hebbian_weight
                        * factor
                    )
                    new_activations[neighbor_tag.id] = max(
                        new_activations[neighbor_tag.id], propagation
                    )

            # 将新激活节点加入
            visited.update(new_activations.keys())
            activation_map.update(new_activations)

        # 归一化
        max_act = max(activation_map.values()) if activation_map else 1.0
        if max_act > 0:
            activation_map = {k: v / max_act for k, v in activation_map.items()}

        logger.debug(
            f"图扩散激活: {len(seed_tags)} 个种子 → {len(activation_map)} 个激活节点"
        )

        # Step 3: 着陆 —— 从特征词到记忆单元
        memory_scores: dict[str, float] = defaultdict(float)

        for tag_id, activation in activation_map.items():
            mentions = graph_store.get_tag_mentions(tag_id)
            for mention in mentions:
                memory_scores[mention.memory_unit_id] += (
                    activation * mention.relevance_score
                )

        # Step 4: 按分数排序
        sorted_scores = sorted(
            memory_scores.items(), key=lambda x: x[1], reverse=True
        )
        return dict(sorted_scores[:top_k])

    def _find_seed_tags(self, query: str) -> list[str]:
        """从查询中找到种子特征词。

        策略：
          1. 向量检索特征词（语义匹配）
          2. 取 top-3 最相似的特征词作为种子

        返回特征词 ID 列表。
        """
        # 用向量检索找匹配的特征词
        results = vector_store.search(query, top_k=5, search_tags=True)
        tag_ids = [
            rid.replace("tag:", "")
            for rid, score in results
            if rid.startswith("tag:") and score > 0.4
        ]
        return tag_ids[:3]


# 全局单例
graph_search = GraphSearch()
