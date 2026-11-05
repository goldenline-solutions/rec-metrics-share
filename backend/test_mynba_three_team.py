"""
Three-team trades.

The hard parts are not the player moves -- `mynba_trade_assets` always stored
from/to per player. They are: every team having to accept before a commissioner
sees it, one team's decline killing the whole thing, and a third team not being
allowed to vote on a deal it is part of.

    python test_mynba_three_team.py
"""
import sys

from db import SessionLocal
import mynba_service as svc
from mynba_models import (
    MynbaLeague, MynbaCommissioner, MynbaTeam, MynbaPlayer,
    MynbaTrade, MynbaTradeAsset, MynbaTradeVote, MynbaTransaction, MynbaTradeTeam,
    TRADE_PENDING_GM, TRADE_PENDING_COMMISSIONER, TRADE_EXECUTED,
    TRADE_DECLINED, TRADE_OVERTURNED,
)

GUILD = "test-guild-three-team"

CSV = """Name,Team,Position,OVR
Alpha One,Bulls,PG,90
Alpha Two,Bulls,SG,80
Alpha Three,Bulls,SF,78
Bravo One,Knicks,PG,88
Bravo Two,Knicks,C,82
Bravo Three,Knicks,PF,75
Charlie One,Lakers,SF,91
Charlie Two,Lakers,C,84
Charlie Three,Lakers,SG,77
Delta One,Heat,PG,86
Echo One,Suns,SG,85
"""

passes, failures = [], []


def check(label, condition, detail=""):
    if condition:
        passes.append(label)
        print(f"  PASS  {label}")
    else:
        failures.append(f"{label}{(' -- ' + detail) if detail else ''}")
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))


def cleanup(db):
    league = svc.get_league(db, GUILD)
    if not league:
        return
    ids = [t.id for t in db.query(MynbaTrade).filter(MynbaTrade.league_id == league.id).all()]
    if ids:
        for model in (MynbaTradeVote, MynbaTradeAsset, MynbaTradeTeam):
            db.query(model).filter(model.trade_id.in_(ids)).delete(synchronize_session=False)
    for model in (MynbaTransaction, MynbaTrade, MynbaPlayer, MynbaCommissioner, MynbaTeam):
        db.query(model).filter(model.league_id == league.id).delete(synchronize_session=False)
    db.query(MynbaLeague).filter(MynbaLeague.id == league.id).delete(synchronize_session=False)
    db.commit()


def build(db):
    league = svc.create_league(db, GUILD, name="Three Team League")
    league.gameplan_lock_override = False  # trade checks run on the real clock; keep the weekly lock out
    svc.import_roster_csv(db, league, CSV)
    teams = {}
    for name, gm in [("Bulls", "gm-bulls"), ("Knicks", "gm-knicks"), ("Lakers", "gm-lakers"),
                     ("Heat", "gm-heat"), ("Suns", "gm-suns")]:
        t = svc.resolve_team(db, league.id, name)
        t.gm_discord_id, t.is_cpu, t.gm_display_name = gm, False, gm
        teams[name] = t
    db.add(MynbaCommissioner(league_id=league.id, discord_id="commish-1"))
    db.commit()
    return league, teams


def three_legs(db, league, teams):
    """Classic cycle: Bulls -> Knicks -> Lakers -> Bulls."""
    return [
        {"from": teams["Bulls"], "to": teams["Knicks"],
         "players": [svc.resolve_player(db, league.id, "Alpha One")]},
        {"from": teams["Knicks"], "to": teams["Lakers"],
         "players": [svc.resolve_player(db, league.id, "Bravo One")]},
        {"from": teams["Lakers"], "to": teams["Bulls"],
         "players": [svc.resolve_player(db, league.id, "Charlie One")]},
    ]


def run():
    db = SessionLocal()
    try:
        cleanup(db)
        league, teams = build(db)

        print("\nA three-team cycle needs all three to sign off")
        trade, warnings = svc.create_trade(db, league, teams["Bulls"],
                                           three_legs(db, league, teams),
                                           actor_discord_id="gm-bulls")
        db.commit()
        check("recorded as a 3-team trade", trade.team_count == 3, str(trade.team_count))
        check("three seats created", len(svc.trade_team_rows(db, trade)) == 3)
        check("waiting on a GM", trade.status == TRADE_PENDING_GM, trade.status)
        awaiting = {t.name for t in
                    [db.query(MynbaTeam).filter(MynbaTeam.id == s.team_id).first()
                     for s in svc.teams_awaiting(db, trade)]}
        check("proposer counts as accepted", "Bulls" not in awaiting, str(awaiting))
        check("both partners still owe an answer", awaiting == {"Knicks", "Lakers"}, str(awaiting))

        svc.accept_trade(db, trade, "gm-knicks", team=teams["Knicks"])
        db.commit()
        check("one acceptance is not enough", trade.status == TRADE_PENDING_GM, trade.status)
        check("still waiting on the Lakers",
              [s.team_id for s in svc.teams_awaiting(db, trade)] == [teams["Lakers"].id])

        svc.accept_trade(db, trade, "gm-lakers", team=teams["Lakers"])
        db.commit()
        check("last acceptance sends it to the commissioner",
              trade.status == TRADE_PENDING_COMMISSIONER, trade.status)

        print("\nExecution moves all three players")
        svc.approve_trade(db, trade, league, "commish-1", skip_window=True)
        db.commit()
        a1 = svc.resolve_player(db, league.id, "Alpha One")
        b1 = svc.resolve_player(db, league.id, "Bravo One")
        c1 = svc.resolve_player(db, league.id, "Charlie One")
        check("executed", trade.status == TRADE_EXECUTED, trade.status)
        check("Alpha One -> Knicks", a1.team_id == teams["Knicks"].id)
        check("Bravo One -> Lakers", b1.team_id == teams["Lakers"].id)
        check("Charlie One -> Bulls", c1.team_id == teams["Bulls"].id)
        logged = db.query(MynbaTransaction).filter(MynbaTransaction.trade_id == trade.id).count()
        check("three movements logged", logged == 3, str(logged))

        print("\nAny one team can kill it")
        t2, _ = svc.create_trade(db, league, teams["Bulls"], [
            {"from": teams["Bulls"], "to": teams["Knicks"],
             "players": [svc.resolve_player(db, league.id, "Alpha Two")]},
            {"from": teams["Lakers"], "to": teams["Bulls"],
             "players": [svc.resolve_player(db, league.id, "Charlie Two")]},
        ], actor_discord_id="gm-bulls")
        db.commit()
        svc.accept_trade(db, t2, "gm-knicks", team=teams["Knicks"])
        db.commit()
        svc.decline_trade(db, t2, "gm-lakers", team=teams["Lakers"])
        db.commit()
        check("one decline kills the trade", t2.status == TRADE_DECLINED, t2.status)
        check("decline names the team", "Lakers" in (t2.resolution_reason or ""), str(t2.resolution_reason))
        check("nobody moved", svc.resolve_player(db, league.id, "Alpha Two").team_id == teams["Bulls"].id)

        print("\nA CPU team in the middle doesn't block anything")
        spurs = svc.resolve_team(db, league.id, "Spurs")
        check("Spurs are CPU", spurs.is_cpu is True)
        t3, _ = svc.create_trade(db, league, teams["Bulls"], [
            {"from": teams["Bulls"], "to": spurs,
             "players": [svc.resolve_player(db, league.id, "Alpha Three")]},
            {"from": teams["Knicks"], "to": teams["Bulls"],
             "players": [svc.resolve_player(db, league.id, "Bravo Two")]},
        ], actor_discord_id="gm-bulls")
        db.commit()
        awaiting3 = [s.team_id for s in svc.teams_awaiting(db, t3)]
        check("CPU team auto-accepts", spurs.id not in awaiting3)
        check("only the human partner is asked", awaiting3 == [teams["Knicks"].id])

        print("\nEvery participating team is barred from voting")
        t4, _ = svc.create_trade(db, league, teams["Bulls"], three_legs_alt(db, league, teams),
                                 actor_discord_id="gm-bulls")
        db.commit()
        svc.accept_trade(db, t4, "gm-knicks", team=teams["Knicks"])
        svc.accept_trade(db, t4, "gm-lakers", team=teams["Lakers"])
        svc.approve_trade(db, t4, league, "commish-1")
        db.commit()
        for name in ("Bulls", "Knicks", "Lakers"):
            try:
                svc.protest_trade(db, t4, teams[name], f"gm-{name.lower()}")
                check(f"{name} cannot protest their own trade", False)
            except svc.LeagueError as err:
                check(f"{name} cannot protest their own trade", err.code == "party_to_trade", err.code)

        svc.protest_trade(db, t4, teams["Heat"], "gm-heat", "too lopsided")
        db.commit()
        tally = svc.vote_tally(db, t4)
        check("three parties excluded from the electorate",
              tally["eligible"] == 2, f"eligible={tally['eligible']} (Heat + Suns)")

        svc.cast_vote(db, t4, teams["Suns"], uphold=False, actor_discord_id="gm-suns")
        db.commit()
        svc.resolve_protest(db, t4, "commish-1")
        db.commit()
        check("league vote overturns the 3-team deal", t4.status == TRADE_OVERTURNED, t4.status)

        print("\nGuards")
        try:
            svc.create_trade(db, league, teams["Bulls"], [
                {"from": teams["Bulls"], "to": teams["Knicks"],
                 "players": [svc.resolve_player(db, league.id, "Delta One")]},
            ], actor_discord_id="gm-bulls")
            check("still catches a player on the wrong team", False)
        except svc.LeagueError as err:
            check("still catches a player on the wrong team", err.code == "wrong_team", err.code)

        try:
            svc.create_trade(db, league, teams["Bulls"], [
                {"from": teams["Bulls"], "to": teams["Knicks"],
                 "players": [svc.resolve_player(db, league.id, "Alpha Two")]},
                {"from": teams["Knicks"], "to": teams["Lakers"],
                 "players": [svc.resolve_player(db, league.id, "Bravo Three")]},
                {"from": teams["Lakers"], "to": teams["Heat"],
                 "players": [svc.resolve_player(db, league.id, "Charlie Three")]},
                {"from": teams["Heat"], "to": teams["Suns"],
                 "players": [svc.resolve_player(db, league.id, "Delta One")]},
            ], actor_discord_id="gm-bulls")
            check("blocks a fourth team", False)
        except svc.LeagueError as err:
            check("blocks a fourth team", err.code == "too_many_teams", err.code)

        print("\nSerializer describes each team's side")
        payload = svc.trade_json(db, t4)
        check("payload reports 3 teams", payload["team_count"] == 3, str(payload["team_count"]))
        check("movement covers every team", len(payload["movement"]) == 3, str(len(payload["movement"])))
        first = payload["movement"][0]
        check("movement names who each player goes to",
              bool(first["sends"] and first["sends"][0]["team"]), str(first))

    finally:
        cleanup(db)
        db.close()

    print(f"\n{len(passes)} passed, {len(failures)} failed")
    for f in failures:
        print(f"  FAILED: {f}")
    return 1 if failures else 0


def three_legs_alt(db, league, teams):
    """A second cycle using players who haven't moved yet."""
    return [
        {"from": teams["Bulls"], "to": teams["Knicks"],
         "players": [svc.resolve_player(db, league.id, "Charlie One")]},
        {"from": teams["Knicks"], "to": teams["Lakers"],
         "players": [svc.resolve_player(db, league.id, "Alpha One")]},
        {"from": teams["Lakers"], "to": teams["Bulls"],
         "players": [svc.resolve_player(db, league.id, "Bravo One")]},
    ]


if __name__ == "__main__":
    sys.exit(run())
