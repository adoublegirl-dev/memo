"""快照管道 —— 定期生成全局记忆快照。"""

from datetime import datetime

from memo.core.config import config
from memo.store.database import db, json_encode, new_id
from memo.store.graph_store import graph_store
from memo.utils.logger import logger

# 上次快照时间和条数
_last_snapshot_at: str = ""
_last_snapshot_count: int = 0


def check_and_snapshot() -> dict:
    """检查是否需要生成快照，需要则生成。"""
    global _last_snapshot_at, _last_snapshot_count

    current_count_row = db.fetchone("SELECT COUNT(*) as c FROM memory_units")
    current_count = current_count_row["c"] if current_count_row else 0

    now = datetime.now().isoformat()

    # 条件①：新记忆数 ≥ 50
    count_triggered = (current_count - _last_snapshot_count) >= config.snapshot_trigger_count

    # 条件②：距上次快照 ≥ 7 天
    days_since = 999
    if _last_snapshot_at:
        try:
            last = datetime.fromisoformat(_last_snapshot_at)
            days_since = (datetime.now() - last).days
        except Exception:
            pass
    time_triggered = days_since >= config.snapshot_trigger_days

    if not count_triggered and not time_triggered:
        return {"triggered": False}

    logger.info(f"生成快照: count_diff={current_count - _last_snapshot_count}, days={days_since}")

    # 收集统计信息
    sessions_row = db.fetchone("SELECT COUNT(*) as c FROM sessions")
    tags_row = db.fetchone("SELECT COUNT(*) as c FROM feature_tags")
    relations_row = db.fetchone("SELECT COUNT(*) as c FROM feature_relations")

    hot_tags = graph_store.get_hot_tags(limit=50)

    snapshot_id = new_id()
    db.execute(
        """INSERT INTO global_snapshots
           (id, snapshot_at, total_sessions, total_memory_units,
            total_feature_tags, total_relations, hot_tags)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            snapshot_id,
            now,
            sessions_row["c"] if sessions_row else 0,
            current_count,
            tags_row["c"] if tags_row else 0,
            relations_row["c"] if relations_row else 0,
            json_encode([t.id for t in hot_tags]),
        ),
    )

    # 清理旧快照（保留最近 10 个）
    db.execute(
        """DELETE FROM global_snapshots
           WHERE id NOT IN (
               SELECT id FROM global_snapshots ORDER BY snapshot_at DESC LIMIT ?
           )""",
        (config.max_snapshots,),
    )
    db.commit()

    _last_snapshot_at = now
    _last_snapshot_count = current_count

    return {
        "triggered": True,
        "snapshot_id": snapshot_id,
        "total_memories": current_count,
    }
