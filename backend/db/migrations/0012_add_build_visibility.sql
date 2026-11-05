-- Migration 12: Add build visibility flag (SQLite)
-- 0 = private (default), 1 = public

ALTER TABLE builds ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_builds_is_public ON builds(is_public);
