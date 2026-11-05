-- Migration 6: Create player analysis cache table
-- This migration creates a table for caching OpenAI-generated player analysis results

CREATE TABLE IF NOT EXISTS player_analysis_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    last_n INTEGER,
    payload_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_player_analysis_cache_username ON player_analysis_cache(username);
CREATE INDEX IF NOT EXISTS idx_player_analysis_cache_payload_hash ON player_analysis_cache(payload_hash);
CREATE INDEX IF NOT EXISTS idx_player_analysis_cache_created_at ON player_analysis_cache(created_at);

