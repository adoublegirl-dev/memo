-- 002: V0.3.0 数据库迁移
-- CAS: 允许新关系类型 + ESA: signal_level + SCB: last_session_id

-- 1. 重建 feature_relations 表的 CHECK 约束，允许 REFINES/SUPERSEDES
CREATE TABLE IF NOT EXISTS feature_relations_new (
    id TEXT PRIMARY KEY,
    source_tag_id TEXT NOT NULL,
    target_tag_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK (relation_type IN (
        'CO_OCCUR', 'DERIVED', 'CAUSAL', 'TEMPORAL', 'CONTRADICT',
        'REFINES', 'SUPERSEDES'
    )),
    hebbian_weight REAL DEFAULT 0.1,
    co_activation_count INTEGER DEFAULT 0,
    last_co_activated_at TEXT,
    first_observed_at TEXT,
    contexts TEXT DEFAULT '[]',
    last_session_id TEXT DEFAULT '',
    FOREIGN KEY (source_tag_id) REFERENCES feature_tags(id),
    FOREIGN KEY (target_tag_id) REFERENCES feature_tags(id),
    UNIQUE(source_tag_id, target_tag_id, relation_type)
);

INSERT INTO feature_relations_new
SELECT id, source_tag_id, target_tag_id, relation_type,
       hebbian_weight, co_activation_count, last_co_activated_at,
       first_observed_at, contexts, '' as last_session_id
FROM feature_relations;

DROP TABLE feature_relations;
ALTER TABLE feature_relations_new RENAME TO feature_relations;

-- 2. memory_units 增加 signal_level（ESA 显式信号放大）
ALTER TABLE memory_units ADD COLUMN signal_level INTEGER DEFAULT 0;
-- 0=L0 普通自动, 1=L1 高价值自动, 2=L2 显式手动

-- 3. 创建索引加速 CAS 变更检测
CREATE INDEX IF NOT EXISTS idx_memory_units_superseded ON memory_units(is_superseded);
CREATE INDEX IF NOT EXISTS idx_memory_units_confidence ON memory_units(confidence);
