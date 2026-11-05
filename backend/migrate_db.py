"""
Safe database migration script.
Adds missing columns to existing tables without losing any data.

Usage:
    python migrate_db.py

This script will:
1. Check existing tables and columns
2. Add any missing columns from the current models
3. Create any missing tables
4. Never drop or modify existing data
"""
import os
import sys
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from db import engine, Base
from models import Game, Player, GamePlayer, PlayerGameStats, TeamTotal, Matchup, User

def get_existing_columns(conn, table_name):
    """Get list of existing columns for a table."""
    inspector = inspect(engine)
    try:
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        return columns
    except Exception:
        return []

def column_exists(conn, table_name, column_name):
    """Check if a column exists in a table."""
    existing_columns = get_existing_columns(conn, table_name)
    return column_name in existing_columns

def add_column_safe(conn, table_name, column_def):
    """
    Safely add a column to a table if it doesn't exist.
    column_def should be a SQLAlchemy Column object.
    """
    column_name = column_def.name
    
    if column_exists(conn, table_name, column_name):
        print(f"  ✓ Column '{column_name}' already exists in '{table_name}'")
        return False
    
    # Get SQL type from column
    column_type = column_def.type.compile(dialect=engine.dialect)
    
    # Build ALTER TABLE statement
    # For safety, we'll add columns as nullable (even if the model says NOT NULL)
    # This prevents errors if there's existing data
    # The application code will handle defaults for new rows
    nullable = "NULL"
    
    alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} {nullable}"
    
    try:
        conn.execute(text(alter_sql))
        print(f"  ✓ Added column '{column_name}' to '{table_name}'")
        return True
    except Exception as e:
        print(f"  ✗ Error adding column '{column_name}' to '{table_name}': {e}")
        raise

def migrate_table(conn, model_class):
    """Migrate a single table by adding missing columns."""
    table_name = model_class.__tablename__
    print(f"\nChecking table: {table_name}")
    
    # Check if table exists
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        print(f"  ⚠ Table '{table_name}' does not exist. It will be created by init_db().")
        return
    
    # Get existing columns
    existing_columns = get_existing_columns(conn, table_name)
    print(f"  Existing columns: {', '.join(existing_columns) if existing_columns else 'None'}")
    
    # Get model columns
    model_columns = {col.name: col for col in model_class.__table__.columns}
    print(f"  Model columns: {', '.join(model_columns.keys())}")
    
    # Add missing columns
    added_count = 0
    for col_name, col_def in model_columns.items():
        if col_name not in existing_columns:
            if add_column_safe(conn, table_name, col_def):
                added_count += 1
    
    if added_count == 0:
        print(f"  ✓ Table '{table_name}' is up to date")
    else:
        print(f"  ✓ Added {added_count} column(s) to '{table_name}'")

def main():
    """Main migration function."""
    print("=" * 60)
    print("Database Migration Script")
    print("=" * 60)
    print("\nThis script will:")
    print("  1. Check existing tables and columns")
    print("  2. Add any missing columns from current models")
    print("  3. Create any missing tables")
    print("  4. Never drop or modify existing data")
    print("\n" + "=" * 60)
    
    # Confirm before proceeding
    response = input("\nProceed with migration? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("Migration cancelled.")
        return
    
    with engine.begin() as conn:
        try:
            # First, create any missing tables
            print("\n" + "=" * 60)
            print("Step 1: Creating missing tables...")
            print("=" * 60)
            Base.metadata.create_all(bind=engine)
            print("✓ Missing tables created (if any)")
            
            # Then, migrate each table
            print("\n" + "=" * 60)
            print("Step 2: Adding missing columns to existing tables...")
            print("=" * 60)
            
            migrate_table(conn, Game)
            migrate_table(conn, Player)
            migrate_table(conn, GamePlayer)
            migrate_table(conn, PlayerGameStats)
            migrate_table(conn, TeamTotal)
            migrate_table(conn, Matchup)
            migrate_table(conn, User)
            
            print("\n" + "=" * 60)
            print("✓ Migration completed successfully!")
            print("=" * 60)
            
        except Exception as e:
            print(f"\n✗ Migration failed: {e}")
            print("Rolled back all changes.")
            raise

if __name__ == "__main__":
    main()

