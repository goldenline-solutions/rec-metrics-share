-- Migration 2: Create identity system tables
-- This migration creates the core tables for player identity tracking

-- 1. New players table (replaces/extends existing players table concept)
-- Note: We're creating a new table structure, but we'll need to migrate existing data
CREATE TABLE IF NOT EXISTS players_identity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    canonical_norm TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_players_canonical_norm ON players_identity(canonical_norm);

-- 2. Player name variants table
CREATE TABLE IF NOT EXISTS player_name_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players_identity(id) ON DELETE CASCADE,
    raw_name TEXT NOT NULL,
    norm_name TEXT NOT NULL,
    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    seen_count INTEGER DEFAULT 1,
    UNIQUE(player_id, norm_name)
);

CREATE INDEX IF NOT EXISTS idx_variants_norm_name ON player_name_variants(norm_name);

-- 3. Name claims table
CREATE TABLE IF NOT EXISTS name_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players_identity(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    status TEXT CHECK (status IN ('unverified','verified','revoked','rejected')) NOT NULL DEFAULT 'unverified',
    verified_at DATETIME,
    verified_by_user_id TEXT REFERENCES users(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_claims_normalized_name ON name_claims(normalized_name);
CREATE INDEX IF NOT EXISTS idx_claims_user_id ON name_claims(user_id);

-- 4. Claim verification attempts table
CREATE TABLE IF NOT EXISTS claim_verification_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL REFERENCES name_claims(id) ON DELETE CASCADE,
    upload_id TEXT,
    status TEXT CHECK (status IN ('pending','approved','rejected')) NOT NULL DEFAULT 'pending',
    reviewed_by_user_id TEXT REFERENCES users(id),
    reviewed_at DATETIME,
    notes TEXT
);

