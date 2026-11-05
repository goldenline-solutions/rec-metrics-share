-- Migration 1: Create schema_migrations table
-- This table tracks which migrations have been applied

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY
);

