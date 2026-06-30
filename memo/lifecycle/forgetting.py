"""遗忘管道 —— Bjork 双强度遗忘 + 三维度修剪。"""

from datetime import datetime, timedelta

from memo.core.config import config
from memo.store.database import db
from memo.utils.logger import logger


def run_forgetting() -> dict:
    """执行一次遗忘周期。

    1. 检索强度衰减
    2. 三维度修剪 → 标记休眠
    3. 更新 cooldown_days
    """
    now = datetime.now()

    # 1. 检索强度衰减：所有未休眠特征词
    # 但排除与 L2 显式记忆关联的特征词（ESA 遗忘豁免）
    decay_rate = config.retrieval_strength_decay  # 0.02 / 天
    db.execute(
        """UPDATE feature_tags
           SET retrieval_strength = MAX(
                 retrieval_strength * (1 - ? * MAX(cooldown_days + 1, 1)),
                 0.01
               ),
               cooldown_days = cooldown_days + 1
           WHERE is_dormant = 0
             AND id NOT IN (
               SELECT DISTINCT tm.tag_id FROM tag_mentions tm
               JOIN memory_units mu ON mu.id = tm.memory_unit_id
               WHERE mu.signal_level = 2 AND mu.is_superseded = 0
             )""",
        (decay_rate,),
    )

    # 2. 三维度修剪：标记休眠（排除 L2 显式记忆关联的特征词）
    dormant_cutoff = (now - timedelta(days=config.dormant_threshold_days)).isoformat()
    db.execute(
        """UPDATE feature_tags
           SET is_dormant = 1
           WHERE is_dormant = 0
             AND (storage_strength * retrieval_strength) < ?
             AND (last_activated_at IS NULL OR last_activated_at < ?)
             AND total_activations < 2
             AND id NOT IN (
               SELECT DISTINCT tm.tag_id FROM tag_mentions tm
               JOIN memory_units mu ON mu.id = tm.memory_unit_id
               WHERE mu.signal_level = 2 AND mu.is_superseded = 0
             )""",
        (config.dormant_threshold_weight, dormant_cutoff),
    )

    db.commit()

    # 统计
    total = db.fetchone("SELECT COUNT(*) as c FROM feature_tags")
    dormant = db.fetchone("SELECT COUNT(*) as c FROM feature_tags WHERE is_dormant = 1")

    active_count = total["c"] - dormant["c"] if total and dormant else 0
    dormant_count = dormant["c"] if dormant else 0

    logger.info(f"遗忘完成: {active_count} 活跃, {dormant_count} 休眠")

    return {
        "active_tags": active_count,
        "dormant_tags": dormant_count,
        "total_tags": total["c"] if total else 0,
    }
