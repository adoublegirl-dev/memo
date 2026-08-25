import json
from pathlib import Path
from uuid import uuid4

from memo.core.engine import engine
from memo.store.database import db
from scripts.source_aware_import import CodexAdapter


def test_source_content_backfill_is_dry_run_first_and_backs_up_before_apply(tmp_path: Path):
    engine.init()
    transcript = tmp_path / "codex-session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"timestamp": "2026-08-01T10:00:00Z", "type": "session_meta", "payload": {"session_id": "backfill-test", "cwd": str(tmp_path)}}),
                json.dumps({"timestamp": "2026-08-01T10:00:01Z", "type": "event_msg", "payload": {"type": "user_message", "message": "需要安全回填的原始正文"}}, ensure_ascii=False),
            ]
        ),
        encoding="utf-8",
    )
    draft = CodexAdapter().load_session(transcript)
    turn = draft.turns[0]
    source_id = f"ss_backfill_{uuid4().hex[:10]}"
    turn_id = f"turn_backfill_{uuid4().hex[:10]}"
    db.execute(
        """INSERT INTO source_sessions
           (id, source_agent, agent_session_id, source_path, source_hash, display_title,
            title_source, display_title_source, created_at, updated_at, imported_at, message_count, status)
           VALUES (?, 'Codex', ?, ?, 'source-hash', '正文回填测试', 'agent_original',
                   'agent_original', datetime('now'), datetime('now'), datetime('now'), 1, 'active')""",
        (source_id, source_id, str(transcript)),
    )
    db.execute(
        """INSERT INTO source_turns
           (id, source_session_id, role, content, content_hash, metadata_json, turn_index,
            is_final_answer, is_tool_call, is_tool_result, source_event_type)
           VALUES (?, ?, ?, '', ?, ?, ?, 0, 0, 0, ?)""",
        (turn_id, source_id, turn.role, turn.content_hash, json.dumps({"content_length": len(turn.text)}), turn.turn_index, turn.source_event_type),
    )
    db.commit()

    inspection = engine.source_session_content_backfill(source_id)
    assert inspection["dry_run"] is True
    assert inspection["fillable"] == 1
    assert db.fetchone("SELECT content FROM source_turns WHERE id=?", (turn_id,))["content"] == ""
    assert "需要安全回填的原始正文" not in json.dumps(inspection, ensure_ascii=False)

    rejected = engine.source_session_content_backfill(source_id, apply=True, confirm="WRONG")
    assert "error" in rejected
    assert db.fetchone("SELECT content FROM source_turns WHERE id=?", (turn_id,))["content"] == ""

    applied = engine.source_session_content_backfill(source_id, apply=True, confirm="BACKFILL_CONTENT")
    assert applied["updated"] == 1
    assert Path(applied["backup"]).is_file()
    assert db.fetchone("SELECT content FROM source_turns WHERE id=?", (turn_id,))["content"] == "需要安全回填的原始正文"
