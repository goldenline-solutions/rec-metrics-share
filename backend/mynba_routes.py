"""
MyNBA league HTTP API.

Two callers, one authorization model. The Discord bot authenticates with the
shared bot token and names the acting user via `actor_discord_id`; the website
authenticates with the normal session cookie. Either way we end up with a Discord
id, and every permission check runs against the database — the bot's role checks
are for fast feedback in Discord, never for security.
"""
import json
import os
from contextlib import contextmanager

from flask import Blueprint, request, jsonify
from sqlalchemy import func

from db import SessionLocal
from models import User
from auth_utils import verify_session_token
from mynba_models import (
    MynbaLeague, MynbaCommissioner, MynbaTeam, MynbaPlayer,
    MynbaTrade, MynbaTransaction, MynbaGameplan, MynbaGame,
    TRADE_OPEN_STATUSES, TRADE_APPROVED_WINDOW, TRADE_PROTESTED,
)
import mynba_service as svc
import mynba_gameplan as gp
import mynba_games as games
import mynba_rules as rulebook
from mynba_schedule import roster_lock_message
import nba2k_service as ratings
from mynba_service import LeagueError, AmbiguousName
from nba2k_models import Nba2kPlayer, Nba2kSyncRun
from nba2k_service import RatingsApiError

mynba_bp = Blueprint("mynba", __name__, url_prefix="/api/mynba")


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Who is calling
# ---------------------------------------------------------------------------

class Actor:
    def __init__(self, discord_id=None, user_id=None, via="anonymous", display_name=None):
        self.discord_id = str(discord_id) if discord_id else None
        self.user_id = user_id
        self.via = via
        self.display_name = display_name

    @property
    def authenticated(self):
        return bool(self.discord_id or self.user_id)


def _bot_token_ok():
    token = os.getenv("INGEST_BOT_TOKEN", "").strip()
    if not token:
        return False
    auth = (request.headers.get("Authorization") or "").strip()
    return auth in (f"Bearer {token}", token)


def _payload():
    return request.get_json(silent=True) or {}


def get_actor(db):
    """Resolve the acting user from either the bot token or a session cookie."""
    if _bot_token_ok():
        body = _payload()
        discord_id = body.get("actor_discord_id") or request.args.get("actor_discord_id")
        name = body.get("actor_display_name")
        return Actor(discord_id=discord_id, via="bot", display_name=name)

    token = request.cookies.get("access_token")
    if token:
        valid, user_id = verify_session_token(token)
        if valid and user_id:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                return Actor(discord_id=user.discord_id, user_id=user.id, via="web",
                             display_name=user.display_name or user.discord_username)
    return Actor()


def _site_admin(db, actor):
    """A site-wide admin (users.roles contains "admin") always has commissioner powers."""
    if not actor.user_id:
        return False
    user = db.query(User).filter(User.id == actor.user_id).first()
    if not user or not user.roles:
        return False
    try:
        return "admin" in json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        return False


def leagues_for_actor(db, actor):
    """Every league this caller belongs to, oldest first.

    A site admin can see them all; everyone else sees the ones where they run a
    team or hold a commissioner seat.
    """
    if not actor or not (actor.discord_id or actor.user_id):
        return []

    all_leagues = db.query(MynbaLeague).order_by(MynbaLeague.created_at).all()
    if _site_admin(db, actor):
        return all_leagues
    return [
        lg for lg in all_leagues
        if svc.team_for_gm(db, lg, actor.discord_id) or svc.is_commissioner(db, lg, actor.discord_id)
    ]


def league_choice_json(db, league):
    return {"guild_id": league.guild_id, "name": league.name, "id": league.id}


def resolve_league(db, actor=None):
    """Which league this request is about.

    Order: an explicit guild_id, then the single league this caller belongs to,
    then — only when nobody is identified — the single league that exists.

    Counting leagues is deliberately the last resort. Picking "the only league"
    worked right up until a second one was created, and then it broke the portal
    for everyone rather than just for people in both.
    """
    guild_id = _payload().get("guild_id") or request.args.get("guild_id")
    if guild_id:
        league = svc.get_league(db, guild_id)
        if not league:
            raise LeagueError("No league is set up for this server yet.", code="no_league")
        return league

    if actor is None:
        actor = get_actor(db)

    mine = leagues_for_actor(db, actor)
    if len(mine) == 1:
        return mine[0]
    if len(mine) > 1:
        raise LeagueError(
            "You're in more than one league — pick which one.",
            code="pick_league",
            extra={"leagues": [league_choice_json(db, lg) for lg in mine]},
        )

    leagues = db.query(MynbaLeague).order_by(MynbaLeague.created_at).all()
    if len(leagues) == 1:
        return leagues[0]
    if not leagues:
        raise LeagueError("No league has been set up yet.", code="no_league")
    raise LeagueError(
        "More than one league exists — say which with guild_id.",
        code="pick_league",
        extra={"leagues": [league_choice_json(db, lg) for lg in leagues]},
    )


class Access:
    """What this caller may do in this league."""

    def __init__(self, db, league, actor):
        self.actor = actor
        self.league = league
        self.team = svc.team_for_gm(db, league, actor.discord_id) if actor.discord_id else None
        self.is_commissioner = svc.is_commissioner(db, league, actor.discord_id) or _site_admin(db, actor)
        self.is_gm = self.team is not None

    @property
    def is_member(self):
        return self.is_gm or self.is_commissioner


def _forbidden(message):
    return jsonify({"error": message}), 403


@mynba_bp.errorhandler(RatingsApiError)
def _ratings_error(err):
    return jsonify({"error": str(err), "code": "ratings_api"}), 502


@mynba_bp.errorhandler(LeagueError)
def _league_error(err):
    body = {"error": err.message, "code": err.code}
    body.update(err.extra)
    return jsonify(body), 404 if err.code in ("no_league", "no_game") else 409


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

@mynba_bp.route("/leagues", methods=["POST"])
def create_league():
    body = _payload()
    guild_id = body.get("guild_id")
    if not guild_id:
        return jsonify({"error": "guild_id is required."}), 400

    with session_scope() as db:
        actor = get_actor(db)
        if not (_bot_token_ok() or _site_admin(db, actor)):
            return _forbidden("Only a server admin can create the league.")

        league = svc.create_league(
            db, guild_id,
            name=body.get("name"),
            seed_teams=body.get("seed_teams", True),
            commissioner_role_id=body.get("commissioner_role_id"),
            gm_role_id=body.get("gm_role_id"),
            trade_channel_id=body.get("trade_channel_id"),
            approvals_channel_id=body.get("approvals_channel_id"),
            roster_size=body.get("roster_size"),
        )
        # Whoever sets the league up is its first commissioner.
        if actor.discord_id:
            db.add(MynbaCommissioner(league_id=league.id, discord_id=actor.discord_id,
                                     user_id=actor.user_id, display_name=actor.display_name))
        db.flush()
        return jsonify({"league": _league_json(db, league), "teams_seeded": 30}), 201


def _league_json(db, league):
    return {
        "id": league.id,
        "guild_id": league.guild_id,
        "name": league.name,
        "roster_size": league.roster_size,
        "enforce_roster_size": league.enforce_roster_size,
        "salary_cap": league.salary_cap,
        "enforce_salary_cap": league.enforce_salary_cap,
        "trades_locked": league.trades_locked,
        "trades_locked_reason": league.trades_locked_reason,
        "protest_window_hours": league.protest_window_hours,
        "proposal_ttl_hours": league.proposal_ttl_hours,
        "trade_channel_id": league.trade_channel_id,
        "approvals_channel_id": league.approvals_channel_id,
        "commissioner_role_id": league.commissioner_role_id,
        "untouchables_per_team": league.untouchables_per_team,
        "sim_weekday": league.sim_weekday,
        "gameplan_lock_days": league.gameplan_lock_days,
        "gameplan_lock_minute": league.gameplan_lock_minute,
        "lock_roster_moves": league.lock_roster_moves,
        "roster_lock_message": roster_lock_message(league),
        "gameplan_lock_override": league.gameplan_lock_override,
        "gameplan_channel_id": league.gameplan_channel_id,
        "sixth_man_min_minutes": league.sixth_man_min_minutes,
        "bench_min_minutes": league.bench_min_minutes,
        "max_trade_teams": league.max_trade_teams,
        "sim_hour": league.sim_hour,
        "gameplan_lock": gp.lock_status(league),
    }


@mynba_bp.route("/league", methods=["GET"])
def get_league_config():
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")
        return jsonify({"league": _league_json(db, league)})


@mynba_bp.route("/league", methods=["PATCH"])
def update_league_config():
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not access.is_commissioner:
            return _forbidden("Only a commissioner can change league settings.")

        for field in ("name", "enforce_roster_size", "salary_cap",
                      "enforce_salary_cap", "trades_locked", "trades_locked_reason",
                      "trade_channel_id", "approvals_channel_id", "commissioner_role_id",
                      "gm_role_id", "gameplan_lock_override", "gameplan_channel_id",
                      "lock_roster_moves"):
            if field in body:
                setattr(league, field, body[field])
        # Numbers the site enforces get range-checked before they're stored.
        for field in rulebook.SETTING_LIMITS:
            if field in body:
                setattr(league, field, rulebook.check_setting(field, body[field]))
        db.flush()
        return jsonify({"league": _league_json(db, league)})


@mynba_bp.route("/commissioners", methods=["POST"])
def add_commissioner():
    body = _payload()
    discord_id = body.get("discord_id")
    if not discord_id:
        return jsonify({"error": "discord_id is required."}), 400

    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not access.is_commissioner:
            return _forbidden("Only a commissioner can add another commissioner.")
        if svc.is_commissioner(db, league, discord_id):
            return jsonify({"ok": True, "already": True})
        db.add(MynbaCommissioner(league_id=league.id, discord_id=str(discord_id),
                                 display_name=body.get("display_name")))
        db.flush()
        return jsonify({"ok": True}), 201


@mynba_bp.route("/teams/<team_id>/gm", methods=["POST"])
def set_team_gm(team_id):
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not access.is_commissioner:
            return _forbidden("Only a commissioner can assign a GM.")

        team = db.query(MynbaTeam).filter(MynbaTeam.id == team_id, MynbaTeam.league_id == league.id).first()
        if not team:
            return jsonify({"error": "No such team."}), 404

        discord_id = body.get("discord_id")
        if discord_id:
            taken = db.query(MynbaTeam).filter(
                MynbaTeam.league_id == league.id,
                MynbaTeam.gm_discord_id == str(discord_id),
                MynbaTeam.id != team.id,
            ).first()
            if taken:
                return jsonify({"error": f"That person already runs the {taken.name}."}), 409
            team.gm_discord_id = str(discord_id)
            team.gm_display_name = body.get("display_name")
            team.is_cpu = False
        else:
            team.gm_discord_id = None
            team.gm_display_name = None
            team.is_cpu = True
        if "discord_role_id" in body:
            team.discord_role_id = body["discord_role_id"]
        db.flush()
        return jsonify({"team": svc.team_json(team)})


@mynba_bp.route("/import", methods=["POST"])
def import_rosters():
    """Seed rosters from the league spreadsheet. CSV as a file upload or raw body text."""
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        if not access.is_commissioner:
            return _forbidden("Only a commissioner can import rosters.")

        if "file" in request.files:
            csv_text = request.files["file"].read().decode("utf-8-sig", errors="replace")
        else:
            csv_text = _payload().get("csv") or request.get_data(as_text=True)
        if not (csv_text or "").strip():
            return jsonify({"error": "No CSV content received."}), 400

        dry_run = str(request.args.get("dry_run", "")).lower() in ("1", "true", "yes")
        summary = svc.import_roster_csv(
            db, league, csv_text,
            actor_discord_id=actor.discord_id,
            dry_run=dry_run,
            replace=str(request.args.get("replace", "")).lower() in ("1", "true", "yes"),
        )
        return jsonify(summary)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@mynba_bp.route("/me", methods=["GET"])
def whoami():
    """What the caller is allowed to do — the portal calls this before rendering.

    Three states that look alike from the outside but need different fixes:
    no league exists at all, the caller is in several and has to pick one, or
    they're signed in but not part of the league they landed on.
    """
    with session_scope() as db:
        actor = get_actor(db)
        mine = leagues_for_actor(db, actor)
        choices = [league_choice_json(db, lg) for lg in mine]

        try:
            league = resolve_league(db, actor)
        except LeagueError as err:
            return jsonify({
                "league": None,
                "has_league": err.code != "no_league",
                "needs_choice": err.code == "pick_league",
                "leagues": err.extra.get("leagues", choices),
                "reason": err.message,
                "is_member": False,
                "is_gm": False,
                "is_commissioner": False,
                "is_site_admin": _site_admin(db, actor),
                "discord_id": actor.discord_id,
                "display_name": actor.display_name,
                "team": None,
            })

        access = Access(db, league, actor)
        return jsonify({
            "league": _league_json(db, league) if access.is_member else {
                "name": league.name, "guild_id": league.guild_id,
            },
            "has_league": True,
            "needs_choice": False,
            "leagues": choices,
            "discord_id": actor.discord_id,
            "display_name": actor.display_name,
            "is_member": access.is_member,
            "is_gm": access.is_gm,
            "is_commissioner": access.is_commissioner,
            "is_site_admin": _site_admin(db, actor),
            "team": svc.team_json(access.team) if access.team else None,
        })


@mynba_bp.route("/leagues", methods=["GET"])
def my_leagues():
    """Leagues the caller can open, for the portal's league picker."""
    with session_scope() as db:
        actor = get_actor(db)
        return jsonify({"leagues": [league_choice_json(db, lg) for lg in leagues_for_actor(db, actor)]})


@mynba_bp.route("/teams", methods=["GET"])
def list_teams():
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")

        teams = db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id).order_by(MynbaTeam.name).all()
        counts = dict(
            db.query(MynbaPlayer.team_id, func.count(MynbaPlayer.id))
            .filter(MynbaPlayer.league_id == league.id)
            .group_by(MynbaPlayer.team_id).all()
        )
        return jsonify({
            "teams": [svc.team_json(t, league.roster_size, counts.get(t.id, 0)) for t in teams],
            "free_agent_count": counts.get(None, 0),
            "roster_size": league.roster_size,
        })


@mynba_bp.route("/teams/<team_ref>/roster", methods=["GET"])
def team_roster(team_ref):
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")

        team = db.query(MynbaTeam).filter(MynbaTeam.id == team_ref, MynbaTeam.league_id == league.id).first()
        if not team:
            team = svc.resolve_team(db, league.id, team_ref)

        players = (db.query(MynbaPlayer)
                   .filter(MynbaPlayer.league_id == league.id, MynbaPlayer.team_id == team.id)
                   .order_by(MynbaPlayer.ovr.desc().nullslast(), MynbaPlayer.name)
                   .all())
        return jsonify({
            "team": svc.team_json(team, league.roster_size, len(players)),
            "players": [svc.player_json(p, team) for p in players],
        })


@mynba_bp.route("/free-agents", methods=["GET"])
def free_agents():
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")

        q = db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id, MynbaPlayer.team_id.is_(None))
        position = request.args.get("position")
        if position:
            q = q.filter(MynbaPlayer.position == position.upper())
        players = q.order_by(MynbaPlayer.ovr.desc().nullslast(), MynbaPlayer.name).limit(500).all()
        return jsonify({"players": [svc.player_json(p) for p in players], "count": len(players)})


@mynba_bp.route("/players/search", methods=["GET"])
def player_search():
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")

        team_id = request.args.get("team_id")
        players = svc.search_players(db, league.id, request.args.get("q", ""),
                                     limit=int(request.args.get("limit", 25)))
        if team_id:
            players = [p for p in players if p.team_id == team_id]
        teams = {t.id: t for t in db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id).all()}
        return jsonify({"players": [svc.player_json(p, teams.get(p.team_id)) for p in players]})


@mynba_bp.route("/transactions", methods=["GET"])
def transactions():
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")

        q = db.query(MynbaTransaction).filter(MynbaTransaction.league_id == league.id)
        team_id = request.args.get("team_id")
        if team_id:
            q = q.filter((MynbaTransaction.from_team_id == team_id) | (MynbaTransaction.to_team_id == team_id))
        rows = q.order_by(MynbaTransaction.created_at.desc()).limit(int(request.args.get("limit", 100))).all()
        return jsonify({"transactions": [svc.transaction_json(t) for t in rows]})


@mynba_bp.route("/trades", methods=["GET"])
def list_trades():
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")

        q = db.query(MynbaTrade).filter(MynbaTrade.league_id == league.id)
        status = request.args.get("status")
        if status == "open":
            q = q.filter(MynbaTrade.status.in_(TRADE_OPEN_STATUSES))
        elif status:
            q = q.filter(MynbaTrade.status == status)
        if request.args.get("mine") and access.team:
            q = q.filter((MynbaTrade.proposer_team_id == access.team.id) |
                         (MynbaTrade.counterparty_team_id == access.team.id))

        trades = q.order_by(MynbaTrade.created_at.desc()).limit(int(request.args.get("limit", 50))).all()
        return jsonify({"trades": [svc.trade_json(db, t) for t in trades]})


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

def _resolve_side(db, league, team, names):
    """Turn a list of typed names into players, failing loudly on ambiguity."""
    players, problems = [], []
    for raw in names:
        if not str(raw).strip():
            continue
        try:
            players.append(svc.resolve_player(db, league.id, raw, team_id=team.id))
        except AmbiguousName as err:
            problems.append(err)
        except LeagueError as err:
            problems.append(err)
    if problems:
        raise problems[0]
    return players


def _names(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [part.strip() for part in str(value).split(",") if part.strip()]


@mynba_bp.route("/trades", methods=["POST"])
def propose_trade():
    """Create a proposal.

    Two shapes are accepted. The simple one, unchanged:
        {"with_team": "Knicks", "send": [...], "receive": [...]}
    And the general one, which is how three-team deals arrive:
        {"legs": [{"from": "Bulls", "to": "Knicks", "players": ["Jordan"]}, ...]}
    """
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)

        if body.get("from_team"):
            proposer = svc.resolve_team(db, league.id, body["from_team"])
        else:
            proposer = access.team
        if not proposer:
            return _forbidden("You don't run a team. Ask a commissioner to assign you one.")
        if not access.is_commissioner and (not access.team or access.team.id != proposer.id):
            return _forbidden(f"You don't run the {proposer.name}.")

        if body.get("moves"):
            # {"moves": [{"player": "Jordan", "to": "Knicks"}, ...]}
            # The origin is whichever team currently holds the player, so callers
            # never have to state it and can never state it wrongly.
            grouped = {}
            for move in body["moves"]:
                player = svc.resolve_player(db, league.id, move.get("player"))
                to_team = svc.resolve_team(db, league.id, move.get("to"))
                if player.team_id is None:
                    raise LeagueError(
                        f"{player.name} is a free agent — sign him instead of trading for him.",
                        code="free_agent",
                    )
                from_team = db.query(MynbaTeam).filter(MynbaTeam.id == player.team_id).first()
                grouped.setdefault((from_team.id, to_team.id), {
                    "from": from_team, "to": to_team, "players": []
                })["players"].append(player)
            legs = list(grouped.values())
            if not legs:
                return jsonify({"error": "No players in that trade."}), 400
        elif body.get("legs"):
            legs = []
            for raw in body["legs"]:
                from_team = svc.resolve_team(db, league.id, raw.get("from"))
                to_team = svc.resolve_team(db, league.id, raw.get("to"))
                players = _resolve_side(db, league, from_team, _names(raw.get("players")))
                if players:
                    legs.append({"from": from_team, "to": to_team, "players": players})
            if not legs:
                return jsonify({"error": "None of those legs had players in them."}), 400
        else:
            counterparty = svc.resolve_team(db, league.id, body.get("with_team") or body.get("team"))
            send = _resolve_side(db, league, proposer, _names(body.get("send")))
            receive = _resolve_side(db, league, counterparty, _names(body.get("receive")))
            legs = []
            if send:
                legs.append({"from": proposer, "to": counterparty, "players": send})
            if receive:
                legs.append({"from": counterparty, "to": proposer, "players": receive})

        trade, warnings = svc.create_trade(
            db, league, proposer, legs,
            actor_discord_id=actor.discord_id, actor_user_id=actor.user_id,
            note=body.get("note"),
        )
        db.flush()
        return jsonify({"trade": svc.trade_json(db, trade), "warnings": warnings}), 201


def _load_trade(db, league, trade_ref):
    trade = db.query(MynbaTrade).filter(
        MynbaTrade.league_id == league.id,
        (MynbaTrade.id == trade_ref) | (MynbaTrade.ref == trade_ref.upper()),
    ).first()
    if not trade:
        raise LeagueError(f'No trade called "{trade_ref}".', code="no_trade")
    return trade


@mynba_bp.route("/trades/<trade_ref>/accept", methods=["POST"])
def accept(trade_ref):
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        trade = _load_trade(db, league, trade_ref)

        locked = roster_lock_message(league)
        if locked and not access.is_commissioner:
            return jsonify({"error": locked, "code": "locked"}), 409
        if access.team and svc.is_party(db, trade, access.team):
            svc.accept_trade(db, trade, actor.discord_id, team=access.team)
        elif access.is_commissioner:
            svc.accept_trade(db, trade, actor.discord_id)
        else:
            return _forbidden("Only a GM in this trade can accept it.")
        db.flush()
        return jsonify({"trade": svc.trade_json(db, trade)})


@mynba_bp.route("/trades/<trade_ref>/decline", methods=["POST"])
def decline(trade_ref):
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        trade = _load_trade(db, league, trade_ref)

        team = access.team if (access.team and svc.is_party(db, trade, access.team)) else None
        if not team and not access.is_commissioner:
            return _forbidden("Only a GM in this trade can decline it.")
        svc.decline_trade(db, trade, actor.discord_id, _payload().get("reason"), team=team)
        db.flush()
        return jsonify({"trade": svc.trade_json(db, trade)})


@mynba_bp.route("/trades/<trade_ref>/cancel", methods=["POST"])
def cancel(trade_ref):
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        trade = _load_trade(db, league, trade_ref)

        own = access.team and access.team.id == trade.proposer_team_id
        if not (own or access.is_commissioner):
            return _forbidden("Only the proposing GM can withdraw this trade.")
        svc.cancel_trade(db, trade, actor.discord_id, _payload().get("reason"))
        db.flush()
        return jsonify({"trade": svc.trade_json(db, trade)})


@mynba_bp.route("/trades/<trade_ref>/approve", methods=["POST"])
def approve(trade_ref):
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        trade = _load_trade(db, league, trade_ref)

        if not access.is_commissioner:
            return _forbidden("Only a commissioner can approve a trade.")
        svc.approve_trade(db, trade, league, actor.discord_id,
                          skip_window=bool(_payload().get("skip_window")))
        db.flush()
        return jsonify({"trade": svc.trade_json(db, trade)})


@mynba_bp.route("/trades/<trade_ref>/veto", methods=["POST"])
def veto(trade_ref):
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        trade = _load_trade(db, league, trade_ref)

        if not access.is_commissioner:
            return _forbidden("Only a commissioner can veto a trade.")
        svc.veto_trade(db, trade, actor.discord_id, _payload().get("reason"))
        db.flush()
        return jsonify({"trade": svc.trade_json(db, trade)})


@mynba_bp.route("/trades/<trade_ref>/execute", methods=["POST"])
def execute_now(trade_ref):
    """Close an open protest window early and apply the trade."""
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        trade = _load_trade(db, league, trade_ref)

        if not access.is_commissioner:
            return _forbidden("Only a commissioner can execute a trade early.")
        svc.force_execute(db, trade, actor.discord_id)
        db.flush()
        return jsonify({"trade": svc.trade_json(db, trade)})


@mynba_bp.route("/trades/<trade_ref>/protest", methods=["POST"])
def protest(trade_ref):
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        trade = _load_trade(db, league, trade_ref)

        if not access.team:
            return _forbidden("Only a GM can protest a trade.")
        svc.protest_trade(db, trade, access.team, actor.discord_id, _payload().get("reason"))
        db.flush()
        return jsonify({"trade": svc.trade_json(db, trade)})


@mynba_bp.route("/trades/<trade_ref>/vote", methods=["POST"])
def vote(trade_ref):
    body = _payload()
    if "uphold" not in body:
        return jsonify({"error": "Send uphold: true or false."}), 400

    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        trade = _load_trade(db, league, trade_ref)

        if not access.team:
            return _forbidden("Only a GM can vote.")
        if svc.is_party(db, trade, access.team):
            return _forbidden("You're party to this trade — you don't get a vote.")
        tally = svc.cast_vote(db, trade, access.team, bool(body["uphold"]), actor.discord_id)
        db.flush()
        return jsonify({"trade": svc.trade_json(db, trade), "votes": tally})


@mynba_bp.route("/trades/<trade_ref>/resolve-protest", methods=["POST"])
def resolve_protest(trade_ref):
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        trade = _load_trade(db, league, trade_ref)

        if not access.is_commissioner:
            return _forbidden("Only a commissioner can close the vote.")
        trade, tally = svc.resolve_protest(db, trade, actor.discord_id)
        db.flush()
        return jsonify({"trade": svc.trade_json(db, trade), "votes": tally})


# ---------------------------------------------------------------------------
# Free agency + commissioner overrides
# ---------------------------------------------------------------------------

@mynba_bp.route("/players/<player_ref>/sign", methods=["POST"])
def sign(player_ref):
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)

        team = svc.resolve_team(db, league.id, body["team"]) if body.get("team") else access.team
        if not team:
            return _forbidden("You don't run a team.")
        if not access.is_commissioner and (not access.team or access.team.id != team.id):
            return _forbidden(f"You don't run the {team.name}.")
        locked = roster_lock_message(league)
        if locked and not access.is_commissioner:
            return jsonify({"error": locked.replace("Trading", "Signing"), "code": "locked"}), 409

        player = svc.resolve_player(db, league.id, player_ref)
        if player.team_id is not None:
            raise LeagueError(f"{player.name} isn't a free agent.", code="not_fa")

        # Optional: drop someone in the same step, so a full roster can still sign.
        released = None
        if body.get("release"):
            released = svc.resolve_player(db, league.id, body["release"], team_id=team.id)

        # Checked before anything moves: returning an error here still commits the session.
        count = db.query(MynbaPlayer).filter(MynbaPlayer.team_id == team.id).count() - (1 if released else 0)
        if count >= league.roster_size and not access.is_commissioner:
            return jsonify({
                "error": f"The {team.name} already have {count} players (max {league.roster_size}). "
                         "Pick someone to release.",
                "code": "roster_full",
            }), 409

        if released:
            svc.release_player(db, league, released, actor.discord_id, f"Released to sign {player.name}")
            db.flush()
        svc.sign_free_agent(db, league, player, team, actor.discord_id)
        db.flush()
        return jsonify({"player": svc.player_json(player, team),
                        "released": svc.player_json(released) if released else None})


@mynba_bp.route("/players/<player_ref>/release", methods=["POST"])
def release(player_ref):
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)

        player = svc.resolve_player(db, league.id, player_ref)
        if not access.is_commissioner and (not access.team or access.team.id != player.team_id):
            return _forbidden("You can only release your own players.")
        locked = roster_lock_message(league)
        if locked and not access.is_commissioner:
            return jsonify({"error": locked, "code": "locked"}), 409
        svc.release_player(db, league, player, actor.discord_id, _payload().get("reason"))
        db.flush()
        return jsonify({"player": svc.player_json(player)})


@mynba_bp.route("/players/<player_ref>/move", methods=["POST"])
def admin_move(player_ref):
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        if not access.is_commissioner:
            return _forbidden("Only a commissioner can move a player directly.")

        player = svc.resolve_player(db, league.id, player_ref)
        team = svc.resolve_team(db, league.id, body["team"]) if body.get("team") else None
        svc.admin_move_player(db, league, player, team, actor.discord_id, body.get("reason"))
        db.flush()
        return jsonify({"player": svc.player_json(player, team)})


@mynba_bp.route("/sweep", methods=["POST"])
def sweep():
    """Expire stale proposals and execute matured protest windows. Called on a timer."""
    if not _bot_token_ok():
        return _forbidden("Bot token required.")
    with session_scope() as db:
        league = resolve_league(db)
        result = svc.sweep_trades(db, league)
        db.flush()
        return jsonify({
            "expired": [svc.trade_json(db, t, include_assets=False) for t in result["expired"]],
            "executed": [svc.trade_json(db, t) for t in result["executed"]],
        })


@mynba_bp.route("/players/<player_ref>/untouchable", methods=["POST"])
def set_untouchable(player_ref):
    """Mark or clear a player as untradeable. GMs for their own team; commissioners for any."""
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        player = svc.resolve_player(db, league.id, player_ref)
        if not access.is_commissioner and (not access.team or access.team.id != player.team_id):
            return _forbidden("You can only mark players on your own team.")
        svc.set_untouchable(db, league, player, body.get("untouchable", True))
        db.flush()
        return jsonify({"player": svc.player_json(player, player.team)})


# ---------------------------------------------------------------------------
# Rulebook
# ---------------------------------------------------------------------------

@mynba_bp.route("/rules", methods=["GET"])
def get_rules():
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")
        body = rulebook.rulebook_json(league)
        body["can_edit"] = access.is_commissioner
        body["settings"] = _league_json(db, league)
        return jsonify(body)


@mynba_bp.route("/rules", methods=["PUT"])
def save_rules():
    """Replace the written rules. Body: {rules: [{id?, title, body}], base_version}."""
    payload = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        if not access.is_commissioner:
            return _forbidden("Only a commissioner can change the rules.")
        rulebook.save_rules(league, payload.get("rules"), payload.get("base_version"), actor.display_name)
        db.flush()
        body = rulebook.rulebook_json(league)
        body["can_edit"] = True
        body["settings"] = _league_json(db, league)
        return jsonify(body)


# ---------------------------------------------------------------------------
# Weekly gameplans
# ---------------------------------------------------------------------------

def _team_from_ref(db, league, team_ref):
    team = db.query(MynbaTeam).filter(MynbaTeam.id == team_ref, MynbaTeam.league_id == league.id).first()
    return team or svc.resolve_team(db, league.id, team_ref)


def _can_edit_gameplan(access, team):
    if access.is_commissioner:
        return True
    return bool(access.team and access.team.id == team.id and not gp.lock_status(access.league)["locked"])


@mynba_bp.route("/gameplan/options", methods=["GET"])
def gameplan_options():
    """Every setting a gameplan holds, its allowed values, and the rotation rules."""
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")
        body = gp.options_json(league)
        body["lock"] = gp.lock_status(league)
        return jsonify(body)


@mynba_bp.route("/gameplans", methods=["GET"])
def all_gameplans():
    """Every team's current settings, for the Coaching tab. Rotations are left out."""
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")
        teams = db.query(MynbaTeam).filter(MynbaTeam.league_id == league.id).order_by(MynbaTeam.name).all()
        plans = {p.team_id: p for p in db.query(MynbaGameplan).filter(MynbaGameplan.league_id == league.id)}
        rows = []
        for team in teams:
            plan = plans.get(team.id)
            rows.append({
                "team": svc.team_json(team),
                "settings": json.loads(plan.settings) if plan and plan.settings else {},
                "submitted": plan is not None,
                "updated_at": plan.updated_at.isoformat() + "Z" if plan else None,
            })
        return jsonify({"teams": rows, "lock": gp.lock_status(league)})


@mynba_bp.route("/teams/<team_ref>/gameplan", methods=["GET"])
def team_gameplan(team_ref):
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")
        team = _team_from_ref(db, league, team_ref)
        return jsonify({
            "gameplan": gp.gameplan_json(db, league, team, viewer_can_edit=_can_edit_gameplan(access, team)),
            "lock": gp.lock_status(league),
        })


@mynba_bp.route("/teams/<team_ref>/gameplan", methods=["PUT"])
def save_team_gameplan(team_ref):
    """Save settings and/or the rotation. Body: {settings?, rotation?, base_version?}."""
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        team = _team_from_ref(db, league, team_ref)
        if not access.is_commissioner and (not access.team or access.team.id != team.id):
            return _forbidden(f"You don't run the {team.name}.")

        plan, changes = gp.save_gameplan(
            db, league, team,
            settings=body.get("settings"),
            rotation=body.get("rotation"),
            actor=actor,
            is_commissioner=access.is_commissioner,
            base_version=body.get("base_version"),
        )
        return jsonify({
            "gameplan": gp.gameplan_json(db, league, team, plan, viewer_can_edit=_can_edit_gameplan(access, team)),
            "changes": [gp.change_json(c) for c in changes],
        })


@mynba_bp.route("/gameplan/changes", methods=["GET"])
def gameplan_changes():
    """The commissioner's to-do list: what to change in 2K, grouped by team."""
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_commissioner or _bot_token_ok()):
            return _forbidden("Only commissioners see the change feed.")
        include_done = str(request.args.get("include_done", "")).lower() in ("1", "true", "yes")
        rows = gp.list_changes(db, league, include_done=include_done, team_id=request.args.get("team_id"))
        return jsonify({"changes": [gp.change_json(r) for r in rows]})


@mynba_bp.route("/gameplan/changes/mark", methods=["POST"])
def mark_gameplan_changes():
    """Body: {ids: [...], done: true|false}. Done means it has been changed in 2K."""
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        if not access.is_commissioner:
            return _forbidden("Only a commissioner can mark changes done.")
        rows = gp.mark_changes(db, league, body.get("ids") or [], body.get("done", True), actor.discord_id)
        return jsonify({"changes": [gp.change_json(r) for r in rows]})


# ---------------------------------------------------------------------------
# Games: box scores, standings, stats
# ---------------------------------------------------------------------------

def _member_or_bot(db, league):
    access = Access(db, league, get_actor(db))
    return access.is_member or _bot_token_ok()


@mynba_bp.route("/games/read", methods=["POST"])
def read_box_scores():
    """Multipart `files`: box-score screenshots. Returns game drafts to review; saves nothing."""
    with session_scope() as db:
        league = resolve_league(db)
        if not Access(db, league, get_actor(db)).is_commissioner:
            return _forbidden("Only a commissioner can upload box scores.")
        files = []
        for f in request.files.getlist("files"):
            data = f.read()
            if data:
                files.append((f.filename or "screenshot", data, f.mimetype or "image/png"))
        result = games.read_screenshots(db, league, files)
        return jsonify(result)


@mynba_bp.route("/games", methods=["GET"])
def list_games():
    with session_scope() as db:
        league = resolve_league(db)
        if not _member_or_bot(db, league):
            return _forbidden("This league portal is for GMs and commissioners.")
        return jsonify({"games": games.games_json(db, league),
                        "default_played_on": games.default_played_on(league).isoformat()})


def _game_or_404(db, league, game_id):
    game = db.query(MynbaGame).filter(MynbaGame.id == game_id, MynbaGame.league_id == league.id).first()
    if not game:
        raise LeagueError("That game doesn't exist.", code="no_game")
    return game


@mynba_bp.route("/games", methods=["POST"])
@mynba_bp.route("/games/<game_id>", methods=["PUT"])
def save_game(game_id=None):
    """Body: {played_on, away: {team_id, score, quarters, lines}, home: {...}, allow_duplicate?}."""
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        if not Access(db, league, actor).is_commissioner:
            return _forbidden("Only a commissioner can save games.")
        existing = _game_or_404(db, league, game_id) if game_id else None
        game = games.save_game(db, league, body, actor, game=existing)
        players = {p.id: p for p in db.query(MynbaPlayer).filter(MynbaPlayer.league_id == league.id)}
        return jsonify({"game": games.game_json(game, games._teams(db, league), players)})


@mynba_bp.route("/games/<game_id>", methods=["DELETE"])
def delete_game(game_id):
    with session_scope() as db:
        league = resolve_league(db)
        if not Access(db, league, get_actor(db)).is_commissioner:
            return _forbidden("Only a commissioner can delete games.")
        db.delete(_game_or_404(db, league, game_id))
        return jsonify({"ok": True})


@mynba_bp.route("/standings", methods=["GET"])
def standings():
    """Standings by conference plus the award races, all computed from saved games."""
    with session_scope() as db:
        league = resolve_league(db)
        if not _member_or_bot(db, league):
            return _forbidden("This league portal is for GMs and commissioners.")
        rows = games.player_stats(db, league)
        return jsonify({"standings": games.standings_json(db, league),
                        "awards": games.award_races(rows),
                        "games_played": db.query(MynbaGame).filter(MynbaGame.league_id == league.id).count()})


@mynba_bp.route("/stats", methods=["GET"])
def stats():
    with session_scope() as db:
        league = resolve_league(db)
        if not _member_or_bot(db, league):
            return _forbidden("This league portal is for GMs and commissioners.")
        return jsonify({"players": games.player_stats(db, league)})


# ---------------------------------------------------------------------------
# 2K ratings reference
# ---------------------------------------------------------------------------

@mynba_bp.route("/ratings/sync", methods=["POST"])
def ratings_sync():
    """Refresh the 2K reference data. Never touches a roster."""
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        if not (access.is_commissioner or _bot_token_ok()):
            return _forbidden("Only a commissioner can sync ratings.")

        result = ratings.sync_players(
            db, era=body.get("era", "curr"),
            triggered_by=body.get("triggered_by") or actor.discord_id or "manual",
        )
        db.flush()
        return jsonify(result)


@mynba_bp.route("/ratings/badges", methods=["POST"])
def ratings_badges():
    """Fill in badges, which only come from the per-player endpoint. Needs an API key."""
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        if not (access.is_commissioner or _bot_token_ok()):
            return _forbidden("Only a commissioner can sync badges.")

        result = ratings.sync_badges(
            db, era=body.get("era", "curr"),
            limit=int(body["limit"]) if body.get("limit") else None,
            triggered_by=actor.discord_id,
        )
        db.flush()
        return jsonify(result)


@mynba_bp.route("/ratings/status", methods=["GET"])
def ratings_status():
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")

        total = db.query(func.count(Nba2kPlayer.id)).filter(Nba2kPlayer.team_type == "curr").scalar() or 0
        with_badges = db.query(func.count(Nba2kPlayer.id)).filter(
            Nba2kPlayer.team_type == "curr", Nba2kPlayer.detail_synced_at.isnot(None)
        ).scalar() or 0
        runs = db.query(Nba2kSyncRun).order_by(Nba2kSyncRun.started_at.desc()).limit(5).all()
        return jsonify({
            "players": total,
            "with_badges": with_badges,
            "has_api_key": ratings.has_key(),
            "runs": [ratings.sync_run_json(r) for r in runs],
        })


@mynba_bp.route("/ratings/seed-rosters", methods=["POST"])
def ratings_seed_rosters():
    """Create league rosters from the 2K reference data. A setup step, not the weekly sync."""
    body = _payload()
    with session_scope() as db:
        league = resolve_league(db)
        actor = get_actor(db)
        access = Access(db, league, actor)
        if not (access.is_commissioner or _bot_token_ok()):
            return _forbidden("Only a commissioner can seed rosters.")

        summary = ratings.seed_league_rosters(
            db, league,
            era=body.get("era", "curr"),
            actor_discord_id=actor.discord_id,
            dry_run=bool(body.get("dry_run")),
            include_free_agents=body.get("include_free_agents", True),
        )
        return jsonify(summary)


@mynba_bp.route("/players/<player_ref>/card", methods=["GET"])
def player_card(player_ref):
    """League state plus the full 2K card for one player."""
    with session_scope() as db:
        league = resolve_league(db)
        access = Access(db, league, get_actor(db))
        if not (access.is_member or _bot_token_ok()):
            return _forbidden("This league portal is for GMs and commissioners.")

        player = svc.resolve_player(db, league.id, player_ref)
        team = db.query(MynbaTeam).filter(MynbaTeam.id == player.team_id).first() if player.team_id else None

        reference = db.query(Nba2kPlayer).filter(
            Nba2kPlayer.name_key == player.name_key, Nba2kPlayer.team_type == "curr"
        ).first()

        history = (db.query(MynbaTransaction)
                   .filter(MynbaTransaction.player_id == player.id)
                   .order_by(MynbaTransaction.created_at.desc()).limit(20).all())

        return jsonify({
            "player": svc.player_json(player, team),
            "ratings": ratings.reference_json(reference, full=True),
            "history": [svc.transaction_json(t) for t in history],
        })
