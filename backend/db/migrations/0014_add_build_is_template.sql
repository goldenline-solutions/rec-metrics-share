-- Migration 14: Flag a build as a browsable template (SQLite)
-- 0 = normal build (default), 1 = shown in the template gallery at /builds/templates.
-- Admin-only flag; set via PATCH /api/builds/<id>.

ALTER TABLE builds ADD COLUMN is_template INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_builds_is_template ON builds(is_template);
