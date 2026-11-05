"""
Check gameplans, the weekly lock, the change feed, and untouchables.

Runs against a throwaway in-memory SQLite database, so it never touches the
real league. Run it directly:

    python test_mynba_gameplan.py
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
import mynba_gameplan as gp
from mynba_models import MynbaPlayer, MynbaGameplanChange
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


CSV = """Name,Team,Position,Secondary Position,OVR
A. Nembhard,Pacers,PG,SG,81
T. Johnson,Pacers,SG,SF,79
D. Daniels,Pacers,SF,,82
J. Jackson Jr.,Pacers,PF,C,87
J. Embiid,Pacers,C,,91
M. Turner,Pacers,C,PF,80
D. DiVincenzo,Pacers,SG,,79
K. Ellis,Pacers,SG,,77
P. Ewing,Knicks,C,,94
J. Starks,Knicks,SG,,80
"""

GM = SimpleNamespace(discord_id="gm-1", display_name="Pacers GM")
COMMISH = SimpleNamespace(discord_id="c-1", display_name="Commish")

# 2026-10-05 is a Monday. Times are UTC; Eastern is UTC-4 in October.
MONDAY_NOON = datetime(2026, 10, 5, 16, 0)
THURSDAY_LATE = datetime(2026, 10, 9, 3, 30)    # Thu Oct 8, 11:30 PM ET
FRIDAY_EARLY = datetime(2026, 10, 9, 4, 30)     # Fri Oct 9, 12:30 AM ET
SATURDAY_NIGHT = datetime(2026, 10, 11, 3, 30)  # Sat Oct 10, 11:30 PM ET
SUNDAY_EARLY = datetime(2026, 10, 11, 4, 30)    # Sun Oct 11, 12:30 AM ET


def rotation_for(db, league, team, minutes):
    players = (db.query(MynbaPlayer).filter(MynbaPlayer.team_id == team.id)
               .order_by(MynbaPlayer.ovr.desc()).all())
    by_name = {p.name: p for p in players}
    order = ["A. Nembhard", "T. Johnson", "D. Daniels", "J. Jackson Jr.", "J. Embiid",
             "M. Turner", "D. DiVincenzo", "K. Ellis"]
    return [{"player_id": by_name[n].id, "minutes": m} for n, m in zip(order, minutes)]


def run():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    league = svc.create_league(db, "test-guild-gameplan")
    svc.import_roster_csv(db, league, CSV)
    db.flush()
    pacers = svc.resolve_team(db, league.id, "Pacers")
    knicks = svc.resolve_team(db, league.id, "Knicks")
    pacers.gm_discord_id, pacers.is_cpu = "gm-1", False

    print("\nLeague defaults")
    check("roster size defaults to 8", league.roster_size == 8)
    check("2 untouchables per team", league.untouchables_per_team == 2)
    embiid = svc.resolve_player(db, league.id, "J. Embiid")
    check("secondary position imported from CSV",
          svc.resolve_player(db, league.id, "J. Jackson Jr.").secondary_position == "C")

    print("\nLock schedule (Saturday sim, Thursday deadline, Eastern)")
    check("open on Monday", not gp.lock_status(league, MONDAY_NOON)["locked"])
    check("open Thursday 11:30 PM ET", not gp.lock_status(league, THURSDAY_LATE)["locked"])
    check("locked Friday 12:30 AM ET", gp.lock_status(league, FRIDAY_EARLY)["locked"])
    check("locked Saturday 11:30 PM ET", gp.lock_status(league, SATURDAY_NIGHT)["locked"])
    check("open again Sunday 12:30 AM ET", not gp.lock_status(league, SUNDAY_EARLY)["locked"])
    status = gp.lock_status(league, MONDAY_NOON)
    check("deadline label reads Thursday 11:59 PM ET", status["deadline_label"] == "Thu Oct 8, 11:59 PM ET",
          status["deadline_label"])
    check("deadline is Thu 11:59 PM EDT = 03:59 UTC Fri", status["deadline_utc"] == "2026-10-09T03:59:00Z", status["deadline_utc"])
    winter = gp.lock_status(league, datetime(2026, 12, 7, 17, 0))
    check("winter deadline uses EST", winter["deadline_utc"] == "2026-12-11T04:59:00Z", winter["deadline_utc"])

    print("\nSaturday 3 PM lock (commissioner setting)")
    league.gameplan_lock_days, league.gameplan_lock_minute = 0, 15 * 60
    SAT_2_59 = datetime(2026, 10, 10, 18, 59)   # Sat Oct 10, 2:59 PM ET
    SAT_3_01 = datetime(2026, 10, 10, 19, 1)    # 3:01 PM ET
    check("open Friday night", not gp.lock_status(league, FRIDAY_EARLY)["locked"])
    check("open Saturday 2:59 PM ET", not gp.lock_status(league, SAT_2_59)["locked"])
    check("locked Saturday 3:01 PM ET", gp.lock_status(league, SAT_3_01)["locked"])
    check("still locked Saturday 11:30 PM ET", gp.lock_status(league, SATURDAY_NIGHT)["locked"])
    check("open again Sunday", not gp.lock_status(league, SUNDAY_EARLY)["locked"])
    label = gp.lock_status(league, MONDAY_NOON)["deadline_label"]
    check("label reads Sat Oct 10, 3:00 PM ET", label == "Sat Oct 10, 3:00 PM ET", label)
    import mynba_schedule
    check("roster moves blocked during the lock",
          mynba_schedule.roster_lock_message(league, SAT_3_01) == "Rosters are locked until after the sim.")
    league.lock_roster_moves = False
    check("roster lock can be turned off", mynba_schedule.roster_lock_message(league, SAT_3_01) is None)
    league.lock_roster_moves = True
    league.gameplan_lock_days, league.gameplan_lock_minute = 2, 23 * 60 + 59
    league.gameplan_lock_override = True
    check("override forces a lock", gp.lock_status(league, MONDAY_NOON)["locked"])
    league.gameplan_lock_override = None

    print("\nSettings validation")
    raises("unknown setting rejected", "bad_settings",
           lambda: gp.clean_settings({"pace": "Fast"}))
    raises("slider out of range rejected", "bad_settings",
           lambda: gp.clean_settings({"bench_depth": 20}))
    raises("option not in 2K list rejected", "bad_settings",
           lambda: gp.clean_settings({"offensive_focus": "Run And Gun"}))
    cleaned = gp.clean_settings({"offensive_focus": "feed the post", "bench_depth": "11"})
    check("choice matched case-insensitively to 2K spelling", cleaned["offensive_focus"] == "Feed The Post")
    check("slider coerced to int", cleaned["bench_depth"] == 11)

    print("\nRotation rules")
    good = [32, 30, 32, 34, 34, 28, 26, 24]
    check("sample rotation totals 240", sum(good) == 240)
    raises("total under 240 rejected", "bad_rotation",
           lambda: gp.clean_rotation(db, league, pacers, rotation_for(db, league, pacers, [30] * 7 + [20])))
    raises("6th man under 20 rejected", "bad_rotation",
           lambda: gp.clean_rotation(db, league, pacers,
                                     rotation_for(db, league, pacers, [36, 36, 36, 36, 36, 19, 21, 20])))
    raises("slot 8 under 10 rejected", "bad_rotation",
           lambda: gp.clean_rotation(db, league, pacers,
                                     rotation_for(db, league, pacers, [36, 36, 36, 36, 36, 26, 25, 9])))
    raises("over 48 minutes rejected", "bad_rotation",
           lambda: gp.clean_rotation(db, league, pacers,
                                     rotation_for(db, league, pacers, [49, 31, 36, 36, 36, 20, 16, 16])))
    ewing = svc.resolve_player(db, league.id, "P. Ewing")
    raises("another team's player rejected", "bad_rotation",
           lambda: gp.clean_rotation(db, league, pacers, [{"player_id": ewing.id, "minutes": 240}]))

    print("\nSaving and the change feed")
    plan, changes = gp.save_gameplan(
        db, league, pacers,
        settings={"offensive_focus": "Pick & Roll Offense", "playbook": "Pistons Playbook"},
        rotation=rotation_for(db, league, pacers, good),
        actor=GM, now_utc=MONDAY_NOON,
    )
    check("first save is version 1", plan.version == 1)
    check("first save logs 2 settings + 8 rotation rows", len(changes) == 10, str(len(changes)))

    _, changes = gp.save_gameplan(db, league, pacers, settings={"offensive_focus": "Feed The Post"},
                                  actor=GM, base_version=1, now_utc=MONDAY_NOON)
    open_rows = gp.list_changes(db, league)
    focus = [r for r in open_rows if r.field_key == "offensive_focus"]
    check("repeat edit folds into one open row", len(focus) == 1)
    check("folded row keeps original old value", focus[0].old_value is None and focus[0].new_value == "Feed The Post")

    gp.mark_changes(db, league, [r.id for r in open_rows], True, "c-1")
    check("marking done empties the feed", gp.list_changes(db, league) == [])

    _, changes = gp.save_gameplan(db, league, pacers, settings={"offensive_focus": "Get To The Basket"},
                                  actor=GM, base_version=2, now_utc=MONDAY_NOON)
    check("edit after done opens a new row with the 2K value as old",
          len(changes) == 1 and changes[0].old_value == "Feed The Post")
    gp.save_gameplan(db, league, pacers, settings={"offensive_focus": "Feed The Post"},
                     actor=GM, base_version=3, now_utc=MONDAY_NOON)
    check("changing back to the 2K value clears the row", gp.list_changes(db, league) == [])

    swapped = rotation_for(db, league, pacers, good)
    swapped[4]["minutes"], swapped[5]["minutes"] = 28, 34
    _, changes = gp.save_gameplan(db, league, pacers, rotation=swapped, actor=GM, base_version=4,
                                  now_utc=MONDAY_NOON)
    check("minutes change logs only the 2 players touched", len(changes) == 2, str([c.field_label for c in changes]))
    check("rotation row reads minutes and slot", changes[0].new_value in ("28 min · C", "34 min · 6th man"),
          changes[0].new_value)

    raises("stale base_version rejected", "stale",
           lambda: gp.save_gameplan(db, league, pacers, settings={"bench_depth": 9}, actor=GM,
                                    base_version=1, now_utc=MONDAY_NOON))
    raises("GM blocked after the Thursday deadline", "locked",
           lambda: gp.save_gameplan(db, league, pacers, settings={"bench_depth": 9}, actor=GM,
                                    now_utc=FRIDAY_EARLY))
    plan, changes = gp.save_gameplan(db, league, pacers, settings={"bench_depth": 9}, actor=COMMISH,
                                     is_commissioner=True, now_utc=FRIDAY_EARLY)
    check("commissioner can edit while locked", plan.settings and '"bench_depth": 9' in plan.settings)
    check("commissioner edit flagged in the feed", changes and changes[0].by_commissioner)

    view = gp.gameplan_json(db, league, pacers)
    check("plan view lists all 8 rostered players", len(view["rotation"]) == 8)
    check("plan view slots first five as PG..C", [r["slot"] for r in view["rotation"][:5]] == list(gp.STARTER_SLOTS))
    check("valid plan shows no problems", view["problems"] == [], str(view["problems"]))

    print("\nPositions")
    rot = rotation_for(db, league, pacers, good)
    rot[0], rot[5] = rot[5], rot[0]   # M. Turner (C/PF) starting at PG
    raises("starter out of position rejected", "bad_rotation",
           lambda: gp.clean_rotation(db, league, pacers, rot))
    rot = rotation_for(db, league, pacers, good)
    rot[3], rot[4] = rot[4], rot[3]   # J. Embiid (C) at PF — not listed there
    raises("primary C can't start at PF", "bad_rotation", lambda: gp.clean_rotation(db, league, pacers, rot))
    rot = rotation_for(db, league, pacers, good)
    rot[4], rot[5] = rot[5], rot[4]   # M. Turner (C/PF) at C, Embiid to the bench
    check("bench player can be any position; secondary counts for starters",
          gp.clean_rotation(db, league, pacers, rot) is not None)
    rot = rotation_for(db, league, pacers, good)
    rot[3], rot[5] = rot[5], rot[3]   # M. Turner at PF via his secondary position
    check("secondary position is eligible to start", gp.clean_rotation(db, league, pacers, rot) is not None)

    print("\nRulebook")
    import mynba_rules as rules
    book = rules.rulebook_json(league)
    minutes_rule = next(r for r in book["rules"] if r["title"] == "Minutes")
    check("default rules fill in live numbers", "AT LEAST 20 minutes" in minutes_rule["body_rendered"])
    check("default rules name the sim time", "Saturdays at 8:00 PM ET" in book["rules"][0]["body_rendered"],
          book["rules"][0]["body_rendered"])
    check("deadline day derived as Thursday",
          "Thursday" in next(r for r in book["rules"] if r["title"] == "Gameplans")["body_rendered"])
    league.sixth_man_min_minutes = rules.check_setting("sixth_man_min_minutes", "22")
    minutes_rule = next(r for r in rules.rulebook_json(league)["rules"] if r["title"] == "Minutes")
    check("changing a setting updates the rule text", "AT LEAST 22 minutes" in minutes_rule["body_rendered"])
    league.sixth_man_min_minutes = 20
    raises("setting out of range rejected", "bad_setting", lambda: rules.check_setting("max_trade_teams", 4))
    saved = rules.save_rules(league, [{"title": "Be nice", "body": "{roster_size}-man rosters, {typo} stays"}],
                             base_version=0, actor_name="Commish")
    book = rules.rulebook_json(league)
    check("saved rulebook replaces the default", len(book["rules"]) == 1 and not book["is_default"])
    check("tokens render, unknown tokens stay visible",
          book["rules"][0]["body_rendered"] == "8-man rosters, {typo} stays", book["rules"][0]["body_rendered"])
    raises("stale rulebook save rejected", "stale",
           lambda: rules.save_rules(league, saved, base_version=0))
    raises("rule without a title rejected", "bad_rules",
           lambda: rules.save_rules(league, [{"title": "", "body": "x"}], base_version=1))

    print("\nTrade size")
    league.gameplan_lock_override = False   # these use the real clock; keep the weekly lock out of it
    celtics = svc.resolve_team(db, league.id, "Celtics")
    starks = svc.resolve_player(db, league.id, "J. Starks")
    ellis = svc.resolve_player(db, league.id, "K. Ellis")
    league.max_trade_teams = 2
    raises("3-team trade blocked when the limit is 2", "too_many_teams",
           lambda: svc.create_trade(db, league, pacers,
                                    [{"from": pacers, "to": knicks, "players": [ellis]},
                                     {"from": knicks, "to": celtics, "players": [starks]}]))
    league.max_trade_teams = 3

    print("\nUntouchables")
    svc.set_untouchable(db, league, embiid, True)
    svc.set_untouchable(db, league, svc.resolve_player(db, league.id, "J. Jackson Jr."), True)
    raises("third untouchable rejected", "untouchable_limit",
           lambda: svc.set_untouchable(db, league, svc.resolve_player(db, league.id, "K. Ellis"), True))
    raises("trade including an untouchable blocked", "untouchable",
           lambda: svc.create_trade(db, league, knicks,
                                    [{"from": pacers, "to": knicks, "players": [embiid]},
                                     {"from": knicks, "to": pacers, "players": [ewing]}]))
    svc.admin_move_player(db, league, embiid, knicks)
    check("moving teams clears untouchable", embiid.is_untouchable is False)

    print("\nRoster change after saving")
    view = gp.gameplan_json(db, league, pacers)
    check("departed player flagged on the plan", any("No longer on the roster" in p for p in view["problems"]),
          str(view["problems"]))

    db.close()
    print(f"\n{len(passes)} passed, {len(failures)} failed")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
