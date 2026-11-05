"""
Check box-score games: validation, duplicates, standings, stats and awards.

Runs against a throwaway in-memory SQLite database and never calls OpenAI.
Run it directly:

    python test_mynba_games.py
"""
import sys
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base
import models  # noqa: F401  — registers users etc. for the foreign keys
import mynba_models  # noqa: F401
import mynba_service as svc
import mynba_games as games
from mynba_models import MynbaGame, MynbaGameLine, MynbaPlayer
from mynba_service import LeagueError

passes, failures = [], []


def check(label, condition, detail=""):
    if condition:
        passes.append(label)
        print(f"  PASS  {label}")
    else:
        failures.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))


def raises(label, code, fn):
    try:
        fn()
    except LeagueError as err:
        check(label, err.code == code, f"got code {err.code}: {err.message}")
        return
    check(label, False, "no error raised")


CSV = """Name,Team,Position,OVR
Kentavious Caldwell-Pope,Warriors,SG,78
Draymond Green,Warriors,PF,80
C.J. McCollum,Warriors,SG,81
Kevin Durant,Warriors,PF,92
Evan Mobley,Warriors,C,88
Paul George,Celtics,SF,85
Josh Giddey,Celtics,PG,82
Chet Holmgren,Celtics,C,86
Jalen Green,Celtics,SG,80
Josh Green,,SF,75
"""

COMMISH = SimpleNamespace(discord_id="c-1", display_name="Commish")


def line(name, pid=None, minutes=40, fgm=0, fga=0, tpm=0, tpa=0, ftm=0, fta=0, reb=0, oreb=0, **kw):
    out = dict(player_name=name, player_id=pid, minutes=minutes, fgm=fgm, fga=fga, tpm=tpm, tpa=tpa,
               ftm=ftm, fta=fta, reb=reb, oreb=oreb, pts=2 * fgm + tpm + ftm,
               ast=0, stl=0, blk=0, tov=0, fouls=0)
    out.update(kw)
    return out


def run():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    league = svc.create_league(db, "g-games")
    svc.import_roster_csv(db, league, CSV)
    db.commit()
    gsw = svc.resolve_team(db, league.id, "Warriors")
    bos = svc.resolve_team(db, league.id, "Celtics")
    lal = svc.resolve_team(db, league.id, "Lakers")
    p = {pl.name: pl for pl in db.query(MynbaPlayer)}

    print("\nName matching")
    m = games.PlayerMatcher(db, league)
    check("hyphenated surname", m.match("K. Caldwell-Pope", gsw.id) is p["Kentavious Caldwell-Pope"])
    check("dotted initials", m.match("C.J. McCollum", gsw.id) is p["C.J. McCollum"])
    check("same signature, own roster wins", m.match("J. Green", bos.id) is p["Jalen Green"])
    check("same signature, other team stays unlinked", m.match("J. Green", lal.id) is None)
    check("unique league-wide match (free agent)", m.match("J. Giddey", gsw.id) is p["Josh Giddey"])
    check("unknown name unlinked", m.match("K. Peat", gsw.id) is None)

    print("\nDefault sim date")
    # Thu Oct 29 2026, noon ET -> previous Saturday Oct 24; Sat Oct 31 -> same day.
    check("Thursday -> last Saturday", games.default_played_on(league, datetime(2026, 10, 29, 16)).isoformat() == "2026-10-24")
    check("Saturday -> today", games.default_played_on(league, datetime(2026, 10, 31, 16)).isoformat() == "2026-10-31")

    def body(away_score=50, home_score=40, **over):
        b = {
            "played_on": "2026-10-24",
            "away": {"team_id": gsw.id, "score": away_score, "quarters": [20, 10, 10, 10], "lines": [
                line("K. Durant", p["Kevin Durant"].id, minutes=40, fgm=10, fga=20, tpm=2, tpa=5, ftm=8, fta=8, reb=8, oreb=2, ast=5, stl=1, blk=1),
                line("E. Mobley", p["Evan Mobley"].id, minutes=40, fgm=10, fga=15, reb=12, oreb=4, stl=2, blk=4),
                line("K. Peat", None, minutes=10, fgm=0, fga=2),
            ]},
            "home": {"team_id": bos.id, "score": home_score, "quarters": [10, 10, 10, 10], "lines": [
                line("P. George", p["Paul George"].id, minutes=38, fgm=10, fga=22, tpm=4, tpa=10, ftm=6, fta=6, reb=5),
                line("C. Holmgren", p["Chet Holmgren"].id, minutes=36, fgm=7, fga=12, reb=10, oreb=1, blk=5),
            ]},
        }
        b.update(over)
        return b

    print("\nValidation")
    raises("missing date", "bad_game", lambda: games.clean_game(db, league, body(played_on="")))
    raises("same team twice", "bad_game", lambda: games.clean_game(db, league, body(home=dict(body()["home"], team_id=gsw.id))))
    raises("tie", "bad_game", lambda: games.clean_game(db, league, body(away_score=40)))
    bad = body()
    bad["away"]["lines"][0]["fgm"] = 30
    raises("made > attempted", "bad_game", lambda: games.clean_game(db, league, bad))
    bad = body()
    bad["away"]["lines"][0]["tpm"] = 12
    bad["away"]["lines"][0]["tpa"] = 12
    raises("3PT more than FG", "bad_game", lambda: games.clean_game(db, league, bad))
    bad = body()
    bad["home"]["lines"].append(line("K. Durant", p["Kevin Durant"].id))
    raises("same player on both teams", "bad_game", lambda: games.clean_game(db, league, bad))
    bad = body()
    bad["away"]["lines"][1]["player_id"] = "nope"
    raises("unknown player id", "bad_game", lambda: games.clean_game(db, league, bad))

    print("\nSoft checks")
    warn = games.check_game({"away": {"team_name": "Warriors", "score": 50, "quarters": [20, 10, 10, 10],
                                      "lines": body()["away"]["lines"]},
                             "home": {"team_name": "Celtics", "score": 40, "quarters": [10, 10, 10, 10], "lines": None}})
    check("unlinked player flagged", any("K. Peat" in w for w in warn), str(warn))
    check("missing box flagged", any("Celtics: no box score" in w for w in warn), str(warn))
    check("points that match the score aren't flagged", not any("player points" in w for w in warn), str(warn))
    check("short minutes flagged", any("minutes add up to 90" in w for w in warn), str(warn))

    print("\nSaving")
    g1 = games.save_game(db, league, body(), COMMISH)
    db.commit()
    check("game saved with 5 lines", len(g1.lines) == 5)
    check("unlinked line kept", any(l.player_id is None and l.player_name == "K. Peat" for l in g1.lines))
    raises("exact duplicate refused", "duplicate_game", lambda: games.save_game(db, league, body(), COMMISH))
    flipped = body()
    flipped["away"], flipped["home"] = flipped["home"], flipped["away"]
    flipped["away"]["score"], flipped["home"]["score"] = 40, 50
    raises("duplicate with sides swapped refused", "duplicate_game", lambda: games.save_game(db, league, flipped, COMMISH))
    db.rollback()
    g2 = games.save_game(db, league, body(away_score=30, home_score=40, played_on="2026-10-31"), COMMISH)
    g3 = games.save_game(db, league, body(away_score=60, home_score=40, played_on="2026-10-31"), COMMISH)
    db.commit()
    check("same matchup, different score saves", db.query(MynbaGame).count() == 3)

    edited = games.save_game(db, league, body(away_score=61, home_score=40, played_on="2026-10-31"), COMMISH, game=g3)
    db.commit()
    check("edit replaces lines, keeps row", edited.id == g3.id and edited.away_score == 61
          and db.query(MynbaGameLine).filter(MynbaGameLine.game_id == g3.id).count() == 5)

    print("\nStandings")
    st = {r["team"]["name"]: r for conf in games.standings_json(db, league) for r in conf["teams"]}
    check("Warriors 2-1", (st["Warriors"]["w"], st["Warriors"]["l"]) == (2, 1), str(st["Warriors"]))
    check("Celtics 1-2", (st["Celtics"]["w"], st["Celtics"]["l"]) == (1, 2))
    check("streak after W, L, W", st["Warriors"]["streak"] == "W1", st["Warriors"]["streak"])
    check("away/home split", st["Warriors"]["away"] == "2-1" and st["Celtics"]["home"] == "1-2")
    west = next(c for c in games.standings_json(db, league) if c["conference"] == "West")
    check("leader has no games back", west["teams"][0]["team"]["name"] == "Warriors" and west["teams"][0]["gb"] == "-")
    check("teams without games listed", st["Lakers"]["gp"] == 0 and st["Lakers"]["ppg"] is None)
    check("points per game", st["Warriors"]["ppg"] == round((50 + 30 + 61) / 3, 1))

    print("\nStats + awards")
    rows = games.player_stats(db, league)
    kd = next(r for r in rows if r["name"] == "Kevin Durant")
    check("games played", kd["gp"] == 3)
    check("per game points", kd["per_game"]["pts"] == 30.0, str(kd["per_game"]))
    check("FG%", kd["fg_pct"] == 0.5)
    peat = next(r for r in rows if r["box_name"] == "K. Peat")
    check("unlinked player has stats under 2K name", not peat["linked"] and peat["team"]["name"] == "Warriors")
    check("only 3 Warriors played, so nobody counts as bench", peat["bench_games"] == 0)
    aw = games.award_races(rows)
    check("MVP race has leaders", aw["mvp"]["leaders"] and aw["mvp"]["leaders"][0]["name"] in ("Kevin Durant", "Evan Mobley"),
          str(aw["mvp"]["leaders"][:2]))
    check("DPOY leader is a shot blocker", aw["dpoy"]["leaders"][0]["name"] in ("Chet Holmgren", "Evan Mobley"))
    check("ROY empty until rookies are marked", aw["roy"]["leaders"] == [])
    p["Chet Holmgren"].is_rookie = True
    db.commit()
    aw = games.award_races(games.player_stats(db, league))
    check("ROY uses the rookie flag", [e["name"] for e in aw["roy"]["leaders"]] == ["Chet Holmgren"])

    print("\nDelete")
    db.delete(g2)
    db.commit()
    st = {r["team"]["name"]: r for conf in games.standings_json(db, league) for r in conf["teams"]}
    check("deleting a game updates standings", (st["Warriors"]["w"], st["Warriors"]["l"]) == (2, 0))
    check("lines deleted with the game", db.query(MynbaGameLine).count() == 10)

    db.close()
    print(f"\n{len(passes)} passed, {len(failures)} failed")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
