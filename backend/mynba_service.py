"""
MyNBA league business logic: roster import, name resolution, and the trade lifecycle.

The one rule that shapes this whole module: rosters change in exactly one place,
`execute_trade`, inside a single transaction with the affected rows locked. Every
other function moves a trade between states. If you are adding a feature that
changes who is on a team, route it through `_apply_move` so it lands in the
transaction log like everything else.
"""
import csv
import io
import json
import re
from datetime import datetime, timedelta

from sqlalchemy import func, or_

from name_utils import normalize_name
from mynba_schedule import roster_lock_message, lock_status
from mynba_models import (
    MynbaLeague, MynbaCommissioner, MynbaTeam, MynbaPlayer,
    MynbaTrade, MynbaTradeAsset, MynbaTradeVote, MynbaTransaction, MynbaTradeTeam,
    TRADE_PENDING_GM, TRADE_PENDING_COMMISSIONER, TRADE_APPROVED_WINDOW,
    TRADE_PROTESTED, TRADE_EXECUTED, TRADE_DECLINED, TRADE_VETOED,
    TRADE_CANCELLED, TRADE_EXPIRED, TRADE_VOIDED, TRADE_OVERTURNED,
    TRADE_OPEN_STATUSES,
    TXN_TRADE, TXN_SIGN, TXN_RELEASE, TXN_IMPORT, TXN_ADMIN_MOVE,
)


class LeagueError(Exception):
    """A rule violation worth showing the user verbatim."""

    def __init__(self, message, code="invalid", extra=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra or {}


class AmbiguousName(LeagueError):
    """The typed name matched more than one player; `candidates` holds the options."""

    def __init__(self, query, candidates):
        names = ", ".join(c.name for c in candidates[:6])
        super().__init__(
            f'"{query}" matches {len(candidates)} players: {names}',
            code="ambiguous",
            extra={"candidates": [{"id": c.id, "name": c.name} for c in candidates[:25]]},
        )
        self.candidates = candidates


# ---------------------------------------------------------------------------
# The league
# ---------------------------------------------------------------------------

NBA_TEAMS = [
    # (nickname, full name, abbrev, conference)
    ("Celtics", "Boston Celtics", "BOS", "East"),
    ("Nets", "Brooklyn Nets", "BKN", "East"),
    ("Knicks", "New York Knicks", "NYK", "East"),
    ("76ers", "Philadelphia 76ers", "PHI", "East"),
    ("Raptors", "Toronto Raptors", "TOR", "East"),
    ("Bulls", "Chicago Bulls", "CHI", "East"),
    ("Cavaliers", "Cleveland Cavaliers", "CLE", "East"),
    ("Pistons", "Detroit Pistons", "DET", "East"),
    ("Pacers", "Indiana Pacers", "IND", "East"),
    ("Bucks", "Milwaukee Bucks", "MIL", "East"),
    ("Hawks", "Atlanta Hawks", "ATL", "East"),
    ("Hornets", "Charlotte Hornets", "CHA", "East"),
    ("Heat", "Miami Heat", "MIA", "East"),
    ("Magic", "Orlando Magic", "ORL", "East"),
    ("Wizards", "Washington Wizards", "WAS", "East"),
    ("Nuggets", "Denver Nuggets", "DEN", "West"),
    ("Timberwolves", "Minnesota Timberwolves", "MIN", "West"),
    ("Thunder", "Oklahoma City Thunder", "OKC", "West"),
    ("Trail Blazers", "Portland Trail Blazers", "POR", "West"),
    ("Jazz", "Utah Jazz", "UTA", "West"),
    ("Warriors", "Golden State Warriors", "GSW", "West"),
    ("Clippers", "LA Clippers", "LAC", "West"),
    ("Lakers", "Los Angeles Lakers", "LAL", "West"),
    ("Suns", "Phoenix Suns", "PHX", "West"),
    ("Kings", "Sacramento Kings", "SAC", "West"),
    ("Mavericks", "Dallas Mavericks", "DAL", "West"),
    ("Rockets", "Houston Rockets", "HOU", "West"),
    ("Grizzlies", "Memphis Grizzlies", "MEM", "West"),
    ("Pelicans", "New Orleans Pelicans", "NOP", "West"),
    ("Spurs", "San Antonio Spurs", "SAS", "West"),
]

# Spellings people actually type that don't prefix-match the real name.
MAX_TRADE_TEAMS = 3

# Spellings people actually type that don't prefix-match the real name.
TEAM_ALIASES = {
    "sixers": "PHI", "philly": "PHI", "phila": "PHI",
    "blazers": "POR", "portland": "POR",
    "cavs": "CLE", "wolves": "MIN", "twolves": "MIN", "timberwolfs": "MIN",
    "mavs": "DAL", "dubs": "GSW", "warriors": "GSW", "gsw": "GSW",
    "okc": "OKC", "nola": "NOP", "pels": "NOP",
    "lakeshow": "LAL", "clips": "LAC",
    "nyk": "NYK", "ny": "NYK", "bklyn": "BKN",
}


def player_key(name):
    """Lookup key for a player name: normalized, punctuation stripped.

    "C.J. McCollum", "CJ McCollum" and "cj mccollum" all collapse to the same key,
    which is what makes typing a name in Discord work.
    """
    base = normalize_name(name or "")
    # Periods and apostrophes vanish so "C.J." == "CJ" and "O'Neale" == "ONeale";
    # hyphens become spaces so "Karl-Anthony" == "Karl Anthony".
    base = re.sub(r"[.'’`]", "", base)
    base = re.sub(r"[^a-z0-9 ]+", " ", base)
    return re.sub(r"\s+", " ", base).strip()


def get_league(db, guild_id):
    return db.query(MynbaLeague).filter(MynbaLeague.guild_id == str(guild_id)).first()


def require_league(db, guild_id):
    league = get_league(db, guild_id)
    if not league:
        raise LeagueError("No league is set up for this server yet. Run /league-setup first.", code="no_league")
    return league


def create_league(db, guild_id, name=None, seed_teams=True, **config):
    """Register a guild as a league and (by default) seed all 30 NBA franchises."""
    existing = get_league(db, guild_id)
    if existing:
        raise LeagueError("This server already has a league.", code="exists")

    league = MynbaLeague(guild_id=str(guild_id), name=name or "MyNBA League")
    for field in (
        "commissioner_role_id", "gm_role_id", "trade_channel_id", "approvals_channel_id",
        "roster_size", "enforce_roster_size", "salary_cap", "enforce_salary_cap",
        "protest_window_hours", "proposal_ttl_hours", "game_version",
    ):
        if config.get(field) is not None:
            setattr(league, field, config[field])
    db.add(league)
    db.flush()

    if seed_teams:
        seed_nba_teams(db, league)
    return league


def seed_nba_teams(db, league):
    """Insert any of the 30 franchises this league is missing. Safe to re-run."""
    have = {t.abbrev for t in db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id).all()}
    added = []
    for nickname, full_name, abbrev, conference in NBA_TEAMS:
        if abbrev in have:
            continue
        team = MynbaTeam(
            league_id=league.id, name=nickname, full_name=full_name,
            abbrev=abbrev, conference=conference, is_cpu=True,
        )
        db.add(team)
        added.append(team)
    db.flush()
    return added


def is_commissioner(db, league, discord_id):
    if not discord_id:
        return False
    return db.query(MynbaCommissioner).filter(
        MynbaCommissioner.league_id == league.id,
        MynbaCommissioner.discord_id == str(discord_id),
    ).first() is not None


def team_for_gm(db, league, discord_id):
    if not discord_id:
        return None
    return db.query(MynbaTeam).filter(
        MynbaTeam.league_id == league.id,
        MynbaTeam.gm_discord_id == str(discord_id),
    ).first()


# ---------------------------------------------------------------------------
# Resolving what somebody typed
# ---------------------------------------------------------------------------

def resolve_team(db, league_id, query):
    """Match a team by abbrev, nickname, full name, alias, or unique substring."""
    if not query or not str(query).strip():
        raise LeagueError("No team given.", code="missing_team")
    q = normalize_name(str(query))
    teams = db.query(MynbaTeam).filter(MynbaTeam.league_id == league_id).all()

    alias = TEAM_ALIASES.get(q.replace(" ", ""))
    if alias:
        for t in teams:
            if t.abbrev.lower() == alias.lower():
                return t

    for t in teams:
        if q in (t.abbrev.lower(), normalize_name(t.name), normalize_name(t.full_name or "")):
            return t

    partial = [t for t in teams
               if q in normalize_name(t.full_name or "") or q in normalize_name(t.name)]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(t.name for t in partial[:6])
        raise LeagueError(f'"{query}" matches several teams: {names}', code="ambiguous_team")
    raise LeagueError(f'No team called "{query}".', code="no_team")


def resolve_player(db, league_id, query, team_id=None):
    """Match a player by exact key, then by unique last-name / substring match.

    Raises AmbiguousName rather than guessing — a wrong guess here trades the
    wrong player.
    """
    if not query or not str(query).strip():
        raise LeagueError("No player given.", code="missing_player")

    key = player_key(query)
    base = db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league_id)
    if team_id:
        base = base.filter(MynbaPlayer.team_id == team_id)

    exact = base.filter(MynbaPlayer.name_key == key).all()
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousName(query, exact)

    candidates = [p for p in base.all() if key and key in p.name_key]
    if not candidates:
        # Last resort: match on any whole word (a bare surname).
        words = set(key.split())
        candidates = [p for p in base.all() if words & set(p.name_key.split())]

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise AmbiguousName(query, candidates)
    raise LeagueError(f'No player called "{query}" in this league.', code="no_player")


def search_players(db, league_id, q, limit=25):
    """Loose prefix/substring search for Discord autocomplete."""
    query = db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league_id)
    key = player_key(q or "")
    if key:
        query = query.filter(MynbaPlayer.name_key.like(f"%{key}%"))
    return query.order_by(MynbaPlayer.name).limit(limit).all()


# ---------------------------------------------------------------------------
# Roster import — the one-time spreadsheet seed
# ---------------------------------------------------------------------------

CSV_ALIASES = {
    "name": ("name", "player", "player name", "playername", "full name"),
    "team": ("team", "team name", "franchise", "roster", "current team",
             "fantasy draft team", "draft team", "fantasy team"),
    "position": ("position", "pos", "primary position"),
    "secondary_position": ("secondary position", "secondary", "pos2", "sec pos", "2nd position"),
    "ovr": ("ovr", "overall", "rating", "ovr rating", "2k rating", "nba 2k27 rating", "2k27 rating"),
    "age": ("age",),
    "salary": ("salary", "cap hit", "contract", "contract value"),
    "contract_years": ("years", "contract years", "yrs"),
    "jersey": ("jersey", "number", "#", "jersey number"),
}

FREE_AGENT_LABELS = {"", "fa", "free agent", "free agents", "none", "n/a", "na", "unsigned", "-"}


def _map_headers(fieldnames):
    mapping = {}
    for raw in fieldnames or []:
        norm = normalize_name(raw or "")
        for field, aliases in CSV_ALIASES.items():
            if norm in aliases and field not in mapping:
                mapping[field] = raw
                break
    return mapping


def _to_int(value):
    if value is None:
        return None
    digits = re.sub(r"[^0-9-]", "", str(value))
    if digits in ("", "-"):
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def import_roster_csv(db, league, csv_text, actor_discord_id=None, dry_run=False, replace=False):
    """Seed rosters from the league spreadsheet.

    After this runs, the database is the source of truth — the sheet is not read
    again unless somebody re-imports on purpose.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    mapping = _map_headers(reader.fieldnames)
    if "name" not in mapping:
        raise LeagueError(
            "The CSV needs a player-name column (one called 'Name' or 'Player'). "
            f"Found: {', '.join(reader.fieldnames or []) or 'nothing'}",
            code="bad_csv",
        )

    teams = {t.abbrev.lower(): t for t in db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id).all()}
    for t in list(teams.values()):
        teams[normalize_name(t.name)] = t
        teams[normalize_name(t.full_name or "")] = t

    existing = {p.name_key: p for p in db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id).all()}
    known_fields = set(mapping.values())

    created, updated, freed, problems = [], [], [], []
    seen_keys = set()
    if "team" not in mapping:
        problems.append(
            "No team column found (expected one called 'Team'), so every player would be imported "
            f"as a free agent. Columns found: {', '.join(reader.fieldnames or [])}"
        )

    for line_no, row in enumerate(reader, start=2):
        raw_name = (row.get(mapping["name"]) or "").strip()
        if not raw_name:
            continue
        key = player_key(raw_name)
        if not key:
            continue
        if key in seen_keys:
            problems.append(f"Line {line_no}: duplicate entry for {raw_name} — kept the first one.")
            continue
        seen_keys.add(key)

        team = None
        if "team" in mapping:
            raw_team = (row.get(mapping["team"]) or "").strip()
            if normalize_name(raw_team) not in FREE_AGENT_LABELS:
                team = teams.get(normalize_name(raw_team)) or teams.get(raw_team.lower())
                if team is None:
                    problems.append(f'Line {line_no}: no team called "{raw_team}" — {raw_name} left as a free agent.')

        values = {
            "position": (row.get(mapping["position"]) or "").strip().upper() or None if "position" in mapping else None,
            "secondary_position": (row.get(mapping["secondary_position"]) or "").strip().upper() or None
            if "secondary_position" in mapping else None,
            "ovr": _to_int(row.get(mapping["ovr"])) if "ovr" in mapping else None,
            "age": _to_int(row.get(mapping["age"])) if "age" in mapping else None,
            "salary": _to_int(row.get(mapping["salary"])) if "salary" in mapping else None,
            "contract_years": _to_int(row.get(mapping["contract_years"])) if "contract_years" in mapping else None,
            "jersey": (row.get(mapping["jersey"]) or "").strip() or None if "jersey" in mapping else None,
        }
        leftovers = {k: v for k, v in row.items() if k and k not in known_fields and (v or "").strip()}

        player = existing.get(key)
        if player:
            # Keep the stored spelling: it's 2K's, and the CSV's may be a
            # looser one ("Lebron James" for "LeBron James") that matched the key.
            player.team_id = team.id if team else None
            for field, value in values.items():
                if value is not None:
                    setattr(player, field, value)
            if leftovers:
                player.extra = json.dumps(leftovers)
            updated.append(player)
        else:
            player = MynbaPlayer(
                league_id=league.id, name=raw_name, name_key=key,
                team_id=team.id if team else None,
                extra=json.dumps(leftovers) if leftovers else None,
                **values,
            )
            db.add(player)
            existing[key] = player
            created.append(player)

    if replace:
        for key, player in existing.items():
            if key not in seen_keys and player.team_id is not None:
                player.team_id = None
                freed.append(player)

    summary = {
        "created": len(created),
        "updated": len(updated),
        "released": len(freed),
        "problems": problems,
        "columns_used": {k: v for k, v in mapping.items()},
        "columns_ignored": sorted(set(reader.fieldnames or []) - known_fields),
        "dry_run": bool(dry_run),
    }

    if dry_run:
        db.rollback()
        return summary

    db.flush()
    db.add(MynbaTransaction(
        league_id=league.id, kind=TXN_IMPORT, player_name="(roster import)",
        actor_discord_id=actor_discord_id,
        note=f"{len(created)} added, {len(updated)} updated, {len(freed)} released",
    ))
    return summary


# ---------------------------------------------------------------------------
# Roster helpers
# ---------------------------------------------------------------------------

def roster_count(db, league_id, team_id):
    return db.query(func.count(MynbaPlayer.id)).filter(
        MynbaPlayer.league_id == league_id, MynbaPlayer.team_id == team_id
    ).scalar() or 0


def team_salary(db, league_id, team_id):
    return db.query(func.coalesce(func.sum(MynbaPlayer.salary), 0)).filter(
        MynbaPlayer.league_id == league_id, MynbaPlayer.team_id == team_id
    ).scalar() or 0


def players_in_open_trades(db, league_id, exclude_trade_id=None):
    """Player ids already promised in a trade that hasn't finished yet."""
    q = (db.query(MynbaTradeAsset.player_id)
         .join(MynbaTrade, MynbaTradeAsset.trade_id == MynbaTrade.id)
         .filter(MynbaTrade.league_id == league_id,
                 MynbaTrade.status.in_(TRADE_OPEN_STATUSES)))
    if exclude_trade_id:
        q = q.filter(MynbaTrade.id != exclude_trade_id)
    return {row[0] for row in q.all()}


def _next_ref(db, league_id):
    n = db.query(func.count(MynbaTrade.id)).filter(MynbaTrade.league_id == league_id).scalar() or 0
    return f"T-{n + 1:04d}"


# ---------------------------------------------------------------------------
# Trade lifecycle
# ---------------------------------------------------------------------------

def create_trade(db, league, proposer_team, legs, actor_discord_id=None,
                 actor_user_id=None, note=None):
    """Validate and record a proposal. Nothing moves yet.

    `legs` is a list of {"from": team, "to": team, "players": [MynbaPlayer, ...]},
    already resolved by the caller. Two teams or three (or more) — the shape is
    the same, which is why three-team deals need no special case below.
    """
    locked = roster_lock_message(league)
    if locked:
        raise LeagueError(locked, code="locked")
    if not legs:
        raise LeagueError("A trade needs at least one player moving.", code="empty")

    moves = []
    for leg in legs:
        from_team, to_team = leg["from"], leg["to"]
        if from_team.id == to_team.id:
            raise LeagueError(f"The {from_team.name} cannot trade with themselves.", code="same_team")
        for player in leg["players"]:
            moves.append((player, from_team, to_team))

    if not moves:
        raise LeagueError("A trade needs at least one player moving.", code="empty")

    for player, from_team, _ in moves:
        if player.team_id != from_team.id:
            where = _team_label(db, player.team_id)
            raise LeagueError(
                f"{player.name} is not on the {from_team.name} — he's on {where}.",
                code="wrong_team",
            )

    untouchable = [p.name for p, _, _ in moves if p.is_untouchable]
    if untouchable:
        raise LeagueError(
            f"Untouchable — can't be traded: {', '.join(untouchable)}.",
            code="untouchable",
        )

    ids = [p.id for p, _, _ in moves]
    if len(ids) != len(set(ids)):
        raise LeagueError("The same player appears twice in this trade.", code="duplicate")

    promised = players_in_open_trades(db, league.id)
    clash = [p.name for p, _, _ in moves if p.id in promised]
    if clash:
        raise LeagueError(
            f"Already part of a pending trade: {', '.join(clash)}. Resolve that one first.",
            code="already_pending",
        )

    # Every team touched by any leg is a party to the trade.
    teams = {}
    for _, from_team, to_team in moves:
        teams[from_team.id] = from_team
        teams[to_team.id] = to_team
    teams[proposer_team.id] = proposer_team

    if len(teams) < 2:
        raise LeagueError("A trade needs at least two teams.", code="same_team")
    max_teams = league.max_trade_teams or MAX_TRADE_TEAMS
    if len(teams) > max_teams:
        raise LeagueError(
            f"That's {len(teams)} teams — the most allowed in one trade is {max_teams}.",
            code="too_many_teams",
        )
    if proposer_team.id not in {t.id for t in teams.values()}:
        raise LeagueError("The proposing team has to be part of the trade.", code="not_a_party")

    warnings = _roster_warnings(db, league, teams, moves)
    if warnings and league.enforce_roster_size:
        raise LeagueError(" ".join(warnings), code="roster_size")

    now = datetime.utcnow()
    others = [t for t in teams.values() if t.id != proposer_team.id]
    others.sort(key=lambda t: t.name)

    trade = MynbaTrade(
        league_id=league.id,
        ref=_next_ref(db, league.id),
        status=TRADE_PENDING_GM,
        proposer_team_id=proposer_team.id,
        counterparty_team_id=others[0].id,
        team_count=len(teams),
        proposer_discord_id=str(actor_discord_id) if actor_discord_id else None,
        proposer_user_id=actor_user_id,
        note=note,
        expires_at=now + timedelta(hours=league.proposal_ttl_hours or 72),
    )
    db.add(trade)
    db.flush()

    for team in teams.values():
        is_proposer = team.id == proposer_team.id
        # A CPU team has nobody to click Accept, so it counts as accepted up front.
        cpu = bool(team.is_cpu or not team.gm_discord_id)
        db.add(MynbaTradeTeam(
            trade_id=trade.id,
            team_id=team.id,
            is_proposer=is_proposer,
            is_cpu=cpu,
            accepted_at=now if (is_proposer or cpu) else None,
            accepted_by_discord_id=str(actor_discord_id) if is_proposer and actor_discord_id else None,
        ))

    for player, from_team, to_team in moves:
        db.add(MynbaTradeAsset(
            trade_id=trade.id, player_id=player.id, player_name=player.name,
            from_team_id=from_team.id, to_team_id=to_team.id,
        ))
    db.flush()

    # Everyone might already be accounted for (all partners are CPU).
    _advance_if_all_accepted(db, trade)
    return trade, warnings


def trade_team_rows(db, trade):
    return db.query(MynbaTradeTeam).filter(MynbaTradeTeam.trade_id == trade.id).all()


def teams_awaiting(db, trade):
    """Teams that still have to accept before a commissioner sees this."""
    return [r for r in trade_team_rows(db, trade) if r.accepted_at is None and r.declined_at is None]


def _advance_if_all_accepted(db, trade):
    if trade.status != TRADE_PENDING_GM:
        return trade
    if teams_awaiting(db, trade):
        return trade
    trade.status = TRADE_PENDING_COMMISSIONER
    trade.accepted_at = datetime.utcnow()
    return trade


def _team_label(db, team_id):
    if not team_id:
        return "free agency"
    team = db.query(MynbaTeam).filter(MynbaTeam.id == team_id).first()
    return team.name if team else "another team"


def _roster_warnings(db, league, teams, moves):
    """Flag any team that would land off the league's target roster size."""
    target = league.roster_size or 11
    warnings = []

    outgoing = {tid: 0 for tid in teams}
    incoming = {tid: 0 for tid in teams}
    salary_delta = {tid: 0 for tid in teams}
    for player, from_team, to_team in moves:
        outgoing[from_team.id] += 1
        incoming[to_team.id] += 1
        salary_delta[from_team.id] -= player.salary or 0
        salary_delta[to_team.id] += player.salary or 0

    for team_id, team in sorted(teams.items(), key=lambda kv: kv[1].name):
        after = roster_count(db, league.id, team_id) - outgoing[team_id] + incoming[team_id]
        if after != target:
            direction = "over" if after > target else "under"
            warnings.append(f"{team.name} would be at {after} players ({direction} {target}).")

    if league.enforce_salary_cap and league.salary_cap:
        for team_id, team in sorted(teams.items(), key=lambda kv: kv[1].name):
            after = team_salary(db, league.id, team_id) + salary_delta[team_id]
            if after > league.salary_cap:
                warnings.append(f"{team.name} would be ${after - league.salary_cap:,} over the cap.")
    return warnings


def _seat(db, trade, team):
    row = db.query(MynbaTradeTeam).filter(
        MynbaTradeTeam.trade_id == trade.id, MynbaTradeTeam.team_id == team.id
    ).first()
    if row is None:
        raise LeagueError(f"The {team.name} are not part of {trade.ref}.", code="not_a_party")
    return row


def accept_trade(db, trade, actor_discord_id, team=None):
    """One team signs off. The trade advances only once every team has."""
    if trade.status != TRADE_PENDING_GM:
        raise LeagueError(f"Trade {trade.ref} is not waiting on a GM ({_pretty_status(trade.status)}).", code="bad_state")

    if team is not None:
        seat = _seat(db, trade, team)
        if seat.is_proposer:
            raise LeagueError("You proposed this trade — you don't accept your own offer.", code="own_trade")
        if seat.accepted_at:
            raise LeagueError(f"The {team.name} already accepted {trade.ref}.", code="already_accepted")
        seat.accepted_at = datetime.utcnow()
        seat.accepted_by_discord_id = str(actor_discord_id) if actor_discord_id else None
    else:
        # Commissioner accepting on everyone's behalf.
        now = datetime.utcnow()
        for seat in teams_awaiting(db, trade):
            seat.accepted_at = now
            seat.accepted_by_discord_id = str(actor_discord_id) if actor_discord_id else None

    trade.accepted_by_discord_id = str(actor_discord_id) if actor_discord_id else None
    db.flush()
    _advance_if_all_accepted(db, trade)
    return trade


def decline_trade(db, trade, actor_discord_id, reason=None, team=None):
    """Any one team can kill the whole trade."""
    if trade.status != TRADE_PENDING_GM:
        raise LeagueError(f"Trade {trade.ref} is not waiting on a GM ({_pretty_status(trade.status)}).", code="bad_state")
    if team is not None:
        seat = _seat(db, trade, team)
        seat.declined_at = datetime.utcnow()
        if reason is None:
            reason = f"Declined by the {team.name}."
    return _close(trade, TRADE_DECLINED, actor_discord_id, reason)


def cancel_trade(db, trade, actor_discord_id, reason=None):
    if trade.status not in (TRADE_PENDING_GM, TRADE_PENDING_COMMISSIONER):
        raise LeagueError(f"Trade {trade.ref} can no longer be withdrawn ({_pretty_status(trade.status)}).", code="bad_state")
    return _close(trade, TRADE_CANCELLED, actor_discord_id, reason)


def veto_trade(db, trade, actor_discord_id, reason=None):
    if trade.status not in (TRADE_PENDING_COMMISSIONER, TRADE_APPROVED_WINDOW, TRADE_PROTESTED):
        raise LeagueError(f"Trade {trade.ref} cannot be vetoed now ({_pretty_status(trade.status)}).", code="bad_state")
    return _close(trade, TRADE_VETOED, actor_discord_id, reason)


def _close(trade, status, actor_discord_id, reason):
    trade.status = status
    trade.resolved_by_discord_id = str(actor_discord_id) if actor_discord_id else None
    trade.resolution_reason = reason
    return trade


def approve_trade(db, trade, league, actor_discord_id, skip_window=False):
    """Commissioner sign-off. Opens the protest window; does not move anyone yet."""
    if trade.status != TRADE_PENDING_COMMISSIONER:
        raise LeagueError(f"Trade {trade.ref} is not waiting on a commissioner ({_pretty_status(trade.status)}).", code="bad_state")
    if actor_discord_id and str(actor_discord_id) == (trade.proposer_discord_id or ""):
        raise LeagueError("You proposed this trade — another commissioner has to approve it.", code="self_approval")

    now = datetime.utcnow()
    trade.approved_by_discord_id = str(actor_discord_id) if actor_discord_id else None
    trade.approved_at = now

    window = 0 if skip_window else (league.protest_window_hours or 0)
    if window <= 0:
        return execute_trade(db, trade, actor_discord_id)

    trade.status = TRADE_APPROVED_WINDOW
    trade.execute_after = now + timedelta(hours=window)
    return trade


def force_execute(db, trade, actor_discord_id=None):
    """Commissioner closes the protest window early and applies the trade now."""
    if trade.status != TRADE_APPROVED_WINDOW:
        raise LeagueError(
            f"Trade {trade.ref} is not sitting in a protest window ({_pretty_status(trade.status)}).",
            code="bad_state",
        )
    return execute_trade(db, trade, actor_discord_id, note="Commissioner skipped the protest window.")


def protest_trade(db, trade, team, actor_discord_id, reason=None):
    if trade.status != TRADE_APPROVED_WINDOW:
        raise LeagueError(f"Trade {trade.ref} is not open to protest ({_pretty_status(trade.status)}).", code="bad_state")
    if is_party(db, trade, team):
        raise LeagueError("You agreed to this trade — you cannot protest it.", code="party_to_trade")
    trade.status = TRADE_PROTESTED
    trade.resolution_reason = reason
    trade.execute_after = None
    db.add(MynbaTradeVote(trade_id=trade.id, team_id=team.id,
                          discord_id=str(actor_discord_id) if actor_discord_id else None, uphold=False))
    return trade


def cast_vote(db, trade, team, uphold, actor_discord_id=None):
    if trade.status != TRADE_PROTESTED:
        raise LeagueError(f"Trade {trade.ref} is not being voted on ({_pretty_status(trade.status)}).", code="bad_state")
    vote = db.query(MynbaTradeVote).filter(
        MynbaTradeVote.trade_id == trade.id, MynbaTradeVote.team_id == team.id
    ).first()
    if vote:
        vote.uphold = bool(uphold)
    else:
        db.add(MynbaTradeVote(trade_id=trade.id, team_id=team.id,
                              discord_id=str(actor_discord_id) if actor_discord_id else None,
                              uphold=bool(uphold)))
    db.flush()
    return vote_tally(db, trade)


def is_party(db, trade, team):
    """Is this team in the trade? Covers three-team deals, not just the two named columns."""
    return db.query(MynbaTradeTeam).filter(
        MynbaTradeTeam.trade_id == trade.id, MynbaTradeTeam.team_id == team.id
    ).first() is not None


def party_team_ids(db, trade):
    rows = db.query(MynbaTradeTeam.team_id).filter(MynbaTradeTeam.trade_id == trade.id).all()
    ids = [r[0] for r in rows]
    # Fall back to the named columns for any trade recorded before seats existed.
    return ids or [trade.proposer_team_id, trade.counterparty_team_id]


def vote_tally(db, trade):
    votes = db.query(MynbaTradeVote).filter(MynbaTradeVote.trade_id == trade.id).all()
    uphold = sum(1 for v in votes if v.uphold)
    overturn = sum(1 for v in votes if not v.uphold)
    eligible = db.query(func.count(MynbaTeam.id)).filter(
        MynbaTeam.league_id == trade.league_id,
        MynbaTeam.is_cpu.is_(False),
        MynbaTeam.id.notin_(party_team_ids(db, trade)),
    ).scalar() or 0
    return {"uphold": uphold, "overturn": overturn, "cast": len(votes), "eligible": eligible}


def resolve_protest(db, trade, actor_discord_id=None):
    """Close the vote: a majority of cast votes to overturn kills the trade."""
    if trade.status != TRADE_PROTESTED:
        raise LeagueError(f"Trade {trade.ref} is not being voted on ({_pretty_status(trade.status)}).", code="bad_state")
    tally = vote_tally(db, trade)
    if tally["overturn"] > tally["uphold"]:
        _close(trade, TRADE_OVERTURNED, actor_discord_id,
               f"League vote: {tally['overturn']} to overturn, {tally['uphold']} to uphold.")
        return trade, tally
    execute_trade(db, trade, actor_discord_id,
                  note=f"League vote upheld it {tally['uphold']}–{tally['overturn']}.")
    return trade, tally


def execute_trade(db, trade, actor_discord_id=None, note=None):
    """Move the players. The only function in the codebase that changes a roster.

    Re-checks every player against the roster it locked, because an earlier trade
    may have moved somebody while this one sat in the protest window. If that
    happened the trade is voided rather than half-applied.
    """
    assets = db.query(MynbaTradeAsset).filter(MynbaTradeAsset.trade_id == trade.id).all()
    if not assets:
        raise LeagueError(f"Trade {trade.ref} has no players in it.", code="empty")

    player_ids = [a.player_id for a in assets]
    locked = (db.query(MynbaPlayer)
              .filter(MynbaPlayer.id.in_(player_ids))
              .with_for_update()
              .all())
    by_id = {p.id: p for p in locked}

    stale = []
    for asset in assets:
        player = by_id.get(asset.player_id)
        if player is None:
            stale.append(f"{asset.player_name} is no longer in the league")
        elif player.team_id != asset.from_team_id:
            stale.append(f"{asset.player_name} has already moved to {_team_label(db, player.team_id)}")

    if stale:
        _close(trade, TRADE_VOIDED, actor_discord_id, "; ".join(stale))
        return trade

    for asset in assets:
        _apply_move(db, trade.league_id, by_id[asset.player_id], asset.to_team_id,
                    kind=TXN_TRADE, trade=trade, actor_discord_id=actor_discord_id, note=note)

    trade.status = TRADE_EXECUTED
    trade.executed_at = datetime.utcnow()
    trade.execute_after = None
    return trade


def _apply_move(db, league_id, player, to_team_id, kind, trade=None, actor_discord_id=None, note=None):
    """Move one player and log it. Every roster change goes through here."""
    from_team_id = player.team_id
    from_name = _team_label(db, from_team_id) if from_team_id else None
    to_name = _team_label(db, to_team_id) if to_team_id else None

    player.team_id = to_team_id
    # Untouchable status belongs to the team that set it, not the player.
    player.is_untouchable = False
    db.add(MynbaTransaction(
        league_id=league_id, kind=kind,
        player_id=player.id, player_name=player.name,
        from_team_id=from_team_id, from_team_name=from_name,
        to_team_id=to_team_id, to_team_name=to_name,
        trade_id=trade.id if trade else None,
        trade_ref=trade.ref if trade else None,
        actor_discord_id=str(actor_discord_id) if actor_discord_id else None,
        note=note,
    ))
    return player


def sign_free_agent(db, league, player, team, actor_discord_id=None):
    if player.team_id is not None:
        raise LeagueError(f"{player.name} is on the {_team_label(db, player.team_id)}, not a free agent.", code="not_fa")
    return _apply_move(db, league.id, player, team.id, kind=TXN_SIGN, actor_discord_id=actor_discord_id)


def release_player(db, league, player, actor_discord_id=None, note=None):
    if player.team_id is None:
        raise LeagueError(f"{player.name} is already a free agent.", code="already_fa")
    return _apply_move(db, league.id, player, None, kind=TXN_RELEASE, actor_discord_id=actor_discord_id, note=note)


def admin_move_player(db, league, player, team, actor_discord_id=None, note=None):
    """Commissioner override — fix a roster without a trade. Still logged."""
    return _apply_move(db, league.id, player, team.id if team else None,
                       kind=TXN_ADMIN_MOVE, actor_discord_id=actor_discord_id, note=note)


def set_untouchable(db, league, player, untouchable):
    """Mark or clear a player as untradeable, within the league's per-team limit."""
    untouchable = bool(untouchable)
    if player.is_untouchable == untouchable:
        return player
    if untouchable:
        if player.team_id is None:
            raise LeagueError(f"{player.name} is a free agent — only rostered players can be untouchable.",
                              code="not_rostered")
        limit = league.untouchables_per_team or 0
        current = db.query(func.count(MynbaPlayer.id)).filter(
            MynbaPlayer.league_id == league.id,
            MynbaPlayer.team_id == player.team_id,
            MynbaPlayer.is_untouchable.is_(True),
        ).scalar() or 0
        if current >= limit:
            raise LeagueError(
                f"The {_team_label(db, player.team_id)} already have {current} untouchable"
                f"{'s' if current != 1 else ''} — the limit is {limit}. Clear one first.",
                code="untouchable_limit",
            )
        if player.id in players_in_open_trades(db, league.id):
            raise LeagueError(f"{player.name} is in a pending trade. Resolve it first.", code="already_pending")
    player.is_untouchable = untouchable
    return player


def sweep_trades(db, league):
    """Expire stale proposals and execute any protest window that has run out.

    Called on a timer by the bot. Returns what changed so it can post about it.
    """
    now = datetime.utcnow()
    expired, executed = [], []

    stale = db.query(MynbaTrade).filter(
        MynbaTrade.league_id == league.id,
        MynbaTrade.status.in_([TRADE_PENDING_GM, TRADE_PENDING_COMMISSIONER]),
        MynbaTrade.expires_at.isnot(None),
        MynbaTrade.expires_at <= now,
    ).all()
    for trade in stale:
        _close(trade, TRADE_EXPIRED, None, "Nobody responded in time.")
        expired.append(trade)

    matured = db.query(MynbaTrade).filter(
        MynbaTrade.league_id == league.id,
        MynbaTrade.status == TRADE_APPROVED_WINDOW,
        MynbaTrade.execute_after.isnot(None),
        MynbaTrade.execute_after <= now,
    ).all()
    # Rosters don't move during the weekly lock; these run once the sim is done.
    held = league.lock_roster_moves and lock_status(league)["locked"]
    for trade in ([] if held else matured):
        execute_trade(db, trade, None, note="Protest window closed with no objections.")
        executed.append(trade)

    return {"expired": expired, "executed": executed}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

STATUS_LABELS = {
    TRADE_PENDING_GM: "Waiting on the other GM",
    TRADE_PENDING_COMMISSIONER: "Waiting on a commissioner",
    TRADE_APPROVED_WINDOW: "Approved — protest window open",
    TRADE_PROTESTED: "Protested — league voting",
    TRADE_EXECUTED: "Done",
    TRADE_DECLINED: "Declined",
    TRADE_VETOED: "Vetoed",
    TRADE_CANCELLED: "Withdrawn",
    TRADE_EXPIRED: "Expired",
    TRADE_VOIDED: "Voided — a player had already moved",
    TRADE_OVERTURNED: "Overturned by league vote",
}


def _pretty_status(status):
    return STATUS_LABELS.get(status, status)


def player_json(player, team=None):
    return {
        "id": player.id,
        "name": player.name,
        "team_id": player.team_id,
        "team": team.name if team else None,
        "team_abbrev": team.abbrev if team else None,
        "position": player.position,
        "secondary_position": player.secondary_position,
        "ovr": player.ovr,
        "age": player.age,
        "salary": player.salary,
        "contract_years": player.contract_years,
        "jersey": player.jersey,
        "is_rookie": bool(player.is_rookie),
        "is_untouchable": bool(player.is_untouchable),
        "is_free_agent": player.team_id is None,
    }


def team_json(team, roster_size=None, count=None):
    return {
        "id": team.id,
        "name": team.name,
        "full_name": team.full_name,
        "abbrev": team.abbrev,
        "conference": team.conference,
        "is_cpu": team.is_cpu,
        "gm_discord_id": team.gm_discord_id,
        "gm_display_name": team.gm_display_name,
        "roster_count": count,
        "roster_target": roster_size,
    }


def trade_json(db, trade, include_assets=True):
    seats = db.query(MynbaTradeTeam).filter(MynbaTradeTeam.trade_id == trade.id).all()
    team_ids = {s.team_id for s in seats} | {trade.proposer_team_id, trade.counterparty_team_id}
    teams = {t.id: t for t in db.query(MynbaTeam).filter(MynbaTeam.id.in_(team_ids)).all()}

    proposer = teams.get(trade.proposer_team_id)
    counterparty = teams.get(trade.counterparty_team_id)

    payload = {
        "id": trade.id,
        "ref": trade.ref,
        "status": trade.status,
        "status_label": _pretty_status(trade.status),
        "is_open": trade.status in TRADE_OPEN_STATUSES,
        "team_count": trade.team_count or len(seats) or 2,
        "proposer_team": team_json(proposer) if proposer else None,
        "counterparty_team": team_json(counterparty) if counterparty else None,
        "proposer_discord_id": trade.proposer_discord_id,
        "note": trade.note,
        "resolution_reason": trade.resolution_reason,
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
        "accepted_at": trade.accepted_at.isoformat() if trade.accepted_at else None,
        "approved_at": trade.approved_at.isoformat() if trade.approved_at else None,
        "executed_at": trade.executed_at.isoformat() if trade.executed_at else None,
        "expires_at": trade.expires_at.isoformat() if trade.expires_at else None,
        "execute_after": trade.execute_after.isoformat() if trade.execute_after else None,
    }

    payload["teams"] = [
        {
            **team_json(teams[s.team_id]),
            "is_proposer": s.is_proposer,
            "is_cpu": s.is_cpu,
            "accepted": s.accepted_at is not None,
            "declined": s.declined_at is not None,
            "accepted_by_discord_id": s.accepted_by_discord_id,
        }
        for s in sorted(seats, key=lambda r: (not r.is_proposer, teams[r.team_id].name))
        if s.team_id in teams
    ]
    payload["awaiting"] = [t["name"] for t in payload["teams"] if not t["accepted"] and not t["declined"]]

    if include_assets:
        assets = db.query(MynbaTradeAsset).filter(MynbaTradeAsset.trade_id == trade.id).all()

        # Per-team view: what each side gives up and picks up. Reads correctly
        # whether the trade has two teams or three.
        movement = {}
        for asset in assets:
            for team_id, bucket in ((asset.from_team_id, "out"), (asset.to_team_id, "in")):
                entry = movement.setdefault(team_id, {"out": [], "in": []})
                other = asset.to_team_id if bucket == "out" else asset.from_team_id
                entry[bucket].append({
                    "player": asset.player_name,
                    "team": teams[other].name if other in teams else None,
                })
        payload["movement"] = [
            {
                "team": teams[tid].name if tid in teams else None,
                "abbrev": teams[tid].abbrev if tid in teams else None,
                "sends": movement[tid]["out"],
                "gets": movement[tid]["in"],
            }
            for tid in [t["id"] for t in payload["teams"]] if tid in movement
        ]

        # Kept so two-team callers (and the old Discord card) still work.
        payload["sending"] = [a.player_name for a in assets if a.from_team_id == trade.proposer_team_id]
        payload["receiving"] = [a.player_name for a in assets if a.to_team_id == trade.proposer_team_id]

    if trade.status == TRADE_PROTESTED:
        payload["votes"] = vote_tally(db, trade)
    return payload


def transaction_json(txn):
    return {
        "id": txn.id,
        "kind": txn.kind,
        "player_name": txn.player_name,
        "from_team": txn.from_team_name,
        "to_team": txn.to_team_name,
        "trade_ref": txn.trade_ref,
        "note": txn.note,
        "created_at": txn.created_at.isoformat() if txn.created_at else None,
    }
