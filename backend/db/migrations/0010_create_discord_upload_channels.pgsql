-- Migration 10 (PostgreSQL): Create discord_upload_channels table
-- Run once: psql $DATABASE_URL -f 0010_create_discord_upload_channels.pgsql

CREATE TABLE IF NOT EXISTS discord_upload_channels (
    id SERIAL PRIMARY KEY,
    guild_id TEXT NOT NULL UNIQUE,
    channel_id TEXT NOT NULL,
    registered_by_discord_id TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_discord_upload_channels_guild_id ON discord_upload_channels(guild_id);
CREATE INDEX IF NOT EXISTS idx_discord_upload_channels_channel_id ON discord_upload_channels(channel_id);
