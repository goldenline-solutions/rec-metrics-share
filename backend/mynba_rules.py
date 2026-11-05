"""
The league rulebook shown on the Rules tab.

Rules are plain text that commissioners edit on the site. Numbers the site
enforces are written as {tokens} — "{sixth_man_min} minutes" — and filled from
the league's settings when shown, so changing a setting updates the text too.
"""
import json
import re
import uuid
from datetime import datetime

from mynba_service import LeagueError
from mynba_schedule import lock_settings, format_minute

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

MAX_RULES = 60
MAX_TITLE = 120
MAX_BODY = 4000

# The league's rules as first written by the commissioners (2026-10-05).
DEFAULT_RULES = [
    ("Sim days",
     "Sims take place on {sim_day}s at {sim_time} and cover one FULL week of NBA games."),
    ("Rosters and untouchables",
     "Rosters are {roster_size} players total. {untouchables} of them are untouchable: you CANNOT trade "
     "them, no matter what. Mark your untouchables on the Coaching tab."),
    ("Minutes",
     "Your 5 starters can play as many minutes as you want. Your 6th man must play AT LEAST "
     "{sixth_man_min} minutes a game, and your other {other_bench} bench players must play AT LEAST "
     "{bench_min} minutes a game. Team minutes always add up to {team_minutes}."),
    ("Positions",
     "Players can only play the positions they're listed at, primary or secondary. You CANNOT start "
     "someone out of position. Be careful who you draft: tendencies and attributes will be key to "
     "building your team."),
    ("Trades",
     "Trades are at your discretion, and you can trade as many times as you want. A trade can include "
     "at most {max_trade_teams} teams: you and up to {max_trade_partners} others."),
    ("Gameplans",
     "Submit your gameplan on the Coaching tab by {deadline_day} at {deadline_time} before the sim. It covers "
     "your sim points of emphasis, minutes, playbook, system proficiency, and coaching sliders. "
     "Gameplans lock at the deadline until the sim is done.{roster_lock}"),
    ("Coaches",
     "Every team's coach has the same coaching attributes. Nobody gets a good or bad coach, so results "
     "come down to how you use your team."),
    ("Box scores",
     "After each game, the winner uploads a screenshot of BOTH box scores to the website. They're used "
     "for the standings and stats."),
]

TOKEN_HELP = {
    "roster_size": "Players per roster",
    "untouchables": "Untouchables per team",
    "sixth_man_min": "6th man minimum minutes",
    "bench_min": "Minimum minutes for the rest of the bench",
    "other_bench": "Bench players after the 6th man",
    "team_minutes": "Team minutes per game (240)",
    "max_trade_teams": "Most teams in one trade",
    "max_trade_partners": "Other teams you can trade with at once",
    "sim_day": "Sim day",
    "sim_time": "Sim start time",
    "deadline_day": "Gameplan deadline day",
    "deadline_time": "Gameplan deadline time",
    "roster_lock": "Sentence about trades/signings locking (blank when they don't)",
}


def tokens(league):
    roster = league.roster_size or 8
    max_teams = league.max_trade_teams or 3
    sim_weekday = league.sim_weekday if league.sim_weekday is not None else 5
    sim_day = WEEKDAYS[sim_weekday % 7]
    lock_days, lock_minute = lock_settings(league)
    deadline_day = WEEKDAYS[(sim_weekday - lock_days) % 7]
    return {
        "roster_size": roster,
        "untouchables": league.untouchables_per_team if league.untouchables_per_team is not None else 2,
        "sixth_man_min": league.sixth_man_min_minutes,
        "bench_min": league.bench_min_minutes,
        "other_bench": max(0, roster - 6),
        "team_minutes": 240,
        "max_trade_teams": max_teams,
        "max_trade_partners": max(1, max_teams - 1),
        "sim_day": sim_day,
        "sim_time": format_hour(league.sim_hour if league.sim_hour is not None else 20),
        "deadline_day": deadline_day,
        "deadline_time": f"{format_minute(lock_minute)} ET",
        "roster_lock": (" Trades, signings and releases lock at the same time." if league.lock_roster_moves else ""),
    }


def format_hour(hour):
    hour = int(hour) % 24
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12}:00 {suffix} ET"


_TOKEN_RE = re.compile(r"\{([a-z_]+)\}")


def render(text, values):
    """Fill {tokens}; unknown ones are left as typed so a typo is visible."""
    return _TOKEN_RE.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text or "")


def _default_rules():
    return [{"id": f"r{i + 1}", "title": t, "body": b} for i, (t, b) in enumerate(DEFAULT_RULES)]


def get_rules(league):
    if league.rulebook:
        try:
            rules = json.loads(league.rulebook)
            if isinstance(rules, list):
                return rules
        except (TypeError, ValueError):
            pass
    return _default_rules()


def rulebook_json(league):
    values = tokens(league)
    rules = get_rules(league)
    return {
        "rules": [
            {**r, "title_rendered": render(r["title"], values), "body_rendered": render(r["body"], values)}
            for r in rules
        ],
        "tokens": [{"key": k, "label": TOKEN_HELP[k], "value": values[k]} for k in TOKEN_HELP],
        "version": league.rulebook_version or 0,
        "is_default": not league.rulebook,
        "updated_at": league.rulebook_updated_at.isoformat() + "Z" if league.rulebook_updated_at else None,
        "updated_by": league.rulebook_updated_by,
    }


def save_rules(league, rules, base_version=None, actor_name=None):
    """Replace the rulebook. `base_version` stops two commissioners overwriting each other."""
    if base_version is not None and int(base_version) != (league.rulebook_version or 0):
        who = f" by {league.rulebook_updated_by}" if league.rulebook_updated_by else ""
        raise LeagueError(f"The rules were changed{who} after you opened them. Reload, then redo your edit.",
                          code="stale")
    if not isinstance(rules, list):
        raise LeagueError("Rules must be a list.", code="bad_rules")
    if len(rules) > MAX_RULES:
        raise LeagueError(f"That's {len(rules)} rules — the most is {MAX_RULES}.", code="bad_rules")

    clean = []
    for i, rule in enumerate(rules, start=1):
        title = str((rule or {}).get("title") or "").strip()
        body = str((rule or {}).get("body") or "").strip()
        if not title and not body:
            continue
        if not title:
            raise LeagueError(f"Rule {i} needs a title.", code="bad_rules")
        if len(title) > MAX_TITLE or len(body) > MAX_BODY:
            raise LeagueError(f'"{title[:40]}" is too long.', code="bad_rules")
        clean.append({"id": str(rule.get("id") or uuid.uuid4().hex[:8]), "title": title, "body": body})

    league.rulebook = json.dumps(clean)
    league.rulebook_version = (league.rulebook_version or 0) + 1
    league.rulebook_updated_at = datetime.utcnow()
    league.rulebook_updated_by = actor_name
    return clean


# League settings a commissioner can change from the Rules tab, with the range
# each must fall in. The PATCH /league route checks against this.
SETTING_LIMITS = {
    "roster_size": (5, 15),
    "untouchables_per_team": (0, 8),
    "sixth_man_min_minutes": (0, 48),
    "bench_min_minutes": (0, 48),
    "max_trade_teams": (2, 3),
    "sim_weekday": (0, 6),
    "sim_hour": (0, 23),
    "gameplan_lock_days": (0, 6),
    "gameplan_lock_minute": (0, 1439),
    "protest_window_hours": (0, 168),
    "proposal_ttl_hours": (1, 336),
}


def check_setting(field, value):
    """Coerce and range-check one numeric league setting."""
    lo, hi = SETTING_LIMITS[field]
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise LeagueError(f"{field.replace('_', ' ')} needs a whole number.", code="bad_setting")
    if not lo <= number <= hi:
        raise LeagueError(f"{field.replace('_', ' ')} must be between {lo} and {hi}.", code="bad_setting")
    return number
