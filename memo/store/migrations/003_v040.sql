-- 003: V0.4.0 MERGED_INTO 关系类型
-- 仅在 feature_relations 的 CHECK 约束中新增 MERGED_INTO

CREATE TABLE IF NOT EXISTS feature_relations_new_003 (
    id TEXT PRIMARY KEY,
    source_tag_id TEXT NOT NULL,
    target_tag_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK (relation_type IN (
        'CO_OCCUR', 'DERIVED', 'CAUSAL', 'TEMPORAL', 'CONTRADICT',
        'REFINES', 'SUPERSEDES', 'MERGED_INTO'
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

INSERT INTO feature_relations_new_003
SELECT id, source_tag_id, target_tag_id, relation_type,
       hebbian_weight, co_activation_count, last_co_activated_at,
       first_observed_at, contexts, last_session_id
FROM feature_relations;

DROP TABLE feature_relations;
ALTER TABLE feature_relations_new_003 RENAME TO feature_relations;
