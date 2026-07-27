import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "memo" / "store" / "migrations"


def apply_all_migrations(conn: sqlite3.Connection):
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.executescript(migration.read_text(encoding="utf-8"))
        version = int(migration.stem.split("_", 1)[0])
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT OR IGNORE INTO schema_version(version) VALUES (?)", (version,))
    conn.commit()


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_source_aware_migration_creates_turn_episode_and_evidence_tables(tmp_path: Path):
    db_path = tmp_path / "memo_schema.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")

    apply_all_migrations(conn)

    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 20

    source_session_cols = table_columns(conn, "source_sessions")
    assert {"agent_session_id", "source_hash", "original_title", "title_source", "display_title", "display_title_source"}.issubset(source_session_cols)

    assert {"id", "source_session_id", "role", "content_hash", "turn_index", "is_tool_call", "is_tool_result"}.issubset(
        table_columns(conn, "source_turns")
    )
    assert {"id", "source_session_id", "start_turn_id", "end_turn_id", "status", "confidence"}.issubset(
        table_columns(conn, "episodes")
    )
    assert {"episode_id", "turn_id", "role_in_episode", "weight"}.issubset(table_columns(conn, "episode_turns"))
    assert {"memory_id", "turn_id", "evidence_role", "weight"}.issubset(table_columns(conn, "memory_turn_sources"))
    assert {"memory_id", "review_status", "retention_class", "recall_policy", "quality_score", "auto_flags_json"}.issubset(
        table_columns(conn, "memory_quality_reviews")
    )
    assert {"source_session_id", "review_status", "review_note", "manual_done_count", "manual_progress_count"}.issubset(
        table_columns(conn, "source_session_review_states")
    )

    memory_cols = table_columns(conn, "memory_units")
    assert {
        "source_session_id",
        "episode_id",
        "source_turn_start_id",
        "source_turn_end_id",
        "memory_granularity",
        "speaker_scope",
        "source_confidence",
        "is_canonical",
    }.issubset(memory_cols)

    conn.close()


def test_source_aware_migration_supports_minimal_evidence_chain(tmp_path: Path):
    db_path = tmp_path / "memo_chain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_all_migrations(conn)

    conn.execute("INSERT INTO sessions(id, agent_id, title) VALUES ('memo-session-1', 'test', 'test session')")
    conn.execute(
        """INSERT INTO source_sessions
           (id, source_type, source_agent, agent_session_id, title_source, original_title, display_title, legacy_session_id)
           VALUES ('source-1', 'agent_session', 'HanaAgent', 'agent-session-1', 'agent_original', 'Original Title', 'Original Title', 'memo-session-1')"""
    )
    conn.execute(
        """INSERT INTO source_turns
           (id, source_session_id, role, content, content_hash, turn_index)
           VALUES ('turn-1', 'source-1', 'user', 'hello', 'hash-1', 0)"""
    )
    conn.execute(
        """INSERT INTO episodes
           (id, source_session_id, title, user_intent, start_turn_id, end_turn_id, status, confidence)
           VALUES ('episode-1', 'source-1', 'Episode', 'intent', 'turn-1', 'turn-1', 'ready', 0.9)"""
    )
    conn.execute(
        """INSERT INTO episode_turns(episode_id, turn_id, role_in_episode, weight)
           VALUES ('episode-1', 'turn-1', 'trigger', 1.0)"""
    )
    conn.execute(
        """INSERT INTO memory_units
           (id, session_id, title, summary, memory_type, source_session_id, episode_id,
            source_turn_start_id, source_turn_end_id, memory_granularity, speaker_scope, source_confidence, is_canonical)
           VALUES ('memory-1', 'memo-session-1', 'Memory', 'Summary', 'FACT', 'source-1', 'episode-1',
                   'turn-1', 'turn-1', 'turn', 'user_claim', 0.95, 0)"""
    )
    conn.execute(
        """INSERT INTO memory_turn_sources(memory_id, turn_id, evidence_role, weight)
           VALUES ('memory-1', 'turn-1', 'source', 1.0)"""
    )
    conn.commit()

    row = conn.execute(
        """SELECT mu.id, ss.original_title, st.role, e.title
           FROM memory_units mu
           JOIN source_sessions ss ON ss.id=mu.source_session_id
           JOIN source_turns st ON st.id=mu.source_turn_start_id
           JOIN episodes e ON e.id=mu.episode_id
           WHERE mu.id='memory-1'"""
    ).fetchone()

    assert row == ("memory-1", "Original Title", "user", "Episode")
    conn.close()
