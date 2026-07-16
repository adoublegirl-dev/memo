-- 013: Memory dedupe gate
-- 入库前/后去重记录：exact hash、结构化动作 key、事实 key。

CREATE TABLE IF NOT EXISTS memory_dedupe_records (
    id               TEXT PRIMARY KEY,
    memory_id        TEXT,
    session_id       TEXT DEFAULT '',
    source_agent     TEXT DEFAULT '',
    raw_hash         TEXT NOT NULL,
    normalized_hash  TEXT NOT NULL,
    fact_key         TEXT DEFAULT '',
    action_key       TEXT DEFAULT '',
    entity_key       TEXT DEFAULT '',
    decision         TEXT NOT NULL DEFAULT 'created',
    reason           TEXT DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (memory_id) REFERENCES memory_units(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_dedupe_normalized_created
    ON memory_dedupe_records(normalized_hash)
    WHERE decision = 'created';

CREATE INDEX IF NOT EXISTS idx_memory_dedupe_fact_key
    ON memory_dedupe_records(fact_key, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_dedupe_action_key
    ON memory_dedupe_records(action_key, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_dedupe_memory
    ON memory_dedupe_records(memory_id);
