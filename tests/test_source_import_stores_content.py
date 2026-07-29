import sqlite3
from pathlib import Path

from scripts.source_aware_import import SourceSessionDraft, SourceTurnDraft, insert_turns


def test_insert_turns_stores_raw_content_and_never_replaces_existing_with_empty(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "test.db")
    conn.execute("CREATE TABLE source_turns (id TEXT PRIMARY KEY, source_session_id TEXT, agent_turn_id TEXT, parent_turn_id TEXT, role TEXT, content TEXT, content_hash TEXT, timestamp TEXT, turn_index INTEGER, is_final_answer INTEGER, is_tool_call INTEGER, is_tool_result INTEGER, tool_name TEXT, source_event_type TEXT, metadata_json TEXT)")
    turn = SourceTurnDraft(role="user", text="真实对话正文", content_hash="hash1", turn_index=0)
    session = SourceSessionDraft(source_agent="HanaAgent", agent_session_id="s", source_path="x", source_hash="h", title_source="agent_original", has_original_title=True, turns=[turn])
    insert_turns(conn, "source1", session)
    assert conn.execute("SELECT content FROM source_turns").fetchone()[0] == "真实对话正文"
    turn.text = ""
    insert_turns(conn, "source1", session)
    assert conn.execute("SELECT content FROM source_turns").fetchone()[0] == "真实对话正文"
