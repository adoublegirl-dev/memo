-- Batch-review state for raw source turns. Raw content is never deleted.
CREATE TABLE IF NOT EXISTS source_turn_review_states (
  source_turn_id TEXT PRIMARY KEY REFERENCES source_turns(id) ON DELETE CASCADE,
  review_status TEXT NOT NULL DEFAULT 'active',
  review_note TEXT NOT NULL DEFAULT '',
  reviewed_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_turn_review_status ON source_turn_review_states(review_status, updated_at DESC);
