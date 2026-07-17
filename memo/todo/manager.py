"""待办管理器 —— 增删改查 + 风险检测 + 历史记录。"""

from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any
import re

from memo.store.database import db, new_id
from memo.utils.logger import logger


# ── 创建 ──

_TODO_NOISE_RE = re.compile(r"[\s\t\r\n，。！？、；：,.!?;:（）()【】\[\]{}《》<>\"'“”‘’`~@#$%^&*_+=|\\/-]+")


def _normalize_todo_title(title: str) -> str:
    """待办标题归一化，用于保守本体去重。"""
    text = (title or "").strip().lower()
    text = re.sub(r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", "<date>", text)
    text = _TODO_NOISE_RE.sub("", text)
    return text


def _todo_title_similarity(a: str, b: str) -> float:
    na, nb = _normalize_todo_title(a), _normalize_todo_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        short, long = sorted([len(na), len(nb)])
        if short / max(long, 1) >= 0.72:
            return 0.94
    return SequenceMatcher(None, na, nb).ratio()


def find_duplicate_todo(title: str, priority: str = "medium", due_date: str = "", space_id: str = "") -> dict | None:
    """查找未完成待办中的保守重复项。

    只在同 Space（或双方都无 Space）、同优先级、同截止日期（或双方都为空）且标题高度相似时命中。
    """
    if not _normalize_todo_title(title):
        return None
    if space_id:
        rows = db.fetchall(
            """SELECT * FROM todos
               WHERE status IN ('todo','doing') AND priority = ? AND COALESCE(space_id,'') = ?
               ORDER BY updated_at DESC LIMIT 80""",
            (priority, space_id),
        )
    else:
        rows = db.fetchall(
            """SELECT * FROM todos
               WHERE status IN ('todo','doing') AND priority = ? AND COALESCE(space_id,'') = ''
               ORDER BY updated_at DESC LIMIT 80""",
            (priority,),
        )
    for row in rows:
        todo = dict(row)
        existing_due = todo.get("due_date") or ""
        new_due = due_date or ""
        if existing_due != new_due:
            continue
        sim = _todo_title_similarity(title, todo.get("title", ""))
        if sim >= 0.92:
            todo["duplicate_similarity"] = round(sim, 4)
            return todo
    return None


def add_todo(
    title: str,
    description: str = "",
    priority: str = "medium",
    due_date: str = "",
    session_id: str = "",
    memory_id: str = "",
    source_agent: str = "",
    space_id: str = "",
    space_relation_type: str = "action",
) -> dict:
    """创建待办，返回创建结果。"""
    duplicate = find_duplicate_todo(title=title, priority=priority, due_date=due_date, space_id=space_id)
    if duplicate:
        note = f"重复创建被跳过: {title}"
        if description and description not in (duplicate.get("description") or ""):
            note += f"；新描述: {description[:120]}"
        _log_history(duplicate["id"], duplicate.get("status"), duplicate.get("status", "doing"), note, source_agent)
        db.commit()
        return {
            "id": duplicate["id"],
            "title": duplicate["title"],
            "priority": duplicate["priority"],
            "status": duplicate["status"],
            "due_date": duplicate.get("due_date") or "",
            "source_agent": duplicate.get("source_agent") or source_agent,
            "space_id": duplicate.get("space_id") or "",
            "created": False,
            "duplicate": True,
            "duplicate_reason": "active_todo_title_priority_due_space_match",
            "duplicate_similarity": duplicate.get("duplicate_similarity", 1.0),
            "existing_id": duplicate["id"],
        }

    tid = new_id()
    now = datetime.now().isoformat()
    status = "doing"  # 直接进入进行中

    db.execute(
        """INSERT INTO todos (id, title, description, priority, status,
           session_id, memory_id, source_agent, due_date, created_at, updated_at,
           space_id, space_relation_type)
           VALUES (?, ?, ?, ?, ?, NULLIF(?, ''), NULLIF(?, ''), ?, ?, ?, ?, NULLIF(?, ''), ?)""",
        (tid, title, description, priority, status,
         session_id, memory_id, source_agent, due_date, now, now,
         space_id, space_relation_type),
    )
    # 写历史
    _log_history(tid, None, status, f"创建: {title}", source_agent)
    if space_id:
        db.execute(
            """UPDATE spaces
               SET todo_count = (SELECT COUNT(*) FROM todos WHERE space_id = ?),
                   updated_at = ?
               WHERE id = ?""",
            (space_id, now, space_id),
        )
    db.commit()

    return {
        "id": tid,
        "title": title,
        "priority": priority,
        "status": status,
        "due_date": due_date,
        "source_agent": source_agent,
        "space_id": space_id,
        "created": True,
    }


# ── 查询 ──

def search_todos(
    keyword: str = "",
    status: str = "todo+doing",
    include_done: bool = False,
    limit: int = 10,
    space_id: str = "",
) -> list[dict]:
    """搜索匹配的待办。"""
    conditions = []
    params = []

    if include_done:
        conditions.append("status != 'cancelled'")
    elif status == "all":
        pass  # 不过滤
    else:
        st_list = status.split("+")
        placeholders = ",".join("?" * len(st_list))
        conditions.append(f"status IN ({placeholders})")
        params.extend(st_list)

    if keyword:
        conditions.append("title LIKE ?")
        params.append(f"%{keyword}%")

    if space_id:
        conditions.append("space_id = ?")
        params.append(space_id)

    where = " AND ".join(conditions) if conditions else "1=1"
    rows = db.fetchall(
        f"SELECT * FROM todos WHERE {where} ORDER BY "
        "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
        "due_date ASC, created_at DESC LIMIT ?",
        params + [limit],
    )
    return [dict(r) for r in rows]


def list_todos(
    status: str = "todo+doing",
    priority: str = "",
    limit: int = 20,
    offset: int = 0,
    space_id: str = "",
) -> list[dict]:
    """分页列出待办。"""
    conditions = []
    params = []

    st_list = status.split("+")
    placeholders = ",".join("?" * len(st_list))
    conditions.append(f"status IN ({placeholders})")
    params.extend(st_list)

    if priority:
        conditions.append("priority = ?")
        params.append(priority)

    if space_id:
        conditions.append("space_id = ?")
        params.append(space_id)

    where = " AND ".join(conditions)
    rows = db.fetchall(
        f"SELECT * FROM todos WHERE {where} ORDER BY "
        "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
        "due_date ASC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    return [dict(r) for r in rows]


def get_todo(todo_id: str) -> dict | None:
    """获取单条待办。"""
    row = db.fetchone("SELECT * FROM todos WHERE id = ?", (todo_id,))
    return dict(row) if row else None


def get_todo_history(todo_id: str) -> list[dict]:
    """获取待办的历史记录。"""
    rows = db.fetchall(
        "SELECT * FROM todo_history WHERE todo_id = ? ORDER BY created_at",
        (todo_id,),
    )
    return [dict(r) for r in rows]


# ── 操作 ──

def close_todos(ids: list[str], note: str = "", agent: str = "") -> list[dict]:
    """批量关闭待办。返回关闭结果列表。"""
    results = []
    now = datetime.now().isoformat()

    for tid in ids:
        todo = get_todo(tid)
        if not todo:
            results.append({"id": tid, "error": "not found"})
            continue
        if todo["status"] in ("done", "cancelled"):
            results.append({"id": tid, "title": todo["title"], "skipped": True,
                           "reason": f"状态已是 {todo['status']}"})
            continue

        old_status = todo["status"]
        db.execute(
            "UPDATE todos SET status='done', completed_at=?, updated_at=? WHERE id=?",
            (now, now, tid),
        )
        _log_history(tid, old_status, "done", note, agent)
        db.commit()

        results.append({"id": tid, "title": todo["title"], "closed": True})
        logger.info(f"待办已关闭: {todo['title'][:40]}")

    return results


def reopen_todos(ids: list[str], agent: str = "") -> list[dict]:
    """批量重新开启待办。"""
    results = []
    now = datetime.now().isoformat()

    for tid in ids:
        todo = get_todo(tid)
        if not todo:
            results.append({"id": tid, "error": "not found"})
            continue
        if todo["status"] != "done":
            results.append({"id": tid, "title": todo["title"], "skipped": True,
                           "reason": f"状态是 {todo['status']}，不是 done"})
            continue

        db.execute(
            "UPDATE todos SET status='todo', reopened_at=?, completed_at=NULL, updated_at=? WHERE id=?",
            (now, now, tid),
        )
        _log_history(tid, "done", "todo", "重新开启", agent)
        db.commit()

        results.append({"id": tid, "title": todo["title"], "reopened": True})
        logger.info(f"待办已重开: {todo['title'][:40]}")

    return results


def update_todo(
    todo_id: str,
    title: str = "",
    priority: str = "",
    status: str = "",
    due_date: str = "",
    description: str = "",
    agent: str = "",
) -> dict:
    """更新待办字段。"""
    todo = get_todo(todo_id)
    if not todo:
        return {"error": "not found"}

    now = datetime.now().isoformat()
    old_status = todo["status"]

    if title:
        db.execute("UPDATE todos SET title=?, updated_at=? WHERE id=?", (title, now, todo_id))
    if priority:
        db.execute("UPDATE todos SET priority=?, updated_at=? WHERE id=?", (priority, now, todo_id))
    if status and status != old_status:
        db.execute("UPDATE todos SET status=?, updated_at=? WHERE id=?", (status, now, todo_id))
        if status == "done":
            db.execute("UPDATE todos SET completed_at=? WHERE id=?", (now, todo_id))
        _log_history(todo_id, old_status, status, "", agent)
    if due_date:
        db.execute("UPDATE todos SET due_date=?, updated_at=? WHERE id=?", (due_date, now, todo_id))
    if description:
        db.execute("UPDATE todos SET description=?, updated_at=? WHERE id=?", (description, now, todo_id))

    db.commit()
    return {"id": todo_id, "updated": True}


# ── 风险检测 ──

def check_risk() -> dict:
    """检查待办风险。

    Returns:
        {"urgent": [...], "overdue": [...], "warning": [...], "summary": str}
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    rows = db.fetchall(
        "SELECT * FROM todos WHERE status IN ('todo', 'doing') ORDER BY "
        "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, due_date ASC"
    )

    urgent = []
    overdue = []
    warning = []

    for r in rows:
        todo = dict(r)
        due = todo.get("due_date", "")

        if due:
            try:
                due_dt = datetime.fromisoformat(due)
                days_left = (due_dt - now).total_seconds() / 86400
            except:
                days_left = 999

            if days_left < 0:
                overdue.append({
                    "id": todo["id"], "title": todo["title"],
                    "priority": todo["priority"],
                    "due": due, "days_overdue": int(abs(days_left)),
                    "level": "critical",
                })
            elif days_left <= 1 and todo["priority"] == "high":
                urgent.append({
                    "id": todo["id"], "title": todo["title"],
                    "priority": todo["priority"],
                    "due": due, "hours_left": int(days_left * 24),
                    "level": "critical",
                })
            elif days_left <= 1:
                warning.append({
                    "id": todo["id"], "title": todo["title"],
                    "due": due, "level": "warning",
                })
            elif days_left <= 3:
                warning.append({
                    "id": todo["id"], "title": todo["title"],
                    "due": due, "level": "warning",
                })

        # 高优 + 3 天未动
        created = todo.get("created_at", "")
        if created and todo["priority"] == "high":
            try:
                created_dt = datetime.fromisoformat(created)
                days_idle = (now - created_dt).days
                if days_idle >= 3 and todo["id"] not in [x["id"] for x in urgent + overdue + warning]:
                    warning.append({
                        "id": todo["id"], "title": todo["title"],
                        "days_idle": days_idle, "level": "warning",
                    })
            except:
                pass

        # 创建超过 7 天未动
        if created:
            try:
                created_dt = datetime.fromisoformat(created)
                days_idle = (now - created_dt).days
                if days_idle >= 7 and todo["id"] not in [x["id"] for x in urgent + overdue + warning]:
                    warning.append({
                        "id": todo["id"], "title": todo["title"],
                        "days_idle": days_idle, "level": "info",
                    })
            except:
                pass

    total_risks = len(urgent) + len(overdue)
    parts = []
    if urgent:
        parts.append(f"{len(urgent)} 条紧急")
    if overdue:
        parts.append(f"{len(overdue)} 条逾期")
    if warning:
        parts.append(f"{len(warning)} 条预警")
    summary = "，".join(parts) if parts else "无风险"

    return {
        "urgent": urgent,
        "overdue": overdue,
        "warning": warning[:5],  # 最多 5 条
        "summary": summary,
        "checked_at": today,
    }


def get_todo_stats() -> dict:
    """获取待办统计。"""
    active = db.fetchone(
        "SELECT COUNT(*) as c FROM todos WHERE status IN ('todo','doing')"
    )
    high = db.fetchone(
        "SELECT COUNT(*) as c FROM todos WHERE status IN ('todo','doing') AND priority='high'"
    )
    done = db.fetchone(
        "SELECT COUNT(*) as c FROM todos WHERE status='done'"
    )
    return {
        "active": active["c"] if active else 0,
        "high_priority": high["c"] if high else 0,
        "done": done["c"] if done else 0,
    }


# ── 内部 ──

def _log_history(todo_id: str, from_status: str | None, to_status: str,
                 note: str, agent: str):
    """写入状态变更历史。"""
    db.execute(
        "INSERT INTO todo_history (todo_id, from_status, to_status, note, agent, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (todo_id, from_status, to_status, note, agent, datetime.now().isoformat()),
    )
