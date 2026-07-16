-- 012_space_classification_queue.sql
-- Space 自动归类确认队列：Detector 只给候选，用户确认后才绑定。

CREATE TABLE IF NOT EXISTS space_classification_queue (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    suggested_space_id TEXT,
    suggested_space_name TEXT,
    confidence REAL DEFAULT 0.0,
    reason TEXT DEFAULT '',
    status TEXT DEFAULT 'pending', -- pending / accepted / rejected / new_space / ignored
    decided_space_id TEXT,
    decided_by TEXT DEFAULT '',
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(memory_id, suggested_space_id)
);

CREATE INDEX IF NOT EXISTS idx_space_classification_status ON space_classification_queue(status, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_space_classification_memory ON space_classification_queue(memory_id);
CREATE INDEX IF NOT EXISTS idx_space_classification_space ON space_classification_queue(suggested_space_id);
