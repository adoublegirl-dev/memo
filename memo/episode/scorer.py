"""Episode 长期价值评分。

评分用于 dry-run 候选排序和导入闸门。它不是最终真理，用户确认与治理优先。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from memo.episode.model import Episode


_POSITIVE_RULES: list[tuple[str, float, str]] = [
    (r"\b(决定|决策|确认|结论|最终|采用|放弃|推荐|原则)\b", 0.18, "包含明确决策或结论"),
    (r"\b(项目|版本|发布|上线|部署|打包|Release|GitHub|commit|迁移|schema)\b", 0.16, "包含项目进展或发布部署信息"),
    (r"\b(偏好|喜欢|讨厌|倾向|要求|原则|红线|不要|必须)\b", 0.16, "包含用户偏好或长期原则"),
    (r"\b(修复|根因|报错|事故|风险|回滚|备份|恢复|排查)\b", 0.16, "包含事故、风险或修复结论"),
    (r"\b(待办|提醒|计划|下一步|后续|todo|TODO)\b", 0.12, "包含计划或待办线索"),
    (r"([A-Za-z]:\\|/root/|localhost:\d+|\b\d{1,5}\b|\.bat|\.py|\.db|\.exe)", 0.10, "包含路径、端口或环境信息"),
]

_NEGATIVE_RULES: list[tuple[str, float, str]] = [
    (r"\b(我先|正在|准备|继续检查|等待|工具|调用|snapshot|loading)\b", -0.12, "偏模型过程或工具过程"),
    (r"^(好的|收到|明白|可以|嗯|谢谢)[。！!\s]*$", -0.35, "临时寒暄或低信息回复"),
    (r"Traceback|Command exited|PowerShell|stdout|stderr", -0.10, "偏原始工具日志"),
]

_SENSITIVE_RULES: list[tuple[str, str]] = [
    (r"(?i)(api[_-]?key|secret|token|password|passwd|密码|密钥)\s*[:=]", "疑似密钥/密码字段"),
    (r"(?i)sk-[A-Za-z0-9_-]{16,}", "疑似 API token"),
]


@dataclass
class ScoreResult:
    score: float
    reasons: list[str] = field(default_factory=list)
    skip_reasons: list[str] = field(default_factory=list)
    sensitive_hints: list[str] = field(default_factory=list)


class EpisodeQualityScorer:
    """规则型长期价值评分器。后续可替换/叠加 LLM scorer。"""

    recommended_threshold = 0.70
    manual_threshold = 0.45

    def score(self, episode: Episode) -> ScoreResult:
        text = self._episode_text(episode)
        if not text.strip():
            return ScoreResult(score=0.0, skip_reasons=["空 episode"])

        score = 0.25
        reasons: list[str] = []
        skip_reasons: list[str] = []
        sensitive_hints: list[str] = []

        user_count = len(episode.user_turns)
        assistant_count = len(episode.assistant_turns)
        if user_count:
            score += 0.10
            reasons.append("包含用户意图")
        if assistant_count:
            score += 0.06
            reasons.append("包含处理结果或回复")
        if len(text) >= 300:
            score += 0.08
            reasons.append("上下文较完整")
        if len(text) >= 1200:
            score += 0.05
            reasons.append("信息量较高")

        for pattern, delta, reason in _POSITIVE_RULES:
            if re.search(pattern, text, re.IGNORECASE):
                score += delta
                reasons.append(reason)
        for pattern, delta, reason in _NEGATIVE_RULES:
            if re.search(pattern, text, re.IGNORECASE):
                score += delta
                skip_reasons.append(reason)
        for pattern, hint in _SENSITIVE_RULES:
            if re.search(pattern, text):
                sensitive_hints.append(hint)
                score -= 0.20
                skip_reasons.append("包含疑似敏感字段，需人工确认或跳过")

        # 只有工具/系统内容，不作为长期记忆候选。
        if not user_count and not assistant_count:
            score = min(score, 0.20)
            skip_reasons.append("仅包含工具/系统过程")

        score = max(0.0, min(1.0, round(score, 3)))
        return ScoreResult(
            score=score,
            reasons=self._dedupe(reasons),
            skip_reasons=self._dedupe(skip_reasons),
            sensitive_hints=self._dedupe(sensitive_hints),
        )

    def classify(self, score: float) -> str:
        if score >= self.recommended_threshold:
            return "recommended"
        if score >= self.manual_threshold:
            return "manual_review"
        return "skip"

    def _episode_text(self, episode: Episode) -> str:
        return "\n".join(t.content for t in episode.turns if t.content)

    def _dedupe(self, items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result
