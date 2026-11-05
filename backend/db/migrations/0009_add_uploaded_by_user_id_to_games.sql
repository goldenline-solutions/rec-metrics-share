-- Migration 9: Add uploaded_by_user_id to games table
-- Tracks which user uploaded each screenshot (for authenticated uploads)

ALTER TABLE games ADD COLUMN uploaded_by_user_id TEXT;

CREATE INDEX IF NOT EXISTS idx_games_uploaded_by_user_id ON games(uploaded_by_user_id);
