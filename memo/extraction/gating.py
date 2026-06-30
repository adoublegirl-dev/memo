"""记忆价值门控（Memory Value Gating, MVG）

写入前用轻量 LLM 调用判断「这条对话是否值得长期记忆」。
参考 D-Mem Multi-dimensional Quality Gating + Mem0 生产经验。

评分维度（4 维，1-5 分）：
  - factuality:  是否包含具体事实（非闲聊）
  - decision:    是否包含决策、偏好或结论
  - persistence: 一周后是否仍有参考价值
  - uniqueness:  是否引入了新信息

门控规则：
  总分 = factuality×0.3 + decision×0.3 + persistence×0.25 + uniqueness×0.15
  总分 ≥ 3.0 → 写入
  总分 < 3.0 → 跳过
  2.5 ≤ 总分 < 3.0 → 灰色地带，写入但标记 confidence=low
"""

import re
from typing import Any

from memo.core.config import config
from memo.utils.llm import llm_client
from memo.utils.logger import logger

# ── 门控阈值 ──

GATING_THRESHOLD = 3.0      # 写入阈值
GRAY_ZONE_MIN = 2.5         # 灰色地带下限

# ── 权重 ──

WEIGHTS = {
    "factuality": 0.30,
    "decision": 0.30,
    "persistence": 0.25,
    "uniqueness": 0.15,
}

# ── LLM Prompt ──

_GATING_SYSTEM = """你是一个记忆价值评估引擎。你的任务是判断一段对话是否值得存入 AI Agent 的长期记忆系统。

长期记忆的标准：
- 包含可被未来检索锚定的具体事实、决策或偏好
- 一周后仍有参考价值
- 引入了新信息而非重复问候或闲聊

评分 1-5（1=完全没价值，5=极有价值），输出纯 JSON。"""

_GATING_PROMPT = """评估以下对话片段的长期记忆价值。

评分标准（1-5分）：
- factuality: 是否包含具体事实（不是闲聊、客套）
- decision: 是否包含决策、偏好或明确结论
- persistence: 一周后是否还有参考价值
- uniqueness: 是否引入了新概念、新关系或新信息

对话：
{conversation}

输出 JSON：{{"factuality": N, "decision": N, "persistence": N, "uniqueness": N}}"""


def evaluate_importance(conversation: str) -> dict[str, Any]:
    """评估对话片段的记忆价值。

    Args:
        conversation: 对话文本

    Returns:
        {
            "total_score": float,
            "scores": {"factuality": int, "decision": int, "persistence": int, "uniqueness": int},
            "verdict": "write" | "skip" | "gray",
            "method": "llm" | "rule",
            "reason": str,
        }
    """
    # 规则前置：明显无价值的直接跳过，节省 LLM 调用
    rule_result = _rule_precheck(conversation)
    if rule_result:
        return rule_result

    # LLM 评估
    if not llm_client.available:
        logger.info("MVG: LLM 不可用，使用规则降级")
        return _rule_fallback(conversation)

    if not config.gating_enabled:
        return {
            "total_score": 5.0,
            "scores": {"factuality": 5, "decision": 5, "persistence": 5, "uniqueness": 5},
            "verdict": "write",
            "method": "bypass",
            "reason": "门控未启用",
        }

    try:
        prompt = _GATING_PROMPT.format(conversation=conversation[:3000])
        result = llm_client.chat_json(
            messages=[
                {"role": "system", "content": _GATING_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=256,
        )
        scores = _normalize_scores(result)
        total = _compute_total(scores)
        verdict = _decide_verdict(total)

        logger.info(
            f"MVG: total={total:.2f} fact={scores['factuality']} "
            f"dec={scores['decision']} pers={scores['persistence']} "
            f"uniq={scores['uniqueness']} → {verdict}"
        )

        return {
            "total_score": round(total, 2),
            "scores": scores,
            "verdict": verdict,
            "method": "llm",
            "reason": "",
        }
    except Exception as e:
        logger.warning(f"MVG: LLM 调用失败 ({e})，降级为规则判断")
        return _rule_fallback(conversation)


def should_remember(conversation: str) -> tuple[bool, dict[str, Any]]:
    """便捷方法：返回是否应该写入 + 详细信息。

    Returns:
        (should_write, details_dict)
    """
    result = evaluate_importance(conversation)
    should = result["verdict"] in ("write", "gray")
    return should, result


# ── 内部函数 ──

def _compute_total(scores: dict[str, float]) -> float:
    """加权计算总分。"""
    return sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)


def _decide_verdict(total: float) -> str:
    """根据总分判定。"""
    if total >= GATING_THRESHOLD:
        return "write"
    elif total >= GRAY_ZONE_MIN:
        return "gray"
    else:
        return "skip"


def _normalize_scores(raw: dict) -> dict[str, int]:
    """标准化 LLM 输出的分数，裁剪到 1-5。"""
    scores = {}
    for dim in WEIGHTS:
        val = raw.get(dim, 3)
        if isinstance(val, (int, float)):
            scores[dim] = max(1, min(5, int(round(val))))
        else:
            scores[dim] = 3  # 默认中等
    return scores


def _rule_precheck(conversation: str) -> dict[str, Any] | None:
    """规则前置检查：明显无价值的直接跳过。

    Returns:
        如果判定为跳过则返回结果 dict，否则返回 None 表示需要 LLM 进一步判断。
    """
    text = conversation.strip()

    # 过短 → 跳过
    if len(text) < 30:
        return _make_skip("rule", "消息过短 (<30 字符)")

    # 纯问候/确认 → 跳过
    pure_greetings = {
        "嗯", "好的", "好", "ok", "OK", "行", "可以", "对", "是的",
        "谢谢", "不客气", "再见", "拜拜", "bye", "hi", "hello", "你好",
        "收到", "明白", "知道了", "了解",
    }
    if text in pure_greetings:
        return _make_skip("rule", "纯问候/确认消息")

    # 纯系统指令（如 "看板地址 localhost:9120"）→ 跳过
    if re.match(r"^(http|https)://", text) and len(text) < 80:
        return _make_skip("rule", "纯 URL 消息")

    # 非对话内容 → 跳过
    if text.startswith(("toolCall", "toolResult", "thinking")):
        return _make_skip("rule", "非对话消息")

    return None


def _rule_fallback(conversation: str) -> dict[str, Any]:
    """LLM 不可用时的规则降级。"""
    text = conversation.strip()
    length = len(text)

    # 基于长度的启发式评分
    if length > 500:
        scores = {"factuality": 4, "decision": 3, "persistence": 3, "uniqueness": 3}
    elif length > 200:
        scores = {"factuality": 3, "decision": 2, "persistence": 2, "uniqueness": 2}
    elif length > 100:
        scores = {"factuality": 2, "decision": 2, "persistence": 2, "uniqueness": 2}
    else:
        scores = {"factuality": 2, "decision": 1, "persistence": 1, "uniqueness": 1}

    total = _compute_total(scores)
    verdict = _decide_verdict(total)
    return {
        "total_score": round(total, 2),
        "scores": scores,
        "verdict": verdict,
        "method": "rule",
        "reason": "LLM 不可用，规则降级",
    }


def _make_skip(method: str, reason: str) -> dict[str, Any]:
    """构造跳过结果。"""
    return {
        "total_score": 0.0,
        "scores": {"factuality": 1, "decision": 1, "persistence": 1, "uniqueness": 1},
        "verdict": "skip",
        "method": method,
        "reason": reason,
    }
