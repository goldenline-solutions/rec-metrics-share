"""
Fix matchup mismatches where a matchup's player_id no longer matches the actual
player assigned to that position in game_players.

For POSITIONAL matchups the correct state is always:
  - For each position P, there are 2 matchups:
      HOME[P] defends AWAY[P]
      AWAY[P] defends HOME[P]
  - The player_ids must match the current game_players entries for that position.

The script priorities stats (game_players) over the matchup table.
game_players entries whose player_id is not in the players table are skipped
(orphaned rows from prior merges).

Usage:
  python fix_matchup_mismatches.py            # dry-run
  python fix_matchup_mismatches.py --execute  # apply
"""

import argparse
from db import SessionLocal, init_db
from models import Game, GamePlayer, Matchup, Player
from sqlalchemy import text


POSITIONS = ['PG', 'SG', 'SF', 'PF', 'C']


def get_valid_player_ids(db) -> set:
    """Return all player_ids that actually exist in the players table."""
    rows = db.execute(text("SELECT id FROM players")).fetchall()
    return {r[0] for r in rows}


def get_position_map(db, game_id: str, valid_ids: set) -> dict:
    """
    Returns {(team_side, position): player_id} for a game.
    Skips game_player rows whose player_id is not in valid_ids (orphaned).
    """
    gps = db.query(GamePlayer).filter_by(game_id=game_id).all()
    pos_map = {}
    for gp in gps:
        if gp.player_id not in valid_ids:
            continue  # orphaned — skip
        key = (gp.team_side, gp.position)
        pos_map[key] = gp.player_id
    return pos_map


def fix_game_matchups(db, game_id: str, valid_ids: set, dry_run: bool) -> dict:
    stats = {"checked": 0, "fixed": 0, "deleted": 0, "created": 0, "skipped_orphan": 0}

    pos_map = get_position_map(db, game_id, valid_ids)
    if not pos_map:
        return stats

    existing_matchups = db.query(Matchup).filter_by(game_id=game_id).all()
    stats["checked"] = len(existing_matchups)

    # Build the expected set of matchups from game_players
    # {(defender_player_id, offender_player_id, def_pos, off_pos): True}
    expected = {}
    for pos in POSITIONS:
        home_pid = pos_map.get(('HOME', pos))
        away_pid = pos_map.get(('AWAY', pos))
        if home_pid and away_pid:
            expected[(home_pid, away_pid, pos, pos)] = True  # HOME defends AWAY
            expected[(away_pid, home_pid, pos, pos)] = True  # AWAY defends HOME

    # Check existing matchups against expected
    existing_keys = set()
    to_delete = []
    for m in existing_matchups:
        # If either side is an orphaned player_id, remove the matchup
        if m.defender_player_id not in valid_ids or m.offender_player_id not in valid_ids:
            print(
                f"  DEL  game={game_id[:8]}  orphaned player in matchup"
                f"  def={m.defender_player_id[:8]}  off={m.offender_player_id[:8]}"
            )
            to_delete.append(m)
            stats["deleted"] += 1
            continue

        key = (m.defender_player_id, m.offender_player_id, m.defender_position, m.offender_position)
        if key in expected:
            existing_keys.add(key)
        else:
            corrected = _find_corrected_key(m, pos_map)
            if corrected:
                new_def_pid, new_off_pid = corrected
                print(
                    f"  FIX  game={game_id[:8]}  pos={m.defender_position}"
                    f"  defender: {_tag(db, m.defender_player_id)!r} → {_tag(db, new_def_pid)!r}"
                    f"  offender: {_tag(db, m.offender_player_id)!r} → {_tag(db, new_off_pid)!r}"
                )
                if not dry_run:
                    m.defender_player_id = new_def_pid
                    m.offender_player_id = new_off_pid
                corrected_key = (new_def_pid, new_off_pid, m.defender_position, m.offender_position)
                existing_keys.add(corrected_key)
                stats["fixed"] += 1
            else:
                print(
                    f"  DEL  game={game_id[:8]}  stale matchup"
                    f"  def={_tag(db, m.defender_player_id)!r}"
                    f"  off={_tag(db, m.offender_player_id)!r}"
                )
                to_delete.append(m)
                stats["deleted"] += 1

    if not dry_run:
        for m in to_delete:
            db.delete(m)

    # Create any expected matchups that are completely missing
    for key in expected:
        if key not in existing_keys:
            def_pid, off_pid, def_pos, off_pos = key
            print(
                f"  ADD  game={game_id[:8]}  pos={def_pos}"
                f"  def={_tag(db, def_pid)!r}  off={_tag(db, off_pid)!r}"
            )
            if not dry_run:
                db.add(Matchup(
                    game_id=game_id,
                    defender_player_id=def_pid,
                    offender_player_id=off_pid,
                    defender_position=def_pos,
                    offender_position=off_pos,
                    matchup_type='POSITIONAL'
                ))
            stats["created"] += 1

    return stats


def _find_corrected_key(matchup: Matchup, pos_map: dict):
    """
    Given a stale matchup and the current pos_map, figure out the correct
    player_ids for the same positional slot.
    Returns (new_defender_pid, new_offender_pid) or None.
    """
    def_pos = matchup.defender_position
    off_pos = matchup.offender_position
    if def_pos != off_pos:
        return None

    home_pid = pos_map.get(('HOME', def_pos))
    away_pid = pos_map.get(('AWAY', def_pos))
    if not home_pid or not away_pid:
        return None

    home_pids = {v for (side, _), v in pos_map.items() if side == 'HOME'}
    away_pids = {v for (side, _), v in pos_map.items() if side == 'AWAY'}

    old_def = matchup.defender_player_id
    old_off = matchup.offender_player_id

    if old_def in home_pids:
        return (home_pid, away_pid)
    elif old_def in away_pids:
        return (away_pid, home_pid)
    elif old_off in home_pids:
        return (away_pid, home_pid)
    elif old_off in away_pids:
        return (home_pid, away_pid)

    return None


_tag_cache: dict = {}


def _tag(db, player_id: str) -> str:
    if player_id not in _tag_cache:
        p = db.query(Player).filter_by(id=player_id).first()
        _tag_cache[player_id] = p.gamertag if p else f"<orphan:{player_id[:8]}>"
    return _tag_cache[player_id]


def run(dry_run: bool):
    db = SessionLocal()
    totals = {"checked": 0, "fixed": 0, "deleted": 0, "created": 0, "skipped_orphan": 0}
    try:
        print("Loading valid player ids...")
        valid_ids = get_valid_player_ids(db)
        print(f"  {len(valid_ids)} players in table\n")

        games = db.query(Game).all()
        print(f"Scanning {len(games)} games...\n")

        games_with_changes = 0
        for game in games:
            s = fix_game_matchups(db, game.id, valid_ids, dry_run)
            changes = s["fixed"] + s["deleted"] + s["created"]
            if changes:
                games_with_changes += 1
                if not dry_run:
                    # Flush per-game so FK violations surface individually
                    db.flush()
            for k in totals:
                totals[k] += s[k]

        print()
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  Games scanned        : {len(games)}")
        print(f"  Games with changes   : {games_with_changes}")
        print(f"  Matchups checked     : {totals['checked']}")
        print(f"  Fixed (player swap)  : {totals['fixed']}")
        print(f"  Deleted (stale)      : {totals['deleted']}")
        print(f"  Created (missing)    : {totals['created']}")

        if dry_run:
            print()
            print("  DRY RUN – no changes written.")
            print("  Re-run with --execute to apply.")
        else:
            db.commit()
            print()
            print("  Changes committed.")

    except Exception as exc:
        db.rollback()
        print(f"\nERROR: {exc}")
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Fix matchup player_id mismatches against game_players (stats take priority)."
    )
    parser.add_argument("--execute", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()
    init_db()
    run(dry_run=not args.execute)


if __name__ == "__main__":
    main()
