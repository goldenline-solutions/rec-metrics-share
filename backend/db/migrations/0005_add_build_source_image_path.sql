-- Migration 5: Add source_image_path to builds table
-- This migration adds a column to store the path to the uploaded build sheet screenshot

-- Add source_image_path column (rename from source_image_id if it exists)
-- SQLite doesn't support renaming columns, so we'll just add the new one
-- If source_image_id exists, we can migrate data manually if needed
ALTER TABLE builds ADD COLUMN source_image_path TEXT;

-- Note: If source_image_id column exists and has data, you may want to migrate it:
-- UPDATE builds SET source_image_path = (SELECT path FROM uploads WHERE id = source_image_id) WHERE source_image_id IS NOT NULL;
