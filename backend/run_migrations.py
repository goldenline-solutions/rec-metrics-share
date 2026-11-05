"""
Manual script to run database migrations.
Run this if migrations don't run automatically on startup.
"""
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

import sys
from pathlib import Path

# Add the migrations directory to the path
migrations_dir = Path(__file__).parent / "db" / "migrations"
sys.path.insert(0, str(migrations_dir.parent))

# Import after adding to path
from db import engine
import importlib.util

# Load migration_runner module
migration_runner_path = migrations_dir / "migration_runner.py"
spec = importlib.util.spec_from_file_location("migration_runner", migration_runner_path)
migration_runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration_runner)
run_migrations = migration_runner.run_migrations

def main():
    """Run all pending migrations."""
    # Get database path from engine
    db_url = str(engine.url)
    
    if not db_url.startswith("sqlite"):
        print("Migrations are only supported for SQLite databases currently.")
        return 1
    
    # Extract file path from SQLite URL
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        if db_path.startswith("./"):
            # Relative path - resolve relative to backend directory
            db_path = str(backend_dir / db_path[2:])
        elif not os.path.isabs(db_path):
            # Relative path without ./
            db_path = str(backend_dir / db_path)
    else:
        print("Cannot determine database path from URL:", db_url)
        return 1
    
    print(f"Database path: {db_path}")
    
    # Get migrations directory
    migrations_dir = backend_dir / "db" / "migrations"
    print(f"Migrations directory: {migrations_dir}")
    
    if not migrations_dir.exists():
        print(f"Error: Migrations directory not found: {migrations_dir}")
        return 1
    
    # Run migrations
    print("Running migrations...")
    success = run_migrations(db_path, str(migrations_dir))
    
    if success:
        print("[SUCCESS] All migrations completed successfully!")
        return 0
    else:
        print("[FAILED] Some migrations failed. Check the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

