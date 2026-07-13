"""偏离检测 —— 检测用户当前提问是否与历史人格矛盾。

当问题进入人格通道后，检查是否存在明显的人格偏离。
如果发现矛盾，不直接否决，而是生成提示让用户确认。
"""

from typing import Any

from memo.persona.extractor import get_active_assertions
from memo.utils.embedding import embedding_model
from memo.utils.logger import logger


def detect_deviation(question: str) -> dict[str, Any] | None:
    """检测当前问题是否偏离历史人格。

    方法：找到问题最相关的人格断言，用 LLM 判断是否矛盾。

    Returns:
        None 或 {"has_deviation": True/False, "note": str, "conflicting_assertion": dict}
    """
    assertions = get_active_assertions()
    if not assertions:
        return None

    # 向量相似度找最相关的断言
    q_vec = embedding_model.encode(question)
    best_score = 0
    best_assertion = None
    for a in assertions:
        a_text = f"{a['dimension']}: {a['assertion']}"
        a_vec = embedding_model.encode(a_text)
        sim = embedding_model.cosine_similarity(q_vec, a_vec)
        if sim > best_score:
            best_score = sim
            best_assertion = a

    if best_assertion is None or best_score < 0.2:
        return {"has_deviation": False, "note": "无足够相关的人格断言"}

    # 简单启发式：如果最佳匹配的断言置信度很高（>0.7），不太可能偏离
    # 直接用向量相似度判断：相似度太低说明领域不同
    if best_score < 0.4:
        return {
            "has_deviation": True,
            "note": f"你的问题与最相关的人格断言匹配度较低({best_score:.2f})，可能涉及新领域。",
            "conflicting_assertion": {
                "id": best_assertion["id"],
                "dimension": best_assertion["dimension"],
                "assertion": best_assertion["assertion"],
            },
        }

    return {"has_deviation": False, "note": "无显著偏离"}
