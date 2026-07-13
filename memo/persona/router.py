"""人格路由器 —— 领域匹配度 + 三通道分流 + 偏离检测。

核心逻辑：
1. 计算用户问题与人格画像的领域匹配度
2. 根据匹配度分流入格通道 / 混合通道 / 经验通道
3. 人格通道内检测偏离
"""

from typing import Any

from memo.persona.extractor import get_active_assertions, get_sensitivity_level
from memo.utils.embedding import embedding_model
from memo.utils.logger import logger


def domain_match_score(question: str) -> float:
    """计算问题与人格画像的领域匹配度。

    用向量相似度：问题向量 × 所有活跃断言向量的 top-K 平均。

    Returns:
        0~1 的匹配分数
    """
    assertions = get_active_assertions()
    if not assertions:
        return 0.0

    q_vec = embedding_model.encode(question)

    scores = []
    for a in assertions:
        a_text = f"{a['dimension']}: {a['assertion']}"
        a_vec = embedding_model.encode(a_text)
        sim = embedding_model.cosine_similarity(q_vec, a_vec)
        scores.append(max(0, sim))  # 截断负值

    # Top-5 平均
    scores.sort(reverse=True)
    top_k = scores[:5]
    return sum(top_k) / len(top_k) if top_k else 0.0


def route(question: str) -> dict[str, Any]:
    """路由判断：决定问题走哪条通道。

    Returns:
        {
            "channel": "persona" | "mixed" | "experience",
            "score": float,           # 领域匹配度
            "threshold": float,       # 当前灵敏度阈值
            "deviation": dict | None, # 偏离检测结果（仅人格通道）
        }
    """
    threshold = get_sensitivity_level()
    score = domain_match_score(question)

    if score < 0.15:
        channel = "experience"
    elif score >= threshold:
        channel = "persona"
    else:
        channel = "mixed"

    result = {
        "channel": channel,
        "score": round(score, 4),
        "threshold": threshold,
    }

    # 人格通道内做偏离检测
    if channel == "persona":
        from memo.persona.deviation import detect_deviation
        result["deviation"] = detect_deviation(question)

    logger.debug(f"路由: channel={channel} score={score:.4f} threshold={threshold}")
    return result


def build_persona_reply(question: str, route_result: dict) -> dict[str, Any]:
    """根据路由结果构建人格化回复。

    Returns:
        {
            "reply": str,              # 人格化回复文本
            "citations": list[dict],   # 引用的记忆和断言
            "channel": str,
            "confidence": float,
        }
    """
    channel = route_result["channel"]
    assertions = get_active_assertions()

    if channel == "experience":
        return {
            "reply": "",
            "citations": [],
            "channel": "experience",
            "confidence": 0.0,
        }

    # 获取最相关的断言
    top_assertions = _rank_assertions(question, assertions)[:3]

    citations = []
    for a in top_assertions:
        citations.append({
            "type": "assertion",
            "id": a["id"],
            "dimension": a["dimension"],
            "assertion": a["assertion"],
            "confidence": a["confidence"],
        })

    if channel == "persona":
        # 用人格立场回复
        assertion_texts = [f"  - {a['assertion']}" for a in top_assertions]
        deviation = route_result.get("deviation", {})
        dev_note = ""
        if deviation and deviation.get("has_deviation"):
            dev_note = f"\n\n⚠️ 偏离提示: {deviation.get('note', '')}"

        reply = f"基于我对你的了解：\n" + "\n".join(assertion_texts) + dev_note
        return {
            "reply": reply,
            "citations": citations,
            "channel": "persona",
            "confidence": round(sum(a["confidence"] for a in top_assertions) / max(len(top_assertions), 1), 2),
        }

    else:  # mixed
        return {
            "reply": "",
            "citations": citations,
            "channel": "mixed",
            "confidence": 0.0,
        }


def _rank_assertions(question: str, assertions: list[dict]) -> list[dict]:
    """按与问题的相关性排序断言。"""
    q_vec = embedding_model.encode(question)
    scored = []
    for a in assertions:
        a_text = f"{a['dimension']}: {a['assertion']}"
        a_vec = embedding_model.encode(a_text)
        sim = embedding_model.cosine_similarity(q_vec, a_vec)
        scored.append((max(0, sim), a))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored]
