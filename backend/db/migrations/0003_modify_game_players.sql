-- Migration 3: Modify game_players table to support identity resolution
-- Add new columns to track detected names, player identity, and claims
-- Note: SQLite doesn't support IF NOT EXISTS for ALTER TABLE, so the migration runner
-- will handle "duplicate column" errors gracefully

-- Add detected_raw_name column (stores the raw name as detected from OCR)
ALTER TABLE game_players ADD COLUMN detected_raw_name TEXT;

-- Add detected_norm_name column (stores normalized version of detected name)
ALTER TABLE game_players ADD COLUMN detected_norm_name TEXT;

-- Add player_id_identity column (references players_identity table)
ALTER TABLE game_players ADD COLUMN player_id_identity INTEGER REFERENCES players_identity(id);

-- Add claim_id column (references name_claims table)
ALTER TABLE game_players ADD COLUMN claim_id INTEGER REFERENCES name_claims(id);

-- Add match_confidence column (0-100, how confident the match is)
ALTER TABLE game_players ADD COLUMN match_confidence INTEGER;

-- Add match_method column (how the match was made: exact, variant, fuzzy, manual, none)
ALTER TABLE game_players ADD COLUMN match_method TEXT CHECK (match_method IN ('exact','variant','fuzzy','manual','none'));

-- Add needs_review column (boolean flag for manual review)
ALTER TABLE game_players ADD COLUMN needs_review INTEGER DEFAULT 0;

-- Create indexes for the new columns
CREATE INDEX IF NOT EXISTS idx_game_players_detected_norm ON game_players(detected_norm_name);
CREATE INDEX IF NOT EXISTS idx_game_players_player_id_identity ON game_players(player_id_identity);
CREATE INDEX IF NOT EXISTS idx_game_players_claim_id ON game_players(claim_id);

