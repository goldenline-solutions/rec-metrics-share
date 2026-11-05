-- Migration 15 (PostgreSQL): First-party product/marketing event log
-- Durable, ad-blocker-resistant analytics we own. Written by POST /api/events.
-- No raw PII: params/attribution are app-controlled JSON, user_id only when known.

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT,
    params TEXT,
    attribution TEXT,
    referrer TEXT,
    user_id TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
