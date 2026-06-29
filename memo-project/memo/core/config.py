"""配置管理 —— 从环境变量 + .env 文件读取全部配置。

所有模块统一从此处获取配置，不硬编码任何参数。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录 (memo-project/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 自动加载 .env
_env_file = _PROJECT_ROOT / ".env"
if _env_file.exists():
    load_dotenv(_env_file)


@dataclass
class MemoConfig:
    """Memo 全局配置，所有字段都有合理默认值。"""

    # ── 数据库 ──
    db_path: str = field(
        default_factory=lambda: os.getenv(
            "MEMO_DB_PATH",
            str(_PROJECT_ROOT / "data" / "memo.db"),
        )
    )

    # ── LLM 提取（API 调用，轻量模型即可） ──
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    openai_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    extraction_model: str = field(
        default_factory=lambda: os.getenv("MEMO_EXTRACTION_MODEL", "gpt-4o-mini")
    )

    # ── 嵌入模型（本地 BGE-small） ──
    embedding_model_name: str = field(
        default_factory=lambda: os.getenv(
            "MEMO_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"
        )
    )
    embedding_dim: int = 512  # BGE-small-zh-v1.5 实际输出 512 维

    # ── 赫布学习 ──
    hebbian_learning_rate: float = 0.05
    co_occurrence_boost_cap: float = 2.0
    storage_strength_increment: float = 0.01

    # ── 扩散激活 ──
    spreading_decay_rate: float = 0.5
    spreading_max_hops: int = 3

    # ── 遗忘 ──
    retrieval_strength_decay: float = 0.02  # 每天
    dormant_threshold_days: int = 90
    dormant_threshold_weight: float = 0.05
    dormant_access_window: int = 30  # 近 N 天访问次数

    # ── 生命周期 ──
    consolidation_trigger_count: int = 10
    snapshot_trigger_count: int = 50
    snapshot_trigger_days: int = 7
    max_snapshots: int = 10

    # ── 检索 ──
    top_k_retrieval: int = 5
    rrf_k: int = 60
    llm_rerank_timeout_ms: int = 500

    # ── 日志 ──
    log_level: str = field(
        default_factory=lambda: os.getenv("MEMO_LOG_LEVEL", "INFO")
    )

    def ensure_dirs(self) -> None:
        """确保数据目录存在。"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)


# 全局单例
config = MemoConfig()
