"""Memo 数据模型 —— 六维存储模型的核心数据结构。

参考: architecture.md §3 六维存储模型。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════════

class MemoryType(str, Enum):
    """记忆类型。"""
    FACT = "FACT"              # 事实
    DECISION = "DECISION"      # 决策
    PREFERENCE = "PREFERENCE"  # 偏好
    EVENT = "EVENT"            # 事件
    REASONING = "REASONING"    # 推理


class RelationType(str, Enum):
    """特征词间关系类型。"""
    CO_OCCUR = "CO_OCCUR"      # 共现关系
    CAUSAL = "CAUSAL"          # 因果关系
    TEMPORAL = "TEMPORAL"      # 时序关系
    DERIVED = "DERIVED"        # 派生关系
    CONTRADICT = "CONTRADICT"  # 矛盾关系


class SessionStatus(str, Enum):
    """会话状态。"""
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class MentionType(str, Enum):
    """特征词提及类型。"""
    DIRECT = "DIRECT"      # 直接提及
    INFERRED = "INFERRED"  # 推断
    TITLE = "TITLE"        # 标题


class FeatureCategory(str, Enum):
    """POLE+O 特征词分类。"""
    PERSON = "PERSON"
    OBJECT = "OBJECT"
    LOCATION = "LOCATION"
    EVENT = "EVENT"
    ORGANIZATION = "ORGANIZATION"
    CONCEPT = "CONCEPT"


# ═══════════════════════════════════════════════════════════════
# 扩散激活系数（图搜索用）
# ═══════════════════════════════════════════════════════════════

RELATION_TYPE_FACTOR: dict[RelationType, float] = {
    RelationType.CO_OCCUR: 1.0,
    RelationType.CAUSAL: 2.0,
    RelationType.TEMPORAL: 1.2,
    RelationType.DERIVED: 0.8,
    RelationType.CONTRADICT: 0.3,
}


# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class Session:
    """会话（§3.1）"""
    id: str
    agent_id: str = "default"
    title: str = ""
    created_at: str = ""
    ended_at: Optional[str] = None
    status: SessionStatus = SessionStatus.ACTIVE
    memory_count: int = 0


@dataclass
class FeatureTag:
    """特征词（§3.2）——最关键的数据结构。

    采用 Bjork 双强度遗忘模型：
    - storage_strength：只增不减
    - retrieval_strength：不用时衰减
    """
    id: str
    name: str
    category: FeatureCategory = FeatureCategory.CONCEPT
    # 双强度遗忘
    storage_strength: float = 0.1
    retrieval_strength: float = 1.0
    # 赫布权重
    total_activations: int = 0
    last_activated_at: str = ""
    cooldown_days: float = 0.0
    # 休眠标记
    is_dormant: bool = False
    # 元数据
    first_seen_at: str = ""
    created_by: str = "LLM_AUTO"  # LLM_AUTO / USER_MANUAL
    embedding: Optional[list[float]] = None  # 512-dim for BGE-small-zh-v1.5

    @property
    def effective_weight(self) -> float:
        """有效权重 = 存储强度 × 检索强度"""
        return self.storage_strength * self.retrieval_strength


@dataclass
class FeatureRelation:
    """特征关系（§3.3）——图的边"""
    id: str
    source_tag_id: str
    target_tag_id: str
    relation_type: RelationType = RelationType.CO_OCCUR
    hebbian_weight: float = 0.1
    co_activation_count: int = 0
    last_co_activated_at: str = ""
    first_observed_at: str = ""
    contexts: list[str] = field(default_factory=list)


@dataclass
class MemoryUnit:
    """记忆单元（§3.4）——六维存储核心"""
    id: str
    session_id: str = ""
    # 六维存储
    title: str = ""
    feature_tags: list[str] = field(default_factory=list)  # tag name 列表
    summary: str = ""          # 一级摘要 ≤300字
    summary_detail: str = ""   # 二级摘要 ≤1500字
    raw_text: str = ""         # 原文
    # 时序
    valid_from: str = ""
    valid_until: Optional[str] = None
    recorded_at: str = ""
    created_at: str = ""
    is_superseded: bool = False
    superseded_by: Optional[str] = None
    # 置信度
    confidence: float = 0.8
    # 类型
    memory_type: MemoryType = MemoryType.FACT
    # 向量嵌入（768-dim）
    embedding: Optional[list[float]] = None

    @property
    def embedding_bytes(self) -> Optional[bytes]:
        """将 embedding 列表转为 bytes（用于 SQLite blob 存储）。"""
        if self.embedding is None:
            return None
        import struct
        return struct.pack(f'{len(self.embedding)}f', *self.embedding)


@dataclass
class TagMention:
    """特征词↔记忆单元关联（§3.5）"""
    id: str
    tag_id: str
    memory_unit_id: str
    mention_type: MentionType = MentionType.DIRECT
    relevance_score: float = 0.8
    position_index: int = 0


@dataclass
class GlobalMemorySnapshot:
    """全局记忆快照（§3.6）"""
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


# ═══════════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════════

__all__ = [
    # 枚举
    "MemoryType",
    "RelationType",
    "SessionStatus",
    "MentionType",
    "FeatureCategory",
    # 常量
    "RELATION_TYPE_FACTOR",
    # 数据类
    "Session",
    "FeatureTag",
    "FeatureRelation",
    "MemoryUnit",
    "TagMention",
    "GlobalMemorySnapshot",
]
