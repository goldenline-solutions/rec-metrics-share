-- Migration 10: Create discord_upload_channels table (SQLite)
-- Stores guild_id + channel_id for Discord bot upload channels (slash command registration)

CREATE TABLE IF NOT EXISTS discord_upload_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL UNIQUE,
    channel_id TEXT NOT NULL,
    registered_by_discord_id TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_discord_upload_channels_guild_id ON discord_upload_channels(guild_id);
CREATE INDEX IF NOT EXISTS idx_discord_upload_channels_channel_id ON discord_upload_channels(channel_id);
