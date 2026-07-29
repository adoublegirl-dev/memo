from memo.core.engine import engine
from memo.store.database import db


def test_source_session_detail_returns_content_only_for_opened_session():
    engine.init()
    source_id = "ss_detail_content_test"
    other_id = "ss_detail_content_other"
    for sid in (source_id, other_id):
        db.execute(
            """INSERT OR REPLACE INTO source_sessions
               (id, source_agent, agent_session_id, source_path, source_hash, display_title, title_source, display_title_source, created_at, updated_at, imported_at, message_count, status)
               VALUES (?, 'HanaAgent', ?, 'test', ?, ?, 'agent_original', 'agent_original', datetime('now'), datetime('now'), datetime('now'), 1, 'active')""",
            (sid, sid, f"hash-{sid}", sid),
        )
    db.execute(
        """INSERT OR REPLACE INTO source_turns
           (id, source_session_id, role, content, content_hash, metadata_json, turn_index, is_final_answer, is_tool_call, is_tool_result)
           VALUES ('turn_detail_content_test', ?, 'user', '仅此会话详情应返回的原始内容', 'hash-turn', '{}', 1, 0, 0, 0)""",
        (source_id,),
    )
    db.commit()

    detail = engine.source_aware_session_detail(source_id)
    assert detail is not None
    assert detail["turns"][0]["content"] == "仅此会话详情应返回的原始内容"
    assert all(turn["source_session_id"] == source_id if "source_session_id" in turn else True for turn in detail["turns"])
