"""Episode 切分器。

默认策略：新的用户问题开启新 episode；工具调用、系统消息、阶段性回复归入当前 episode。
"""

from __future__ import annotations

import re
from uuid import uuid4

from memo.episode.model import Episode, Turn
from memo.episode.scorer import EpisodeQualityScorer

_TASK_SWITCH_HINTS = re.compile(
    r"(另外|换个|还有|接下来|下一步|新项目|另一个|顺便|再帮我|开始|继续|发布|部署|修复|检查|分析|设计|实现|开发|整理)"
)


def _shorten(text: str, limit: int = 42) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text[:limit] + ("…" if len(text) > limit else "")


class EpisodeSplitter:
    """将标准 turns 切分为 episode 候选。"""

    def __init__(self, scorer: EpisodeQualityScorer | None = None):
        self.scorer = scorer or EpisodeQualityScorer()

    def split(self, turns: list[Turn], source_session_id: str = "", agent_name: str = "") -> list[Episode]:
        episodes: list[Episode] = []
        current: list[Turn] = []
        current_intent = ""

        for turn in turns:
            if turn.is_user and current:
                # 默认一个用户新问题开启新 episode；短追问也单独成 episode，后续 canonicalizer 可合并。
                episodes.append(self._make_episode(current, current_intent, source_session_id, agent_name))
                current = []
                current_intent = ""

            if turn.is_user and not current_intent:
                current_intent = _shorten(turn.content, 120)

            # 如果会话开头是 assistant/tool，也先收进 episode 证据层，但评分会降低。
            current.append(turn)

        if current:
            episodes.append(self._make_episode(current, current_intent, source_session_id, agent_name))

        return episodes

    def _make_episode(self, turns: list[Turn], user_intent: str, source_session_id: str, agent_name: str) -> Episode:
        first = turns[0]
        last = turns[-1]
        title = self._title_from_turns(turns, user_intent)
        episode = Episode(
            id=str(uuid4()),
            source_session_id=source_session_id or first.session_id,
            agent_name=agent_name or first.agent,
            title=title,
            user_intent=user_intent or title,
            start_turn_id=first.turn_id,
            end_turn_id=last.turn_id,
            turns=turns,
            metadata={
                "turn_count": len(turns),
                "user_turn_count": len([t for t in turns if t.is_user]),
                "assistant_turn_count": len([t for t in turns if t.is_assistant]),
                "has_task_switch_hint": bool(_TASK_SWITCH_HINTS.search(user_intent or title)),
            },
        )
        score = self.scorer.score(episode)
        episode.long_term_value_score = score.score
        episode.score_reasons = score.reasons
        episode.skip_reasons = score.skip_reasons
        episode.confidence = score.score
        episode.status = self.scorer.classify(score.score)
        return episode

    def _title_from_turns(self, turns: list[Turn], user_intent: str) -> str:
        if user_intent:
            return _shorten(user_intent, 42)
        for turn in turns:
            if turn.content.strip():
                return _shorten(turn.content, 42)
        return "未命名 episode"
