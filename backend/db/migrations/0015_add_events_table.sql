-- Migration 15: First-party product/marketing event log (SQLite)
-- Durable, ad-blocker-resistant analytics we own. Written by POST /api/events.
-- No raw PII: params/attribution are app-controlled JSON, user_id only when known.

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT,
    params TEXT,          -- JSON: event-specific fields (position, ovr, template_id, ...)
    attribution TEXT,     -- JSON: utm_source/medium/campaign, gclid, landing_path
    referrer TEXT,
    user_id TEXT,         -- set when the visitor is authenticated; else NULL
    user_agent TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
