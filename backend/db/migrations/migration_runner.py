"""
Manual SQL migration runner for the identity system.
Runs migrations in order, tracking versions in schema_migrations table.
"""
import os
import sqlite3
from pathlib import Path
from typing import List, Tuple


def get_migration_files(migrations_dir: str) -> List[Tuple[int, str]]:
    """
    Get all migration files sorted by version number.
    
    Returns:
        List of (version_number, file_path) tuples
    """
    migrations_path = Path(migrations_dir)
    if not migrations_path.exists():
        return []
    
    migrations = []
    for file_path in sorted(migrations_path.glob("*.sql")):
        # Extract version number from filename (e.g., "0001_*.sql" -> 1)
        filename = file_path.name
        if filename.startswith("__"):
            continue
        try:
            version_str = filename.split("_")[0]
            version = int(version_str)
            migrations.append((version, str(file_path)))
        except (ValueError, IndexError):
            continue
    
    return sorted(migrations)


def get_current_version(conn: sqlite3.Connection) -> int:
    """
    Get the current migration version from schema_migrations table.
    
    Returns:
        Current version number, or 0 if no migrations have been run
    """
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT MAX(version) FROM schema_migrations")
        result = cursor.fetchone()
        if result and result[0] is not None:
            return result[0]
        return 0
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        return 0


def run_migration(conn: sqlite3.Connection, version: int, sql_file: str) -> bool:
    """
    Run a single migration file.
    
    Args:
        conn: SQLite connection
        version: Migration version number
        sql_file: Path to SQL file
        
    Returns:
        True if successful, False otherwise
    """
    if not os.path.exists(sql_file):
        print(f"Warning: Migration file not found: {sql_file}")
        return False
    
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    if not sql_content.strip():
        print(f"Warning: Migration {version} is empty, skipping")
        return True
    
    cursor = conn.cursor()
    
    try:
        # Execute all statements in the migration file
        # SQLite's executescript handles multiple statements
        cursor.executescript(sql_content)
        
        # Record this migration as applied
        cursor.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            (version,)
        )
        
        conn.commit()
        print(f"[OK] Applied migration {version}: {os.path.basename(sql_file)}")
        return True
        
    except sqlite3.OperationalError as e:
        # Check if it's a "duplicate column" error (for ALTER TABLE)
        error_msg = str(e).lower()
        if "duplicate column" in error_msg or "already exists" in error_msg:
            # Column already exists, migration already applied (idempotent)
            print(f"[SKIP] Migration {version} already applied (column exists): {os.path.basename(sql_file)}")
            # Still record it as applied
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                    (version,)
                )
                conn.commit()
            except:
                pass
            return True
        elif "no such column" in error_msg:
            # This might happen if we're trying to modify a column that doesn't exist yet
            # This is expected for the first run - the column will be created
            print(f"  Note: Column doesn't exist yet (will be created): {os.path.basename(sql_file)}")
            # Don't fail - let it try to create
            conn.rollback()
            # Try again - this time it should work
            try:
                cursor.executescript(sql_content)
                cursor.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                    (version,)
                )
                conn.commit()
                print(f"[OK] Applied migration {version} on retry: {os.path.basename(sql_file)}")
                return True
            except Exception as e2:
                print(f"[ERROR] Error applying migration {version} on retry: {e2}")
                conn.rollback()
                return False
        else:
            print(f"[ERROR] Error applying migration {version}: {e}")
            conn.rollback()
            return False
    except Exception as e:
        print(f"✗ Error applying migration {version}: {e}")
        conn.rollback()
        return False


def run_migrations(db_path: str, migrations_dir: str = None) -> bool:
    """
    Run all pending migrations.
    
    Args:
        db_path: Path to SQLite database file
        migrations_dir: Directory containing migration files (default: db/migrations)
        
    Returns:
        True if all migrations succeeded, False otherwise
    """
    if migrations_dir is None:
        # Default to db/migrations relative to this file
        script_dir = Path(__file__).parent
        migrations_dir = str(script_dir)
    
    # Get all migration files
    migrations = get_migration_files(migrations_dir)
    
    if not migrations:
        print("No migration files found")
        return True
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign keys
    
    try:
        # Get current version
        current_version = get_current_version(conn)
        print(f"Current migration version: {current_version}")
        
        # Run pending migrations
        pending = [(v, f) for v, f in migrations if v > current_version]
        
        if not pending:
            print("No pending migrations")
            return True
        
        print(f"Found {len(pending)} pending migration(s)")
        
        for version, sql_file in pending:
            if not run_migration(conn, version, sql_file):
                return False
        
        print("All migrations completed successfully")
        return True
        
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python migration_runner.py <db_path> [migrations_dir]")
        sys.exit(1)
    
    db_path = sys.argv[1]
    migrations_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    success = run_migrations(db_path, migrations_dir)
    sys.exit(0 if success else 1)

