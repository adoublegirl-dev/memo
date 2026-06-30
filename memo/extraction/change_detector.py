"""变更感知（Change Awareness, CAS）

不依赖 LLM 在提取时主动猜 `is_update_of`，而是写入后主动检索相似旧记忆，
用 LLM 做语义级对比判断。

两级检测：
  L1 - 写入时实时检测（每次 remember_conversation 后）
  L2 - Consolidation 定期扫描（run_lifecycle 触发）
"""

from typing import Any

from memo.core.config import config
from memo.models import RelationType
from memo.store.database import db
from memo.store.graph_store import graph_store
from memo.store.memory_store import memory_store
from memo.store.vector_store import vector_store
from memo.utils.llm import llm_client
from memo.utils.logger import logger

# ── Prompt ──

_CONFLICT_SYSTEM = """你是一个事实冲突检测引擎。判断新记忆是否更新、推翻或细化了一条旧记忆。

判断标准：
- supersede（推翻）：新记忆的结论与旧记忆矛盾，旧记忆已过时。如「决定用A」→「改用B」
- refine（细化）：新记忆补充或细化了旧记忆，但核心结论不变。如「用PostgreSQL」→「PostgreSQL版本需≥15」
- unrelated（无关）：两者虽语义相似但无更新关系

输出纯 JSON。"""

_CONFLICT_PROMPT = """判断以下新记忆是否更新、推翻或细化了一条旧记忆。

旧记忆 [{old_id}]:
  标题: {old_title}
  摘要: {old_summary}

新记忆:
  标题: {new_title}
  摘要: {new_summary}

输出 JSON：
{{"relation": "supersede" | "refine" | "unrelated", "reason": "简述判断原因"}}"""


def detect_change(
    new_memory_id: str,
    new_title: str,
    new_summary: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """L1 写入时语义冲突检测。

    在写入新记忆后调用。主动检索相似旧记忆，逐个让 LLM 判断是否有更新关系。

    Args:
        new_memory_id: 新记忆 ID
        new_title: 新记忆标题
        new_summary: 新记忆摘要
        top_k: 检索的相似记忆数量

    Returns:
        {
            "superseded": [old_id, ...],   # 被推翻的旧记忆 ID
            "refined": [old_id, ...],      # 被细化的旧记忆 ID
            "details": [{"old_id": str, "relation": str, "reason": str}, ...],
        }
    """
    if not config.change_detection_enabled:
        return {"superseded": [], "refined": [], "details": []}

    if not llm_client.available:
        logger.info("CAS: LLM 不可用，跳过变更检测")
        return {"superseded": [], "refined": [], "details": []}

    # 向量检索相似旧记忆（排除自身、已失效的）
    similar = vector_store.search(new_title, top_k=top_k + 1)
    candidates = []
    for mem_id, score in similar:
        if mem_id == new_memory_id:
            continue
        mem = memory_store.get_memory(mem_id)
        if mem and not mem.is_superseded and score > 0.5:
            candidates.append((mem_id, score, mem))

    if not candidates:
        return {"superseded": [], "refined": [], "details": []}

    superseded: list[str] = []
    refined: list[str] = []
    details: list[dict] = []

    for old_id, score, old_mem in candidates[:top_k]:
        try:
            prompt = _CONFLICT_PROMPT.format(
                old_id=old_id[:8],
                old_title=old_mem.title[:100],
                old_summary=old_mem.summary[:300],
                new_title=new_title[:100],
                new_summary=new_summary[:300],
            )
            result = llm_client.chat_json(
                messages=[
                    {"role": "system", "content": _CONFLICT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=256,
            )
            relation = result.get("relation", "unrelated")
            reason = result.get("reason", "")

            detail = {
                "old_id": old_id,
                "relation": relation,
                "reason": reason,
                "score": round(score, 4),
            }
            details.append(detail)

            if relation == "supersede":
                superseded.append(old_id)
                logger.info(f"CAS: 变更检测 → 推翻 {old_id[:8]} ({reason[:60]})")
            elif relation == "refine":
                refined.append(old_id)
                logger.info(f"CAS: 变更检测 → 细化 {old_id[:8]} ({reason[:60]})")

        except Exception as e:
            logger.warning(f"CAS: LLM 对比失败 ({old_id[:8]}): {e}")

    return {
        "superseded": superseded,
        "refined": refined,
        "details": details,
    }


def apply_changes(
    new_memory_id: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    """应用变更检测结果到数据库。

    Args:
        new_memory_id: 新记忆 ID
        changes: detect_change() 的返回结果

    Returns:
        {"superseded_count": int, "refined_count": int}
    """
    superseded_count = 0
    refined_count = 0

    for old_id in changes.get("superseded", []):
        # 标记旧记忆被替代
        memory_store.supersede_memory(old_id, new_memory_id)
        # 建立推翻关系边
        _ensure_relation(old_id, new_memory_id, RelationType.SUPERSEDES)
        superseded_count += 1

    for old_id in changes.get("refined", []):
        # 不标记失效，只建立细化关系边
        _ensure_relation(old_id, new_memory_id, RelationType.REFINES)
        refined_count += 1

    if superseded_count or refined_count:
        logger.info(
            f"CAS: 应用变更 → 推翻 {superseded_count} 条, 细化 {refined_count} 条"
        )

    return {"superseded_count": superseded_count, "refined_count": refined_count}


# ── L2: Consolidation 定期扫描 ──

def scan_conflicts_batch(
    min_similarity: float = 0.75,
    batch_size: int = 10,
) -> dict[str, Any]:
    """L2 批量扫描：检查所有未失效记忆之间的潜在冲突。

    Args:
        min_similarity: 向量相似度阈值，低于此值的不检查
        batch_size: 每次扫描的配对数量上限

    Returns:
        {"pairs_checked": int, "conflicts_found": int, "details": [...]}
    """
    if not config.change_detection_enabled or not llm_client.available:
        return {"pairs_checked": 0, "conflicts_found": 0, "details": []}

    # 获取所有未失效记忆
    rows = db.fetchall(
        "SELECT id, title, summary FROM memory_units "
        "WHERE is_superseded = 0 ORDER BY created_at DESC LIMIT 100"
    )
    if len(rows) < 2:
        return {"pairs_checked": 0, "conflicts_found": 0, "details": []}

    # 找候选配对（向量相似度 > threshold）
    pairs: list[tuple] = []
    for i in range(len(rows)):
        similar = vector_store.search(rows[i]["title"], top_k=10)
        for mem_id, score in similar:
            if mem_id == rows[i]["id"]:
                continue
            if score > min_similarity:
                # 避免重复配对
                pair = tuple(sorted([rows[i]["id"], mem_id]))
                if pair not in [p[0] for p in pairs]:
                    pairs.append((pair, rows[i], score))

    if not pairs:
        return {"pairs_checked": 0, "conflicts_found": 0, "details": []}

    # 取 top batch_size 对进行检查
    pairs = pairs[:batch_size]
    conflicts_found = 0
    details: list[dict] = []

    for (old_id, new_id), old_row, score in pairs:
        # 找到另一条记忆
        other_row = db.fetchone(
            "SELECT title, summary FROM memory_units WHERE id = ?", (new_id,)
        )
        if not other_row:
            continue

        try:
            prompt = _CONFLICT_PROMPT.format(
                old_id=old_id[:8],
                old_title=old_row["title"][:100],
                old_summary=old_row["summary"][:300],
                new_title=other_row["title"][:100],
                new_summary=other_row["summary"][:300],
            )
            result = llm_client.chat_json(
                messages=[
                    {"role": "system", "content": _CONFLICT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=256,
            )
            relation = result.get("relation", "unrelated")
            if relation != "unrelated":
                changes = {"superseded": [], "refined": [], "details": []}
                if relation == "supersede":
                    changes["superseded"] = [old_id]
                elif relation == "refine":
                    changes["refined"] = [old_id]
                apply_changes(new_id, changes)
                conflicts_found += 1
                details.append({
                    "old_id": old_id[:8],
                    "new_id": new_id[:8],
                    "relation": relation,
                    "reason": result.get("reason", ""),
                })
        except Exception as e:
            logger.debug(f"CAS L2: 检查失败 ({old_id[:8]}): {e}")

    return {
        "pairs_checked": len(pairs),
        "conflicts_found": conflicts_found,
        "details": details,
    }


# ── 辅助 ──

def _ensure_relation(source_id: str, target_id: str, rel_type: RelationType) -> None:
    """确保两个特征词之间存在指定类型的关系。"""
    # 对于 SUPERSEDES/REFINES，关系建立在记忆单元之间，
    # 这里通过特征词共现来间接表达，避免修改图存储的底层结构
    source_tags = graph_store.get_memory_tags(source_id)
    target_tags = graph_store.get_memory_tags(target_id)
    for st in source_tags:
        for tt in target_tags:
            if st.id != tt.id:
                graph_store.upsert_relation(
                    source_id=st.id,
                    target_id=tt.id,
                    relation_type=rel_type,
                    semantic_similarity=0.3,
                )
