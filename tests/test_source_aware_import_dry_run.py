import json
import subprocess
import sys
from pathlib import Path

from scripts.source_aware_import import (
    GenericTranscriptAdapter,
    apply_all_migrations,
    apply_to_test_db,
    extract_memory_units_from_source_sessions,
    insert_episodes_only,
    insert_source_session,
    insert_turns,
    parse_codex_jsonl,
    parse_generic_jsonl,
    run_dry_run,
    is_memory_subject_text,
)


def test_parse_generic_jsonl_counts_roles_and_tools(tmp_path: Path):
    transcript = tmp_path / "session.jsonl"
    lines = [
        {"type": "message", "role": "user", "content": "请帮我分析一个长期记忆系统的架构问题"},
        {"type": "message", "role": "assistant", "content": "可以，我们先拆解底层数据结构。"},
        {"type": "tool_call", "role": "assistant", "content": [{"type": "tool_use", "name": "read"}]},
        {"type": "tool_result", "role": "tool", "content": [{"type": "tool_result", "text": "ok"}]},
    ]
    transcript.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")

    turns, first_user_text = parse_generic_jsonl(transcript)

    assert len(turns) == 4
    assert "长期记忆系统" in first_user_text
    assert turns[0].role == "user"
    assert turns[1].is_final_answer is True
    assert any(t.is_tool_call for t in turns)
    assert any(t.is_tool_result for t in turns)


def test_parse_codex_jsonl_payload_wrapped_events(tmp_path: Path):
    transcript = tmp_path / "codex.jsonl"
    lines = [
        {"timestamp": "2026-07-20T10:00:00Z", "type": "session_meta", "payload": {"session_id": "codex-session-1", "cwd": "D:/demo"}},
        {"timestamp": "2026-07-20T10:00:01Z", "type": "event_msg", "payload": {"type": "user_message", "message": "请分析这个 source-aware 导入方案如何处理 Codex 正文结构"}},
        {"timestamp": "2026-07-20T10:00:02Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "可以，先识别 payload 包裹。"}]}},
        {"timestamp": "2026-07-20T10:00:03Z", "type": "response_item", "payload": {"type": "function_call", "name": "read", "arguments": "{}", "call_id": "call_1"}},
        {"timestamp": "2026-07-20T10:00:04Z", "type": "response_item", "payload": {"type": "function_call_output", "call_id": "call_1", "output": "ok"}},
    ]
    transcript.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")

    turns, first_user_text, agent_session_id = parse_codex_jsonl(transcript)

    assert agent_session_id == "codex-session-1"
    assert len(turns) == 4
    assert turns[0].role == "user"
    assert "Codex 正文结构" in first_user_text
    assert turns[1].is_final_answer is True
    assert turns[2].is_tool_call is True
    assert turns[3].is_tool_result is True


def test_generic_adapter_dry_run_does_not_include_raw_content(tmp_path: Path):
    transcript = tmp_path / "session.jsonl"
    secret_text = "这是不应该进入报告的原始聊天正文"
    transcript.write_text(
        json.dumps({"type": "message", "role": "user", "content": secret_text}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    report = GenericTranscriptAdapter(transcript).dry_run()
    payload = json.dumps(report.to_dict(), ensure_ascii=False)

    assert report.scanned_sessions == 1
    assert report.importable_source_sessions == 1
    assert report.source_turns == 1
    assert secret_text not in payload
    assert "content_hash" not in payload  # preview intentionally stays at aggregate/session level


def test_run_dry_run_generic(tmp_path: Path):
    transcript = tmp_path / "session.txt"
    transcript.write_text("User: 这个项目后续要保留来源会话关系，并且每一条长期记忆都必须可以追溯到具体 turn\nAssistant: 好，先做 dry-run。", encoding="utf-8")

    report = run_dry_run("generic", path=str(transcript))

    assert report.source == "generic"
    assert report.scanned_sessions == 1
    assert report.estimated_episodes >= 1


def test_source_only_insert_does_not_create_memory_units(tmp_path: Path):
    import sqlite3
    transcript = tmp_path / "session.txt"
    transcript.write_text(
        "User: 这个项目后续要保留来源会话关系，并且先只导入 source 和 episode\nAssistant: 好。",
        encoding="utf-8",
    )
    db_path = tmp_path / "source_aware_source_only_test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_all_migrations(conn)
    session = GenericTranscriptAdapter(transcript).load_session(transcript)

    source_id, memo_session_id = insert_source_session(conn, session)
    turn_ids = insert_turns(conn, source_id, session)
    episodes = insert_episodes_only(conn, source_id, memo_session_id, session, turn_ids)
    conn.commit()

    assert episodes >= 1
    assert conn.execute("SELECT COUNT(*) FROM source_sessions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM source_turns").fetchone()[0] == len(turn_ids)
    assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == episodes
    assert conn.execute("SELECT COUNT(*) FROM memory_units").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM memory_turn_sources").fetchone()[0] == 0
    conn.close()


def test_memory_subject_filter_blocks_system_and_command_markup():
    assert is_memory_subject_text("这个项目后续要保留来源会话关系，并且先只导入 source 和 episode") is True
    assert is_memory_subject_text('<system-reminder data-role="user-context">hidden</system-reminder>') is False
    assert is_memory_subject_text('<command-name>/status</command-name>') is False
    assert is_memory_subject_text('<local-command-stdout>ok</local-command-stdout>') is False
    assert is_memory_subject_text('[Use skill: user-guide] 默认模型指的是助手的配置吗') is False
    assert is_memory_subject_text('[SessionFile] {"fileId":"sf_xxx"}') is False
    assert is_memory_subject_text('<environment_context><cwd>C:/tmp</cwd></environment_context>') is False
    assert is_memory_subject_text('The following is the Codex agent history after compaction') is False


def test_source_only_episode_boundary_ignores_system_markup(tmp_path: Path):
    import sqlite3
    transcript = tmp_path / "session.txt"
    transcript.write_text(
        'User: <system-reminder data-role="user-context">hidden context should not become episode</system-reminder>\nAssistant: 好。',
        encoding="utf-8",
    )
    db_path = tmp_path / "source_aware_system_skip_test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_all_migrations(conn)
    session = GenericTranscriptAdapter(transcript).load_session(transcript)
    source_id, memo_session_id = insert_source_session(conn, session)
    turn_ids = insert_turns(conn, source_id, session)
    episodes = insert_episodes_only(conn, source_id, memo_session_id, session, turn_ids)
    conn.commit()
    assert episodes == 0
    assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0
    conn.close()


def test_conservative_memory_extraction_ignores_tool_subjects(tmp_path: Path):
    import sqlite3
    transcript = tmp_path / "session.txt"
    transcript.write_text(
        "User: 这个项目后续要保留来源会话关系，并且先只导入 source 和 episode\nAssistant: 好，这是最终回答。\nTool: 这是过程性工具结果，不应成为长期记忆主体。",
        encoding="utf-8",
    )
    db_path = tmp_path / "source_aware_extract_test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_all_migrations(conn)
    session = GenericTranscriptAdapter(transcript).load_session(transcript)
    source_id, memo_session_id = insert_source_session(conn, session)
    turn_ids = insert_turns(conn, source_id, session)
    insert_episodes_only(conn, source_id, memo_session_id, session, turn_ids)
    conn.commit()
    conn.close()

    result = extract_memory_units_from_source_sessions(db_path, source_agent="GenericTranscript", limit=5)

    assert result["extracted"]["memory_units_created"] == 1
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT speaker_scope, raw_text FROM memory_units LIMIT 1").fetchone()
    evidence_roles = conn.execute("SELECT evidence_role FROM memory_turn_sources ORDER BY evidence_role").fetchall()
    conn.close()
    assert row[0] == "user_claim"
    assert row[1] == ""
    assert ("source",) in evidence_roles


def test_source_aware_import_apply_requires_confirm():
    result = subprocess.run(
        [sys.executable, "scripts/source_aware_import.py", "--source", "generic", "--path", ".", "--apply"],
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 2
    assert "--confirm TEST_APPLY" in result.stderr


def test_apply_to_test_db_rejects_unsafe_path(tmp_path: Path):
    transcript = tmp_path / "session.txt"
    transcript.write_text("User: 这个项目后续要保留来源会话关系\nAssistant: 好。", encoding="utf-8")

    unsafe_db = Path(__file__).resolve().parent.parent / "data" / "memo.db"
    try:
        apply_to_test_db("generic", unsafe_db, path=str(transcript), limit=1)
    except ValueError as exc:
        assert "拒绝写入生产数据库路径" in str(exc) or "必须包含 test/dev/sandbox/dryrun/source_aware" in str(exc)
    else:
        raise AssertionError("unsafe db path should be rejected")


def test_apply_to_test_db_writes_evidence_chain_to_test_database(tmp_path: Path):
    transcript = tmp_path / "session.txt"
    transcript.write_text(
        "User: 这个项目后续要保留来源会话关系，并且每一条长期记忆都必须能追溯到原始会话和具体对话轮次\nAssistant: 好，先做测试库导入。",
        encoding="utf-8",
    )
    db_path = tmp_path / "source_aware_test.db"

    result = apply_to_test_db("generic", db_path, path=str(transcript), limit=1)

    assert result["validation"]["schema_version"] == 19
    assert result["validation"]["source_sessions"] == 1
    assert result["validation"]["source_turns"] >= 1
    assert result["validation"]["episodes"] >= 1
    assert result["validation"]["memory_units"] >= 1
    assert result["validation"]["evidence_links"] >= 1


def test_apply_to_test_db_uses_first_user_turn_display_title_for_missing_original_title(tmp_path: Path):
    transcript = tmp_path / "session.txt"
    transcript.write_text(
        "User: 这是一个没有原始标题的测试会话，需要用首个用户问题作为展示标题\nAssistant: 好。",
        encoding="utf-8",
    )
    db_path = tmp_path / "source_aware_display_test.db"

    result = apply_to_test_db("generic", db_path, path=str(transcript), limit=1)

    assert result["validation"]["schema_version"] == 19
    import sqlite3
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT original_title, display_title, display_title_source FROM source_sessions LIMIT 1").fetchone()
    conn.close()
    assert row[0] == ""
    assert "没有原始标题" in row[1]
    assert row[2] == "first_user_turn"
