"""
Create the MyNBA league tables and seed the 30 NBA franchises.

Safe to re-run: create_all skips tables that already exist, and the team seed
only inserts franchises the league is missing.

    python migrate_mynba.py                     # create tables only
    python migrate_mynba.py --guild <guild_id>  # also create the league + 30 teams
"""
import argparse
import sys

from db import engine, Base, SessionLocal
import models  # noqa: F401  — registers the existing tables on Base
import mynba_models  # noqa: F401  — registers the mynba_* tables
import nba2k_models  # noqa: F401  — registers the nba2k_* tables
import mynba_service as svc
from mynba_models import (
    MynbaLeague, MynbaCommissioner, MynbaTeam, MynbaPlayer,
    MynbaTrade, MynbaTradeAsset, MynbaTradeVote, MynbaTransaction, MynbaTradeTeam,
    MynbaGameplan, MynbaGameplanChange, MynbaGame, MynbaGameLine,
)
from nba2k_models import Nba2kPlayer, Nba2kSyncRun

MYNBA_TABLES = [
    MynbaLeague.__table__, MynbaTeam.__table__, MynbaCommissioner.__table__,
    MynbaPlayer.__table__, MynbaTrade.__table__, MynbaTradeAsset.__table__,
    MynbaTradeVote.__table__, MynbaTransaction.__table__, MynbaTradeTeam.__table__,
    Nba2kPlayer.__table__, Nba2kSyncRun.__table__,
    MynbaGameplan.__table__, MynbaGameplanChange.__table__,
    MynbaGame.__table__, MynbaGameLine.__table__,
]


# Columns added to tables that already existed. create_all() only creates whole
# tables, so anything added later needs its own idempotent ALTER.
ADDED_COLUMNS = [
    ("mynba_trades", "team_count", "INTEGER NOT NULL DEFAULT 2"),
    ("mynba_leagues", "untouchables_per_team", "INTEGER NOT NULL DEFAULT 2"),
    ("mynba_leagues", "sim_weekday", "INTEGER NOT NULL DEFAULT 5"),
    ("mynba_leagues", "gameplan_lock_days", "INTEGER NOT NULL DEFAULT 2"),
    ("mynba_leagues", "gameplan_lock_override", "BOOLEAN"),
    ("mynba_leagues", "gameplan_channel_id", "VARCHAR"),
    ("mynba_leagues", "sixth_man_min_minutes", "INTEGER NOT NULL DEFAULT 20"),
    ("mynba_leagues", "bench_min_minutes", "INTEGER NOT NULL DEFAULT 10"),
    ("mynba_players", "secondary_position", "VARCHAR"),
    ("mynba_players", "is_rookie", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("mynba_players", "is_untouchable", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("mynba_leagues", "max_trade_teams", "INTEGER NOT NULL DEFAULT 3"),
    ("mynba_leagues", "sim_hour", "INTEGER NOT NULL DEFAULT 20"),
    ("mynba_leagues", "rulebook", "TEXT"),
    ("mynba_leagues", "rulebook_version", "INTEGER NOT NULL DEFAULT 0"),
    ("mynba_leagues", "rulebook_updated_at", "TIMESTAMP"),
    ("mynba_leagues", "rulebook_updated_by", "VARCHAR"),
    ("mynba_leagues", "gameplan_lock_minute", "INTEGER NOT NULL DEFAULT 1439"),
    ("mynba_leagues", "lock_roster_moves", "BOOLEAN NOT NULL DEFAULT TRUE"),
]


def create_tables():
    print(f"Database: {engine.url}")
    Base.metadata.create_all(bind=engine, tables=MYNBA_TABLES)
    for table in MYNBA_TABLES:
        print(f"  ready: {table.name}")
    add_missing_columns()


def add_missing_columns():
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if table not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table)}
            if column in have:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            print(f"  added column: {table}.{column}")


def setup_league(guild_id, name, commissioner_discord_id=None):
    db = SessionLocal()
    try:
        league = svc.get_league(db, guild_id)
        if league:
            print(f'League "{league.name}" already exists for guild {guild_id}.')
            added = svc.seed_nba_teams(db, league)
            print(f"  seeded {len(added)} missing team(s)")
        else:
            league = svc.create_league(db, guild_id, name=name)
            print(f'Created league "{league.name}" for guild {guild_id} with 30 teams.')

        if commissioner_discord_id and not svc.is_commissioner(db, league, commissioner_discord_id):
            db.add(MynbaCommissioner(league_id=league.id, discord_id=str(commissioner_discord_id)))
            print(f"  added commissioner {commissioner_discord_id}")

        db.commit()

        teams = db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id).count()
        players = db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).count()
        print(f"\nLeague id: {league.id}")
        print(f"Teams: {teams}   Players: {players}")
        print("\nNext: import the roster CSV with POST /api/mynba/import (or /league-import in Discord).")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Set up the MyNBA league tables.")
    parser.add_argument("--guild", help="Discord guild id — also creates the league and seeds 30 teams")
    parser.add_argument("--name", default="MyNBA League", help="League display name")
    parser.add_argument("--commissioner", help="Discord user id to make the first commissioner")
    args = parser.parse_args()

    create_tables()
    if args.guild:
        print()
        setup_league(args.guild, args.name, args.commissioner)
    else:
        print("\nTables ready. Re-run with --guild <id> to create the league and seed teams.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
