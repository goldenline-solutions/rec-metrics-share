# Database Migration Guide

This guide explains how to safely update your production database schema without losing any data.

## Quick Migration (Recommended)

The safest way to update your database is to use the migration script:

```bash
cd backend
python migrate_db.py
```

This script will:
- ✅ Check all existing tables and columns
- ✅ Add any missing columns from the current models
- ✅ Create any missing tables
- ✅ **Never drop or modify existing data**
- ✅ Ask for confirmation before making changes

## Manual Migration (Alternative)

If you prefer to do it manually or the script doesn't work for your setup:

### For SQLite:

1. **Backup your database first:**
   ```bash
   cp app.db app.db.backup
   ```

2. **Run the migration script:**
   ```bash
   python migrate_db.py
   ```

3. **Verify the changes:**
   ```bash
   sqlite3 app.db
   .schema users
   .quit
   ```

### For PostgreSQL:

1. **Backup your database first:**
   ```bash
   pg_dump -U username -d database_name > backup.sql
   ```

2. **Run the migration script:**
   ```bash
   python migrate_db.py
   ```

3. **Verify the changes:**
   ```sql
   \d users
   ```

## What Gets Updated?

The migration script checks for and adds:

- **Missing tables**: Any new tables defined in `models.py`
- **Missing columns**: Any new columns in existing tables (e.g., `roles` and `permissions` in `users` table)

## Important Notes

1. **Always backup first**: Even though the script is safe, always backup your production database before running migrations.

2. **Test in development**: Test the migration script on a copy of your production database first.

3. **No data loss**: The script only adds columns/tables. It never:
   - Drops tables
   - Drops columns
   - Modifies existing data
   - Changes column types

4. **Default values**: New columns will be added with appropriate defaults (NULL for nullable columns).

## Troubleshooting

### Error: "Column already exists"
This is normal - it means the column was already added. The script will skip it.

### Error: "Table does not exist"
The script will create missing tables automatically using `Base.metadata.create_all()`.

### Error: "Cannot add NOT NULL column without default"
If you see this error, you may need to:
1. Add the column as nullable first
2. Update existing rows with default values
3. Then make it NOT NULL (if needed)

The migration script handles this automatically for most cases.

## Verification

After running the migration, verify everything worked:

```python
# Test script
from db import SessionLocal
from models import User

db = SessionLocal()
try:
    # Check if new columns exist
    user = db.query(User).first()
    if user:
        print(f"User roles: {user.roles}")
        print(f"User permissions: {user.permissions}")
    print("✓ Migration successful!")
finally:
    db.close()
```

## Rollback

If something goes wrong:

1. **SQLite**: Restore from backup
   ```bash
   cp app.db.backup app.db
   ```

2. **PostgreSQL**: Restore from backup
   ```bash
   psql -U username -d database_name < backup.sql
   ```

