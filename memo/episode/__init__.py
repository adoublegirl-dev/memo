"""Episode Memory：用户意图级长期记忆整理层。

V0.9 Phase 1 只提供纯函数/轻量对象能力：
- 标准 turn 模型
- episode 切分
- 长期价值评分
- canonical memory draft 生成

这些模块默认不写生产库，用于 dry-run 导入、迁移预览和后续实时写入改造。
"""

from memo.episode.model import CanonicalMemoryDraft, Episode, EpisodeSource, Turn
from memo.episode.splitter import EpisodeSplitter
from memo.episode.scorer import EpisodeQualityScorer
from memo.episode.canonicalizer import EpisodeCanonicalizer
from memo.episode.manager import episode_manager, EpisodeManager

__all__ = [
    "Turn",
    "Episode",
    "EpisodeSource",
    "CanonicalMemoryDraft",
    "EpisodeSplitter",
    "EpisodeQualityScorer",
    "EpisodeCanonicalizer",
    "EpisodeManager",
    "episode_manager",
]
