import os
from uuid import uuid4

os.environ["MEMO_ENV"] = "test"

from memo.core.engine import engine
from memo.store.database import db


def _seed_source_aware_fixture():
    engine.init()
    suffix = uuid4().hex[:8]
    session_id = f"memo_session_{suffix}"
    source_id = f"source_{suffix}"
    turn_user = f"turn_user_{suffix}"
    turn_assistant = f"turn_assistant_{suffix}"
    episode_id = f"episode_{suffix}"
    memory_id = f"memory_{suffix}"

    db.execute(
        "INSERT INTO sessions(id, agent_id, title, status, created_at) VALUES (?, 'test-agent', 'source aware test', 'active', '2026-07-27T10:00:00')",
        (session_id,),
    )
    db.execute(
        """INSERT INTO source_sessions
           (id, source_type, source_agent, external_session_id, agent_session_id, source_path,
            source_hash, original_title, title_source, display_title, display_title_source,
            started_at, updated_at, imported_at, message_count, content_hash, status, metadata_json, created_at)
           VALUES (?, 'agent_session', 'Codex', ?, ?, '~/redacted.jsonl', 'hash123', '', 'missing',
                   '首个用户问题生成的展示标题', 'first_user_turn', '2026-07-27T10:00:00',
                   '2026-07-27T10:05:00', '2026-07-27T10:06:00', 2, 'hash123', 'active', '{}', '2026-07-27T10:06:00')""",
        (source_id, source_id, source_id),
    )
    db.execute(
        """INSERT INTO source_turns
           (id, source_session_id, role, content, content_hash, timestamp, turn_index,
            is_final_answer, is_tool_call, is_tool_result, tool_name, source_event_type, metadata_json)
           VALUES (?, ?, 'user', '', 'userhash', '2026-07-27T10:01:00', 0, 0, 0, 0, '', 'event_msg:user_message', '{""content_length"":42}')""".replace('""', '"'),
        (turn_user, source_id),
    )
    db.execute(
        """INSERT INTO source_turns
           (id, source_session_id, role, content, content_hash, timestamp, turn_index,
            is_final_answer, is_tool_call, is_tool_result, tool_name, source_event_type, metadata_json)
           VALUES (?, ?, 'assistant', '', 'assisthash', '2026-07-27T10:02:00', 1, 1, 0, 0, '', 'response_item:message', '{""content_length"":80}')""".replace('""', '"'),
        (turn_assistant, source_id),
    )
    db.execute(
        """INSERT INTO episodes
           (id, source_session_id, title, user_intent, start_turn_id, end_turn_id, start_turn_index, end_turn_index,
            status, confidence, metadata_json, created_at, updated_at)
           VALUES (?, ?, '测试 episode', '验证 source-aware dashboard', ?, ?, 0, 1, 'imported', 0.9, '{}', '2026-07-27T10:03:00', '2026-07-27T10:03:00')""",
        (episode_id, source_id, turn_user, turn_assistant),
    )
    db.execute(
        "INSERT INTO episode_turns(episode_id, turn_id, role_in_episode, weight) VALUES (?, ?, 'trigger', 1.0)",
        (episode_id, turn_user),
    )
    db.execute(
        """INSERT INTO memory_units
           (id, session_id, title, summary, raw_text, memory_type, source_session_id, episode_id,
            source_turn_start_id, source_turn_end_id, memory_granularity, speaker_scope, source_confidence, is_canonical)
           VALUES (?, ?, '测试记忆', '这是一条用于 source-aware dashboard 的测试记忆', '', 'FACT', ?, ?, ?, ?, 'episode', 'user_claim', 0.85, 1)""",
        (memory_id, session_id, source_id, episode_id, turn_user, turn_assistant),
    )
    db.execute(
        "INSERT INTO memory_turn_sources(memory_id, turn_id, evidence_role, weight) VALUES (?, ?, 'source', 1.0)",
        (memory_id, turn_user),
    )
    db.commit()
    return {"source_id": source_id, "memory_id": memory_id}


def test_source_aware_dashboard_lists_missing_titles_and_counts():
    ids = _seed_source_aware_fixture()

    overview = engine.source_aware_dashboard(mode="missing_titles", q="展示标题")

    assert overview["stats"]["source_sessions"] >= 1
    assert overview["stats"]["missing_original_titles"] >= 1
    assert overview["stats"]["memories_with_evidence"] >= 1
    row = next(s for s in overview["sessions"] if s["id"] == ids["source_id"])
    assert row["title_source"] == "missing"
    assert row["display_title_source"] == "first_user_turn"
    assert row["is_missing_title"] is True
    assert row["memory_count"] >= 1
    assert row["evidence_count"] >= 1


def test_source_aware_quality_rules_apply_review_table_and_recall_gate():
    ids = _seed_source_aware_fixture()
    temp_id = f"memory_temp_{ids['memory_id']}"
    db.execute(
        """INSERT INTO memory_units
           (id, session_id, title, summary, raw_text, memory_type, source_session_id, episode_id,
            source_turn_start_id, source_turn_end_id, memory_granularity, speaker_scope, source_confidence, is_canonical)
           SELECT ?, session_id, '帮我安装测试工具', '帮我安装测试工具', '', 'FACT', source_session_id, episode_id,
                  source_turn_start_id, source_turn_end_id, 'episode', 'user_claim', 0.5, 1
           FROM memory_units WHERE id=?""",
        (temp_id, ids["memory_id"]),
    )
    db.commit()

    result = engine.apply_source_aware_quality_rules(dry_run=False)
    temp_review = db.fetchone("SELECT * FROM memory_quality_reviews WHERE memory_id=?", (temp_id,))
    clean_review = db.fetchone("SELECT * FROM memory_quality_reviews WHERE memory_id=?", (ids["memory_id"],))

    assert result["applied"] >= 2
    assert temp_review["retention_class"] == "temporary_task"
    assert temp_review["recall_policy"] == "exclude_default"
    assert clean_review["recall_policy"] in {"include", "downrank"}
    assert engine._memory_quality_gate(temp_id)["participates"] is False


def test_source_aware_memory_quality_returns_readonly_flags():
    ids = _seed_source_aware_fixture()

    db.execute(
        """INSERT INTO memory_units
           (id, session_id, title, summary, raw_text, memory_type, source_session_id, episode_id,
            source_turn_start_id, source_turn_end_id, memory_granularity, speaker_scope, source_confidence, is_canonical)
           SELECT ?, session_id, '帮我安装测试工具', '帮我安装测试工具', '', 'FACT', source_session_id, episode_id,
                  source_turn_start_id, source_turn_end_id, 'episode', 'user_claim', 0.5, 1
           FROM memory_units WHERE id=?""",
        (f"memory_temp_{ids['memory_id']}", ids["memory_id"]),
    )
    db.commit()

    quality = engine.source_aware_memory_quality(limit=5)

    assert quality["schema_status"]["ready"] is True
    assert quality["counts"]["source_aware_memories"] >= 1
    assert quality["flags"]["temporary_task_like_hits"] >= 1
    assert quality["samples"]["temporary_task_like_hits"]
    assert "raw_text" not in quality["samples"]["temporary_task_like_hits"][0]


def test_source_aware_session_detail_and_evidence_do_not_return_raw_content():
    ids = _seed_source_aware_fixture()

    detail = engine.source_aware_session_detail(ids["source_id"])
    evidence = engine.source_aware_memory_evidence(ids["memory_id"])

    assert detail is not None
    assert detail["session"]["id"] == ids["source_id"]
    assert detail["turns"][0]["content_hash"] == "userhash"
    assert "content" not in detail["turns"][0]
    assert detail["episodes"][0]["title"] == "测试 episode"
    assert detail["memory_units"][0]["evidence_count"] >= 1

    assert evidence is not None
    assert evidence["memory"]["id"] == ids["memory_id"]
    assert evidence["evidence"][0]["turn_id"].startswith("turn_user_")
    assert "content" not in evidence["evidence"][0]
