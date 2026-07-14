-- 005: V0.7.0 待办管理
-- 新增 todos（待办表）+ todo_history（状态变更日志）

CREATE TABLE IF NOT EXISTS todos (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT DEFAULT '',
    priority        TEXT DEFAULT 'medium',   -- high / medium / low
    status          TEXT DEFAULT 'todo',     -- todo / doing / done / cancelled
    session_id      TEXT,                    -- 关联会话
    memory_id       TEXT,                    -- 关联记忆
    source_agent    TEXT DEFAULT '',
    due_date        TEXT,
    completed_at    TEXT,
    reopened_at     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (memory_id) REFERENCES memory_units(id)
);

CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(due_date);
CREATE INDEX IF NOT EXISTS idx_todos_session ON todos(session_id);

CREATE TABLE IF NOT EXISTS todo_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    todo_id     TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    note        TEXT DEFAULT '',
    agent       TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    FOREIGN KEY (todo_id) REFERENCES todos(id)
);

CREATE INDEX IF NOT EXISTS idx_history_todo ON todo_history(todo_id);
