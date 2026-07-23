"""Episode Memory 数据对象。

这里的对象是导入/整理流水线的中间态，不直接等同于数据库 ORM。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Turn:
    """统一 Agent 历史 turn 格式。"""

    agent: str
    session_id: str
    turn_id: str
    role: str
    content: str
    timestamp: str = ""
    tool_name: str = ""
    is_final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_user(self) -> bool:
        return self.role.lower() == "user"

    @property
    def is_assistant(self) -> bool:
        return self.role.lower() == "assistant"

    @property
    def is_tool_or_system(self) -> bool:
        return self.role.lower() in {"tool", "system"}


@dataclass
class EpisodeSource:
    source_type: str
    source_id: str
    role: str = ""
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Episode:
    """一次用户意图/任务边界。"""

    id: str
    source_session_id: str = ""
    agent_name: str = ""
    title: str = ""
    user_intent: str = ""
    start_turn_id: str = ""
    end_turn_id: str = ""
    turns: list[Turn] = field(default_factory=list)
    status: str = "candidate"
    confidence: float = 0.0
    long_term_value_score: float = 0.0
    score_reasons: list[str] = field(default_factory=list)
    skip_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def user_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.is_user]

    @property
    def assistant_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.is_assistant]


@dataclass
class CanonicalMemoryDraft:
    """从 episode 提炼出的长期记忆候选。"""

    episode_id: str
    title: str
    user_intent: str
    key_facts: list[str] = field(default_factory=list)
    process_summary: str = ""
    final_conclusion: str = ""
    decision_or_result: str = ""
    future_impact: str = ""
    suggested_memory_type: str = "FACT"
    confidence: float = 0.0
    long_term_value_score: float = 0.0
    feature_tags: list[str] = field(default_factory=list)
    source_turn_ids: list[str] = field(default_factory=list)
    source_memory_ids: list[str] = field(default_factory=list)
    sensitive_hints: list[str] = field(default_factory=list)
    skip: bool = False
    skip_reasons: list[str] = field(default_factory=list)

    def to_memory_text(self) -> str:
        """生成可写入 memory_units.raw_text 的规范正文。"""
        parts = [
            f"标题：{self.title}",
            f"用户意图：{self.user_intent}",
        ]
        if self.key_facts:
            parts.append("关键事实：" + "；".join(self.key_facts))
        if self.process_summary:
            parts.append("处理过程：" + self.process_summary)
        if self.final_conclusion:
            parts.append("最终结论：" + self.final_conclusion)
        if self.decision_or_result:
            parts.append("决策 / 结果：" + self.decision_or_result)
        if self.future_impact:
            parts.append("后续影响：" + self.future_impact)
        return "\n".join(parts)
