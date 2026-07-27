-- 017: Source-aware / Turn-aware memory foundation
--
-- 最终 V0.9 数据骨架：真实 Agent 会话 source_session
--   -> source_turns 证据层
--   -> episodes 用户意图/任务边界
--   -> memory_units 最小长期记忆
--
-- additive only：
-- - 不删除旧表；
-- - 不改写旧数据；
-- - 不触碰旧权重字段（signal_level/user_weight/pinned/hebbian_weight/storage_strength 等）；
-- - 不把 generated fallback title 写成真实 original_title。

-- ── 扩展 016 source_sessions：保留真实标题来源与兼容身份字段 ──
ALTER TABLE source_sessions ADD COLUMN agent_session_id TEXT DEFAULT '';
ALTER TABLE source_sessions ADD COLUMN source_hash TEXT DEFAULT '';
ALTER TABLE source_sessions ADD COLUMN original_title TEXT DEFAULT '';
ALTER TABLE source_sessions ADD COLUMN title_source TEXT NOT NULL DEFAULT 'unknown'
    CHECK(title_source IN ('agent_original', 'session_titles_json_path', 'session_titles_json_id', 'db_title', 'file_name', 'missing', 'generated_fallback', 'unknown'));
ALTER TABLE source_sessions ADD COLUMN display_title TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_source_sessions_agent_session
    ON source_sessions(source_agent, agent_session_id);

CREATE INDEX IF NOT EXISTS idx_source_sessions_title_source
    ON source_sessions(title_source);

CREATE INDEX IF NOT EXISTS idx_source_sessions_source_hash
    ON source_sessions(source_hash);

-- ── 原始 turn / event 证据层 ──
CREATE TABLE IF NOT EXISTS source_turns (
    id                  TEXT PRIMARY KEY,
    source_session_id   TEXT NOT NULL,
    agent_turn_id       TEXT DEFAULT '',
    parent_turn_id      TEXT DEFAULT '',
    role                TEXT NOT NULL DEFAULT 'unknown'
        CHECK(role IN ('user', 'assistant', 'tool', 'system', 'unknown')),
    content             TEXT NOT NULL DEFAULT '',
    content_hash        TEXT NOT NULL DEFAULT '',
    timestamp           TEXT DEFAULT '',
    turn_index          INTEGER NOT NULL DEFAULT 0,
    is_final_answer     INTEGER NOT NULL DEFAULT 0,
    is_tool_call        INTEGER NOT NULL DEFAULT 0,
    is_tool_result      INTEGER NOT NULL DEFAULT 0,
    tool_name           TEXT DEFAULT '',
    source_event_type   TEXT DEFAULT '',
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (source_session_id) REFERENCES source_sessions(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_source_turns_session_index
    ON source_turns(source_session_id, turn_index);

CREATE INDEX IF NOT EXISTS idx_source_turns_session_role
    ON source_turns(source_session_id, role);

CREATE INDEX IF NOT EXISTS idx_source_turns_agent_turn
    ON source_turns(source_session_id, agent_turn_id)
    WHERE agent_turn_id != '';

CREATE INDEX IF NOT EXISTS idx_source_turns_content_hash
    ON source_turns(content_hash);

CREATE INDEX IF NOT EXISTS idx_source_turns_tool_flags
    ON source_turns(is_tool_call, is_tool_result, is_final_answer);

-- ── Episode：source_session 内的用户问题、任务、阶段或决策边界 ──
CREATE TABLE IF NOT EXISTS episodes (
    id                  TEXT PRIMARY KEY,
    source_session_id   TEXT NOT NULL,
    title               TEXT NOT NULL DEFAULT '',
    user_intent         TEXT NOT NULL DEFAULT '',
    start_turn_id       TEXT DEFAULT NULL,
    end_turn_id         TEXT DEFAULT NULL,
    start_turn_index    INTEGER DEFAULT 0,
    end_turn_index      INTEGER DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'ready', 'imported', 'ignored', 'archived')),
    confidence          REAL NOT NULL DEFAULT 0.0,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (source_session_id) REFERENCES source_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (start_turn_id) REFERENCES source_turns(id) ON DELETE SET NULL,
    FOREIGN KEY (end_turn_id) REFERENCES source_turns(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_episodes_source_session
    ON episodes(source_session_id, start_turn_index, end_turn_index);

CREATE INDEX IF NOT EXISTS idx_episodes_status
    ON episodes(status, updated_at);

-- ── Episode 与 turn 的多对多证据映射 ──
CREATE TABLE IF NOT EXISTS episode_turns (
    episode_id          TEXT NOT NULL,
    turn_id             TEXT NOT NULL,
    role_in_episode     TEXT NOT NULL DEFAULT 'context'
        CHECK(role_in_episode IN ('trigger', 'context', 'evidence', 'final_answer', 'tool_support')),
    weight              REAL NOT NULL DEFAULT 1.0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (episode_id, turn_id),
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE,
    FOREIGN KEY (turn_id) REFERENCES source_turns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_episode_turns_turn
    ON episode_turns(turn_id);

CREATE INDEX IF NOT EXISTS idx_episode_turns_role
    ON episode_turns(role_in_episode);

-- ── 扩展长期记忆最小颗粒：保留来源会话、episode 与 turn 证据指针 ──
ALTER TABLE memory_units ADD COLUMN source_session_id TEXT DEFAULT NULL REFERENCES source_sessions(id) ON DELETE SET NULL;
ALTER TABLE memory_units ADD COLUMN episode_id TEXT DEFAULT NULL REFERENCES episodes(id) ON DELETE SET NULL;
ALTER TABLE memory_units ADD COLUMN source_turn_start_id TEXT DEFAULT NULL REFERENCES source_turns(id) ON DELETE SET NULL;
ALTER TABLE memory_units ADD COLUMN source_turn_end_id TEXT DEFAULT NULL REFERENCES source_turns(id) ON DELETE SET NULL;
ALTER TABLE memory_units ADD COLUMN memory_granularity TEXT NOT NULL DEFAULT 'legacy'
    CHECK(memory_granularity IN ('legacy', 'turn', 'episode', 'session', 'canonical', 'manual'));
ALTER TABLE memory_units ADD COLUMN speaker_scope TEXT NOT NULL DEFAULT 'unknown'
    CHECK(speaker_scope IN ('user_claim', 'assistant_result', 'tool_observation', 'decision', 'mixed', 'unknown'));
ALTER TABLE memory_units ADD COLUMN source_confidence REAL NOT NULL DEFAULT 0.0;
ALTER TABLE memory_units ADD COLUMN is_canonical INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_memory_source_session
    ON memory_units(source_session_id);

CREATE INDEX IF NOT EXISTS idx_memory_episode
    ON memory_units(episode_id);

CREATE INDEX IF NOT EXISTS idx_memory_source_turn_range
    ON memory_units(source_turn_start_id, source_turn_end_id);

CREATE INDEX IF NOT EXISTS idx_memory_granularity
    ON memory_units(memory_granularity, is_canonical);

CREATE INDEX IF NOT EXISTS idx_memory_speaker_scope
    ON memory_units(speaker_scope);

-- ── Memory 与具体 source_turn 的证据链 ──
CREATE TABLE IF NOT EXISTS memory_turn_sources (
    memory_id           TEXT NOT NULL,
    turn_id             TEXT NOT NULL,
    evidence_role       TEXT NOT NULL DEFAULT 'support'
        CHECK(evidence_role IN ('source', 'support', 'contradiction', 'decision_basis', 'final_answer', 'tool_observation')),
    weight              REAL NOT NULL DEFAULT 1.0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (memory_id, turn_id, evidence_role),
    FOREIGN KEY (memory_id) REFERENCES memory_units(id) ON DELETE CASCADE,
    FOREIGN KEY (turn_id) REFERENCES source_turns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_turn_sources_turn
    ON memory_turn_sources(turn_id);

CREATE INDEX IF NOT EXISTS idx_memory_turn_sources_role
    ON memory_turn_sources(evidence_role);
