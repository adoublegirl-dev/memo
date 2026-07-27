-- 019: Source-aware memory quality review pipeline
-- 自动质量处理结果独立存储，不覆盖原始 memory 内容；后续 LLM / 人工处理可以在此基础上升级。

CREATE TABLE IF NOT EXISTS memory_quality_reviews (
    memory_id             TEXT PRIMARY KEY,
    review_status         TEXT NOT NULL DEFAULT 'pending'
        CHECK(review_status IN ('pending', 'auto_accepted', 'auto_flagged', 'auto_muted', 'auto_rejected', 'human_accepted', 'human_rejected', 'merged', 'archived')),
    retention_class       TEXT NOT NULL DEFAULT 'candidate'
        CHECK(retention_class IN ('long_term', 'project_state', 'temporary_task', 'noise', 'candidate')),
    recall_policy         TEXT NOT NULL DEFAULT 'include'
        CHECK(recall_policy IN ('include', 'downrank', 'exclude_default', 'exclude')),
    quality_score         REAL NOT NULL DEFAULT 0.5,
    auto_flags_json       TEXT NOT NULL DEFAULT '[]',
    duplicate_group_key   TEXT NOT NULL DEFAULT '',
    duplicate_count       INTEGER NOT NULL DEFAULT 1,
    needs_llm             INTEGER NOT NULL DEFAULT 0,
    processor_version     TEXT NOT NULL DEFAULT 'rules-v1',
    note                  TEXT NOT NULL DEFAULT '',
    reviewed_at           TEXT,
    updated_at            TEXT NOT NULL DEFAULT (datetime('now')),
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(memory_id) REFERENCES memory_units(id)
);

CREATE INDEX IF NOT EXISTS idx_memory_quality_status ON memory_quality_reviews(review_status);
CREATE INDEX IF NOT EXISTS idx_memory_quality_retention ON memory_quality_reviews(retention_class);
CREATE INDEX IF NOT EXISTS idx_memory_quality_recall ON memory_quality_reviews(recall_policy);
CREATE INDEX IF NOT EXISTS idx_memory_quality_duplicate ON memory_quality_reviews(duplicate_group_key);
CREATE INDEX IF NOT EXISTS idx_memory_quality_needs_llm ON memory_quality_reviews(needs_llm);
