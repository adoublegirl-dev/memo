-- 004: V0.6.0 人格引擎
-- 新增 persona_assertions（人格断言表）+ persona_settings（配置表）

CREATE TABLE IF NOT EXISTS persona_assertions (
    id              TEXT PRIMARY KEY,
    dimension       TEXT NOT NULL,        -- value/decision/identity/preference/sensitivity/relationship/knowledge/communication/mental_model/emotion 或自定义
    assertion       TEXT NOT NULL,        -- 断言内容，如"极度重视信任与诚实"
    confidence      REAL DEFAULT 0.5,     -- 置信度 0~1
    evidences       TEXT DEFAULT '[]',    -- JSON: 引用的 memory_units ID 列表
    signal_level    INTEGER DEFAULT 1,    -- 0=自动低置信 1=多次印证 2=手动/初始基线
    is_superseded   INTEGER DEFAULT 0,
    superseded_by   TEXT,
    locked          INTEGER DEFAULT 0,    -- 用户锁定标志
    is_custom       INTEGER DEFAULT 0,    -- 自定义维度标志
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_refreshed  TEXT
);

CREATE INDEX idx_persona_dim ON persona_assertions(dimension);
CREATE INDEX idx_persona_active ON persona_assertions(is_superseded);
CREATE INDEX idx_persona_conf ON persona_assertions(confidence);

CREATE TABLE IF NOT EXISTS persona_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 默认配置
INSERT OR IGNORE INTO persona_settings (key, value) VALUES ('sensitivity_level', '2');
INSERT OR IGNORE INTO persona_settings (key, value) VALUES ('last_baseline_at', '');
INSERT OR IGNORE INTO persona_settings (key, value) VALUES ('last_incremental_at', '');
INSERT OR IGNORE INTO persona_settings (key, value) VALUES ('refresh_interval_hours', '12');
