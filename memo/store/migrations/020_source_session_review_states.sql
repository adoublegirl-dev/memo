-- 020: Source session review states
-- 会话级处理队列状态：只记录处理进度，不修改原始 source_sessions。

CREATE TABLE IF NOT EXISTS source_session_review_states (
    source_session_id       TEXT PRIMARY KEY,
    review_status           TEXT NOT NULL DEFAULT 'rule_processed'
        CHECK(review_status IN ('new', 'rule_processed', 'needs_review', 'needs_llm', 'in_review', 'done', 'postponed', 'has_issue')),
    review_note             TEXT NOT NULL DEFAULT '',
    manual_done_count       INTEGER NOT NULL DEFAULT 0,
    manual_progress_count   INTEGER NOT NULL DEFAULT 0,
    postponed_until         TEXT,
    last_reviewed_memory_id TEXT NOT NULL DEFAULT '',
    reviewed_at             TEXT,
    updated_at              TEXT NOT NULL DEFAULT (datetime('now')),
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(source_session_id) REFERENCES source_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_source_session_review_status ON source_session_review_states(review_status);
CREATE INDEX IF NOT EXISTS idx_source_session_review_updated ON source_session_review_states(updated_at);
