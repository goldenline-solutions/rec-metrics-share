"""
Delete players with zero games played (no game_players, player_game_stats,
or matchup references).

Usage:
  python delete_unused_players.py            # dry-run
  python delete_unused_players.py --execute  # apply
"""

import argparse
from db import SessionLocal, init_db
from models import Player, GamePlayer, PlayerGameStats, Matchup
from sqlalchemy import func


def run(dry_run: bool):
    db = SessionLocal()
    try:
        # Subquery: player_ids that appear in any of the three reference tables
        used_in_gp = db.query(GamePlayer.player_id).distinct()
        used_in_stats = db.query(PlayerGameStats.player_id).distinct()
        used_in_def = db.query(Matchup.defender_player_id).distinct()
        used_in_off = db.query(Matchup.offender_player_id).distinct()

        used_ids = (
            used_in_gp
            .union(used_in_stats)
            .union(used_in_def)
            .union(used_in_off)
        ).subquery()

        unused = (
            db.query(Player)
            .filter(Player.id.notin_(db.query(used_ids)))
            .order_by(Player.gamertag)
            .all()
        )

        total = db.query(func.count(Player.id)).scalar()
        print(f"Total players : {total}")
        print(f"Unused players: {len(unused)}")

        if not unused:
            print("Nothing to delete.")
            return

        print()
        for p in unused:
            print(f"  DELETE  {p.gamertag!r}  (id={p.id})")
            if not dry_run:
                db.delete(p)

        if dry_run:
            print()
            print("DRY RUN – no changes written.")
            print("Re-run with --execute to apply.")
        else:
            db.commit()
            print(f"\nDeleted {len(unused)} unused players.")

    except Exception as exc:
        db.rollback()
        print(f"\nERROR: {exc}")
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Delete players with zero game appearances."
    )
    parser.add_argument("--execute", action="store_true", help="Apply deletions (default is dry-run)")
    args = parser.parse_args()
    init_db()
    run(dry_run=not args.execute)


if __name__ == "__main__":
    main()
