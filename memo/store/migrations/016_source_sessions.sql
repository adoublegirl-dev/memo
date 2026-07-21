-- 016: Source Sessions 来源会话层
-- 用于区分真实 Agent 会话、自动同步、Bridge 导入等外部来源。
-- additive only：不替代 sessions，不改 memory/todo 权重，只建立来源索引和映射。

CREATE TABLE IF NOT EXISTS source_sessions (
    id                  TEXT PRIMARY KEY,
    source_type         TEXT NOT NULL DEFAULT 'memo_session',
    source_agent        TEXT DEFAULT '',
    external_session_id TEXT DEFAULT '',
    external_thread_id  TEXT DEFAULT '',
    legacy_session_id   TEXT DEFAULT '',
    source_path         TEXT DEFAULT '',
    title               TEXT DEFAULT '',
    started_at          TEXT DEFAULT '',
    ended_at            TEXT DEFAULT '',
    imported_at         TEXT NOT NULL DEFAULT (datetime('now')),
    message_count       INTEGER DEFAULT 0,
    memory_count        INTEGER DEFAULT 0,
    todo_count          INTEGER DEFAULT 0,
    content_hash        TEXT DEFAULT '',
    status              TEXT DEFAULT 'active',
    metadata_json       TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_source_sessions_legacy_session
    ON source_sessions(legacy_session_id)
    WHERE legacy_session_id != '';

CREATE INDEX IF NOT EXISTS idx_source_sessions_type_agent
    ON source_sessions(source_type, source_agent);

CREATE INDEX IF NOT EXISTS idx_source_sessions_updated
    ON source_sessions(updated_at);

CREATE TABLE IF NOT EXISTS source_session_memories (
    source_session_id   TEXT NOT NULL,
    memory_id           TEXT NOT NULL,
    relation_type       TEXT DEFAULT 'originated_from',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source_session_id, memory_id),
    FOREIGN KEY (source_session_id) REFERENCES source_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (memory_id) REFERENCES memory_units(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_source_session_memories_memory
    ON source_session_memories(memory_id);

CREATE TABLE IF NOT EXISTS source_session_todos (
    source_session_id   TEXT NOT NULL,
    todo_id             TEXT NOT NULL,
    relation_type       TEXT DEFAULT 'originated_from',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source_session_id, todo_id),
    FOREIGN KEY (source_session_id) REFERENCES source_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (todo_id) REFERENCES todos(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_source_session_todos_todo
    ON source_session_todos(todo_id);
