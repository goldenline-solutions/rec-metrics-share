"""
Seeding a league from the synced 2K reference data.

Uses whatever `nba2k_players` already holds (run the ratings sync first), builds
a throwaway league, seeds it, and checks every player landed somewhere sensible.
Deletes the league afterwards; the reference table is left alone.

    python test_nba2k_seed.py
"""
import sys

from db import SessionLocal
from name_utils import normalize_name
import mynba_service as svc
import nba2k_service as ratings
from mynba_models import (
    MynbaLeague, MynbaCommissioner, MynbaTeam, MynbaPlayer,
    MynbaTrade, MynbaTradeAsset, MynbaTradeVote, MynbaTransaction,
)
from nba2k_models import Nba2kPlayer

GUILD = "test-guild-nba2k-seed"

passes, failures = [], []


def check(label, condition, detail=""):
    if condition:
        passes.append(label)
        print(f"  PASS  {label}")
    else:
        failures.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))


def cleanup(db):
    league = svc.get_league(db, GUILD)
    if not league:
        return
    ids = [t.id for t in db.query(MynbaTrade).filter(MynbaTrade.league_id == league.id).all()]
    if ids:
        db.query(MynbaTradeVote).filter(MynbaTradeVote.trade_id.in_(ids)).delete(synchronize_session=False)
        db.query(MynbaTradeAsset).filter(MynbaTradeAsset.trade_id.in_(ids)).delete(synchronize_session=False)
    for model in (MynbaTransaction, MynbaTrade, MynbaPlayer, MynbaCommissioner, MynbaTeam):
        db.query(model).filter(model.league_id == league.id).delete(synchronize_session=False)
    db.query(MynbaLeague).filter(MynbaLeague.id == league.id).delete(synchronize_session=False)
    db.commit()


def run():
    db = SessionLocal()
    try:
        reference = db.query(Nba2kPlayer).filter(Nba2kPlayer.team_type == "curr").all()
        if not reference:
            print("No 2K reference data. Run the ratings sync first.")
            return 1

        cleanup(db)
        league = svc.create_league(db, GUILD, name="Seed Test League")
        db.commit()

        print(f"\nSeeding from {len(reference)} synced players")
        summary = ratings.seed_league_rosters(db, league, era="curr", actor_discord_id="seed-test")
        db.commit()

        check("every reference player landed in the league",
              summary["created"] == len(reference),
              f"{summary['created']} of {len(reference)}")
        check("no team name failed to map", not summary["unmatched_teams"],
              str(summary["unmatched_teams"]))

        players = db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).all()
        rostered = [p for p in players if p.team_id]
        free = [p for p in players if not p.team_id]
        check("roster + free agents accounts for everyone",
              len(rostered) + len(free) == len(players))
        check("free agents exist", len(free) > 0, f"{len(free)} free agents")

        fa_expected = sum(
            1 for r in reference if normalize_name(r.team or "") in ratings.FREE_AGENT_LABELS
        )
        check("free agent count matches what 2K says",
              len(free) == fa_expected, f"got {len(free)}, 2K says {fa_expected}")

        teams = db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id).all()
        empty = [t.name for t in teams if svc.roster_count(db, league.id, t.id) == 0]
        check("all 30 teams got players", not empty, f"empty: {', '.join(empty)}")

        clippers = next(t for t in teams if t.abbrev == "LAC")
        clipper_count = svc.roster_count(db, league.id, clippers.id)
        check("Clippers mapped despite the name difference",
              clipper_count > 0, f"{clipper_count} players")

        with_ovr = [p for p in players if p.ovr]
        check("overalls carried across", len(with_ovr) > len(players) * 0.9,
              f"{len(with_ovr)} of {len(players)}")
        with_pos = [p for p in players if p.position]
        check("positions carried across", len(with_pos) > len(players) * 0.9,
              f"{len(with_pos)} of {len(players)}")

        print("\nA ratings sync must not move anybody")
        sample = rostered[0]
        before_team = sample.team_id
        ratings.sync_players(db, era="curr", triggered_by="seed-test")
        db.commit()
        db.refresh(sample)
        check("player stayed on their league team after a re-sync",
              sample.team_id == before_team, f"{sample.name} moved")
        check("league player count unchanged after a re-sync",
              db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).count() == len(players))

        print("\nRe-seeding is safe")
        again = ratings.seed_league_rosters(db, league, era="curr", actor_discord_id="seed-test")
        db.commit()
        check("second seed creates nobody new", again["created"] == 0, str(again["created"]))
        check("second seed recognises everyone", again["already_in_league"] == len(reference),
              f"{again['already_in_league']} of {len(reference)}")

        top = max(players, key=lambda p: p.ovr or 0)
        print(f"\n  (top rated seeded player: {top.name}, {top.ovr} OVR)")

    finally:
        cleanup(db)
        db.close()

    print(f"\n{len(passes)} passed, {len(failures)} failed")
    for f in failures:
        print(f"  FAILED: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
