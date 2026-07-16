-- 011: Memory governance
-- 用户可控的记忆治理：状态、权重、置顶、审计日志。

ALTER TABLE memory_units ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active', 'wrong', 'expired', 'muted', 'deleted'));
ALTER TABLE memory_units ADD COLUMN user_weight REAL NOT NULL DEFAULT 1.0;
ALTER TABLE memory_units ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memory_units ADD COLUMN user_note TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_units ADD COLUMN updated_at TEXT;

CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_units(status);
CREATE INDEX IF NOT EXISTS idx_memory_pinned ON memory_units(pinned);
CREATE INDEX IF NOT EXISTS idx_memory_user_weight ON memory_units(user_weight);

CREATE TABLE IF NOT EXISTS memory_audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    old_value   TEXT DEFAULT '',
    new_value   TEXT DEFAULT '',
    actor       TEXT DEFAULT 'system',
    note        TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (memory_id) REFERENCES memory_units(id)
);

CREATE INDEX IF NOT EXISTS idx_memory_audit_memory ON memory_audit_logs(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_audit_created ON memory_audit_logs(created_at);
