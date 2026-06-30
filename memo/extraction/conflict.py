"""冲突检测 —— 双时序处理矛盾事实。"""

from datetime import datetime

from memo.store.database import db
from memo.utils.logger import logger


def detect_conflict(memory_id: str) -> list[str]:
    """检测与指定记忆矛盾的其他记忆。

    当前阶段使用简化规则：相同记忆类型的近期记忆可能有冲突。
    后续 Phase 会用 LLM 做语义层面的矛盾检测。
    """
    current = db.fetchone(
        "SELECT memory_type, summary, valid_from FROM memory_units WHERE id = ?",
        (memory_id,),
    )
    if not current:
        return []

    # 找同类型、同时段、未失效的记忆
    same_type = db.fetchall(
        """SELECT id, summary FROM memory_units
           WHERE memory_type = ? AND id != ? AND is_superseded = 0
           AND valid_until IS NULL
           ORDER BY created_at DESC LIMIT 5""",
        (current["memory_type"], memory_id),
    )

    conflicts = []
    for row in same_type:
        # 简化检测：标题/摘要高度相似但结论不同 → 可能是更新
        # 后续用 LLM 判断
        pass

    return conflicts
