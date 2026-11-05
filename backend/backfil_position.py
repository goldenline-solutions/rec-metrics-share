import sqlite3
import os
from sqlalchemy import create_engine, text

SQLITE_PATH = "app.db"
POSTGRES_URL = "postgresql+psycopg2://USER:PASSWORD@localhost:5432/app_db"

if not POSTGRES_URL:
    raise SystemExit("Set PG_DATABASE_URL to your Postgres connection string first.")

def main():
    # Read from SQLite
    sconn = sqlite3.connect(SQLITE_PATH)
    sconn.row_factory = sqlite3.Row

    rows = sconn.execute("""
        SELECT id, position
        FROM builds
        WHERE position IS NOT NULL AND TRIM(position) <> ''
    """).fetchall()

    payload = [{"id": r["id"], "build_position": r["position"]} for r in rows]
    sconn.close()

    if not payload:
        print("No rows to backfill (SQLite builds.position is empty).")
        return

    # Write to Postgres
    pg = create_engine(POSTGRES_URL, future=True)
    with pg.begin() as conn:
        conn.execute(
            text("UPDATE builds SET build_position = :build_position WHERE id = :id"),
            payload
        )

    print(f"✅ Backfilled build_position for {len(payload)} builds.")

if __name__ == "__main__":
    main()
