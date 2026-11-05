"""
Run PostgreSQL migration 16: add game_version to the games table.

Backfills every existing game to '2K26' and sets the column default to '2K27'
so anything ingested from here on is tagged as the new title.

From backend dir: python run_pg_migration_16.py
"""
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from db import engine
from sqlalchemy import text

STATEMENTS = [
    "ALTER TABLE games ADD COLUMN IF NOT EXISTS game_version TEXT",
    "UPDATE games SET game_version = '2K26' WHERE game_version IS NULL",
    "ALTER TABLE games ALTER COLUMN game_version SET DEFAULT '2K27'",
    "CREATE INDEX IF NOT EXISTS idx_games_game_version ON games(game_version)",
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
            counts = conn.execute(text(
                "SELECT game_version, COUNT(*) FROM games GROUP BY game_version ORDER BY 1"
            )).fetchall()
        print("Migration 16 applied: games.game_version added.")
        for version, count in counts:
            print(f"  {version or 'NULL'}: {count} games")
        return 0
    except Exception as e:
        print("Migration failed:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
