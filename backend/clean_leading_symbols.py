"""
Script to strip leading non-alphanumeric symbols from player names and related fields.

Affected tables:
  - players.gamertag
  - game_players.detected_raw_name, detected_norm_name
  - players_identity.canonical_name, canonical_norm
  - player_name_variants.raw_name, norm_name
  - name_claims.display_name, normalized_name

Usage:
  python clean_leading_symbols.py            # dry-run (shows changes, no DB writes)
  python clean_leading_symbols.py --execute  # apply changes
"""

import re
import argparse
from collections import defaultdict
from db import SessionLocal, init_db
from models import (
    Player, GamePlayer, PlayerGameStats, Matchup,
    PlayerIdentity, PlayerNameVariant, NameClaim,
)


LEADING_SYMBOL_RE  = re.compile(r'^[^a-zA-Z0-9]+')
TRAILING_SYMBOL_RE = re.compile(r'[^a-zA-Z0-9]+$')


def strip_symbols(value: str) -> str:
    """Remove leading and trailing characters that are not alphanumeric."""
    if not value:
        return value
    value = LEADING_SYMBOL_RE.sub('', value)
    value = TRAILING_SYMBOL_RE.sub('', value)
    return value.strip()


def needs_clean(value: str) -> bool:
    return bool(value and (LEADING_SYMBOL_RE.match(value) or TRAILING_SYMBOL_RE.search(value)))


def merge_player_refs(db, from_id: str, to_id: str):
    """Redirect all FK references from one player id to another."""
    db.query(GamePlayer).filter(GamePlayer.player_id == from_id).update(
        {"player_id": to_id}, synchronize_session=False
    )
    db.query(PlayerGameStats).filter(PlayerGameStats.player_id == from_id).update(
        {"player_id": to_id}, synchronize_session=False
    )
    db.query(Matchup).filter(Matchup.defender_player_id == from_id).update(
        {"defender_player_id": to_id}, synchronize_session=False
    )
    db.query(Matchup).filter(Matchup.offender_player_id == from_id).update(
        {"offender_player_id": to_id}, synchronize_session=False
    )


# ---------------------------------------------------------------------------
# Players table  (needs careful merge logic because gamertag is UNIQUE)
# ---------------------------------------------------------------------------

def clean_players(db, dry_run: bool) -> dict:
    stats = {"checked": 0, "cleaned": 0, "merged": 0, "skipped": 0}

    all_players = db.query(Player).all()
    stats["checked"] = len(all_players)

    # Build a lookup: current gamertag → player object
    by_tag = {p.gamertag: p for p in all_players}

    dirty = [p for p in all_players if needs_clean(p.gamertag)]
    if not dirty:
        print("  players.gamertag: nothing to clean")
        return stats

    # Group dirty players by their target (cleaned) gamertag
    # target → list of dirty players that map to it
    groups: dict[str, list] = defaultdict(list)
    for p in dirty:
        target = strip_symbols(p.gamertag)
        if target:
            groups[target].append(p)
        else:
            print(f"  SKIP  {p.gamertag!r} → empty after cleaning")
            stats["skipped"] += 1

    # For each target, decide what to do:
    #   - If a clean (non-dirty) player already has that tag → merge all dirty into it
    #   - If no clean player has it → pick the first dirty as "survivor", rename it,
    #     merge the rest into it
    #
    # We process MERGES first, flush, then do RENAMES so the unique constraint
    # is never violated mid-batch.

    survivors_to_rename: list[tuple[Player, str]] = []  # (player, new_gamertag)

    for target, players_for_target in groups.items():
        existing_clean = by_tag.get(target)  # player that already has the clean name
        # exclude dirty players from "existing_clean" check
        if existing_clean and needs_clean(existing_clean.gamertag):
            existing_clean = None  # it's also dirty, handle within group

        if existing_clean:
            # Merge all dirty players into the existing clean one
            for p in players_for_target:
                print(f"  MERGE {p.gamertag!r} → {target!r}  (into id={existing_clean.id})")
                if not dry_run:
                    merge_player_refs(db, p.id, existing_clean.id)
                    db.delete(p)
                stats["merged"] += 1
        else:
            # No existing clean player — first dirty player becomes the survivor
            survivor = players_for_target[0]
            to_merge = players_for_target[1:]

            # Merge all others into the survivor first
            for p in to_merge:
                print(f"  MERGE {p.gamertag!r} → {target!r}  (into survivor id={survivor.id})")
                if not dry_run:
                    merge_player_refs(db, p.id, survivor.id)
                    db.delete(p)
                stats["merged"] += 1

            # Queue survivor for rename (done after flush)
            print(f"  CLEAN {survivor.gamertag!r} → {target!r}")
            survivors_to_rename.append((survivor, target))
            stats["cleaned"] += 1

    if not dry_run:
        # Flush all deletes first so unique constraint is clear before renames
        db.flush()

        # Now safe to rename survivors
        for player, new_tag in survivors_to_rename:
            player.gamertag = new_tag

    return stats


# ---------------------------------------------------------------------------
# Simple single-column cleaner helper
# ---------------------------------------------------------------------------

def clean_column(db, model, col_attr, label: str, dry_run: bool) -> int:
    """Clean a single text column on any model. Returns count of rows changed."""
    all_rows = db.query(model).all()
    changed = 0
    for row in all_rows:
        value = getattr(row, col_attr)
        if needs_clean(value):
            cleaned = strip_symbols(value)
            print(f"  CLEAN [{label}] {value!r} → {cleaned!r}")
            if not dry_run:
                setattr(row, col_attr, cleaned)
            changed += 1
    if changed == 0:
        print(f"  {label}: nothing to clean")
    return changed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool):
    db = SessionLocal()
    total_changes = 0
    try:
        print()
        print("=" * 65)
        print("PLAYERS TABLE (gamertag)")
        print("=" * 65)
        p_stats = clean_players(db, dry_run)
        total_changes += p_stats["cleaned"] + p_stats["merged"]

        print()
        print("=" * 65)
        print("GAME_PLAYERS TABLE (detected_raw_name, detected_norm_name)")
        print("=" * 65)
        total_changes += clean_column(db, GamePlayer, "detected_raw_name",  "game_players.detected_raw_name",  dry_run)
        total_changes += clean_column(db, GamePlayer, "detected_norm_name", "game_players.detected_norm_name", dry_run)

        print()
        print("=" * 65)
        print("PLAYERS_IDENTITY TABLE (canonical_name, canonical_norm)")
        print("=" * 65)
        total_changes += clean_column(db, PlayerIdentity, "canonical_name", "players_identity.canonical_name", dry_run)
        total_changes += clean_column(db, PlayerIdentity, "canonical_norm", "players_identity.canonical_norm", dry_run)

        print()
        print("=" * 65)
        print("PLAYER_NAME_VARIANTS TABLE (raw_name, norm_name)")
        print("=" * 65)
        total_changes += clean_column(db, PlayerNameVariant, "raw_name",  "player_name_variants.raw_name",  dry_run)
        total_changes += clean_column(db, PlayerNameVariant, "norm_name", "player_name_variants.norm_name", dry_run)

        print()
        print("=" * 65)
        print("NAME_CLAIMS TABLE (display_name, normalized_name)")
        print("=" * 65)
        total_changes += clean_column(db, NameClaim, "display_name",     "name_claims.display_name",     dry_run)
        total_changes += clean_column(db, NameClaim, "normalized_name",  "name_claims.normalized_name",  dry_run)

        print()
        print("=" * 65)
        print("SUMMARY")
        print("=" * 65)
        print(f"  Total fields changed : {total_changes}")
        print(f"  Players cleaned      : {p_stats['cleaned']}")
        print(f"  Players merged (dup) : {p_stats['merged']}")
        print(f"  Players skipped      : {p_stats['skipped']}")

        if dry_run:
            print()
            print("  DRY RUN – no changes written.")
            print("  Re-run with --execute to apply.")
        else:
            db.commit()
            print()
            print("  Changes committed to database.")

    except Exception as exc:
        db.rollback()
        print(f"\nERROR: {exc}")
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Strip leading non-alphanumeric symbols from player names in the DB."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes (default is dry-run)",
    )
    args = parser.parse_args()

    init_db()
    run(dry_run=not args.execute)


if __name__ == "__main__":
    main()
