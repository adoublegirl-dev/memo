-- 021: History processing jobs
-- 安装/升级后按需处理本机 Agent 历史会话。任务状态可续跑，不连接或覆盖旧 memo.db。

CREATE TABLE IF NOT EXISTS history_processing_jobs (
    id                  TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft','ready','running','paused','failed','done')),
    current_step        TEXT NOT NULL DEFAULT 'detect'
        CHECK(current_step IN ('detect','source_import','memory_extract','quality_rules','llm_enhance','done')),
    selected_sources_json TEXT NOT NULL DEFAULT '[]',
    detect_report_json  TEXT NOT NULL DEFAULT '{}',
    model_config_json   TEXT NOT NULL DEFAULT '{}',
    progress_json       TEXT NOT NULL DEFAULT '{}',
    last_error          TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    started_at          TEXT,
    finished_at         TEXT
);

CREATE TABLE IF NOT EXISTS history_processing_job_events (
    id          TEXT PRIMARY KEY,
    job_id      TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    message     TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(job_id) REFERENCES history_processing_jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_history_processing_jobs_status ON history_processing_jobs(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_history_processing_job_events_job ON history_processing_job_events(job_id, created_at);
