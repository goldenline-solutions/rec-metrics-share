"""
Run PostgreSQL migration 9: add uploaded_by_user_id to games table.
Use this when your DB is Postgres and the column is missing (e.g. profile page error).

From backend dir: python run_pg_migration_9.py
"""
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from db import engine
from sqlalchemy import text

STATEMENTS = [
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS uploaded_by_user_id TEXT",
    """
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_games_uploaded_by_user'
      ) THEN
        ALTER TABLE games
          ADD CONSTRAINT fk_games_uploaded_by_user
          FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id);
      END IF;
    END $$
    """,
    "CREATE INDEX IF NOT EXISTS idx_games_uploaded_by_user_id ON games(uploaded_by_user_id)",
]


def main():
    if not str(engine.url).startswith("postgresql"):
        print("This script is for PostgreSQL only. Your DATABASE_URL is not Postgres.")
        return 1
    try:
        with engine.connect() as conn:
            for stmt in STATEMENTS:
                conn.execute(text(stmt.strip()))
            conn.commit()
        print("Migration 9 applied: games.uploaded_by_user_id added.")
        return 0
    except Exception as e:
        print("Migration failed:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
