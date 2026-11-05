-- Migration 16 (SQLite): tag each game with the NBA 2K title it came from.
-- Everything already ingested is 2K26; new uploads are stamped 2K27 by the app.

ALTER TABLE games ADD COLUMN game_version TEXT;

UPDATE games SET game_version = '2K26' WHERE game_version IS NULL;

CREATE INDEX IF NOT EXISTS idx_games_game_version ON games(game_version);
