-- Memo 数据库初始迁移
-- Phase 0: 核心表结构

-- ── 会话表 ──
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL DEFAULT 'default',
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'archived')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    memory_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at);

-- ── 特征词表 ──
CREATE TABLE IF NOT EXISTS feature_tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'CONCEPT'
        CHECK(category IN ('PERSON', 'OBJECT', 'LOCATION', 'EVENT', 'ORGANIZATION', 'CONCEPT')),
    storage_strength REAL NOT NULL DEFAULT 0.1,
    retrieval_strength REAL NOT NULL DEFAULT 1.0,
    total_activations INTEGER NOT NULL DEFAULT 0,
    last_activated_at TEXT,
    cooldown_days REAL NOT NULL DEFAULT 0.0,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by TEXT NOT NULL DEFAULT 'LLM_AUTO' CHECK(created_by IN ('LLM_AUTO', 'USER_MANUAL')),
    embedding BLOB,  -- float32 数组序列化
    is_dormant INTEGER NOT NULL DEFAULT 0  -- 0=活跃, 1=休眠
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_feature_tags_name ON feature_tags(name);
CREATE INDEX IF NOT EXISTS idx_feature_tags_category ON feature_tags(category);
CREATE INDEX IF NOT EXISTS idx_feature_tags_strength ON feature_tags(storage_strength, retrieval_strength);

-- ── 特征关系表（图的边） ──
CREATE TABLE IF NOT EXISTS feature_relations (
    id TEXT PRIMARY KEY,
    source_tag_id TEXT NOT NULL REFERENCES feature_tags(id) ON DELETE CASCADE,
    target_tag_id TEXT NOT NULL REFERENCES feature_tags(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'CO_OCCUR'
        CHECK(relation_type IN ('CO_OCCUR', 'DERIVED', 'CAUSAL', 'TEMPORAL', 'CONTRADICT')),
    hebbian_weight REAL NOT NULL DEFAULT 0.1,
    co_activation_count INTEGER NOT NULL DEFAULT 1,
    last_co_activated_at TEXT NOT NULL DEFAULT (datetime('now')),
    first_observed_at TEXT NOT NULL DEFAULT (datetime('now')),
    contexts TEXT NOT NULL DEFAULT '[]'  -- JSON 数组，最多 3 条上下文
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_pair ON feature_relations(source_tag_id, target_tag_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_relations_source ON feature_relations(source_tag_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON feature_relations(target_tag_id);

-- ── 记忆单元表 ──
CREATE TABLE IF NOT EXISTS memory_units (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    summary_detail TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    valid_from TEXT NOT NULL DEFAULT (datetime('now')),
    valid_until TEXT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_superseded INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT,
    confidence REAL NOT NULL DEFAULT 0.8,
    memory_type TEXT NOT NULL DEFAULT 'FACT'
        CHECK(memory_type IN ('FACT', 'DECISION', 'PREFERENCE', 'EVENT', 'REASONING')),
    embedding BLOB,  -- float32 数组
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_units(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_units(memory_type);
CREATE INDEX IF NOT EXISTS idx_memory_valid ON memory_units(valid_from, valid_until);

-- ── 特征词↔记忆单元关联表 ──
CREATE TABLE IF NOT EXISTS tag_mentions (
    id TEXT PRIMARY KEY,
    tag_id TEXT NOT NULL REFERENCES feature_tags(id) ON DELETE CASCADE,
    memory_unit_id TEXT NOT NULL REFERENCES memory_units(id) ON DELETE CASCADE,
    mention_type TEXT NOT NULL DEFAULT 'DIRECT'
        CHECK(mention_type IN ('DIRECT', 'INFERRED', 'TITLE')),
    relevance_score REAL NOT NULL DEFAULT 0.5,
    position_index INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_mentions_tag ON tag_mentions(tag_id);
CREATE INDEX IF NOT EXISTS idx_mentions_memory ON tag_mentions(memory_unit_id);

-- ── 全局记忆快照表 ──
CREATE TABLE IF NOT EXISTS global_snapshots (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL DEFAULT 'default',
    snapshot_at TEXT NOT NULL DEFAULT (datetime('now')),
    total_sessions INTEGER NOT NULL DEFAULT 0,
    total_memory_units INTEGER NOT NULL DEFAULT 0,
    total_feature_tags INTEGER NOT NULL DEFAULT 0,
    total_relations INTEGER NOT NULL DEFAULT 0,
    agent_profile TEXT NOT NULL DEFAULT '',
    top_domains TEXT NOT NULL DEFAULT '[]',  -- JSON
    active_projects TEXT NOT NULL DEFAULT '[]',  -- JSON
    hot_tags TEXT NOT NULL DEFAULT '[]',  -- JSON tag IDs
    recent_important_memories TEXT NOT NULL DEFAULT '[]'  -- JSON memory IDs
);

CREATE INDEX IF NOT EXISTS idx_snapshots_agent ON global_snapshots(agent_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_time ON global_snapshots(snapshot_at);

-- ── FTS5 全文搜索（用于 BM25 通道） ──
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    title,
    summary,
    summary_detail,
    raw_text,
    content='memory_units',
    content_rowid='rowid'
);

-- 触发器：记忆单元写入时自动同步到 FTS
CREATE TRIGGER IF NOT EXISTS memory_fts_insert AFTER INSERT ON memory_units BEGIN
    INSERT INTO memory_fts(rowid, title, summary, summary_detail, raw_text)
    VALUES (new.rowid, new.title, new.summary, new.summary_detail, new.raw_text);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_delete AFTER DELETE ON memory_units BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, title, summary, summary_detail, raw_text)
    VALUES ('delete', old.rowid, old.title, old.summary, old.summary_detail, old.raw_text);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_update AFTER UPDATE ON memory_units BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, title, summary, summary_detail, raw_text)
    VALUES ('delete', old.rowid, old.title, old.summary, old.summary_detail, old.raw_text);
    INSERT INTO memory_fts(rowid, title, summary, summary_detail, raw_text)
    VALUES (new.rowid, new.title, new.summary, new.summary_detail, new.raw_text);
END;
