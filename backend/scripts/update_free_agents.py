"""
Replace a MyNBA league's free-agent pool with the list from a CSV.

The CSV has abbreviated names as 2K shows them ("C. Gillespie") and a
position. Each is matched to a free agent by first initial + last name;
names with several candidates are settled by PICKS; names not in the league
are created (full name from the 2K reference data when it has one).
Free agents not on the list are deleted. Rostered players are never touched.

    python scripts/update_free_agents.py --guild <id> --csv <path>          # dry run
    python scripts/update_free_agents.py --guild <id> --csv <path> --apply  # do it
"""
import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal  # noqa: E402
import models  # noqa: E402,F401
import mynba_service as svc  # noqa: E402
from mynba_models import MynbaLeague, MynbaPlayer, MynbaTransaction, TXN_IMPORT  # noqa: E402
from nba2k_models import Nba2kPlayer  # noqa: E402

# (abbreviated name, position) -> full name, where the abbreviation fits
# several players. Confirmed by the commissioner 2026-10-29.
PICKS = {
    ("T. Mann", "PG"): "Tre Mann",
    ("T. Mann", "SG"): "Terance Mann",
    ("J. Green", "SF"): "Josh Green",
    ("C. Martin", "PF"): "Caleb Martin",
    ("M. Gueye", "PF"): "Mouhamed Gueye",
    ("J. Walker", "PF"): "Jarace Walker",
    ("D. Powell", "C"): "Dwight Powell",
}

# Lines on the FA list that are really rostered players; skipped.
SKIP = {"J. Jaquez Jr."}

SUFFIX = {"jr", "sr", "ii", "iii", "iv"}


def _fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'’`]", "", s)
    return [t for t in re.split(r"[^a-z]+", s) if t]


def signature(name):
    """('c', 'gillespie') for both "C. Gillespie" and "Collin Gillespie"."""
    tokens = [t for t in _fold(name) if t not in SUFFIX] or _fold(name)
    if not tokens:
        return None
    return tokens[0][0], " ".join(tokens[1:])


def run(guild_id, csv_path, apply):
    db = SessionLocal()
    try:
        league = db.query(MynbaLeague).filter(MynbaLeague.guild_id == str(guild_id)).one()
        players = db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).all()
        by_sig, by_key = {}, {p.name_key: p for p in players}
        for p in players:
            by_sig.setdefault(signature(p.name), []).append(p)
        ref = {}
        for r in db.query(Nba2kPlayer):
            ref.setdefault(signature(r.name), []).append(r)

        with open(csv_path, encoding="utf-8-sig") as fh:
            rows = [r for r in csv.DictReader(fh) if (r.get("Player Name") or "").strip()]

        keep, create, problems = {}, [], []
        for r in rows:
            raw, pos = r["Player Name"].strip(), (r.get("Position") or "").strip().upper() or None
            if raw in SKIP:
                continue
            if (raw, pos) in PICKS:
                player = by_key.get(svc.player_key(PICKS[(raw, pos)]))
                if not player or player.team_id:
                    problems.append(f"{raw} ({pos}): {PICKS[(raw, pos)]} isn't a free agent.")
                    continue
            else:
                free = [p for p in by_sig.get(signature(raw), []) if p.team_id is None]
                if len(free) > 1:
                    problems.append(f"{raw} ({pos}) fits {[p.name for p in free]}. Add it to PICKS.")
                    continue
                if any(p.team_id for p in by_sig.get(signature(raw), [])) and not free:
                    problems.append(f"{raw} ({pos}) only matches a rostered player. Add it to SKIP.")
                    continue
                player = free[0] if free else None
            if player:
                if player.id in keep:
                    problems.append(f"{raw} and {keep[player.id][0]} both match {player.name}.")
                keep[player.id] = (raw, pos, player)
            else:
                known = ref.get(signature(raw), [])
                create.append((raw, pos, known[0] if len(known) == 1 else None))

        drop = [p for p in players if p.team_id is None and p.id not in keep]
        print(f"League: {league.name}")
        print(f"FA list: {len(rows)} lines -> {len(keep)} existing free agents, {len(create)} new, "
              f"{len(SKIP)} skipped")
        print(f"New players: {[(c[2].name if c[2] else c[0]) + ' ' + str(c[1]) for c in create]}")
        print(f"Free agents to remove (not on the list): {len(drop)}")
        print(f"Free agency after: {len(keep) + len(create)}")
        for p in problems:
            print("  PROBLEM:", p)
        if problems:
            print("\nStopping: fix the problems above first.")
            return 1
        if not apply:
            print("\nDry run only. Re-run with --apply to make these changes.")
            return 0

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups",
                            f"free-agents-{league.guild_id}-{stamp}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([{c.name: (getattr(p, c.name).isoformat() if isinstance(getattr(p, c.name), datetime)
                                 else getattr(p, c.name)) for c in p.__table__.columns}
                       for p in players if p.team_id is None], fh, ensure_ascii=False, indent=1)
        print("Backup:", path)

        for raw, pos, player in keep.values():
            if pos:
                player.position = pos
                if player.secondary_position == pos:
                    player.secondary_position = None
        for p in drop:
            db.delete(p)
        db.flush()
        for raw, pos, known in create:
            name = known.name if known else raw
            db.add(MynbaPlayer(
                league_id=league.id, name=name, name_key=svc.player_key(name), team_id=None,
                position=pos, ovr=getattr(known, "overall", None) if known else None,
            ))
        db.add(MynbaTransaction(
            league_id=league.id, kind=TXN_IMPORT, player_name="(free agent list)",
            note=f"Free agency set from {os.path.basename(csv_path)}: {len(keep) + len(create)} players "
                 f"({len(create)} new, {len(drop)} removed)",
        ))
        db.commit()
        print("Done.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--guild", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    sys.exit(run(a.guild, a.csv, a.apply))
