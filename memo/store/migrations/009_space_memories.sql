-- 009: Space 与 MemoryUnit 的多对多关系
-- 一条记忆可属于多个空间，并带 relation_type 表示其在空间中的角色。

CREATE TABLE IF NOT EXISTS space_memories (
    space_id       TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
    memory_id      TEXT NOT NULL REFERENCES memory_units(id) ON DELETE CASCADE,

    relation_type  TEXT DEFAULT 'related',
    relevance      REAL DEFAULT 0.8,
    created_by     TEXT DEFAULT 'auto',
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),

    PRIMARY KEY(space_id, memory_id)
);

CREATE INDEX IF NOT EXISTS idx_space_memories_memory ON space_memories(memory_id);
CREATE INDEX IF NOT EXISTS idx_space_memories_relation ON space_memories(space_id, relation_type);
