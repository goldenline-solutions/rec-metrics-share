-- Migration 11: Add platform to game_players (SQLite)
-- Each game_player row stores the platform that game was played on (PC/Console)

ALTER TABLE game_players ADD COLUMN platform TEXT;

-- Backfill from game's platform
UPDATE game_players SET platform = (SELECT platform FROM games WHERE games.id = game_players.game_id) WHERE platform IS NULL;

CREATE INDEX IF NOT EXISTS idx_game_players_platform ON game_players(platform);
