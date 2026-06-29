"""固化管道 —— 定期将原始记忆聚类、去重、提炼。"""

from memo.core.config import config
from memo.store.database import db
from memo.utils.logger import logger


# 跟踪上次固化的记忆数（简化实现：用 feature_tags 的每次新建作为新记忆代理）
_last_consolidated_count: int = 0


def check_and_consolidate() -> dict:
    """检查是否需要固化，需要则执行。

    触发条件：新记忆单元数 ≥ consolidation_trigger_count。
    """
    global _last_consolidated_count

    current_count_row = db.fetchone("SELECT COUNT(*) as c FROM memory_units")
    current_count = current_count_row["c"] if current_count_row else 0

    new_since_last = current_count - _last_consolidated_count

    if new_since_last < config.consolidation_trigger_count:
        return {"triggered": False, "new_memories": new_since_last, "threshold": config.consolidation_trigger_count}

    # 触发固化
    logger.info(f"触发固化: {new_since_last} 条新记忆")

    # Phase 0 简化实现：仅做基础统计
    # 后续 Phase 会用 LLM 做主题聚类、矛盾检测、重复识别
    _last_consolidated_count = current_count

    return {
        "triggered": True,
        "new_memories": new_since_last,
        "consolidated_at": current_count,
    }
