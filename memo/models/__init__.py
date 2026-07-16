"""数据模型 —— 纯数据类，不含数据库操作（操作在 store 层）。

命名与 architecture.md 中的定义一 一对应。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class FeatureCategory(str, Enum):
    PERSON = "PERSON"
    OBJECT = "OBJECT"
    LOCATION = "LOCATION"
    EVENT = "EVENT"
    ORGANIZATION = "ORGANIZATION"
    CONCEPT = "CONCEPT"


class RelationType(str, Enum):
    CO_OCCUR = "CO_OCCUR"
    DERIVED = "DERIVED"
    CAUSAL = "CAUSAL"
    TEMPORAL = "TEMPORAL"
    CONTRADICT = "CONTRADICT"
    REFINES = "REFINES"        # 细化关系（补充但不推翻旧记忆）
    SUPERSEDES = "SUPERSEDES"  # 推翻关系（新记忆替代旧记忆）


class MemoryType(str, Enum):
    FACT = "FACT"
    DECISION = "DECISION"
    PREFERENCE = "PREFERENCE"
    EVENT = "EVENT"
    REASONING = "REASONING"


class MentionType(str, Enum):
    DIRECT = "DIRECT"
    INFERRED = "INFERRED"
    TITLE = "TITLE"


class CreatedBy(str, Enum):
    LLM_AUTO = "LLM_AUTO"
    USER_MANUAL = "USER_MANUAL"


class SpaceType(str, Enum):
    GENERAL = "general"
    MANAGEMENT = "management"
    PRODUCT = "product"
    DEV_PROJECT = "dev_project"
    CLIENT = "client"
    PERSONAL = "personal"
    LEARNING = "learning"
    WRITING = "writing"
    OPERATION = "operation"
    LEGAL = "legal"
    RELATIONSHIP = "relationship"


@dataclass
class Space:
    id: str
    name: str
    type: str = SpaceType.GENERAL.value
    description: str = ""
    goal: str = ""
    background: str = ""
    current_state: str = ""
    next_action: str = ""
    priority: str = "medium"
    status: str = "active"
    profile_json: str = "{}"
    memory_count: int = 0
    todo_count: int = 0
    session_count: int = 0
    is_default: bool = False
    created_by: str = "auto"
    created_at: str = ""
    updated_at: str = ""
    last_active_at: str = ""
    archived_at: str = ""
    embedding: Any = None


@dataclass
class Session:
    id: str
    agent_id: str = "default"
    title: str = ""
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: str = ""
    ended_at: str = ""
    memory_count: int = 0
    space_id: str = ""


@dataclass
class FeatureTag:
    id: str
    name: str
    category: FeatureCategory = FeatureCategory.CONCEPT
    storage_strength: float = 0.1
    retrieval_strength: float = 1.0
    total_activations: int = 0
    last_activated_at: str = ""
    cooldown_days: float = 0.0
    first_seen_at: str = ""
    created_by: CreatedBy = CreatedBy.LLM_AUTO
    embedding: Any = None
    is_dormant: bool = False

    @property
    def effective_weight(self) -> float:
        """有效权重 = 存储强度 × 检索强度。"""
        return self.storage_strength * self.retrieval_strength


@dataclass
class FeatureRelation:
    id: str
    source_tag_id: str
    target_tag_id: str
    relation_type: RelationType = RelationType.CO_OCCUR
    hebbian_weight: float = 0.1
    co_activation_count: int = 1
    last_co_activated_at: str = ""
    first_observed_at: str = ""
    contexts: list[str] = field(default_factory=list)
    last_session_id: str = ""  # SCB: 最近一次共现所在的会话 ID


@dataclass
class MemoryUnit:
    id: str
    session_id: str
    title: str = ""
    summary: str = ""
    summary_detail: str = ""
    raw_text: str = ""
    valid_from: str = ""
    valid_until: str = ""
    recorded_at: str = ""
    is_superseded: bool = False
    superseded_by: str = ""
    confidence: float = 0.8
    memory_type: MemoryType = MemoryType.FACT
    signal_level: int = 0  # 0=L0普通自动, 1=L1高价值自动, 2=L2显式手动
    embedding: Any = None
    created_at: str = ""
    feature_tags: list[str] = field(default_factory=list)


@dataclass
class TagMention:
    id: str
    tag_id: str
    memory_unit_id: str
    mention_type: MentionType = MentionType.DIRECT
    relevance_score: float = 0.5
    position_index: int = 0


@dataclass
class GlobalSnapshot:
    id: str
    agent_id: str = "default"
    snapshot_at: str = ""
    total_sessions: int = 0
    total_memory_units: int = 0
    total_feature_tags: int = 0
    total_relations: int = 0
    agent_profile: str = ""
    top_domains: list[str] = field(default_factory=list)
    active_projects: list[str] = field(default_factory=list)
    hot_tags: list[str] = field(default_factory=list)
    recent_important_memories: list[str] = field(default_factory=list)


# 扩散激活中传播系数的映射
RELATION_TYPE_FACTOR: dict[RelationType, float] = {
    RelationType.CO_OCCUR: 1.0,
    RelationType.DERIVED: 0.8,
    RelationType.CAUSAL: 2.0,
    RelationType.TEMPORAL: 1.2,
    RelationType.CONTRADICT: -1.0,  # 矛盾关系负向激活
    RelationType.REFINES: 0.6,       # 细化关系，弱关联
    RelationType.SUPERSEDES: 0.0,    # 仅用于追溯链，不参与扩散激活
}
