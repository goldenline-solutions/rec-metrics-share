-- Migration 16 (PostgreSQL): tag each game with the NBA 2K title it came from.
-- Everything already ingested is 2K26; the column default makes new rows 2K27.

ALTER TABLE games ADD COLUMN IF NOT EXISTS game_version TEXT;

UPDATE games SET game_version = '2K26' WHERE game_version IS NULL;

ALTER TABLE games ALTER COLUMN game_version SET DEFAULT '2K27';

CREATE INDEX IF NOT EXISTS idx_games_game_version ON games(game_version);
