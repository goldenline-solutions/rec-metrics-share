"""
MyNBA game results: box-score screenshots in, standings and stats out.

Flow:
  1. A commissioner uploads screenshots. Each one is a single team's box score
     from the 2K sim, with both teams' period scores in the left panel.
     read_screenshots() turns them into game drafts, nothing saved.
  2. The commissioner fixes anything misread and saves each game. save_game()
     validates it; check_game() lists the soft problems (points that don't add
     up to the score) that are shown but don't block.
  3. standings_json(), player_stats() and award_races() are computed from the
     saved games on every read. Nothing is cached, so editing a game fixes
     everything downstream.
"""
import json
import logging
import math
import re
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from mynba_models import MynbaGame, MynbaGameLine, MynbaPlayer, MynbaTeam
from mynba_schedule import utc_to_eastern
from mynba_service import LeagueError, resolve_team

logger = logging.getLogger(__name__)

STAT_FIELDS = ("minutes", "pts", "reb", "ast", "stl", "blk", "tov",
               "fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "fouls")
MAX_IMAGES = 30


# ---------------------------------------------------------------------------
# Screenshot reading (not included in this copy of the repo)
# ---------------------------------------------------------------------------

def _sum_mismatches(data):
    """Stats where the player rows don't add up to the Total row."""
    rows = [p for p in data.get("players") or [] if not p.get("dnp")]
    totals = data.get("totals") or {}
    out = []
    for f in STAT_FIELDS:
        want = totals.get(f)
        if want is None:
            continue
        got = sum(int(p.get(f) or 0) for p in rows)
        if got != want:
            out.append(f"{f}: rows add up to {got}, Total row says {want}")
    return out


def extract_image(image_bytes, mime="image/png"):
    """Read one box-score screenshot.

    The screenshot reader is not part of this copy of the repo. It returns:
      {is_box_score, top_team, top_periods, top_total, bottom_team,
       bottom_periods, bottom_total, shown_team,
       players: [{name, dnp, <STAT_FIELDS>}], totals: {<STAT_FIELDS>}}
    """
    raise NotImplementedError("The box-score screenshot reader is not included in this repo.")


# ---------------------------------------------------------------------------
# Matching 2K names to the league
# ---------------------------------------------------------------------------

SUFFIX = {"jr", "sr", "ii", "iii", "iv"}


def _fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'’`]", "", s)
    return [t for t in re.split(r"[^a-z]+", s) if t]


def signature(name):
    """('k', 'caldwell pope') for both "K. Caldwell-Pope" and "Kentavious Caldwell-Pope"."""
    tokens = [t for t in _fold(name) if t not in SUFFIX] or _fold(name)
    if not tokens:
        return None
    return tokens[0][0], " ".join(tokens[1:])


class PlayerMatcher:
    """Finds the league player behind a 2K box-score name.

    The team's own roster wins; otherwise a unique match anywhere in the league
    (a traded player, or a free agent 2K still has on the bench). Anything
    ambiguous stays unlinked rather than crediting the wrong player.
    """

    def __init__(self, db, league):
        self.players = db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).all()
        self.by_sig = defaultdict(list)
        for p in self.players:
            self.by_sig[signature(p.name)].append(p)

    def match(self, name, team_id):
        found = self.by_sig.get(signature(name), [])
        mine = [p for p in found if p.team_id == team_id]
        if len(mine) == 1:
            return mine[0]
        if not mine and len(found) == 1:
            return found[0]
        return None


def _team_or_none(db, league, text):
    try:
        return resolve_team(db, league.id, text) if (text or "").strip() else None
    except LeagueError:
        return None


def default_played_on(league, now_utc=None):
    """The most recent sim day, in Eastern time."""
    today = utc_to_eastern(now_utc or datetime.utcnow()).date()
    back = (today.weekday() - (league.sim_weekday if league.sim_weekday is not None else 5)) % 7
    return today - timedelta(days=back)


def read_screenshots(db, league, files):
    """files: [(filename, bytes, mime)]. Returns {games: [draft...], unread: [...]}.

    Screenshots of the same game (same two teams, same final score) merge into
    one draft, one side each.
    """
    if not files:
        raise LeagueError("Add at least one screenshot.", code="no_files")
    if len(files) > MAX_IMAGES:
        raise LeagueError(f"Upload at most {MAX_IMAGES} screenshots at a time.", code="too_many_files")

    def run(item):
        name, data, mime = item
        try:
            return name, extract_image(data, mime), None
        except Exception as err:  # one bad image shouldn't sink the batch
            logger.warning("MyNBA box score read failed for %s: %s", name, err)
            return name, None, str(err)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, files))

    matcher = PlayerMatcher(db, league)
    played_on = default_played_on(league).isoformat()
    drafts, unread = {}, []
    for filename, data, error in results:
        if error or not data or not data.get("is_box_score"):
            unread.append({"file": filename, "reason": error or "This doesn't look like a 2K box score."})
            continue
        away = _team_or_none(db, league, data["top_team"])
        home = _team_or_none(db, league, data["bottom_team"])
        key = (away.id if away else data["top_team"], home.id if home else data["bottom_team"],
               data["top_total"], data["bottom_total"])
        draft = drafts.get(key)
        if draft is None:
            draft = drafts[key] = {
                "played_on": played_on,
                "files": [],
                "away": {"team_id": away.id if away else None, "read_as": data["top_team"],
                         "score": data["top_total"], "quarters": data["top_periods"], "lines": None},
                "home": {"team_id": home.id if home else None, "read_as": data["bottom_team"],
                         "score": data["bottom_total"], "quarters": data["bottom_periods"], "lines": None},
                "notes": [],
            }
        draft["files"].append(filename)

        shown = _team_or_none(db, league, data["shown_team"])
        totals_pts = (data.get("totals") or {}).get("pts")
        if shown and away and shown.id == away.id:
            side = "away"
        elif shown and home and shown.id == home.id:
            side = "home"
        elif totals_pts is not None and (totals_pts == data["top_total"]) != (totals_pts == data["bottom_total"]):
            side = "away" if totals_pts == data["top_total"] else "home"
        else:
            draft["notes"].append(f'{filename}: couldn\'t tell whose box score this is ("{data["shown_team"]}").')
            continue
        if draft[side]["lines"] is not None:
            draft["notes"].append(f"{filename}: a second {draft[side]['read_as']} box score; kept the first.")
            continue

        team_id = draft[side]["team_id"]
        lines = []
        for row in data.get("players") or []:
            if row.get("dnp") or not (row.get("name") or "").strip():
                continue
            player = matcher.match(row["name"], team_id)
            line = {f: int(row.get(f) or 0) for f in STAT_FIELDS}
            line.update(player_name=row["name"].strip(), player_id=player.id if player else None,
                        player_full_name=player.name if player else None)
            lines.append(line)
        draft[side]["lines"] = lines
        for miss in _sum_mismatches(data):
            draft["notes"].append(f"{draft[side]['read_as']}: {miss}. Check the rows.")

    games = list(drafts.values())
    for g in games:
        g["warnings"] = check_game(g)
    return {"games": games, "unread": unread}


# ---------------------------------------------------------------------------
# Validation and saving
# ---------------------------------------------------------------------------

def _int(value, label, lo=0, hi=999):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise LeagueError(f"{label} must be a whole number.", code="bad_game")
    if not lo <= n <= hi:
        raise LeagueError(f"{label} must be between {lo} and {hi}.", code="bad_game")
    return n


def clean_game(db, league, body):
    """Validate a game from the review form. Raises LeagueError on anything unsaveable."""
    try:
        played_on = date.fromisoformat(str(body.get("played_on") or ""))
    except ValueError:
        raise LeagueError("Pick the date the game was simmed.", code="bad_game")

    players = {p.id: p for p in db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id)}
    out = {"played_on": played_on}
    for side in ("away", "home"):
        raw = body.get(side) or {}
        team = db.query(MynbaTeam).filter(MynbaTeam.id == raw.get("team_id"),
                                          MynbaTeam.league_id == league.id).first()
        if not team:
            raise LeagueError(f"Pick the {side} team.", code="bad_game")
        quarters = [_int(q, f"{team.name} period score", 0, 99) for q in (raw.get("quarters") or [])]
        lines = []
        seen = set()
        for i, row in enumerate(raw.get("lines") or []):
            name = (row.get("player_name") or "").strip()
            if not name:
                raise LeagueError(f"{team.name} row {i + 1} has no player name.", code="bad_game")
            line = {f: _int(row.get(f, 0), f"{name} {f}") for f in STAT_FIELDS}
            for made, att, label in (("fgm", "fga", "FG"), ("tpm", "tpa", "3PT"), ("ftm", "fta", "FT")):
                if line[made] > line[att]:
                    raise LeagueError(f"{name}: {label} made is more than attempted.", code="bad_game")
            if line["tpm"] > line["fgm"] or line["tpa"] > line["fga"]:
                raise LeagueError(f"{name}: 3PT is part of FG, so it can't be higher.", code="bad_game")
            if line["oreb"] > line["reb"]:
                raise LeagueError(f"{name}: offensive rebounds are more than total rebounds.", code="bad_game")
            pid = row.get("player_id") or None
            if pid and pid not in players:
                raise LeagueError(f"{name} is linked to a player who isn't in this league.", code="bad_game")
            if pid and pid in seen:
                raise LeagueError(f"{players[pid].name} appears twice for the {team.name}.", code="bad_game")
            seen.add(pid)
            line.update(player_name=name, player_id=pid, row=i)
            lines.append(line)
        out[side] = {"team": team, "score": _int(raw.get("score"), f"{team.name} score", 0, 300),
                     "quarters": quarters, "lines": lines}

    if out["away"]["team"].id == out["home"]["team"].id:
        raise LeagueError("A team can't play itself.", code="bad_game")
    if out["away"]["score"] == out["home"]["score"]:
        raise LeagueError("The scores are tied. NBA games can't end in a tie.", code="bad_game")
    linked = [l["player_id"] for s in ("away", "home") for l in out[s]["lines"] if l["player_id"]]
    if len(linked) != len(set(linked)):
        raise LeagueError("The same player is listed for both teams.", code="bad_game")
    return out


def check_game(game):
    """Soft problems worth a second look. Works on a draft or a saved game's JSON."""
    out = []
    for side in ("away", "home"):
        s = game.get(side) or {}
        label = s.get("team_name") or s.get("read_as") or side.title()
        score = s.get("score")
        quarters = s.get("quarters") or []
        if quarters and score is not None and sum(quarters) != score:
            out.append(f"{label}: period scores add up to {sum(quarters)}, not {score}.")
        lines = s.get("lines")
        if lines is None:
            out.append(f"{label}: no box score yet. The result still counts; their player stats won't.")
            continue
        pts = sum(int(l.get("pts") or 0) for l in lines)
        if score is not None and pts != score:
            out.append(f"{label}: player points add up to {pts}, not {score}.")
        mins = sum(int(l.get("minutes") or 0) for l in lines)
        periods = max(4, len(quarters))
        expected = 240 + 25 * (periods - 4)
        if lines and abs(mins - expected) > 2:
            out.append(f"{label}: minutes add up to {mins}, expected about {expected}.")
        for l in lines:
            made = 2 * int(l.get("fgm") or 0) + int(l.get("tpm") or 0) + int(l.get("ftm") or 0)
            if made != int(l.get("pts") or 0):
                out.append(f"{label}: {l.get('player_name')} has {l.get('pts')} PTS but the shooting adds up to {made}.")
            if not l.get("player_id"):
                out.append(f"{label}: {l.get('player_name')} isn't linked to a league player.")
    return out


def find_duplicate(db, league, cleaned, exclude_id=None):
    a, h = cleaned["away"], cleaned["home"]
    q = db.query(MynbaGame).filter(MynbaGame.league_id == league.id, MynbaGame.played_on == cleaned["played_on"])
    for g in q:
        if g.id == exclude_id:
            continue
        same = (g.away_team_id, g.home_team_id, g.away_score, g.home_score)
        if same in ((a["team"].id, h["team"].id, a["score"], h["score"]),
                    (h["team"].id, a["team"].id, h["score"], a["score"])):
            return g
    return None


def save_game(db, league, body, actor, game=None):
    """Create or replace a game. Refuses an exact duplicate unless body.allow_duplicate."""
    cleaned = clean_game(db, league, body)
    dupe = find_duplicate(db, league, cleaned, exclude_id=game.id if game else None)
    if dupe and not body.get("allow_duplicate"):
        raise LeagueError("This game is already saved (same teams, score and date).", code="duplicate_game",
                          extra={"game_id": dupe.id})

    if game is None:
        game = MynbaGame(league_id=league.id, created_by_discord_id=actor.discord_id,
                         created_by_name=actor.display_name)
        db.add(game)
    game.played_on = cleaned["played_on"]
    for side in ("away", "home"):
        s = cleaned[side]
        setattr(game, f"{side}_team_id", s["team"].id)
        setattr(game, f"{side}_score", s["score"])
        setattr(game, f"{side}_quarters", json.dumps(s["quarters"]) if s["quarters"] else None)
    game.lines.clear()
    db.flush()
    for side in ("away", "home"):
        for line in cleaned[side]["lines"]:
            game.lines.append(MynbaGameLine(league_id=league.id, team_id=cleaned[side]["team"].id,
                                            **{k: line[k] for k in (*STAT_FIELDS, "player_name", "player_id", "row")}))
    db.flush()
    return game


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _teams(db, league):
    return {t.id: t for t in db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id)}


def _games(db, league):
    return (db.query(MynbaGame).filter(MynbaGame.league_id == league.id)
            .order_by(MynbaGame.played_on, MynbaGame.created_at).all())


def game_json(game, teams, players=None, with_lines=True):
    players = players or {}
    out = {"id": game.id, "played_on": game.played_on.isoformat(),
           "created_at": game.created_at.isoformat() + "Z" if game.created_at else None}
    for side in ("away", "home"):
        team = teams.get(getattr(game, f"{side}_team_id"))
        s = {"team_id": team.id if team else None, "team_name": team.name if team else "?",
             "abbrev": team.abbrev if team else "?",
             "score": getattr(game, f"{side}_score"),
             "quarters": json.loads(getattr(game, f"{side}_quarters") or "[]")}
        if with_lines:
            rows = [l for l in game.lines if team and l.team_id == team.id]
            s["lines"] = [dict({f: getattr(l, f) for f in STAT_FIELDS}, player_name=l.player_name,
                               player_id=l.player_id,
                               player_full_name=players[l.player_id].name if l.player_id in players else None)
                          for l in rows] or None
        out[side] = s
    if with_lines:
        out["warnings"] = check_game(out)
    return out


def games_json(db, league):
    teams = _teams(db, league)
    players = {p.id: p for p in db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id)}
    return [game_json(g, teams, players) for g in reversed(_games(db, league))]


def standings_json(db, league):
    teams = _teams(db, league)
    rec = {tid: {"w": 0, "l": 0, "pf": 0, "pa": 0, "home": [0, 0], "away": [0, 0], "results": []}
           for tid in teams}
    for g in _games(db, league):
        for side, tid, mine, theirs in (("away", g.away_team_id, g.away_score, g.home_score),
                                        ("home", g.home_team_id, g.home_score, g.away_score)):
            r = rec.get(tid)
            if r is None:
                continue
            won = mine > theirs
            r["w" if won else "l"] += 1
            r[side][0 if won else 1] += 1
            r["pf"] += mine
            r["pa"] += theirs
            r["results"].append("W" if won else "L")

    rows = []
    for tid, r in rec.items():
        t = teams[tid]
        gp = r["w"] + r["l"]
        streak = ""
        if r["results"]:
            last = r["results"][-1]
            n = len(r["results"]) - len("".join(r["results"]).rstrip(last))
            streak = f"{last}{n}"
        last10 = r["results"][-10:]
        rows.append({
            "team": {"id": t.id, "name": t.name, "full_name": t.full_name, "abbrev": t.abbrev,
                     "is_cpu": t.is_cpu},
            "conference": t.conference or "League",
            "w": r["w"], "l": r["l"], "gp": gp,
            "pct": round(r["w"] / gp, 3) if gp else 0.0,
            "ppg": round(r["pf"] / gp, 1) if gp else None,
            "oppg": round(r["pa"] / gp, 1) if gp else None,
            "diff": round((r["pf"] - r["pa"]) / gp, 1) if gp else None,
            "home": f"{r['home'][0]}-{r['home'][1]}", "away": f"{r['away'][0]}-{r['away'][1]}",
            "last10": f"{last10.count('W')}-{last10.count('L')}", "streak": streak,
        })

    conferences = defaultdict(list)
    for row in rows:
        conferences[row["conference"]].append(row)
    out = []
    for conf in sorted(conferences):
        group = sorted(conferences[conf], key=lambda x: (-x["pct"], -x["w"], -(x["diff"] or 0), x["team"]["name"]))
        lead = group[0]
        for i, row in enumerate(group):
            gb = ((lead["w"] - row["w"]) + (row["l"] - lead["l"])) / 2
            row["gb"] = "-" if gb == 0 else (f"{gb:g}")
            row["rank"] = i + 1
        out.append({"conference": conf, "teams": group})
    return out


def _game_score(t):
    """Hollinger's Game Score from summed stats."""
    return (t["pts"] + 0.4 * t["fgm"] - 0.7 * t["fga"] - 0.4 * (t["fta"] - t["ftm"])
            + 0.7 * t["oreb"] + 0.3 * (t["reb"] - t["oreb"]) + t["stl"] + 0.7 * t["ast"]
            + 0.7 * t["blk"] - 0.4 * t["fouls"] - t["tov"])


def player_stats(db, league):
    """Season totals and per-game averages for everyone with a line."""
    teams = _teams(db, league)
    players = {p.id: p for p in db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id)}
    games = _games(db, league)

    team_games = defaultdict(int)
    team_wins = defaultdict(int)
    for g in games:
        team_games[g.away_team_id] += 1
        team_games[g.home_team_id] += 1
        team_wins[g.away_team_id if g.away_score > g.home_score else g.home_team_id] += 1

    acc = {}
    for g in games:
        by_team = defaultdict(list)
        for l in g.lines:
            by_team[l.team_id].append(l)
        for tid, lines in by_team.items():
            # The 2K table is sorted by points, so starters are inferred: the top
            # five in minutes. Everyone else came off the bench.
            starters = {l.id for l in sorted(lines, key=lambda x: (-x.minutes, x.row))[:5]}
            for l in lines:
                key = l.player_id or f"{l.player_name}|{tid}"
                a = acc.get(key)
                if a is None:
                    a = acc[key] = dict({f: 0 for f in STAT_FIELDS}, gp=0, bench=0, team_id=tid,
                                        player_id=l.player_id, name=l.player_name)
                a["gp"] += 1
                a["bench"] += l.id not in starters
                a["team_id"] = tid  # latest team they played for
                for f in STAT_FIELDS:
                    a[f] += getattr(l, f)

    rows = []
    for a in acc.values():
        gp = a["gp"]
        p = players.get(a["player_id"])
        t = teams.get(a["team_id"])
        per = {f: round(a[f] / gp, 1) for f in STAT_FIELDS}
        tg = team_games.get(a["team_id"], 0)
        rows.append({
            "player_id": a["player_id"],
            "name": p.name if p else a["name"],
            "box_name": a["name"],
            "linked": p is not None,
            "position": p.position if p else None,
            "is_rookie": bool(p and p.is_rookie),
            "team": {"id": t.id, "name": t.name, "abbrev": t.abbrev} if t else None,
            "gp": gp,
            "bench_games": a["bench"],
            "team_games": tg,
            "team_win_pct": round(team_wins.get(a["team_id"], 0) / tg, 3) if tg else 0.0,
            "totals": {f: a[f] for f in STAT_FIELDS},
            "per_game": per,
            "fg_pct": round(a["fgm"] / a["fga"], 3) if a["fga"] else None,
            "tp_pct": round(a["tpm"] / a["tpa"], 3) if a["tpa"] else None,
            "ft_pct": round(a["ftm"] / a["fta"], 3) if a["fta"] else None,
            "game_score": round(_game_score(a) / gp, 1),
        })
    rows.sort(key=lambda r: (-r["per_game"]["pts"], r["name"]))
    return rows


AWARD_NOTES = {
    "mvp": "Game Score per game, scaled by team win % (x1.0 at .500).",
    "dpoy": "Per game: 2×STL + 2×BLK + 0.5×defensive rebounds.",
    "roy": "Game Score per game, players marked as rookies.",
    "smoy": "Game Score per game, players who came off the bench in most of their games.",
}


def award_races(rows, top=5):
    """The leaders in each race. Needs half the team's games to qualify."""
    def qualified(r):
        return r["team_games"] and r["gp"] >= math.ceil(r["team_games"] / 2)

    def line(r):
        pg = r["per_game"]
        return f"{pg['pts']:g} PTS · {pg['reb']:g} REB · {pg['ast']:g} AST"

    def def_line(r):
        pg = r["per_game"]
        return f"{pg['stl']:g} STL · {pg['blk']:g} BLK · {pg['reb']:g} REB"

    def entry(r, score, text):
        return {"player_id": r["player_id"], "name": r["name"], "team": r["team"], "gp": r["gp"],
                "score": round(score, 1), "line": text}

    pool = [r for r in rows if qualified(r)]
    races = {
        "mvp": [entry(r, r["game_score"] * (0.6 + 0.8 * r["team_win_pct"]), line(r)) for r in pool],
        "dpoy": [entry(r, 2 * r["per_game"]["stl"] + 2 * r["per_game"]["blk"]
                       + 0.5 * (r["totals"]["reb"] - r["totals"]["oreb"]) / r["gp"], def_line(r)) for r in pool],
        "roy": [entry(r, r["game_score"], line(r)) for r in pool if r["is_rookie"]],
        "smoy": [entry(r, r["game_score"], line(r)) for r in pool if r["bench_games"] * 2 > r["gp"]],
    }
    return {k: {"leaders": sorted(v, key=lambda e: -e["score"])[:top], "how": AWARD_NOTES[k]}
            for k, v in races.items()}
