-- 010: Space 别名
-- 用于将“那个记忆系统”“Memo”“麦默”等别名归一到同一空间。

CREATE TABLE IF NOT EXISTS space_aliases (
    id          TEXT PRIMARY KEY,
    space_id    TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_space_alias_unique ON space_aliases(space_id, alias);
CREATE INDEX IF NOT EXISTS idx_space_alias_alias ON space_aliases(alias);
