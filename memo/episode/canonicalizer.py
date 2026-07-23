"""Episode → CanonicalMemoryDraft 规范化器。

Phase 1 使用可解释的规则型摘要，避免 dry-run 阶段消耗大量 token。
"""

from __future__ import annotations

import re

from memo.episode.model import CanonicalMemoryDraft, Episode, Turn
from memo.episode.scorer import EpisodeQualityScorer

_TAG_PATTERNS: list[tuple[str, str]] = [
    (r"Memo|记忆系统|memory", "Memo"),
    (r"Space|项目|空间", "Context Space"),
    (r"GitHub|Release|commit|tag", "GitHub"),
    (r"Electron|桌面助手|Desktop Companion|exe|安装包", "桌面助手"),
    (r"schema|migration|数据库|SQLite|memo\.db", "数据库治理"),
    (r"MCP|Agent|HanaAgent|WorkBuddy|Qoder|Codex|Claude|Cursor", "Agent 集成"),
    (r"待办|提醒|todo", "待办"),
]

_DECISION_RE = re.compile(r"(决定|确认|结论|最终|采用|推荐|不再|不要|必须|已完成|完成|发布成功|修复)")


def _clean(text: str, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text[:limit] + ("…" if len(text) > limit else "")


def _non_tool_turns(turns: list[Turn]) -> list[Turn]:
    return [t for t in turns if not t.is_tool_or_system and t.content.strip()]


class EpisodeCanonicalizer:
    """生成长期记忆候选，不直接写入数据库。"""

    def __init__(self, scorer: EpisodeQualityScorer | None = None):
        self.scorer = scorer or EpisodeQualityScorer()

    def canonicalize(self, episode: Episode) -> CanonicalMemoryDraft:
        score = self.scorer.score(episode)
        user_turn = episode.user_turns[0] if episode.user_turns else None
        assistant_turns = episode.assistant_turns
        final_turn = self._final_assistant_turn(assistant_turns)
        meaningful_turns = _non_tool_turns(episode.turns)

        key_facts = self._extract_key_facts(meaningful_turns)
        conclusion = _clean(final_turn.content if final_turn else "")
        decision = self._extract_decision(meaningful_turns)
        tags = self._suggest_tags(episode, key_facts + [decision, conclusion])
        classification = self.scorer.classify(score.score)

        draft = CanonicalMemoryDraft(
            episode_id=episode.id,
            title=episode.title or _clean(user_turn.content if user_turn else "未命名记忆", 42),
            user_intent=_clean(user_turn.content if user_turn else episode.user_intent, 180),
            key_facts=key_facts,
            process_summary=self._process_summary(episode),
            final_conclusion=conclusion,
            decision_or_result=decision,
            future_impact=self._future_impact(meaningful_turns),
            suggested_memory_type=self._memory_type(meaningful_turns),
            confidence=score.score,
            long_term_value_score=score.score,
            feature_tags=tags,
            source_turn_ids=[t.turn_id for t in episode.turns],
            sensitive_hints=score.sensitive_hints,
            skip=classification == "skip" or bool(score.sensitive_hints),
            skip_reasons=score.skip_reasons + (["低长期价值，默认跳过"] if classification == "skip" else []),
        )
        return draft

    def _final_assistant_turn(self, turns: list[Turn]) -> Turn | None:
        finals = [t for t in turns if t.is_final]
        return finals[-1] if finals else (turns[-1] if turns else None)

    def _extract_key_facts(self, turns: list[Turn], limit: int = 5) -> list[str]:
        facts: list[str] = []
        for turn in turns:
            sentences = re.split(r"(?<=[。！？!?])\s+|\n+", turn.content)
            for sentence in sentences:
                s = _clean(sentence, 160)
                if len(s) < 12:
                    continue
                if re.search(r"(路径|端口|版本|schema|数据库|发布|修复|决定|要求|原则|安装|配置|项目|用户|风险|备份)", s, re.I):
                    facts.append(s)
                if len(facts) >= limit:
                    return self._dedupe(facts)
        # 兜底：取用户意图和最终回复的短句
        for turn in turns[:3]:
            s = _clean(turn.content, 160)
            if len(s) >= 12:
                facts.append(s)
            if len(facts) >= min(2, limit):
                break
        return self._dedupe(facts[:limit])

    def _extract_decision(self, turns: list[Turn]) -> str:
        candidates = []
        for turn in turns:
            for sentence in re.split(r"(?<=[。！？!?])\s+|\n+", turn.content):
                if _DECISION_RE.search(sentence):
                    candidates.append(_clean(sentence, 220))
        return candidates[-1] if candidates else ""

    def _process_summary(self, episode: Episode) -> str:
        tool_count = len([t for t in episode.turns if t.is_tool_or_system or t.tool_name])
        assistant_count = len(episode.assistant_turns)
        if tool_count:
            return f"本 episode 包含 {assistant_count} 条助手回复和 {tool_count} 条工具/系统证据；长期记忆只保留结论，不保留工具过程。"
        return f"本 episode 包含 {assistant_count} 条助手回复；已压缩为用户意图级长期记忆候选。"

    def _future_impact(self, turns: list[Turn]) -> str:
        text = "\n".join(t.content for t in turns)
        if re.search(r"(后续|下一步|以后|未来|升级|发布|安装器|迁移|治理)", text, re.I):
            return "后续检索、Space、人格与待办应优先参考这类规范化后的长期结论，而不是过程碎片。"
        return ""

    def _memory_type(self, turns: list[Turn]) -> str:
        text = "\n".join(t.content for t in turns)
        if re.search(r"(决定|决策|确认|采用|放弃|原则|必须|不要)", text):
            return "DECISION"
        if re.search(r"(喜欢|偏好|倾向|讨厌|希望|要求)", text):
            return "PREFERENCE"
        if re.search(r"(事故|发布|上线|迁移|完成|修复)", text):
            return "EVENT"
        if re.search(r"(分析|原因|根因|推理|判断)", text):
            return "REASONING"
        return "FACT"

    def _suggest_tags(self, episode: Episode, texts: list[str]) -> list[str]:
        joined = "\n".join([episode.title, episode.user_intent, *texts])
        tags = []
        for pattern, tag in _TAG_PATTERNS:
            if re.search(pattern, joined, re.I):
                tags.append(tag)
        if episode.agent_name:
            tags.append(episode.agent_name)
        return self._dedupe(tags)[:8]

    def _dedupe(self, items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                result.append(item)
        return result
