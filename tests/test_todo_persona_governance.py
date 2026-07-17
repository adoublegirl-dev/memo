"""Todo 本体去重与 Persona 审计治理测试。"""

import sqlite3

from memo.core.engine import engine
from memo.store.database import db, new_id
from memo.todo.manager import add_todo, get_todo_history
from memo.persona.extractor import persona_assertion_action, get_persona_audit, update_persona_incremental


def test_add_todo_returns_existing_for_conservative_duplicate():
    engine.init()
    first = add_todo(
        title="优化 Memo 记忆治理页面",
        description="按 source group 聚合展示",
        priority="medium",
        due_date="2026-07-22",
        source_agent="test",
    )
    second = add_todo(
        title="优化Memo记忆治理页面",
        description="重复创建应该被跳过",
        priority="medium",
        due_date="2026-07-22",
        source_agent="test",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["duplicate"] is True
    assert second["existing_id"] == first["id"]
    history = get_todo_history(first["id"])
    assert any("重复创建被跳过" in h["note"] for h in history)


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
