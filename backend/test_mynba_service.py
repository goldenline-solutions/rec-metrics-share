"""
End-to-end check of the MyNBA trade lifecycle against the real database.

Creates a throwaway league under a test guild id, runs a trade all the way
through, and deletes everything it made. Run it directly:

    python test_mynba_service.py
"""
import sys

from db import SessionLocal
import mynba_service as svc
from mynba_models import (
    MynbaLeague, MynbaCommissioner, MynbaTeam, MynbaPlayer,
    MynbaTrade, MynbaTradeAsset, MynbaTradeVote, MynbaTransaction,
    TRADE_PENDING_GM, TRADE_PENDING_COMMISSIONER, TRADE_APPROVED_WINDOW,
    TRADE_EXECUTED, TRADE_VOIDED, TRADE_OVERTURNED,
)

TEST_GUILD = "test-guild-mynba-selfcheck"

CSV = """Name,Team,Position,OVR,Age
Michael Jordan,Bulls,SG,99,30
Scottie Pippen,Bulls,SF,92,28
Dennis Rodman,Bulls,PF,85,33
Patrick Ewing,Knicks,C,94,31
John Starks,Knicks,SG,80,28
Charles Oakley,Knicks,PF,82,30
Kevin Garnett,Timberwolves,PF,96,27
Latrell Sprewell,Timberwolves,SG,84,33
Sam Cassell,Timberwolves,PG,86,34
Allen Iverson,,PG,97,29
Ben Wallace,,C,88,30
"""

passes, failures = [], []


def swap(proposer, counterparty, send, receive):
    """Two-team trade expressed as legs, which is what create_trade takes now."""
    legs = []
    if send:
        legs.append({"from": proposer, "to": counterparty, "players": send})
    if receive:
        legs.append({"from": counterparty, "to": proposer, "players": receive})
    return legs


def check(label, condition, detail=""):
    if condition:
        passes.append(label)
        print(f"  PASS  {label}")
    else:
        failures.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))


def cleanup(db):
    league = svc.get_league(db, TEST_GUILD)
    if not league:
        return
    trade_ids = [t.id for t in db.query(MynbaTrade).filter(MynbaTrade.league_id == league.id).all()]
    if trade_ids:
        db.query(MynbaTradeVote).filter(MynbaTradeVote.trade_id.in_(trade_ids)).delete(synchronize_session=False)
        db.query(MynbaTradeAsset).filter(MynbaTradeAsset.trade_id.in_(trade_ids)).delete(synchronize_session=False)
    db.query(MynbaTransaction).filter(MynbaTransaction.league_id == league.id).delete(synchronize_session=False)
    db.query(MynbaTrade).filter(MynbaTrade.league_id == league.id).delete(synchronize_session=False)
    db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).delete(synchronize_session=False)
    db.query(MynbaCommissioner).filter(MynbaCommissioner.league_id == league.id).delete(synchronize_session=False)
    db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id).delete(synchronize_session=False)
    db.query(MynbaLeague).filter(MynbaLeague.id == league.id).delete(synchronize_session=False)
    db.commit()


def run():
    db = SessionLocal()
    try:
        cleanup(db)

        print("\nSetup")
        league = svc.create_league(db, TEST_GUILD, name="Selfcheck League")
        league.gameplan_lock_override = False  # trade checks run on the real clock; keep the weekly lock out
        db.commit()
        teams = db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id).all()
        check("30 teams seeded", len(teams) == 30, f"got {len(teams)}")
        check("roster target defaults to 8", league.roster_size == 8)
        check("roster size is not enforced by default", league.enforce_roster_size is False)

        summary = svc.import_roster_csv(db, league, CSV, actor_discord_id="commish-1")
        db.commit()
        check("imported 11 players", summary["created"] == 11, str(summary))
        check("import reported no problems", not summary["problems"], str(summary["problems"]))

        bulls = svc.resolve_team(db, league.id, "Bulls")
        knicks = svc.resolve_team(db, league.id, "NYK")
        wolves = svc.resolve_team(db, league.id, "wolves")
        check("team by nickname / abbrev / alias", all([bulls, knicks, wolves]))
        fa = db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id,
                                          MynbaPlayer.team_id.is_(None)).count()
        check("2 free agents (blank team column)", fa == 2, f"got {fa}")
        check("roster_count(None) counts the free-agent pool",
              svc.roster_count(db, league.id, None) == 2)
        check("Bulls have 3", svc.roster_count(db, league.id, bulls.id) == 3)

        bulls.gm_discord_id, bulls.is_cpu = "gm-bulls", False
        knicks.gm_discord_id, knicks.is_cpu = "gm-knicks", False
        wolves.gm_discord_id, wolves.is_cpu = "gm-wolves", False
        db.add(MynbaCommissioner(league_id=league.id, discord_id="commish-1"))
        db.add(MynbaCommissioner(league_id=league.id, discord_id="commish-2"))
        db.commit()

        print("\nName resolution")
        jordan = svc.resolve_player(db, league.id, "Jordan")
        check("surname resolves to one player", jordan.name == "Michael Jordan", jordan.name)
        try:
            svc.resolve_player(db, league.id, "zzzz")
            check("unknown name raises", False)
        except svc.LeagueError:
            check("unknown name raises", True)

        print("\nHappy path: propose, accept, approve, execute")
        pippen = svc.resolve_player(db, league.id, "Pippen")
        ewing = svc.resolve_player(db, league.id, "Ewing")
        trade, warnings = svc.create_trade(db, league, bulls, swap(bulls, knicks, [pippen], [ewing]),
                                           actor_discord_id="gm-bulls")
        db.commit()
        check("trade waits on the other GM", trade.status == TRADE_PENDING_GM, trade.status)
        check("undersized rosters warn but don't block", len(warnings) == 2, str(warnings))
        check("trade got a readable ref", trade.ref == "T-0001", trade.ref)

        svc.accept_trade(db, trade, "gm-knicks", team=knicks)
        db.commit()
        check("accept moves it to the commissioner", trade.status == TRADE_PENDING_COMMISSIONER)

        try:
            svc.approve_trade(db, trade, league, "gm-bulls")
            check("proposer cannot approve their own trade", False)
        except svc.LeagueError as err:
            check("proposer cannot approve their own trade", err.code == "self_approval", err.code)

        svc.approve_trade(db, trade, league, "commish-1")
        db.commit()
        check("approval opens the protest window", trade.status == TRADE_APPROVED_WINDOW, trade.status)
        check("nobody has moved yet", pippen.team_id == bulls.id and ewing.team_id == knicks.id)

        svc.execute_trade(db, trade, "commish-1")
        db.commit()
        db.refresh(pippen); db.refresh(ewing)
        check("trade executed", trade.status == TRADE_EXECUTED, trade.status)
        check("Pippen is a Knick", pippen.team_id == knicks.id)
        check("Ewing is a Bull", ewing.team_id == bulls.id)

        txns = db.query(MynbaTransaction).filter(MynbaTransaction.trade_id == trade.id).all()
        check("both moves logged", len(txns) == 2, f"got {len(txns)}")
        check("log names the teams", all(t.from_team_name and t.to_team_name for t in txns))

        print("\nGuards")
        try:
            svc.create_trade(db, league, bulls, swap(bulls, knicks, [pippen], []), actor_discord_id="gm-bulls")
            check("cannot trade a player you don't own", False)
        except svc.LeagueError as err:
            check("cannot trade a player you don't own", err.code == "wrong_team", err.code)

        rodman = svc.resolve_player(db, league.id, "Rodman")
        starks = svc.resolve_player(db, league.id, "Starks")
        t2, _ = svc.create_trade(db, league, bulls, swap(bulls, knicks, [rodman], [starks]), actor_discord_id="gm-bulls")
        db.commit()
        try:
            svc.create_trade(db, league, bulls, swap(bulls, knicks, [rodman], []), actor_discord_id="gm-bulls")
            check("a player can't be in two open trades", False)
        except svc.LeagueError as err:
            check("a player can't be in two open trades", err.code == "already_pending", err.code)

        print("\nStale package voids instead of half-applying")
        svc.accept_trade(db, t2, "gm-knicks", team=knicks)
        svc.approve_trade(db, t2, league, "commish-1")
        db.commit()
        # Somebody moves Rodman out from under the pending trade.
        svc.admin_move_player(db, league, rodman, wolves, "commish-2", "testing staleness")
        db.commit()
        svc.execute_trade(db, t2, "commish-1")
        db.commit()
        db.refresh(starks)
        check("stale trade voided", t2.status == TRADE_VOIDED, t2.status)
        check("void explains which player moved", "Rodman" in (t2.resolution_reason or ""), t2.resolution_reason)
        check("the other player did NOT move", starks.team_id == knicks.id)

        print("\nProtest and league vote")
        oakley = svc.resolve_player(db, league.id, "Oakley")
        garnett = svc.resolve_player(db, league.id, "Garnett")
        t3, _ = svc.create_trade(db, league, knicks, swap(knicks, wolves, [oakley], [garnett]), actor_discord_id="gm-knicks")
        svc.accept_trade(db, t3, "gm-wolves", team=wolves)
        svc.approve_trade(db, t3, league, "commish-1")
        db.commit()
        svc.protest_trade(db, t3, bulls, "gm-bulls", "lopsided")
        db.commit()
        check("protest pauses execution", t3.execute_after is None and t3.status == "PROTESTED", t3.status)
        tally = svc.vote_tally(db, t3)
        check("protest counts as an overturn vote", tally["overturn"] == 1, str(tally))
        svc.resolve_protest(db, t3, "commish-1")
        db.commit()
        db.refresh(oakley)
        check("overturned trade doesn't move anyone", t3.status == TRADE_OVERTURNED and oakley.team_id == knicks.id,
              f"{t3.status} / {oakley.team_id}")

        print("\nFree agency")
        iverson = svc.resolve_player(db, league.id, "Iverson")
        svc.sign_free_agent(db, league, iverson, bulls, "gm-bulls")
        db.commit()
        db.refresh(iverson)
        check("free agent signed", iverson.team_id == bulls.id)
        try:
            svc.sign_free_agent(db, league, iverson, knicks, "gm-knicks")
            check("cannot sign a rostered player", False)
        except svc.LeagueError as err:
            check("cannot sign a rostered player", err.code == "not_fa", err.code)

        print("\nTrade lock")
        league.trades_locked = True
        db.commit()
        try:
            svc.create_trade(db, league, bulls, swap(bulls, knicks, [ewing], []), actor_discord_id="gm-bulls")
            check("lock blocks new trades", False)
        except svc.LeagueError as err:
            check("lock blocks new trades", err.code == "locked", err.code)

        print("\nHard roster enforcement (opt-in)")
        league.trades_locked = False
        league.enforce_roster_size = True
        db.commit()
        try:
            svc.create_trade(db, league, bulls, swap(bulls, knicks, [ewing], []), actor_discord_id="gm-bulls")
            check("enforcement blocks an unbalanced trade", False)
        except svc.LeagueError as err:
            check("enforcement blocks an unbalanced trade", err.code == "roster_size", err.code)

    finally:
        cleanup(db)
        db.close()

    print(f"\n{len(passes)} passed, {len(failures)} failed")
    for f in failures:
        print(f"  FAILED: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
