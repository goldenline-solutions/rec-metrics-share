-- Migration 7: Add platform fields to users and games tables
-- This migration adds platform selection (PC/Console) for users and games

-- 1. Add platform column to users table
ALTER TABLE users ADD COLUMN platform TEXT;

-- 2. Add platform column to games table
ALTER TABLE games ADD COLUMN platform TEXT;

-- 3. Set all existing games to 'PC' by default
UPDATE games SET platform = 'PC' WHERE platform IS NULL;

-- 4. Create index on games.platform for filtering
CREATE INDEX IF NOT EXISTS idx_games_platform ON games(platform);
