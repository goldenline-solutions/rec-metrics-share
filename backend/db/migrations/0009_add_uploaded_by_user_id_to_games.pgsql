-- Migration 9 (PostgreSQL): Add uploaded_by_user_id to games table
-- Tracks which user uploaded each screenshot (for authenticated uploads)
-- Run once against your Postgres DB: psql $DATABASE_URL -f 0009_add_uploaded_by_user_id_to_games.pgsql

ALTER TABLE games ADD COLUMN IF NOT EXISTS uploaded_by_user_id TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_games_uploaded_by_user'
  ) THEN
    ALTER TABLE games
      ADD CONSTRAINT fk_games_uploaded_by_user
      FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_games_uploaded_by_user_id ON games(uploaded_by_user_id);
