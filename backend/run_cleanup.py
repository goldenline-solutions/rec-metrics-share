"""
Master data cleanup script. Runs all cleanup steps in the correct order.

Order matters:
  1. clean_leading_symbols  – strip symbol artifacts from player names (merges dupes)
  2. delete_unused_players  – remove players with zero game appearances
  3. fix_matchup_mismatches – reconcile matchup player_ids against game_players

Usage:
  python run_cleanup.py            # dry-run (no DB writes)
  python run_cleanup.py --execute  # apply all changes
"""

import argparse
import clean_leading_symbols
import delete_unused_players
import fix_matchup_mismatches
from db import init_db


STEPS = [
    ("1. Clean leading/trailing symbols", clean_leading_symbols.run),
    ("2. Delete unused players (0 games)", delete_unused_players.run),
    ("3. Fix matchup mismatches",          fix_matchup_mismatches.run),
]


def main():
    parser = argparse.ArgumentParser(
        description="Run all data cleanup scripts in sequence."
    )
    parser.add_argument("--execute", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()
    dry_run = not args.execute

    init_db()

    if dry_run:
        print("=" * 65)
        print("  DRY RUN MODE – no changes will be written")
        print("  Re-run with --execute to apply")
        print("=" * 65)

    for title, run_fn in STEPS:
        print()
        print("=" * 65)
        print(f"  {title}")
        print("=" * 65)
        run_fn(dry_run=dry_run)

    print()
    print("=" * 65)
    print("  All steps complete.")
    print("=" * 65)


if __name__ == "__main__":
    main()
