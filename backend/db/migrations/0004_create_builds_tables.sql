-- Migration 4: Create builds system tables
-- This migration creates tables for storing NBA 2K build data extracted from screenshots

-- 1. Create builds table
CREATE TABLE IF NOT EXISTS builds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    position TEXT,
    archetype TEXT,
    height TEXT,
    weight_lbs INTEGER,
    wingspan TEXT,
    overall_current INTEGER,
    overall_max INTEGER,
    source_image_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_builds_owner_user_id ON builds(owner_user_id);

-- 2. Create build_attributes table
CREATE TABLE IF NOT EXISTS build_attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id INTEGER NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    attribute_name TEXT NOT NULL,
    value_current INTEGER NOT NULL,
    value_max INTEGER,
    display_order INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(build_id, category, attribute_name)
);

CREATE INDEX IF NOT EXISTS idx_build_attributes_build_id ON build_attributes(build_id);
CREATE INDEX IF NOT EXISTS idx_build_attributes_category ON build_attributes(category);

-- 3. Add build_id column to game_players table
ALTER TABLE game_players ADD COLUMN build_id INTEGER REFERENCES builds(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_game_players_build_id ON game_players(build_id);
