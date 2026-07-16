-- 006: V0.9.0 Context Space 基础表
-- Space 是上下文组织层，不替代 memory/session/tag 图谱。

CREATE TABLE IF NOT EXISTS spaces (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    type                TEXT NOT NULL DEFAULT 'general',
    description         TEXT DEFAULT '',

    goal                TEXT DEFAULT '',
    background          TEXT DEFAULT '',
    current_state       TEXT DEFAULT '',
    next_action         TEXT DEFAULT '',

    priority            TEXT DEFAULT 'medium',
    status              TEXT DEFAULT 'active',

    profile_json        TEXT DEFAULT '{}',
    centroid_embedding  BLOB,

    memory_count        INTEGER DEFAULT 0,
    todo_count          INTEGER DEFAULT 0,
    session_count       INTEGER DEFAULT 0,

    is_default          INTEGER NOT NULL DEFAULT 0,

    created_by          TEXT DEFAULT 'auto',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    last_active_at      TEXT,
    archived_at         TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_spaces_name ON spaces(name);
CREATE INDEX IF NOT EXISTS idx_spaces_type ON spaces(type);
CREATE INDEX IF NOT EXISTS idx_spaces_status ON spaces(status);
CREATE INDEX IF NOT EXISTS idx_spaces_default ON spaces(is_default);
CREATE INDEX IF NOT EXISTS idx_spaces_updated ON spaces(updated_at);

-- 默认收纳空间：低置信或未归档上下文进入这里。旧数据不强制回填。
INSERT OR IGNORE INTO spaces (
    id, name, type, description, goal, priority, status, is_default, created_by, created_at, updated_at
) VALUES (
    'space_inbox', 'Inbox / 未归档', 'general', '低置信或尚未归类的上下文空间', '暂存未归档记忆与待办', 'medium', 'active', 1, 'system', datetime('now'), datetime('now')
);
