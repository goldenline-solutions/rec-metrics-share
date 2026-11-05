"""
Scan all games in the database for duplicates and delete them.

Duplicate detection reuses the same logic as ingest_service.check_duplicate_game:
  - Games are duplicates if they share the same score AND the same set of
    (team_side, position, gamertag) tuples for all players.

When a duplicate group is found the OLDEST game (lowest created_at) is kept
and all newer copies are deleted (along with their cascaded child rows).

Usage:
  python dedup_games.py            # dry-run — shows what would be deleted
  python dedup_games.py --execute  # apply deletions
"""

import argparse
from collections import defaultdict
from db import SessionLocal, init_db
from models import Game, GamePlayer, Player


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_game_signature(db, game: Game):
    """
    Return a frozenset-based signature for a game so duplicates can be grouped.
    Signature: (away_score, home_score, frozenset of (team_side, position, gamertag_lower))
    Returns None if the game has no players (can't compare).
    """
    game_players = (
        db.query(GamePlayer, Player)
        .join(Player, GamePlayer.player_id == Player.id)
        .filter(GamePlayer.game_id == game.id)
        .all()
    )

    if not game_players:
        return None

    player_tuples = frozenset(
        (gp.team_side, gp.position, player.gamertag.lower())
        for gp, player in game_players
    )

    return (game.away_score, game.home_score, player_tuples)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool):
    db = SessionLocal()
    try:
        all_games = db.query(Game).order_by(Game.created_at).all()
        print(f"Total games in database: {len(all_games)}")

        # Group games by signature
        sig_to_games: dict = defaultdict(list)
        skipped = 0

        for game in all_games:
            sig = build_game_signature(db, game)
            if sig is None:
                skipped += 1
                continue
            sig_to_games[sig].append(game)

        if skipped:
            print(f"Skipped {skipped} game(s) with no player data (cannot compare).")

        # Find groups with more than one game
        dup_groups = {sig: games for sig, games in sig_to_games.items() if len(games) > 1}

        if not dup_groups:
            print("No duplicates found.")
            return

        total_to_delete = sum(len(games) - 1 for games in dup_groups.values())
        print(f"\nFound {len(dup_groups)} duplicate group(s), {total_to_delete} game(s) to delete.\n")

        for sig, games in dup_groups.items():
            away_score, home_score, _ = sig
            # Sort by created_at ascending so the first entry is the oldest
            games_sorted = sorted(games, key=lambda g: g.created_at or "")
            keeper = games_sorted[0]
            to_delete = games_sorted[1:]

            print(
                f"Group — score {away_score}-{home_score} | "
                f"{len(games)} copies | keeping game {keeper.id} (created {keeper.created_at})"
            )
            for g in to_delete:
                print(f"  {'[DRY-RUN] would delete' if dry_run else 'Deleting'} game {g.id} (created {g.created_at})")
                if not dry_run:
                    db.delete(g)

        if not dry_run:
            db.commit()
            print(f"\nDone. Deleted {total_to_delete} duplicate game(s).")
        else:
            print(f"\nDry-run complete. Run with --execute to apply deletions.")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deduplicate games in the database.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete duplicates. Without this flag the script runs as a dry-run.",
    )
    args = parser.parse_args()

    init_db()
    run(dry_run=not args.execute)
