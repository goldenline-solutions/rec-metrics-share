import os
from sqlalchemy import create_engine, text

SQLITE_URL = os.getenv("SQLITE_URL", "sqlite:///app.db")
POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql+psycopg2://USER:PASSWORD@localhost:5432/app_db"
)

# Tables that exist in SQLite but you don't want / can't import
SKIP_TABLES = {
    "sqlite_sequence",
    "schema_migrations",  # you have this in SQLite but not in models
}


def get_sqlite_tables(sconn):
    rows = sconn.execute(text("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name;
    """)).fetchall()
    return [r[0] for r in rows if r[0] not in SKIP_TABLES]


def pg_table_exists(pconn, table_name: str) -> bool:
    return bool(pconn.execute(text("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema='public' AND table_name=:t
        )
    """), {"t": table_name}).scalar())


def get_pg_columns(pconn, table_name: str) -> list[str]:
    rows = pconn.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:t
        ORDER BY ordinal_position
    """), {"t": table_name}).fetchall()
    return [r[0] for r in rows]


def truncate_all_postgres_tables(pconn):
    pconn.execute(text("""
        DO $$
        DECLARE r RECORD;
        BEGIN
          FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname='public') LOOP
            EXECUTE 'TRUNCATE TABLE ' || quote_ident(r.tablename) || ' CASCADE';
          END LOOP;
        END $$;
    """))


def main():
    sqlite_engine = create_engine(SQLITE_URL, future=True)
    pg_engine = create_engine(POSTGRES_URL, future=True)

    with sqlite_engine.connect() as sconn, pg_engine.begin() as pconn:
        # 1) Disable FK triggers/constraints during load (quick mode)
        pconn.execute(text("SET session_replication_role = 'replica';"))

        # 2) Clean slate
        truncate_all_postgres_tables(pconn)

        # 3) Load
        tables = get_sqlite_tables(sconn)
        print("SQLite tables:", tables)

        for t in tables:
            if not pg_table_exists(pconn, t):
                print(f"Skipping {t}: not found in Postgres.")
                continue

            rows = sconn.execute(text(f'SELECT * FROM "{t}"')).mappings().all()
            if not rows:
                print(f"{t}: 0 rows")
                continue

            pg_cols = set(get_pg_columns(pconn, t))
            sqlite_cols = list(rows[0].keys())

            # Keep only columns that exist in Postgres
            use_cols = [c for c in sqlite_cols if c in pg_cols]
            ignored = [c for c in sqlite_cols if c not in pg_cols]
            if ignored:
                print(f"{t}: ignoring SQLite-only columns: {ignored}")

            if not use_cols:
                print(f"{t}: no common columns, skipping")
                continue

            filtered_rows = [{c: r.get(c) for c in use_cols} for r in rows]

            col_list = ", ".join(f'"{c}"' for c in use_cols)
            val_list = ", ".join(f":{c}" for c in use_cols)
            stmt = text(f'INSERT INTO "{t}" ({col_list}) VALUES ({val_list})')

            pconn.execute(stmt, filtered_rows)
            print(f"{t}: copied {len(filtered_rows)} rows")

        # 4) Re-enable FK triggers/constraints
        pconn.execute(text("SET session_replication_role = 'origin';"))

    print("✅ Migration complete (quick mode).")


if __name__ == "__main__":
    main()
