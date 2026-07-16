-- 008: todos 关联 Context Space
-- NULL 表示全局待办或历史待办。

ALTER TABLE todos ADD COLUMN space_id TEXT DEFAULT NULL REFERENCES spaces(id) ON DELETE SET NULL;
ALTER TABLE todos ADD COLUMN space_relation_type TEXT DEFAULT 'action';

CREATE INDEX IF NOT EXISTS idx_todos_space ON todos(space_id);
