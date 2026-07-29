from memo.core.engine import engine
from memo.store.database import db


def seed(source_id: str):
    db.execute(
        """INSERT OR REPLACE INTO source_sessions
           (id, source_agent, agent_session_id, source_path, source_hash, display_title, title_source, display_title_source, created_at, updated_at, imported_at, message_count, status)
           VALUES (?, 'HanaAgent', ?, 'test', ?, ?, 'agent_original', 'agent_original', datetime('now'), datetime('now'), datetime('now'), 5, 'active')""",
        (source_id, source_id, f'hash-{source_id}', source_id),
    )
    values = [
        ('user', '可审内容 1'), ('assistant', '可审内容 2'), ('assistant', ''), ('unknown', ''), ('user', '可审内容 3'),
    ]
    for index, (role, content) in enumerate(values):
        db.execute(
            """INSERT OR REPLACE INTO source_turns
               (id, source_session_id, role, content, content_hash, metadata_json, turn_index, is_final_answer, is_tool_call, is_tool_result, source_event_type)
               VALUES (?, ?, ?, ?, ?, '{"content_length": 10}', ?, 0, 0, 0, 'message')""",
            (f'{source_id}-{index}', source_id, role, content, f'hash-{source_id}-{index}', index),
        )
    db.commit()


def test_source_session_detail_filters_and_pages_on_server():
    engine.init()
    source_id = 'ss_turn_page_test'
    seed(source_id)

    reviewable = engine.source_aware_session_detail(source_id, turn_filter='reviewable', turn_page=1, turn_page_size=20)
    internal = engine.source_aware_session_detail(source_id, turn_filter='internal', turn_page=1, turn_page_size=20)
    all_turns = engine.source_aware_session_detail(source_id, turn_filter='all', turn_page=1, turn_page_size=2)

    assert reviewable['turn_counts'] == {'all': 5, 'reviewable': 3, 'internal': 2}
    assert reviewable['turn_total'] == 3
    assert len(reviewable['turns']) == 3
    assert internal['turn_total'] == 2
    assert len(internal['turns']) == 2
    assert all_turns['turn_total'] == 5
    assert len(all_turns['turns']) == 2
