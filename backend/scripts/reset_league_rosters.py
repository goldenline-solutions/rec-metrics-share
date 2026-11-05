"""
Reset a MyNBA league to a fresh draft from a roster CSV, keeping a free-agent pool.

What it does, in one transaction:
  1. Writes a JSON backup of every league table it touches.
  2. Deletes trades (and their assets/seats/votes), the transaction log,
     gameplans, and the change feed.
  3. Restores 2K display names that an earlier import overwrote, from the
     nba2k reference table.
  4. Deletes duplicate player records created from misspelled names, after
     pointing those names at the real 2K player (NAME_FIXES).
  5. Moves everyone to free agency, clears untouchables, then puts each CSV
     player on their team with the CSV's positions and rating.

Teams, GMs, commissioners, rules and settings are not touched.

    python scripts/reset_league_rosters.py --guild <id> --csv <path>          # dry run
    python scripts/reset_league_rosters.py --guild <id> --csv <path> --apply  # do it
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal  # noqa: E402
import models  # noqa: E402,F401
import mynba_service as svc  # noqa: E402
from mynba_models import (  # noqa: E402
    MynbaLeague, MynbaTeam, MynbaPlayer, MynbaTrade, MynbaTradeAsset, MynbaTradeTeam,
    MynbaTradeVote, MynbaTransaction, MynbaGameplan, MynbaGameplanChange, TXN_IMPORT,
)
from nba2k_models import Nba2kPlayer  # noqa: E402

# CSV spelling -> 2K spelling, for names that don't normalize to the same key.
NAME_FIXES = {
    "Steph Curry": "Stephen Curry",
    "Cam Johnson": "Cameron Johnson",
    "Tauren Prince": "Taurean Prince",
    "Jonathon Kuminga": "Jonathan Kuminga",
    "Donte Divencenzo": "Donte DiVincenzo",
    "Bobby Portis": "Bobby Portis Jr.",
    "Marvin Bagley": "Marvin Bagley III",
    "Jaime Jacquez Jr": "Jaime Jaquez Jr.",
    "Jarett Allen": "Jarrett Allen",
    "Jonas Valanciunas": "Jonas Valančiūnas",
    "Tre Young": "Trae Young",
    "Lu Dort": "Luguentz Dort",
    "Nic Claxton": "Nicolas Claxton",
    "Derek Lively": "Dereck Lively II",
    "Alex Sarr": "Alexandre Sarr",
    "Bryce Sensabaugh": "Brice Sensabaugh",
    "Carl Carrington": "Carlton Carrington",
    "Egor Demin": "Egor Dëmin",
    "Dearron Fox": "De’Aaron Fox",
    "Victor Wembenyama": "Victor Wembanyama",
    "Yanic Konan Niederhauser": "Yanic Konan Niederhäuser",
    "Dillion Brooks": "Dillon Brooks",
    "Tristan Vukevic": "Tristan Vukcevic",
}

# Corrections to the 2026-10-23 draft CSV, confirmed by the commissioner.
OVERRIDES = {
    "Russell Westbrook": {"ovr": "82"},
    "Jalen Williams": {"position": "SG", "secondary": "SF"},
}

COLS = {
    "team": ("Fantasy Draft Team", "Team"),
    "name": ("Player Name", "Name", "Player"),
    "position": ("Primary Position", "Position"),
    "secondary": ("Secondary Position",),
    "ovr": ("NBA 2K27 Rating", "OVR", "Rating"),
    "role": ("Roster Role",),
}


def col(row, field):
    fix = OVERRIDES.get(_raw_name(row), {})
    if field in fix:
        return fix[field]
    return _col(row, field)


def _raw_name(row):
    return _col(row, "name")


def _col(row, field):
    for name in COLS[field]:
        if name in row:
            return (row[name] or "").strip()
    return ""


def row_dict(obj):
    out = {}
    for c in obj.__table__.columns:
        v = getattr(obj, c.name)
        out[c.name] = v.isoformat() if isinstance(v, datetime) else v
    return out


def backup(db, league, path):
    tables = {}
    trade_ids = [t.id for t in db.query(MynbaTrade).filter(MynbaTrade.league_id == league.id)]
    tables["mynba_players"] = db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).all()
    tables["mynba_trades"] = db.query(MynbaTrade).filter(MynbaTrade.league_id == league.id).all()
    tables["mynba_trade_assets"] = db.query(MynbaTradeAsset).filter(MynbaTradeAsset.trade_id.in_(trade_ids)).all()
    tables["mynba_trade_teams"] = db.query(MynbaTradeTeam).filter(MynbaTradeTeam.trade_id.in_(trade_ids)).all()
    tables["mynba_trade_votes"] = db.query(MynbaTradeVote).filter(MynbaTradeVote.trade_id.in_(trade_ids)).all()
    tables["mynba_transactions"] = db.query(MynbaTransaction).filter(MynbaTransaction.league_id == league.id).all()
    tables["mynba_gameplans"] = db.query(MynbaGameplan).filter(MynbaGameplan.league_id == league.id).all()
    tables["mynba_gameplan_changes"] = db.query(MynbaGameplanChange).filter(
        MynbaGameplanChange.league_id == league.id).all()
    data = {name: [row_dict(r) for r in rows] for name, rows in tables.items()}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"league_id": league.id, "guild_id": league.guild_id, "taken_at": datetime.utcnow().isoformat(),
                   "tables": data}, fh, ensure_ascii=False, indent=1)
    return {k: len(v) for k, v in data.items()}


def run(guild_id, csv_path, apply):
    db = SessionLocal()
    try:
        league = db.query(MynbaLeague).filter(MynbaLeague.guild_id == str(guild_id)).one()
        teams = {t.name: t for t in db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id)}
        players = db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).all()
        by_key = {p.name_key: p for p in players}
        ref_names = {r.name_key: r.name for r in db.query(Nba2kPlayer) if r.name_key}

        with open(csv_path, encoding="utf-8-sig") as fh:
            rows = [r for r in csv.DictReader(fh) if col(r, "name")]

        # Resolve every CSV row to a real player before changing anything.
        problems, picks, duplicates = [], [], []
        for r in rows:
            raw = col(r, "name")
            team = teams.get(col(r, "team"))
            if not team:
                problems.append(f'No team called "{col(r, "team")}" ({raw}).')
                continue
            target = NAME_FIXES.get(raw, raw)
            player = by_key.get(svc.player_key(target))
            if not player:
                problems.append(f'No player matches "{raw}".')
                continue
            if target != raw:
                dup = by_key.get(svc.player_key(raw))
                if dup and dup.id != player.id:
                    duplicates.append(dup)
            picks.append((r, player, team))

        seen = {}
        for r, p, _ in picks:
            if p.id in seen:
                problems.append(f'"{col(r, "name")}" and "{seen[p.id]}" are the same player ({p.name}).')
            seen[p.id] = col(r, "name")

        renamed = [(p, ref_names[p.name_key]) for p in players
                   if p.name_key in ref_names and ref_names[p.name_key] != p.name and p not in duplicates]

        counts = {}
        for _, _, team in picks:
            counts[team.name] = counts.get(team.name, 0) + 1
        short = {t: n for t, n in counts.items() if n != (league.roster_size or 8)}

        print(f"League: {league.name}  ({len(players)} players now)")
        print(f"CSV rows: {len(rows)} -> {len(picks)} resolved, {len(problems)} problems")
        print(f"Teams in CSV: {len(counts)}  (not {league.roster_size} players: {short or 'none'})")
        print(f"Typo names mapped to the real 2K player: {len([1 for r, _, _ in picks if col(r, 'name') in NAME_FIXES])}")
        print(f"Duplicate records to delete: {len(duplicates)}  {[d.name for d in duplicates]}")
        print(f"2K display names to restore: {len(renamed)}  e.g. {[(p.name, n) for p, n in renamed[:6]]}")
        print(f"Free agents after import: {len(players) - len(duplicates) - len(picks)}")
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
                            f"league-{league.guild_id}-{stamp}.json")
        print("\nBackup:", path, backup(db, league, path))

        trade_ids = [t.id for t in db.query(MynbaTrade).filter(MynbaTrade.league_id == league.id)]
        if trade_ids:
            for model in (MynbaTradeVote, MynbaTradeAsset, MynbaTradeTeam):
                db.query(model).filter(model.trade_id.in_(trade_ids)).delete(synchronize_session=False)
        for model in (MynbaTransaction, MynbaGameplanChange, MynbaGameplan, MynbaTrade):
            db.query(model).filter(model.league_id == league.id).delete(synchronize_session=False)

        for p, name in renamed:
            p.name = name
        for d in duplicates:
            db.delete(d)
        db.flush()

        db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).update(
            {MynbaPlayer.team_id: None, MynbaPlayer.is_untouchable: False}, synchronize_session=False)

        for r, p, team in picks:
            primary = col(r, "position").upper() or None
            secondary = col(r, "secondary").upper() or None
            p.team_id = team.id
            p.position = primary
            p.secondary_position = secondary if secondary != primary else None
            ovr = svc._to_int(col(r, "ovr"))
            if ovr is not None:
                p.ovr = ovr
            role = col(r, "role")
            p.extra = json.dumps({"Roster Role": role}) if role else None

        db.add(MynbaTransaction(
            league_id=league.id, kind=TXN_IMPORT, player_name="(fantasy draft import)",
            note=f"Rosters reset from {os.path.basename(csv_path)}: {len(picks)} players on {len(counts)} teams",
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
