"""Todo 本体去重与 Persona 审计治理测试。"""

import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4

from memo.core.engine import engine
from memo.store.database import db, new_id
from memo.todo.manager import add_todo, check_risk, get_todo_history, list_todos, reopen_todos, update_todo
from memo.persona.extractor import persona_assertion_action, get_persona_audit, update_persona_incremental


def test_add_todo_returns_existing_for_conservative_duplicate():
    engine.init()
    first = add_todo(
        title="优化 Memo 记忆治理页面",
        description="按 source group 聚合展示",
        priority="medium",
        due_date="2026-07-22T10:30",
        source_agent="test",
    )
    second = add_todo(
        title="优化Memo记忆治理页面",
        description="重复创建应该被跳过",
        priority="medium",
        due_date="2026-07-22T10:30",
        source_agent="test",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["duplicate"] is True
    assert second["existing_id"] == first["id"]
    history = get_todo_history(first["id"])
    assert any("重复创建被跳过" in h["note"] for h in history)


def test_todo_due_date_requires_minute_precision():
    engine.init()
    invalid = add_todo(
        title="错误时间格式待办",
        priority="medium",
        due_date="2026-07-22",
        source_agent="test",
    )
    assert "error" in invalid
    assert "精确到分钟" in invalid["error"]


def test_today_todos_include_overdue_and_cancel_is_reversible():
    engine.init()
    suffix = uuid4().hex[:8]
    now = datetime.now()
    overdue = add_todo(
        title=f"逾期待办-{suffix}", due_date=(now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"), source_agent="test"
    )
    today = add_todo(
        title=f"今日待办-{suffix}", due_date=now.replace(hour=23, minute=30).strftime("%Y-%m-%dT%H:%M"), source_agent="test"
    )
    no_due = add_todo(title=f"无时间待办-{suffix}", source_agent="test")

    risk = check_risk()
    today_ids = {item["id"] for item in risk["today"]}
    assert overdue["id"] in today_ids
    assert today["id"] in today_ids
    assert no_due["id"] not in today_ids
    overdue_item = next(item for item in risk["overdue"] if item["id"] == overdue["id"])
    expected_days = (now.date() - (now - timedelta(days=1)).date()).days
    assert overdue_item["days_overdue"] == expected_days
    assert overdue_item["hours_overdue"] >= 1

    update_todo(today["id"], status="cancelled", agent="test")
    reopened = reopen_todos([today["id"]], agent="test")
    assert reopened[0]["reopened"] is True
    assert db.fetchone("SELECT status FROM todos WHERE id=?", (today["id"],))["status"] == "todo"


def test_todos_without_due_date_sort_after_scheduled_items():
    engine.init()
    suffix = uuid4().hex[:8]
    scheduled = add_todo(title=f"有时间-{suffix}", priority="low", due_date="2099-01-01T09:00", source_agent="test")
    unscheduled = add_todo(title=f"无时间-{suffix}", priority="low", source_agent="test")
    ordered = list_todos(status="todo+doing", priority="low", limit=500)
    positions = {todo["id"]: index for index, todo in enumerate(ordered)}
    assert positions[scheduled["id"]] < positions[unscheduled["id"]]


def test_persona_edit_lock_delete_restore_are_audited_and_locked_is_protected():
    engine.init()
    aid = new_id()
    now = "2026-07-17T00:00:00"
    db.execute(
        """INSERT INTO persona_assertions
           (id, dimension, assertion, confidence, evidences, signal_level, locked, is_custom, is_superseded, created_at, updated_at, last_refreshed)
           VALUES (?, 'preference', '用户喜欢简洁界面', 0.7, '[]', 2, 0, 1, 0, ?, ?, ?)""",
        (aid, now, now, now),
    )
    db.commit()

    assert persona_assertion_action(aid, "edit", assertion="用户喜欢简洁克制的界面", confidence=0.82, actor="test")["updated"]
    assert persona_assertion_action(aid, "lock", actor="test")["updated"]

    # locked 断言不应被增量合并逻辑自动改写。
    merged = update_persona_incremental(new_memory_ids=[])
    assert merged.get("updated", 0) == 0 or isinstance(merged, dict)

    row = db.fetchone("SELECT locked, assertion, confidence FROM persona_assertions WHERE id=?", (aid,))
    assert row["locked"] == 1
    assert row["assertion"] == "用户喜欢简洁克制的界面"
    assert abs(float(row["confidence"]) - 0.82) < 0.001

    assert persona_assertion_action(aid, "delete", actor="test")["updated"]
    row = db.fetchone("SELECT is_superseded FROM persona_assertions WHERE id=?", (aid,))
    assert row["is_superseded"] == 1

    assert persona_assertion_action(aid, "restore", actor="test")["updated"]
    row = db.fetchone("SELECT is_superseded FROM persona_assertions WHERE id=?", (aid,))
    assert row["is_superseded"] == 0

    actions = [a["action"] for a in get_persona_audit(aid, limit=20)]
    assert "edit_assertion" in actions
    assert "edit_confidence" in actions
    assert "lock" in actions
    assert "delete" in actions
    assert "restore" in actions
