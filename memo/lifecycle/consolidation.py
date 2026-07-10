"""固化管道 —— 定期将原始记忆聚类、去重、合并。"""

from memo.core.config import config
from memo.store.database import db, new_id
from memo.utils.logger import logger

# 跟踪上次固化的记忆数
_last_consolidated_count: int = 0


def check_and_consolidate() -> dict:
    """检查是否需要固化，需要则执行。"""
    global _last_consolidated_count

    current_count_row = db.fetchone("SELECT COUNT(*) as c FROM memory_units")
    current_count = current_count_row["c"] if current_count_row else 0

    new_since_last = current_count - _last_consolidated_count

    if new_since_last < config.consolidation_trigger_count:
        return {"triggered": False, "new_memories": new_since_last, "threshold": config.consolidation_trigger_count}

    logger.info(f"触发固化: {new_since_last} 条新记忆")

    # 执行合并
    merged = merge_session_memories()

    _last_consolidated_count = current_count

    return {
        "triggered": True,
        "new_memories": new_since_last,
        "consolidated_at": current_count,
        "merged": merged,
    }


def merge_session_memories() -> int:
    """合并同会话内 REFINES 关系链的相似记忆。

    逻辑：
    1. 找到有 ≥ 5 条记忆的会话
    2. 在每条记忆间找 REFINES 关系链
    3. 保留最新记忆，将旧记忆标记 is_superseded
    4. 旧记忆的特征词迁移到新记忆

    Returns:
        合并的记忆数量
    """
    merged_count = 0

    # 找到记忆较多的会话
    sessions = db.fetchall(
        """SELECT session_id, COUNT(*) as cnt
           FROM memory_units
           WHERE is_superseded = 0
           GROUP BY session_id
           HAVING cnt >= 5
           ORDER BY cnt DESC"""
    )

    from memo.store.graph_store import graph_store
    from memo.store.memory_store import memory_store

    for sess in sessions:
        session_id = sess["session_id"]
        memories = memory_store.get_session_memories(session_id)
        memories = [m for m in memories if not m.is_superseded]

        if len(memories) < 5:
            continue

        # 按创建时间排序
        memories.sort(key=lambda m: m.created_at)

        # 查找 REFINES 关系链
        # 从最早到最新遍历，相邻记忆间有关系则纳入合并链
        chain = [memories[0]]
        for i in range(1, len(memories)):
            prev = chain[-1]
            curr = memories[i]

            # 检查两个记忆的特征词之间是否有 REFINES 关系
            prev_tags = graph_store.get_memory_tags(prev.id)
            curr_tags = graph_store.get_memory_tags(curr.id)

            has_refine = False
            for pt in prev_tags:
                for ct in curr_tags:
                    # 查是否有 REFINES 边
                    neighbors = graph_store.get_neighbors(ct.id)
                    for ntag, rel, _ in neighbors:
                        if ntag.id == pt.id and rel.relation_type.value == "REFINES":
                            has_refine = True
                            break
                    if has_refine:
                        break
                if has_refine:
                    break

            if has_refine:
                chain.append(curr)
            else:
                # 链断了，如果链长度 ≥ 2 则合并，然后开始新链
                if len(chain) >= 2:
                    merged_count += _merge_chain(chain, session_id)
                chain = [curr]

        # 处理最后一条链
        if len(chain) >= 2:
            merged_count += _merge_chain(chain, session_id)

    logger.info(f"合并完成: {merged_count} 条记忆")
    return merged_count


def _merge_chain(chain: list, session_id: str) -> int:
    """合并一条记忆链：保留最新的，旧标记 is_superseded。"""
    if len(chain) < 2:
        return 0

    from memo.store.graph_store import graph_store
    newest = chain[-1]

    for old in chain[:-1]:
        # 标记旧记忆为已替代
        db.execute(
            "UPDATE memory_units SET is_superseded = 1, superseded_by = ? WHERE id = ?",
            (newest.id, old.id),
        )

        # 迁移特征词关联
        old_tags = graph_store.get_memory_tags(old.id)
        for tag in old_tags:
            # 检查新记忆是否已有这个特征词
            new_tags = graph_store.get_memory_tags(newest.id)
            if not any(t.id == tag.id for t in new_tags):
                graph_store.create_mention(
                    tag_id=tag.id,
                    memory_unit_id=newest.id,
                    mention_type="DIRECT",
                    relevance_score=0.6,  # 合并迁移，置信度略低
                )

        logger.debug(f"合并: {old.title[:30]} → {newest.title[:30]}")

    return len(chain) - 1
