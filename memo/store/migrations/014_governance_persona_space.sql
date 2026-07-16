-- 014: P1-P3 governance / persona / space enhancements
-- ingestion events, memory merge links, persona audit/cost, space aliases normalization and summaries.

CREATE TABLE IF NOT EXISTS ingestion_events (
    id                  TEXT PRIMARY KEY,
    source_type         TEXT NOT NULL DEFAULT 'unknown',
    source_agent        TEXT DEFAULT '',
    source_session_id   TEXT DEFAULT '',
    source_message_hash TEXT DEFAULT '',
    conversation_hash   TEXT DEFAULT '',
    processed_memory_id TEXT,
    status              TEXT NOT NULL DEFAULT 'processed',
    reason              TEXT DEFAULT '',
    metadata_json       TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (processed_memory_id) REFERENCES memory_units(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_unique_message
    ON ingestion_events(source_type, source_agent, source_session_id, source_message_hash)
    WHERE source_message_hash != '';
CREATE INDEX IF NOT EXISTS idx_ingestion_conversation_hash ON ingestion_events(conversation_hash, created_at);
CREATE INDEX IF NOT EXISTS idx_ingestion_status ON ingestion_events(status, created_at);

CREATE TABLE IF NOT EXISTS memory_links (
    id                TEXT PRIMARY KEY,
    source_memory_id  TEXT NOT NULL,
    target_memory_id  TEXT NOT NULL,
    relation_type     TEXT NOT NULL DEFAULT 'MERGED_INTO',
    confidence        REAL NOT NULL DEFAULT 0.8,
    reason            TEXT DEFAULT '',
    created_by        TEXT DEFAULT 'system',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (source_memory_id) REFERENCES memory_units(id),
    FOREIGN KEY (target_memory_id) REFERENCES memory_units(id),
    UNIQUE(source_memory_id, target_memory_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_type ON memory_links(relation_type);

CREATE TABLE IF NOT EXISTS persona_audit_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    assertion_id  TEXT,
    action        TEXT NOT NULL,
    old_value     TEXT DEFAULT '',
    new_value     TEXT DEFAULT '',
    actor         TEXT DEFAULT 'system',
    note          TEXT DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (assertion_id) REFERENCES persona_assertions(id)
);

CREATE INDEX IF NOT EXISTS idx_persona_audit_assertion ON persona_audit_logs(assertion_id);
CREATE INDEX IF NOT EXISTS idx_persona_audit_created ON persona_audit_logs(created_at);

CREATE TABLE IF NOT EXISTS persona_update_runs (
    id                  TEXT PRIMARY KEY,
    new_memories        INTEGER NOT NULL DEFAULT 0,
    skipped_memories    INTEGER NOT NULL DEFAULT 0,
    candidate_checks    INTEGER NOT NULL DEFAULT 0,
    llm_calls_estimated INTEGER NOT NULL DEFAULT 0,
    saved_calls_estimated INTEGER NOT NULL DEFAULT 0,
    top_k_assertions    INTEGER NOT NULL DEFAULT 8,
    result_json         TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

ALTER TABLE space_aliases ADD COLUMN normalized_alias TEXT DEFAULT '';
UPDATE space_aliases SET normalized_alias = lower(trim(alias)) WHERE normalized_alias = '' OR normalized_alias IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_space_alias_normalized ON space_aliases(normalized_alias);

CREATE TABLE IF NOT EXISTS space_summaries (
    id            TEXT PRIMARY KEY,
    space_id      TEXT NOT NULL,
    mode          TEXT NOT NULL DEFAULT 'brief',
    summary_text  TEXT NOT NULL DEFAULT '',
    payload_json  TEXT DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (space_id) REFERENCES spaces(id)
);

CREATE INDEX IF NOT EXISTS idx_space_summaries_space ON space_summaries(space_id, mode, created_at);
