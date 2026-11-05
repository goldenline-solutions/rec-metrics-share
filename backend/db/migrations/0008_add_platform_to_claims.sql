-- Migration 8: Add platform field to name_claims table
-- This migration allows the same username to be claimed on different platforms

-- 1. Add platform column to name_claims table
ALTER TABLE name_claims ADD COLUMN platform TEXT;

-- 2. Set existing claims to user's platform (or 'PC' if user has no platform)
UPDATE name_claims 
SET platform = COALESCE(
    (SELECT platform FROM users WHERE users.id = name_claims.user_id),
    'PC'
)
WHERE platform IS NULL;

-- 3. Create index on name_claims(platform, normalized_name) for platform-specific uniqueness checks
CREATE INDEX IF NOT EXISTS idx_claims_platform_normalized ON name_claims(platform, normalized_name);

-- 4. Create index on name_claims(user_id, platform) for user's claims per platform
CREATE INDEX IF NOT EXISTS idx_claims_user_platform ON name_claims(user_id, platform);
