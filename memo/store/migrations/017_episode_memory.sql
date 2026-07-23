-- 017: Episode Memory / canonical memory foundation
-- 用户意图级 episode 层与历史导入审计层。
-- additive only：不重写既有记忆，不删除旧碎片，不自动迁移生产数据。

CREATE TABLE IF NOT EXISTS episodes (
    id                  TEXT PRIMARY KEY,
    source_session_id   TEXT DEFAULT NULL,
    agent_name          TEXT DEFAULT '',
    title               TEXT DEFAULT '',
    user_intent         TEXT DEFAULT '',
    start_turn_id       TEXT DEFAULT '',
    end_turn_id         TEXT DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'active',
    confidence          REAL NOT NULL DEFAULT 0,
    long_term_value_score REAL NOT NULL DEFAULT 0,
    metadata_json       TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (source_session_id) REFERENCES source_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_episodes_source_session
    ON episodes(source_session_id);
CREATE INDEX IF NOT EXISTS idx_episodes_agent_status
    ON episodes(agent_name, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_episodes_value
    ON episodes(long_term_value_score DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS episode_sources (
    episode_id          TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    role                TEXT DEFAULT '',
    weight              REAL NOT NULL DEFAULT 1.0,
    metadata_json       TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (episode_id, source_type, source_id),
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_episode_sources_source
    ON episode_sources(source_type, source_id);

CREATE TABLE IF NOT EXISTS import_runs (
    id                  TEXT PRIMARY KEY,
    source_agent        TEXT DEFAULT '',
    source_path         TEXT DEFAULT '',
    mode                TEXT DEFAULT 'recommended',
    status              TEXT DEFAULT 'dry_run',
    scanned_sessions    INTEGER NOT NULL DEFAULT 0,
    scanned_turns       INTEGER NOT NULL DEFAULT 0,
    candidate_episodes  INTEGER NOT NULL DEFAULT 0,
    imported_memories   INTEGER NOT NULL DEFAULT 0,
    skipped_items       INTEGER NOT NULL DEFAULT 0,
    report_json         TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_import_runs_source
    ON import_runs(source_agent, created_at);
CREATE INDEX IF NOT EXISTS idx_import_runs_status
    ON import_runs(status, created_at);

CREATE TABLE IF NOT EXISTS canonicalization_runs (
    id                  TEXT PRIMARY KEY,
    mode                TEXT DEFAULT 'recommended',
    status              TEXT DEFAULT 'dry_run',
    input_memory_count  INTEGER NOT NULL DEFAULT 0,
    output_memory_count INTEGER NOT NULL DEFAULT 0,
    superseded_count    INTEGER NOT NULL DEFAULT 0,
    muted_count         INTEGER NOT NULL DEFAULT 0,
    report_json         TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_canonicalization_runs_status
    ON canonicalization_runs(status, created_at);

ALTER TABLE memory_units ADD COLUMN episode_id TEXT DEFAULT '';
ALTER TABLE memory_units ADD COLUMN canonical_kind TEXT DEFAULT 'legacy';
ALTER TABLE memory_units ADD COLUMN long_term_value_score REAL DEFAULT 0;
ALTER TABLE memory_units ADD COLUMN source_trace_json TEXT DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_memory_episode
    ON memory_units(episode_id);
CREATE INDEX IF NOT EXISTS idx_memory_canonical_kind
    ON memory_units(canonical_kind, status, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_value_score
    ON memory_units(long_term_value_score DESC, created_at DESC);
