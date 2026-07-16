-- 007: sessions 关联 Context Space
-- NULL 表示历史会话或未归属会话，避免强制迁移旧数据。

ALTER TABLE sessions ADD COLUMN space_id TEXT DEFAULT NULL REFERENCES spaces(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_space ON sessions(space_id);
