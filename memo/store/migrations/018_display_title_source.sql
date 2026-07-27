-- 018: Display title source for source sessions
--
-- title_source/original_title 只记录真实 Agent 标题来源；
-- display_title 可以是系统兜底展示名，必须明确 display_title_source，避免冒充原始标题。

ALTER TABLE source_sessions ADD COLUMN display_title_source TEXT NOT NULL DEFAULT 'unknown'
    CHECK(display_title_source IN ('agent_original', 'first_user_turn', 'file_name', 'cwd', 'summary_time_range', 'generated_fallback', 'user_custom', 'unknown'));

CREATE INDEX IF NOT EXISTS idx_source_sessions_display_title_source
    ON source_sessions(display_title_source);
