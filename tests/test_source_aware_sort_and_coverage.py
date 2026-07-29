from memo.core.engine import engine
from memo.store.database import db


def seed(source_id: str, turns: list[str]):
    db.execute(
        """INSERT OR REPLACE INTO source_sessions
           (id, source_agent, agent_session_id, source_path, source_hash, display_title, title_source, display_title_source, created_at, updated_at, imported_at, message_count, status)
           VALUES (?, 'HanaAgent', ?, 'test', ?, ?, 'agent_original', 'agent_original', datetime('now'), datetime('now'), datetime('now'), ?, 'active')""",
        (source_id, source_id, f'hash-{source_id}', source_id, len(turns)),
    )
    for index, content in enumerate(turns):
        db.execute(
            """INSERT OR REPLACE INTO source_turns
               (id, source_session_id, role, content, content_hash, metadata_json, turn_index, is_final_answer, is_tool_call, is_tool_result)
               VALUES (?, ?, 'user', ?, ?, ?, ?, 0, 0, 0)""",
            (f'{source_id}-turn-{index}', source_id, content, f'hash-{source_id}-{index}', '{"content_length": 30}', index),
        )
    db.commit()


def test_source_aware_dashboard_exposes_content_coverage_and_turn_sort():
    engine.init()
    seed('ss_coverage_small', ['text'])
    seed('ss_coverage_large', ['text', 'more text', ''])

    page = engine.source_aware_dashboard(q='ss_coverage', sort='turns_desc', page_size=10)
    rows = page['sessions']
    assert rows[0]['id'] == 'ss_coverage_large'
    assert rows[0]['turn_count'] == 3
    assert rows[0]['reviewable_turn_count'] == 2
    assert rows[0]['pending_content_turn_count'] == 1
    assert rows[0]['internal_event_count'] >= 1
