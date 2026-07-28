from memo.core.engine import engine
from memo.store.database import db


def seed_session_with_turns():
    engine.init()
    session = engine.start_session(title="批处理会话")
    source_id = "ss_batch_review_test"
    db.execute(
        """INSERT OR REPLACE INTO source_sessions
           (id, source_agent, agent_session_id, source_path, source_hash, display_title, title_source, display_title_source, created_at, updated_at, imported_at, message_count, status)
           VALUES (?, 'HanaAgent', ?, 'test-path', 'hash-batch', '批处理会话', 'agent_original', 'agent_original', datetime('now'), datetime('now'), datetime('now'), 2, 'active')""",
        (source_id, session.id),
    )
    for index in (1, 2):
        db.execute(
            """INSERT OR REPLACE INTO source_turns
               (id, source_session_id, role, content, content_hash, metadata_json, turn_index, is_final_answer, is_tool_call, is_tool_result)
               VALUES (?, ?, 'user', ?, ?, '{}', ?, 0, 0, 0)""",
            (f"turn_batch_{index}", source_id, f"text {index}", f"hash {index}", index),
        )
    db.commit()
    return source_id, ["turn_batch_1", "turn_batch_2"]


def test_batch_source_session_review_only_updates_selected_rows():
    source_id, _ = seed_session_with_turns()
    result = engine.source_session_review_batch_update([source_id], "in_review", note="统一处理")

    assert result["updated"] == 1
    state = db.fetchone("SELECT review_status, review_note FROM source_session_review_states WHERE source_session_id=?", (source_id,))
    assert dict(state) == {"review_status": "in_review", "review_note": "统一处理"}


def test_batch_turn_soft_delete_is_reversible_state_not_content_delete():
    _, turn_ids = seed_session_with_turns()
    result = engine.source_turn_review_batch_update(turn_ids, "soft_deleted", note="无有效内容")

    assert result["updated"] == 2
    still_there = db.fetchone("SELECT COUNT(*) AS c FROM source_turns WHERE id IN (?, ?)", tuple(turn_ids))
    assert still_there["c"] == 2
    marked = db.fetchone("SELECT COUNT(*) AS c FROM source_turn_review_states WHERE review_status='soft_deleted' AND review_note='无有效内容'")
    assert marked["c"] >= 2

    restored = engine.source_turn_review_batch_update(turn_ids, "active", note="恢复")
    assert restored["updated"] == 2
