-- 015: 基于历史会话的 Space Candidate 候选项目队列
-- Candidate 是系统建议，不是正式 Space；所有确认/合并/忽略均由用户手动操作。

CREATE TABLE IF NOT EXISTS space_candidates (
    id                          TEXT PRIMARY KEY,
    candidate_key               TEXT NOT NULL UNIQUE,
    candidate_name              TEXT NOT NULL,
    candidate_type              TEXT DEFAULT 'project',
    description                 TEXT DEFAULT '',
    confidence                  REAL DEFAULT 0.5,
    reason                      TEXT DEFAULT '',
    status                      TEXT DEFAULT 'pending',

    source_session_ids          TEXT DEFAULT '[]',
    source_memory_ids           TEXT DEFAULT '[]',
    source_todo_ids             TEXT DEFAULT '[]',
    suggested_aliases           TEXT DEFAULT '[]',
    suggested_existing_space_id TEXT DEFAULT '',
    suggested_existing_space_name TEXT DEFAULT '',
    merge_suggestions           TEXT DEFAULT '[]',

    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at                  TEXT,
    decided_by                  TEXT DEFAULT '',
    decided_space_id            TEXT DEFAULT '',
    decision_note               TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_space_candidates_status ON space_candidates(status);
CREATE INDEX IF NOT EXISTS idx_space_candidates_updated ON space_candidates(updated_at);
CREATE INDEX IF NOT EXISTS idx_space_candidates_existing_space ON space_candidates(suggested_existing_space_id);

CREATE TABLE IF NOT EXISTS space_candidate_audit_logs (
    id              TEXT PRIMARY KEY,
    candidate_id    TEXT NOT NULL,
    action          TEXT NOT NULL,
    old_value       TEXT DEFAULT '',
    new_value       TEXT DEFAULT '',
    actor           TEXT DEFAULT 'dashboard',
    note            TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (candidate_id) REFERENCES space_candidates(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_space_candidate_audit_candidate ON space_candidate_audit_logs(candidate_id, created_at);
