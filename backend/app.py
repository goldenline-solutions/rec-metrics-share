"""
Flask application for NBA2K Rec box score ingestion API.
"""
import os
from flask import Flask, request, jsonify, send_file, redirect, make_response
from flask_cors import CORS
from dotenv import load_dotenv
from contextlib import contextmanager

import logging
from logging.handlers import RotatingFileHandler


from db import init_db, SessionLocal
from ingest_service import ingest_box_score
from clean_leading_symbols import run as clean_leading_symbols_run
from fuzzy_merge_players import run as fuzzy_merge_run
from models import Game, Player, GamePlayer, PlayerGameStats, TeamTotal, Matchup, User, Build, PlayerAnalysisCache, PlayerGameAdminMetrics, DiscordUploadChannel, Event
from models import GAME_VERSIONS, CURRENT_GAME_VERSION, LEGACY_GAME_VERSION
from sqlalchemy import desc, exists, and_, or_, func, case
from auth_utils import (
    get_discord_authorize_url, verify_state, exchange_code_for_token,
    get_discord_user_info, create_session_token, verify_session_token
)
from profile_service import get_player_profile, determine_win
from chemistry_service import get_player_chemistry
from player_analysis_service import (
    build_player_analysis_payload,
    analyze_player_with_openai,
    get_payload_hash
)
from claims_service import (
    create_claim, verify_claim, get_user_claims, get_unresolved_games, confirm_game_player
)
from build_service import (
    ingest_build_sheet, create_planned_build, format_build_response, get_user_builds, get_build_by_id,
    update_build, delete_build, assign_build_to_game_player,
    get_public_builds_feed, get_build_usage_breakdown, get_build_votes, set_build_vote,
    get_template_builds
)
from mynba_routes import mynba_bp
from services.admin_metrics_service import (
    upsert_player_game_admin_metrics,
    get_player_admin_metrics
)

import json
import time
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)

# Enable CORS for local development and when ENV=development
# In production (deployed), we use same-origin requests (no CORS needed)
ENV = os.getenv("ENV", "production").lower()

# Always allow localhost origins for local development
localhost_origins = [
    "http://localhost:5173",
    "http://localhost:5000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5000",
]

# In development mode, also allow production origin
if ENV == "development":
    allowed_origins = localhost_origins + ["https://2k.blueozark.dev"]
else:
    # Even in production mode, allow localhost for local testing
    allowed_origins = localhost_origins

ALLOWED = {
    "origins": allowed_origins,
    "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"],
    "supports_credentials": True,  # Enable credentials for cookies
}
CORS(app, resources={r"/api/*": ALLOWED}, supports_credentials=True)

# MyNBA league portal + Discord bot API
app.register_blueprint(mynba_bp)

# Configuration from environment variables
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")

# Ensure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Set up logging for API requests.
# Rotating file handler so the log can't grow without bound (the previous flat
# FileHandler never rotated). 10 MB per file, 5 backups = ~60 MB ceiling.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Console output
        RotatingFileHandler('api_requests.log', maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Ensure ingest_service and openai_client logs show in the same place (they're imported before basicConfig)
for _mod in ('ingest_service', 'openai_client'):
    _log = logging.getLogger(_mod)
    _log.setLevel(logging.INFO)
    if not _log.handlers:
        for _h in logging.root.handlers:
            _log.addHandler(_h)

# Simple in-memory cache for player profiles (keyed by username, TTL 60s)
profile_cache = {}
CACHE_TTL = 10  # seconds - reduced for debugging

def get_cached_profile(username: str):
    """Get cached profile if still valid."""
    if username in profile_cache:
        cached_data, timestamp = profile_cache[username]
        if time.time() - timestamp < CACHE_TTL:
            print(f"Returning cached profile for {username}")
            return cached_data
        else:
            # Cache expired, remove it
            del profile_cache[username]
            print(f"Cache expired for {username}, removed")

    return None

def set_cached_profile(username: str, data: dict):
    """Cache profile data with current timestamp."""
    profile_cache[username] = (data, time.time())

# Leaderboard cache — no TTL, cleared on every successful ingest
leaderboard_cache = {}

def make_leaderboard_key(stat, limit, min_games, position, platform, game_version=None):
    return f"{stat}|{limit}|{min_games}|{position}|{platform}|{game_version or 'all'}"

def get_cached_leaderboard(key):
    return leaderboard_cache.get(key)

def set_cached_leaderboard(key, data):
    leaderboard_cache[key] = data

def invalidate_leaderboard_cache():
    leaderboard_cache.clear()


# ---------------------------------------------------------------------------
# Game version (2K26 / 2K27) filtering
# ---------------------------------------------------------------------------

def parse_game_version_param(default=CURRENT_GAME_VERSION, param="game_version"):
    """
    Read the game_version query param.

    Returns (version, error_message). `version` is a value from GAME_VERSIONS,
    or None meaning "all titles". `error_message` is None unless the caller
    passed something unrecognised.
    """
    raw = (request.args.get(param) or "").strip()
    if not raw:
        return default, None
    if raw.lower() == "all":
        return None, None
    normalized = raw.upper()
    if normalized not in GAME_VERSIONS:
        return None, f"Invalid game_version. Must be one of: {', '.join(GAME_VERSIONS)}, all"
    return normalized, None


def game_version_clause(version):
    """
    SQLAlchemy filter for Game.game_version, or None for "all titles".

    Rows predating the game_version column are treated as the legacy title, so
    a game that somehow escaped the backfill still shows up under 2K26 rather
    than vanishing from every view.
    """
    if version is None:
        return None
    if version == LEGACY_GAME_VERSION:
        return or_(Game.game_version == version, Game.game_version.is_(None))
    return Game.game_version == version


def game_version_of(game):
    """Display value for a game row, defaulting untagged rows to the legacy title."""
    return getattr(game, "game_version", None) or LEGACY_GAME_VERSION

# Query-string keys whose values must never be written to logs.
_SENSITIVE_LOG_KEYS = {"token", "code", "password", "secret", "api_key", "apikey", "auth", "session", "gclid"}


def _redact(mapping):
    """Return a dict with sensitive values masked; used for query-string logging."""
    out = {}
    for k, v in mapping.items():
        out[k] = "***" if k.lower() in _SENSITIVE_LOG_KEYS else v
    return out


# Request logging middleware.
# One compact line per request. We deliberately do NOT log request bodies:
# the old version logged full JSON/form payloads, which meant tokens, session
# data, and other PII landed in a plaintext file. We log shape (size, field
# names, file keys) instead of contents.
@app.before_request
def log_request_info():
    """Log a concise, PII-safe summary of each incoming request."""
    parts = [f'{request.method} {request.path}', f'ip={request.remote_addr}']

    if request.args:
        parts.append(f'qs={_redact(request.args.to_dict())}')

    # Field NAMES only — never form values (they can carry credentials).
    if request.form and 'screenshot' not in request.files:
        parts.append(f'form_fields={list(request.form.keys())}')

    # Body shape, not body content.
    if request.is_json:
        parts.append(f'json_bytes={request.content_length or 0}')

    if request.files:
        parts.append(f'files={list(request.files.keys())}')

    logger.info(' '.join(parts))



@app.after_request
def log_response_info(response):
    """Log response status."""
    logger.info(f'Response: {response.status_code} {response.status}')
    logger.info('=' * 80)
    return response

@contextmanager
def get_db_session():
    """Context manager for database sessions."""
    from db import SessionLocal
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def require_admin():
    """
    Decorator helper to check if user is admin.
    Returns: (is_admin, user_id) tuple
    """
    session_token = request.cookies.get("access_token")
    
    if not session_token:
        return False, None
    
    is_valid, user_id = verify_session_token(session_token)
    if not is_valid or not user_id:
        return False, None
    
    try:
        with get_db_session() as db:
            user = db.query(User).filter_by(id=user_id).first()
            if not user:
                return False, None
            
            # Parse roles
            roles = []
            if user.roles:
                try:
                    roles = json.loads(user.roles)
                except (json.JSONDecodeError, TypeError):
                    roles = []
            
            if "admin" not in roles:
                return False, None
            
            return True, user_id
    except Exception:
        return False, None


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint with version and environment info."""
    import datetime
    version = os.getenv("APP_VERSION", "dev")
    env = os.getenv("ENV", "production")
    time_utc = datetime.datetime.utcnow().isoformat() + "Z"
    
    return jsonify({
        "status": "ok",
        "service": "2k-stats-api",
        "time_utc": time_utc,
        "version": version,
        "env": env
    })


def _require_ingest_bot_token():
    """Return True if request has valid INGEST_BOT_TOKEN Bearer. Else return (False, response_tuple)."""
    ingest_bot_token = os.getenv("INGEST_BOT_TOKEN", "").strip()
    auth = (request.headers.get("Authorization") or "").strip()
    if not ingest_bot_token:
        return False, (jsonify({"error": "Unauthorized"}), 401)
    # Accept "Bearer <token>" or bare "<token>"
    token_match = auth == f"Bearer {ingest_bot_token}" or auth == ingest_bot_token
    if not token_match:
        return False, (jsonify({"error": "Unauthorized"}), 401)
    return True, None


@app.route("/api/discord/upload-channels", methods=["GET"])
def discord_list_upload_channels():
    """Return list of channel_ids where the bot should listen. Auth: Bearer INGEST_BOT_TOKEN."""
    ok, err = _require_ingest_bot_token()
    if not ok:
        return err[0], err[1]
    try:
        with get_db_session() as db:
            rows = db.query(DiscordUploadChannel).all()
            channel_ids = [r.channel_id for r in rows]
        return jsonify({"channel_ids": channel_ids}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/discord/upload-channels", methods=["POST"])
def discord_register_upload_channel():
    """Register or update upload channel for a guild. Auth: Bearer INGEST_BOT_TOKEN. Body: guild_id, channel_id, registered_by_discord_id (optional)."""
    ok, err = _require_ingest_bot_token()
    if not ok:
        return err[0], err[1]
    data = request.get_json(silent=True) or {}
    guild_id = (data.get("guild_id") or "").strip()
    channel_id = (data.get("channel_id") or "").strip()
    registered_by_discord_id = (data.get("registered_by_discord_id") or "").strip() or None
    if not guild_id or not channel_id:
        return jsonify({"error": "guild_id and channel_id are required"}), 400
    try:
        from datetime import datetime
        with get_db_session() as db:
            row = db.query(DiscordUploadChannel).filter_by(guild_id=guild_id).first()
            now = datetime.utcnow().isoformat() + "Z"
            if row:
                row.channel_id = channel_id
                row.registered_by_discord_id = registered_by_discord_id
                row.updated_at = now
            else:
                row = DiscordUploadChannel(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    registered_by_discord_id=registered_by_discord_id,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
        return jsonify({"ok": True, "guild_id": guild_id, "channel_id": channel_id}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats", methods=["GET"])
def site_stats():
    """Lightweight site stats for landing page: games and players counts."""
    try:
        with get_db_session() as db:
            games_count = db.query(Game).count()
            players_count = db.query(Player).count()
        return jsonify({
            "games_tracked": games_count,
            "players_tracked": players_count
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/events", methods=["POST"])
def record_event():
    """
    First-party analytics ingestion. Called by the frontend beacon on pageviews
    and conversions (see frontend/src/utils/analytics.js).

    Public and fire-and-forget: always returns 204 so a failure here can never
    surface to the user or block navigation. Rejects oversized/garbage bodies
    quietly. Stores no raw PII beyond an optional authenticated user_id.
    """
    ALLOWED = {
        "pageview", "opened_planner", "started_from_template",
        "saved_build", "signed_in",
    }
    try:
        # sendBeacon posts a Blob; force JSON parsing regardless of content-type.
        data = request.get_json(force=True, silent=True) or {}
        name = str(data.get("name") or "").strip()[:64]
        if not name or name not in ALLOWED:
            return ("", 204)

        def _json_or_none(v, limit=2000):
            if not v:
                return None
            try:
                s = json.dumps(v)[:limit]
                return s
            except (TypeError, ValueError):
                return None

        with get_db_session() as db:
            db.add(Event(
                name=name,
                path=(str(data.get("path"))[:512] if data.get("path") else None),
                params=_json_or_none(data.get("params")),
                attribution=_json_or_none(data.get("attribution")),
                referrer=(str(data.get("referrer"))[:512] if data.get("referrer") else None),
                user_id=get_current_user_id(),
                user_agent=(request.headers.get("User-Agent", "")[:512] or None),
                created_at=datetime.utcnow().isoformat(),
            ))
        return ("", 204)
    except Exception as e:
        # Never fail the client on an analytics write.
        logger.warning(f"event ingest skipped: {e}")
        return ("", 204)


@app.route("/api/ingest", methods=["POST"])
def ingest():
    """
    Main ingestion endpoint.
    
    Accepts:
    - multipart/form-data with 'screenshot' file field
    - optional 'season_label' and 'mode_label' form fields
    
    Returns:
    - JSON with game_id, stored flag, payload, and warnings
    """
    # Check for required file
    if "screenshot" not in request.files:
        return jsonify({"error": "Missing 'screenshot' file field"}), 400
    
    file = request.files["screenshot"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    
    # Get optional form fields
    season_label = request.form.get("season_label", None)
    mode_label = request.form.get("mode_label", None)
    
    # Get uploader user_id and platform if authenticated (session or Discord bot)
    uploader_user_id = None
    platform = None
    ingest_bot_token = os.getenv("INGEST_BOT_TOKEN", "").strip()
    auth_header = (request.headers.get("Authorization") or "").strip()
    bot_auth_ok = ingest_bot_token and (auth_header == f"Bearer {ingest_bot_token}" or auth_header == ingest_bot_token)
    if bot_auth_ok:
        # Discord bot: resolve uploader from form uploader_discord_id
        uploader_discord_id = request.form.get("uploader_discord_id", "").strip()
        if uploader_discord_id:
            with get_db_session() as db:
                user = db.query(User).filter_by(discord_id=uploader_discord_id).first()
                if user:
                    uploader_user_id = user.id
                    platform = user.platform
    if uploader_user_id is None:
        session_token = request.cookies.get("access_token")
        if session_token:
            from auth_utils import verify_session_token
            is_valid, user_id = verify_session_token(session_token)
            if is_valid and user_id:
                uploader_user_id = user_id
                with get_db_session() as db:
                    user = db.query(User).filter_by(id=user_id).first()
                    if user:
                        platform = user.platform
    
    # Validate OpenAI API key
    if not OPENAI_API_KEY:
        return jsonify({"error": "OPENAI_API_KEY not configured"}), 500
    
    try:
        # Get database session
        with get_db_session() as db:
            # Call ingestion service
            result, warnings = ingest_box_score(
                db=db,
                file=file,
                upload_dir=UPLOAD_DIR,
                season_label=season_label,
                mode_label=mode_label,
                uploader_user_id=uploader_user_id,
                platform=platform
            )
            
            # Add warnings to response if any
            if warnings:
                result["warnings"] = warnings
            
            invalidate_leaderboard_cache()

        # Post-ingest cleanup — only when a new game was stored
        if result.get("stored"):
            try:
                clean_leading_symbols_run(dry_run=False)
            except Exception as e:
                app.logger.warning(f"Post-ingest symbol cleanup failed: {e}")
            try:
                fuzzy_merge_run(dry_run=False, threshold=88, filter_player=None)
            except Exception as e:
                app.logger.warning(f"Post-ingest fuzzy merge failed: {e}")

        return jsonify(result), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # Surface OpenAI API errors (e.g. 400 Bad Request) with their message for debugging
        err_msg = str(e)
        body = getattr(e, "body", None)
        if body is not None:
            try:
                if isinstance(body, dict) and "error" in body:
                    err_msg = body["error"].get("message", err_msg)
                else:
                    err_msg = str(body)
            except Exception:
                pass
        app.logger.exception("Ingest failed: %s", err_msg)
        # 502 when upstream (OpenAI) returned an error; 500 for unexpected failures
        status = 502 if getattr(e, "status_code", None) is not None else 500
        return jsonify({"error": f"Extraction failed: {err_msg}"}), status


def validate_game_data(db, game_id):
    """
    Validate game data for inconsistencies.
    Returns a dict with 'needs_verification' (bool) and 'warnings' (list of strings).
    """
    warnings = []
    needs_verification = False
    
    try:
        # Get team totals
        team_totals = db.query(TeamTotal).filter_by(game_id=game_id).all()
        team_totals_dict = {tt.team_side: tt for tt in team_totals}
        
        # Get all players with stats — batch load to avoid N+1
        game_players = db.query(GamePlayer).filter_by(game_id=game_id).all()
        gp_player_ids = [gp.player_id for gp in game_players]

        stats_by_player = {
            s.player_id: s
            for s in db.query(PlayerGameStats).filter(
                PlayerGameStats.game_id == game_id,
                PlayerGameStats.player_id.in_(gp_player_ids)
            ).all()
        }
        players_by_id_v = {
            p.id: p
            for p in db.query(Player).filter(Player.id.in_(gp_player_ids)).all()
        }

        # Check for players missing stats
        players_missing_stats = []
        for gp in game_players:
            if gp.player_id not in stats_by_player:
                player = players_by_id_v.get(gp.player_id)
                if player:
                    players_missing_stats.append(f"{player.gamertag} ({gp.position}, {gp.team_side})")

        if players_missing_stats:
            if len(players_missing_stats) == 1:
                warnings.append(f"Player missing stats: {players_missing_stats[0]}")
            else:
                warnings.append(f"{len(players_missing_stats)} players missing stats: {', '.join(players_missing_stats[:5])}" +
                              (f" and {len(players_missing_stats) - 5} more" if len(players_missing_stats) > 5 else ""))
            needs_verification = True

        # Check each team
        for team_side in ["AWAY", "HOME"]:
            team_total = team_totals_dict.get(team_side)
            if not team_total:
                continue

            # Sum player stats for this team
            team_players = [gp for gp in game_players if gp.team_side == team_side]
            total_player_pts = 0
            total_player_reb = 0
            total_player_ast = 0
            total_player_fgm = 0
            total_player_fga = 0
            total_player_tpm = 0
            total_player_tpa = 0

            for gp in team_players:
                stats = stats_by_player.get(gp.player_id)

                if stats:
                    total_player_pts += stats.pts
                    total_player_reb += stats.reb
                    total_player_ast += stats.ast
                    total_player_fgm += stats.fgm
                    total_player_fga += stats.fga
                    total_player_tpm += stats.tpm
                    total_player_tpa += stats.tpa
            
            # Check if player points match team total points
            if abs(total_player_pts - team_total.pts) > 1:  # Allow 1 point difference for rounding
                warnings.append(f"{team_side} team: Player points ({total_player_pts}) don't match team total ({team_total.pts})")
                needs_verification = True
            
            # Check if player rebounds match team total (within reasonable margin)
            if abs(total_player_reb - team_total.reb) > 2:  # Allow 2 rebound difference
                warnings.append(f"{team_side} team: Player rebounds ({total_player_reb}) don't match team total ({team_total.reb})")
                needs_verification = True
            
            # Check if player assists match team total
            if abs(total_player_ast - team_total.ast) > 1:
                warnings.append(f"{team_side} team: Player assists ({total_player_ast}) don't match team total ({team_total.ast})")
                needs_verification = True
            
            # Check if shooting stats are valid
            if total_player_fgm > total_player_fga:
                warnings.append(f"{team_side} team: Field goals made ({total_player_fgm}) exceeds attempts ({total_player_fga})")
                needs_verification = True
            
            if total_player_tpm > total_player_tpa:
                warnings.append(f"{team_side} team: 3-pointers made ({total_player_tpm}) exceeds attempts ({total_player_tpa})")
                needs_verification = True
            
            # Check if team totals shooting stats are valid
            if team_total.fgm > team_total.fga:
                warnings.append(f"{team_side} team: Team field goals made ({team_total.fgm}) exceeds attempts ({team_total.fga})")
                needs_verification = True
            
            if team_total.tpm > team_total.tpa:
                warnings.append(f"{team_side} team: Team 3-pointers made ({team_total.tpm}) exceeds attempts ({team_total.tpa})")
                needs_verification = True
        
    except Exception as e:
        warnings.append(f"Validation error: {str(e)}")
        needs_verification = True
    
    return {
        "needs_verification": needs_verification,
        "warnings": warnings
    }


def _list_games_flags_and_fallbacks(db, game_ids):
    """
    Batched computation of has_incomplete_data, needs_verification, and team name
    fallbacks for a list of game ids. Avoids N+1 queries.
    Returns: (has_incomplete_data dict, needs_verification dict, fallbacks dict).
    fallbacks[(game_id, "AWAY")] or [(game_id, "HOME")] = gamertag string.
    """
    if not game_ids:
        return {}, {}, {}

    # One query: all GamePlayers for these games
    game_players = db.query(GamePlayer).filter(GamePlayer.game_id.in_(game_ids)).all()
    gp_by_game = {}
    for gp in game_players:
        gp_by_game.setdefault(gp.game_id, []).append(gp)

    # One query: PlayerGameStats for these games (game_id, player_id, pts) for has_incomplete and sum_pts
    stats_rows = db.query(PlayerGameStats.game_id, PlayerGameStats.player_id, PlayerGameStats.pts).filter(
        PlayerGameStats.game_id.in_(game_ids)
    ).all()
    stats_by_key = {(r.game_id, r.player_id): r.pts for r in stats_rows}
    has_incomplete = {}
    sum_pts = {}
    for gid in game_ids:
        gps = gp_by_game.get(gid, [])
        has_incomplete[gid] = any((gp.game_id, gp.player_id) not in stats_by_key for gp in gps)
        for gp in gps:
            key = (gp.game_id, gp.team_side)
            pts = stats_by_key.get((gp.game_id, gp.player_id), 0)
            sum_pts[key] = sum_pts.get(key, 0) + pts

    # One query: TeamTotals for these games (for pts mismatch check)
    team_totals = db.query(TeamTotal).filter(TeamTotal.game_id.in_(game_ids)).all()
    tt_by_game_side = {(tt.game_id, tt.team_side): tt for tt in team_totals}
    needs_verification = {}
    for gid in game_ids:
        inc = has_incomplete.get(gid, False)
        mismatch = False
        for side in ("AWAY", "HOME"):
            tt = tt_by_game_side.get((gid, side))
            if tt is not None and abs(tt.pts - sum_pts.get((gid, side), 0)) > 1:
                mismatch = True
                break
        needs_verification[gid] = inc or mismatch

    # Fallback team names: first player gamertag per (game_id, team_side)
    fallbacks = {}
    rows = db.query(GamePlayer.game_id, GamePlayer.team_side, Player.gamertag).join(
        Player, Player.id == GamePlayer.player_id
    ).filter(GamePlayer.game_id.in_(game_ids)).all()
    for r in rows:
        key = (r.game_id, r.team_side)
        if key not in fallbacks:
            fallbacks[key] = r.gamertag

    return has_incomplete, needs_verification, fallbacks


@app.route("/api/games", methods=["GET"])
def list_games():
    """
    List games with basic info (paginated).
    Uses DB-level pagination and batched queries for speed.

    Query Parameters:
    - filter: Filter games by status (all, needs_verification, incomplete_data)
    - sort: Sort order (date_desc, date_asc, needs_verification_first)
    - page: Page number (1-based, default 1)
    - per_page: Games per page (default 25)
    - platform: Filter by platform (all, PC, Console)
    - game_version: Filter by NBA 2K title (2K26, 2K27, all) - defaults to 2K27

    Returns:
    - JSON with games (array), total (count), page, per_page, total_pages
    """
    try:
        with get_db_session() as db:
            filter_type = request.args.get("filter", "all").lower()
            sort_type = request.args.get("sort", "date_desc").lower()
            game_version, version_error = parse_game_version_param()
            if version_error:
                return jsonify({"error": version_error}), 400
            version_filter = game_version_clause(game_version)
            platform_param = request.args.get("platform", "all").lower()
            if platform_param == "all":
                platform_filter = None  # no filter
            elif platform_param in ("pc", "console"):
                platform_filter = "PC" if platform_param == "pc" else "Console"
            else:
                return jsonify({"error": "Invalid platform. Must be one of: all, PC, Console"}), 400

            page = max(1, int(request.args.get("page", 1)))
            per_page = max(1, min(100, int(request.args.get("per_page", 25))))

            order_desc = sort_type != "date_asc"
            order = Game.created_at.desc() if order_desc else Game.created_at.asc()

            if filter_type == "all":
                base = db.query(Game).order_by(order)
                if version_filter is not None:
                    base = base.filter(version_filter)
                if platform_filter is not None:
                    base = base.filter(Game.platform == platform_filter)
                total = base.count()
                total_pages = (total + per_page - 1) // per_page if total > 0 else 1
                page = min(page, total_pages)
                offset = (page - 1) * per_page
                games = base.limit(per_page).offset(offset).all()
            else:
                # Subquery: game ids that have at least one GamePlayer without PlayerGameStats
                incomplete_subq = db.query(GamePlayer.game_id).filter(
                    ~exists().where(
                        and_(
                            PlayerGameStats.game_id == GamePlayer.game_id,
                            PlayerGameStats.player_id == GamePlayer.player_id,
                        )
                    )
                ).distinct()
                incomplete_ids = [r[0] for r in incomplete_subq.all()]

                if filter_type == "incomplete_data":
                    filtered_ids = incomplete_ids
                else:
                    # needs_verification: also include games where team total pts != sum player pts
                    player_sum = db.query(
                        GamePlayer.game_id,
                        GamePlayer.team_side,
                        func.coalesce(func.sum(PlayerGameStats.pts), 0).label("sum_pts"),
                    ).outerjoin(
                        PlayerGameStats,
                        and_(
                            PlayerGameStats.game_id == GamePlayer.game_id,
                            PlayerGameStats.player_id == GamePlayer.player_id,
                        ),
                    ).group_by(GamePlayer.game_id, GamePlayer.team_side).subquery()
                    pts_mismatch_subq = db.query(TeamTotal.game_id).join(
                        player_sum,
                        and_(
                            TeamTotal.game_id == player_sum.c.game_id,
                            TeamTotal.team_side == player_sum.c.team_side,
                        ),
                    ).filter(func.abs(TeamTotal.pts - player_sum.c.sum_pts) > 1).distinct()
                    pts_mismatch_ids = [r[0] for r in pts_mismatch_subq.all()]
                    filtered_ids = list(set(incomplete_ids) | set(pts_mismatch_ids))

                base = db.query(Game).filter(Game.id.in_(filtered_ids)).order_by(order)
                if version_filter is not None:
                    base = base.filter(version_filter)
                if platform_filter is not None:
                    base = base.filter(Game.platform == platform_filter)
                total = base.count()
                total_pages = (total + per_page - 1) // per_page if total > 0 else 1
                page = min(page, total_pages)
                offset = (page - 1) * per_page
                games = base.limit(per_page).offset(offset).all()

            game_ids = [g.id for g in games]
            has_incomplete, needs_verification, fallbacks = _list_games_flags_and_fallbacks(db, game_ids)

            result = []
            for game in games:
                away_name = game.away_team_name or fallbacks.get((game.id, "AWAY"), "Away")
                home_name = game.home_team_name or fallbacks.get((game.id, "HOME"), "Home")
                result.append({
                    "id": game.id,
                    "created_at": game.created_at,
                    "away_score": game.away_score,
                    "home_score": game.home_score,
                    "away_team": away_name,
                    "home_team": home_name,
                    "season_label": game.season_label,
                    "mode_label": game.mode_label,
                    "game_version": game_version_of(game),
                    "needs_verification": needs_verification.get(game.id, False),
                    "has_incomplete_data": has_incomplete.get(game.id, False),
                })

            if sort_type == "needs_verification_first":
                result.sort(key=lambda x: (
                    not x["needs_verification"],
                    not x["has_incomplete_data"],
                    x["created_at"],
                ), reverse=True)

            return jsonify({
                "games": result,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
            }), 200

    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/games/<game_id>", methods=["PUT"])
def update_game(game_id):
    """
    Update game information (admin only).
    
    Accepts:
    - JSON with game data to update
    
    Returns:
    - Updated game data
    """
    # Check admin role
    is_admin, user_id = require_admin()
    if not is_admin:
        return jsonify({"error": "Admin access required"}), 403
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        with get_db_session() as db:
            game = db.query(Game).filter_by(id=game_id).first()
            if not game:
                return jsonify({"error": "Game not found"}), 404
            
            # Update game-level fields
            if "away_score" in data:
                game.away_score = int(data["away_score"])
            if "home_score" in data:
                game.home_score = int(data["home_score"])
            if "season_label" in data:
                game.season_label = data["season_label"]
            if "mode_label" in data:
                game.mode_label = data["mode_label"]
            if "platform" in data:
                platform = data["platform"]
                if platform is None or platform == "":
                    game.platform = None
                elif platform in ("PC", "Console"):
                    game.platform = platform
                else:
                    return jsonify({"error": "Invalid platform. Must be one of: PC, Console"}), 400
            if "game_version" in data:
                requested_version = (data["game_version"] or "").strip().upper()
                if requested_version not in GAME_VERSIONS:
                    return jsonify({"error": f"Invalid game_version. Must be one of: {', '.join(GAME_VERSIONS)}"}), 400
                game.game_version = requested_version
            if "away_team_name" in data:
                game.away_team_name = data["away_team_name"]
            if "home_team_name" in data:
                game.home_team_name = data["home_team_name"]

            # Keep existing game_player rows aligned to the game's platform when players are not being rebuilt.
            if "platform" in data and "players" not in data:
                game_players = db.query(GamePlayer).filter_by(game_id=game_id).all()
                for game_player in game_players:
                    game_player.platform = game.platform
            
            # Update quarters
            if "quarters" in data:
                quarters = data["quarters"]
                if "away" in quarters and len(quarters["away"]) == 4:
                    game.away_q1 = int(quarters["away"][0]) if quarters["away"][0] is not None else None
                    game.away_q2 = int(quarters["away"][1]) if quarters["away"][1] is not None else None
                    game.away_q3 = int(quarters["away"][2]) if quarters["away"][2] is not None else None
                    game.away_q4 = int(quarters["away"][3]) if quarters["away"][3] is not None else None
                if "home" in quarters and len(quarters["home"]) == 4:
                    game.home_q1 = int(quarters["home"][0]) if quarters["home"][0] is not None else None
                    game.home_q2 = int(quarters["home"][1]) if quarters["home"][1] is not None else None
                    game.home_q3 = int(quarters["home"][2]) if quarters["home"][2] is not None else None
                    game.home_q4 = int(quarters["home"][3]) if quarters["home"][3] is not None else None
            
            # Update teams
            if "teams" in data:
                for team_data in data["teams"]:
                    team_side = team_data.get("side")
                    if not team_side:
                        continue
                    
                    team_total = db.query(TeamTotal).filter_by(
                        game_id=game_id,
                        team_side=team_side
                    ).first()
                    
                    if not team_total:
                        continue
                    
                    if "grade" in team_data:
                        team_total.grade = team_data["grade"]
                    
                    if "totals" in team_data:
                        totals = team_data["totals"]
                        if "pts" in totals:
                            team_total.pts = int(totals["pts"])
                        if "reb" in totals:
                            team_total.reb = int(totals["reb"])
                        if "ast" in totals:
                            team_total.ast = int(totals["ast"])
                        if "stl" in totals:
                            team_total.stl = int(totals["stl"])
                        if "blk" in totals:
                            team_total.blk = int(totals["blk"])
                        if "fouls" in totals:
                            team_total.fouls = int(totals["fouls"])
                        if "tov" in totals:
                            team_total.tov = int(totals["tov"])
                        if "fgm" in totals:
                            team_total.fgm = int(totals["fgm"])
                        if "fga" in totals:
                            team_total.fga = int(totals["fga"])
                        if "tpm" in totals:
                            team_total.tpm = int(totals["tpm"])
                        if "tpa" in totals:
                            team_total.tpa = int(totals["tpa"])
                        if "ftm" in totals:
                            team_total.ftm = int(totals["ftm"])
                        if "fta" in totals:
                            team_total.fta = int(totals["fta"])
            
            # Update players
            if "players" in data:
                # First, delete all existing game_players and stats for this game
                # We'll recreate them based on the provided data
                db.query(PlayerGameStats).filter_by(game_id=game_id).delete()
                db.query(GamePlayer).filter_by(game_id=game_id).delete()
                
                for player_data in data["players"]:
                    gamertag = player_data.get("gamertag", "").strip()
                    if not gamertag:
                        # Skip empty slots
                        continue
                    
                    team_side = player_data.get("side")
                    position = player_data.get("assigned_position") or player_data.get("position", "PG")
                    row_index = player_data.get("row_index", 0)
                    
                    if not team_side:
                        continue
                    
                    # Find or create player
                    player = db.query(Player).filter_by(gamertag=gamertag).first()
                    if not player:
                        # Create new player
                        player = Player(gamertag=gamertag)
                        db.add(player)
                        db.flush()  # Get the player ID
                    
                    # Create or update game player (use game's platform so players are tagged correctly)
                    game_player = GamePlayer(
                        game_id=game_id,
                        player_id=player.id,
                        team_side=team_side,
                        position=position,
                        row_index=row_index,
                        platform=game.platform
                    )
                    db.add(game_player)
                    db.flush()  # Get the game_player ID
                    
                    # Create or update player stats
                    stats = PlayerGameStats(
                        game_id=game_id,
                        player_id=player.id,
                        grade=player_data.get("grade") or None,
                        pts=int(player_data.get("stats", {}).get("pts", 0)),
                        reb=int(player_data.get("stats", {}).get("reb", 0)),
                        ast=int(player_data.get("stats", {}).get("ast", 0)),
                        stl=int(player_data.get("stats", {}).get("stl", 0)),
                        blk=int(player_data.get("stats", {}).get("blk", 0)),
                        fouls=int(player_data.get("stats", {}).get("fouls", 0)),
                        tov=int(player_data.get("stats", {}).get("tov", 0)),
                        fgm=int(player_data.get("stats", {}).get("fgm", 0)),
                        fga=int(player_data.get("stats", {}).get("fga", 0)),
                        tpm=int(player_data.get("stats", {}).get("tpm", 0)),
                        tpa=int(player_data.get("stats", {}).get("tpa", 0)),
                        ftm=int(player_data.get("stats", {}).get("ftm", 0)),
                        fta=int(player_data.get("stats", {}).get("fta", 0))
                    )
                    db.add(stats)
            
            # Update matchups
            if "matchups" in data:
                # Delete all existing matchups for this game
                db.query(Matchup).filter_by(game_id=game_id).delete()
                
                # Create new matchups
                for matchup_data in data["matchups"]:
                    defender_gamertag = matchup_data.get("defender_gamertag")
                    offender_gamertag = matchup_data.get("offender_gamertag")
                    
                    if not defender_gamertag or not offender_gamertag:
                        continue
                    
                    # Find players by gamertag
                    defender_player = db.query(Player).filter_by(gamertag=defender_gamertag).first()
                    offender_player = db.query(Player).filter_by(gamertag=offender_gamertag).first()
                    
                    if not defender_player or not offender_player:
                        continue
                    
                    # Create matchup
                    matchup = Matchup(
                        game_id=game_id,
                        defender_player_id=defender_player.id,
                        offender_player_id=offender_player.id,
                        defender_position=matchup_data.get("defender_position", "PG"),
                        offender_position=matchup_data.get("offender_position", "PG"),
                        matchup_type=matchup_data.get("matchup_type", "POSITIONAL")
                    )
                    db.add(matchup)
            
            db.commit()
            
            # Return updated game data
            return get_game(game_id)
            
    except ValueError as e:
        return jsonify({"error": f"Invalid data format: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"Error updating game: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/games/<game_id>/clear-warnings", methods=["POST"])
def clear_warnings(game_id):
    """
    Clear warnings for a game by marking it as verified (admin only).
    This doesn't actually remove warnings, but marks the game as verified.
    
    Returns:
    - Success message
    """
    # Check admin role
    is_admin, user_id = require_admin()
    if not is_admin:
        return jsonify({"error": "Admin access required"}), 403
    
    try:
        with get_db_session() as db:
            game = db.query(Game).filter_by(id=game_id).first()
            if not game:
                return jsonify({"error": "Game not found"}), 404
            
            # Note: We don't actually store a "verified" flag, but we can add one
            # For now, we'll just return success - the frontend can handle hiding warnings
            # In the future, you might want to add a `verified` or `warnings_cleared` field to Game model
            
            return jsonify({"message": "Warnings cleared", "game_id": game_id}), 200
            
    except Exception as e:
        logger.error(f"Error clearing warnings: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/games/<game_id>", methods=["DELETE"])
def delete_game(game_id):
    """
    Delete a game and all associated data (admin only).
    
    Returns:
    - Success message
    """
    # Check admin role
    is_admin, user_id = require_admin()
    if not is_admin:
        return jsonify({"error": "Admin access required"}), 403
    
    try:
        with get_db_session() as db:
            game = db.query(Game).filter_by(id=game_id).first()
            if not game:
                return jsonify({"error": "Game not found"}), 404
            
            # Delete the game (cascade will handle related records)
            db.delete(game)
            db.commit()
            
            return jsonify({"message": "Game deleted successfully", "game_id": game_id}), 200
            
    except Exception as e:
        logger.error(f"Error deleting game: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/games/<game_id>", methods=["GET"])
def get_game(game_id):
    """
    Get detailed game information including all players, stats, and matchups.
    
    Returns:
    - JSON with complete game data including payload structure
    """
    try:
        with get_db_session() as db:
            game = db.query(Game).filter_by(id=game_id).first()
            if not game:
                return jsonify({"error": "Game not found"}), 404
            
            # Build payload structure similar to ingest response
            # Get teams
            team_totals = db.query(TeamTotal).filter_by(game_id=game_id).all()
            teams_data = []
            for team_total in team_totals:
                teams_data.append({
                    "side": team_total.team_side,
                    "grade": team_total.grade,
                    "totals": {
                        "pts": team_total.pts,
                        "reb": team_total.reb,
                        "ast": team_total.ast,
                        "stl": team_total.stl,
                        "blk": team_total.blk,
                        "fouls": team_total.fouls,
                        "tov": team_total.tov,
                        "fgm": team_total.fgm,
                        "fga": team_total.fga,
                        "tpm": team_total.tpm,
                        "tpa": team_total.tpa,
                        "ftm": team_total.ftm,
                        "fta": team_total.fta
                    }
                })
            
            # Get players with stats — batch to avoid N+1
            game_players = db.query(GamePlayer).filter_by(game_id=game_id).all()
            gp_player_ids = [gp.player_id for gp in game_players]
            players_by_id = {
                p.id: p
                for p in db.query(Player).filter(Player.id.in_(gp_player_ids)).all()
            }
            stats_by_player_id = {
                s.player_id: s
                for s in db.query(PlayerGameStats).filter(
                    PlayerGameStats.game_id == game_id,
                    PlayerGameStats.player_id.in_(gp_player_ids)
                ).all()
            }
            players_data = []
            for gp in game_players:
                player = players_by_id.get(gp.player_id)
                stats = stats_by_player_id.get(gp.player_id)

                if player and stats:
                    # Get the user_id who owns this row (from claim if exists)
                    claim_owner_user_id = None
                    if gp.claim_id:
                        claim = gp.claim
                        if claim and claim.status == 'verified':
                            claim_owner_user_id = claim.user_id
                    
                    # Player platform: use game_player.platform if set, else game.platform (for backfill)
                    player_platform = getattr(gp, "platform", None) or game.platform
                    players_data.append({
                        "side": gp.team_side,
                        "row_index": gp.row_index,
                        "gamertag": player.gamertag,
                        "grade": stats.grade,
                        "assigned_position": gp.position,
                        "platform": player_platform,
                        "game_player_row_id": gp.id,  # Add game player row ID for build assignment
                        "build_id": gp.build_id,  # Add build_id if assigned
                        "claim_owner_user_id": claim_owner_user_id,  # User who owns this row (for loading their builds)
                        "stats": {
                            "pts": stats.pts,
                            "reb": stats.reb,
                            "ast": stats.ast,
                            "stl": stats.stl,
                            "blk": stats.blk,
                            "fouls": stats.fouls,
                            "tov": stats.tov,
                            "fgm": stats.fgm,
                            "fga": stats.fga,
                            "tpm": stats.tpm,
                            "tpa": stats.tpa,
                            "ftm": stats.ftm,
                            "fta": stats.fta
                        }
                    })
            
            # Get matchups — reuse players_by_id, fetch any missing IDs in one query
            matchups = db.query(Matchup).filter_by(game_id=game_id).all()
            matchup_player_ids = {m.defender_player_id for m in matchups} | {m.offender_player_id for m in matchups}
            missing_ids = matchup_player_ids - set(players_by_id)
            if missing_ids:
                for p in db.query(Player).filter(Player.id.in_(missing_ids)).all():
                    players_by_id[p.id] = p
            matchups_data = []
            for matchup in matchups:
                defender = players_by_id.get(matchup.defender_player_id)
                offender = players_by_id.get(matchup.offender_player_id)

                if defender and offender:
                    matchups_data.append({
                        "defender_gamertag": defender.gamertag,
                        "offender_gamertag": offender.gamertag,
                        "defender_position": matchup.defender_position,
                        "offender_position": matchup.offender_position,
                        "matchup_type": matchup.matchup_type
                    })
            
            # Build response
            payload = {
                "metadata": {
                    "season_label": game.season_label,
                    "mode_label": game.mode_label,
                    "game_version": game_version_of(game),
                    "extracted_from": "nba2k_rec_boxscore_screenshot"
                },
                "game": {
                    "away_score": game.away_score,
                    "home_score": game.home_score,
                    "quarters": {
                        "away": [game.away_q1, game.away_q2, game.away_q3, game.away_q4],
                        "home": [game.home_q1, game.home_q2, game.home_q3, game.home_q4]
                    }
                },
                "teams": teams_data,
                "players": players_data,
                "matchups": matchups_data
            }
            
            # Validate game data
            validation = validate_game_data(db, game_id)
            
            # Platform: use game.platform; if null, fall back to first game_player.platform (for older data)
            display_platform = game.platform
            if not display_platform and game_players:
                for gp in game_players:
                    gp_platform = getattr(gp, "platform", None)
                    if gp_platform:
                        display_platform = gp_platform
                        break
            
            # Check if screenshot exists
            screenshot_path = game.source_image_path if hasattr(game, 'source_image_path') else None
            screenshot_url = None
            if screenshot_path and os.path.exists(screenshot_path):
                screenshot_url = f"/api/games/{game_id}/screenshot"
            
            return jsonify({
                "game_id": game.id,
                "created_at": game.created_at,
                "platform": display_platform,
                "game_version": game_version_of(game),
                "payload": payload,
                "needs_verification": validation["needs_verification"],
                "warnings": validation["warnings"],
                "screenshot_url": screenshot_url
            }), 200
            
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/games/<game_id>/screenshot", methods=["GET"])
def get_game_screenshot(game_id):
    """
    Serve the screenshot image for a game.
    
    Returns:
    - Image file if found, 404 otherwise
    """
    try:
        with get_db_session() as db:
            game = db.query(Game).filter_by(id=game_id).first()
            if not game:
                return jsonify({"error": "Game not found"}), 404
            
            screenshot_path = game.source_image_path
            if not screenshot_path or not os.path.exists(screenshot_path):
                return jsonify({"error": "Screenshot not found"}), 404
            
            # Determine content type based on file extension
            file_ext = os.path.splitext(screenshot_path)[1].lower()
            mimetype_map = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }
            mimetype = mimetype_map.get(file_ext, 'image/png')
            
            return send_file(screenshot_path, mimetype=mimetype)
            
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/players/search", methods=["GET"])
def search_player():
    """
    Search for a player by gamertag and return their stats and paginated games.
    
    Query Parameters:
    - q: gamertag to search for (required, case-insensitive partial match)
    - platform: "PC", "Console", or "ALL" (default: "ALL")
    - page: 1-based page number for games list (default: 1)
    - per_page: games per page (default: 25)
    - game_version: "2K26", "2K27", or "all" (default: "2K27")
    
    Returns:
    - JSON with player info, aggregated stats (from all games), and paginated list of games
    """
    query = request.args.get("q", "").strip()
    platform = request.args.get("platform", "ALL")  # "PC", "Console", or "ALL"
    game_version, version_error = parse_game_version_param()
    if version_error:
        return jsonify({"error": version_error}), 400
    page = max(1, int(request.args.get("page", 1)))
    per_page = max(1, min(100, int(request.args.get("per_page", 25))))
    
    if not query:
        return jsonify({"error": "Missing 'q' query parameter"}), 400
    
    valid_platforms = ["PC", "Console", "ALL"]
    if platform not in valid_platforms:
        return jsonify({"error": f"Invalid platform. Must be one of: {', '.join(valid_platforms)}"}), 400
    
    try:
        with get_db_session() as db:
            # Search for player by gamertag (case-insensitive partial match)
            players = db.query(Player).filter(
                Player.gamertag.ilike(f"%{query}%")
            ).all()
            
            if not players:
                print(f"No players found matching '{query}'")
                return jsonify({
                    "player": None,
                    "games": [],
                    "aggregated_stats": None,
                    "message": f"No players found matching '{query}'"
                }), 200
            
            # Group players by case-insensitive gamertag (normalize to lowercase)
            # This combines players that only differ by capitalization
            player_groups = {}
            for player in players:
                normalized = player.gamertag.lower()
                if normalized not in player_groups:
                    player_groups[normalized] = []
                player_groups[normalized].append(player)
            
            # Prefer exact match; fall back to first group for partial matches
            normalized_key = query.lower() if query.lower() in player_groups else list(player_groups.keys())[0]
            matching_players = player_groups[normalized_key]
            player_ids = [p.id for p in matching_players]
            
            # Use the first player's gamertag as the display name (or most common variant)
            # Prefer the one that matches the query most closely
            display_player = matching_players[0]
            for p in matching_players:
                if p.gamertag.lower() == query.lower():
                    display_player = p
                    break
            
            # Get all games for all matching players (combined)
            game_players_query = db.query(GamePlayer).filter(
                GamePlayer.player_id.in_(player_ids)
            )
            
            # Filter by platform if specified (match Game.platform or GamePlayer.platform)
            if platform != "ALL":
                all_gps = game_players_query.all()
                game_ids = [gp.game_id for gp in all_gps]
                games_with_platform = db.query(Game).filter(
                    Game.id.in_(game_ids),
                    Game.platform == platform
                ).all()
                platform_game_ids = {g.id for g in games_with_platform}
                game_players = [
                    gp for gp in all_gps
                    if gp.game_id in platform_game_ids or getattr(gp, "platform", None) == platform
                ]
            else:
                game_players = game_players_query.all()

            # Restrict to one NBA 2K title unless the caller asked for all of them
            if game_version is not None and game_players:
                version_game_ids = {
                    row.id
                    for row in db.query(Game.id).filter(
                        Game.id.in_([gp.game_id for gp in game_players]),
                        game_version_clause(game_version),
                    ).all()
                }
                game_players = [gp for gp in game_players if gp.game_id in version_game_ids]
            
            games_data = []
            aggregated_stats = {
                "games_played": 0,
                "pts": 0,
                "reb": 0,
                "ast": 0,
                "stl": 0,
                "blk": 0,
                "fouls": 0,
                "tov": 0,
                "fgm": 0,
                "fga": 0,
                "tpm": 0,
                "tpa": 0,
                "ftm": 0,
                "fta": 0
            }
            
            # Track stats by position
            position_stats = {}  # position -> stats dict
            
            for gp in game_players:
                game = db.query(Game).filter_by(id=gp.game_id).first()
                stats = db.query(PlayerGameStats).filter_by(
                    game_id=gp.game_id,
                    player_id=gp.player_id
                ).first()
                
                if game and stats:
                    position = gp.position
                    
                    # Initialize position stats if not exists
                    if position not in position_stats:
                        position_stats[position] = {
                            "games_played": 0,
                            "pts": 0,
                            "reb": 0,
                            "ast": 0,
                            "stl": 0,
                            "blk": 0,
                            "fouls": 0,
                            "tov": 0,
                            "fgm": 0,
                            "fga": 0,
                            "tpm": 0,
                            "tpa": 0,
                            "ftm": 0,
                            "fta": 0
                        }
                    
                    # Add to aggregated stats
                    aggregated_stats["games_played"] += 1
                    aggregated_stats["pts"] += stats.pts
                    aggregated_stats["reb"] += stats.reb
                    aggregated_stats["ast"] += stats.ast
                    aggregated_stats["stl"] += stats.stl
                    aggregated_stats["blk"] += stats.blk
                    aggregated_stats["fouls"] += stats.fouls
                    aggregated_stats["tov"] += stats.tov
                    aggregated_stats["fgm"] += stats.fgm
                    aggregated_stats["fga"] += stats.fga
                    aggregated_stats["tpm"] += stats.tpm
                    aggregated_stats["tpa"] += stats.tpa
                    aggregated_stats["ftm"] += stats.ftm
                    aggregated_stats["fta"] += stats.fta
                    
                    # Add to position-specific stats
                    position_stats[position]["games_played"] += 1
                    position_stats[position]["pts"] += stats.pts
                    position_stats[position]["reb"] += stats.reb
                    position_stats[position]["ast"] += stats.ast
                    position_stats[position]["stl"] += stats.stl
                    position_stats[position]["blk"] += stats.blk
                    position_stats[position]["fouls"] += stats.fouls
                    position_stats[position]["tov"] += stats.tov
                    position_stats[position]["fgm"] += stats.fgm
                    position_stats[position]["fga"] += stats.fga
                    position_stats[position]["tpm"] += stats.tpm
                    position_stats[position]["tpa"] += stats.tpa
                    position_stats[position]["ftm"] += stats.ftm
                    position_stats[position]["fta"] += stats.fta
                    
                    # Get opponent info
                    opponent_players = db.query(GamePlayer).filter(
                        GamePlayer.game_id == gp.game_id,
                        GamePlayer.team_side != gp.team_side
                    ).limit(1).all()
                    
                    opponent_name = "Opponent"
                    if opponent_players:
                        opponent = db.query(Player).filter_by(id=opponent_players[0].player_id).first()
                        if opponent:
                            opponent_name = opponent.gamertag
                    
                    # Get team score
                    team_score = game.away_score if gp.team_side == "AWAY" else game.home_score
                    opponent_score = game.home_score if gp.team_side == "AWAY" else game.away_score
                    
                    # Get build information if assigned
                    build_info = None
                    if gp.build_id:
                        build = db.query(Build).filter_by(id=gp.build_id).first()
                        if build:
                            build_info = {
                                "build_id": build.id,
                                "build_name": build.display_name
                            }
                    
                    games_data.append({
                        "game_id": game.id,
                        "game_player_row_id": gp.id,  # Add game player row ID for build assignment
                        "created_at": game.created_at,
                        "team_side": gp.team_side,
                        "position": gp.position,
                        "platform": game.platform,  # Include platform in game data
                        "game_version": game_version_of(game),
                        "grade": stats.grade,
                        "team_score": team_score,
                        "opponent_score": opponent_score,
                        "opponent_team": opponent_name,
                        "season_label": game.season_label,
                        "mode_label": game.mode_label,
                        "build": build_info,
                        "stats": {
                            "pts": stats.pts,
                            "reb": stats.reb,
                            "ast": stats.ast,
                            "stl": stats.stl,
                            "blk": stats.blk,
                            "fouls": stats.fouls,
                            "tov": stats.tov,
                            "fgm": stats.fgm,
                            "fga": stats.fga,
                            "tpm": stats.tpm,
                            "tpa": stats.tpa,
                            "ftm": stats.ftm,
                            "fta": stats.fta
                        }
                    })
            
            # Calculate averages
            if aggregated_stats["games_played"] > 0:
                games_played = aggregated_stats["games_played"]
                aggregated_stats["avg_pts"] = round(aggregated_stats["pts"] / games_played, 1)
                aggregated_stats["avg_reb"] = round(aggregated_stats["reb"] / games_played, 1)
                aggregated_stats["avg_ast"] = round(aggregated_stats["ast"] / games_played, 1)
                aggregated_stats["avg_stl"] = round(aggregated_stats["stl"] / games_played, 1)
                aggregated_stats["avg_blk"] = round(aggregated_stats["blk"] / games_played, 1)
                aggregated_stats["avg_tov"] = round(aggregated_stats["tov"] / games_played, 1)
                
                # Calculate shooting percentages
                if aggregated_stats["fga"] > 0:
                    aggregated_stats["fg_pct"] = round((aggregated_stats["fgm"] / aggregated_stats["fga"]) * 100, 1)
                else:
                    aggregated_stats["fg_pct"] = 0.0
                
                if aggregated_stats["tpa"] > 0:
                    aggregated_stats["tp_pct"] = round((aggregated_stats["tpm"] / aggregated_stats["tpa"]) * 100, 1)
                else:
                    aggregated_stats["tp_pct"] = 0.0
                
                if aggregated_stats["fta"] > 0:
                    aggregated_stats["ft_pct"] = round((aggregated_stats["ftm"] / aggregated_stats["fta"]) * 100, 1)
                else:
                    aggregated_stats["ft_pct"] = 0.0
            
            # Calculate position-based averages and percentages
            # Sort positions in logical order: PG, SG, SF, PF, C
            position_order = ["PG", "SG", "SF", "PF", "C"]
            position_stats_formatted = {}
            sorted_positions = sorted(position_stats.keys(), key=lambda x: position_order.index(x) if x in position_order else 999)
            
            for pos in sorted_positions:
                stats = position_stats[pos]
                pos_stats = stats.copy()
                games_at_pos = stats["games_played"]
                
                if games_at_pos > 0:
                    pos_stats["avg_pts"] = round(stats["pts"] / games_at_pos, 1)
                    pos_stats["avg_reb"] = round(stats["reb"] / games_at_pos, 1)
                    pos_stats["avg_ast"] = round(stats["ast"] / games_at_pos, 1)
                    pos_stats["avg_stl"] = round(stats["stl"] / games_at_pos, 1)
                    pos_stats["avg_blk"] = round(stats["blk"] / games_at_pos, 1)
                    pos_stats["avg_tov"] = round(stats["tov"] / games_at_pos, 1)
                    
                    if stats["fga"] > 0:
                        pos_stats["fg_pct"] = round((stats["fgm"] / stats["fga"]) * 100, 1)
                    else:
                        pos_stats["fg_pct"] = 0.0
                    
                    if stats["tpa"] > 0:
                        pos_stats["tp_pct"] = round((stats["tpm"] / stats["tpa"]) * 100, 1)
                    else:
                        pos_stats["tp_pct"] = 0.0
                    
                    if stats["fta"] > 0:
                        pos_stats["ft_pct"] = round((stats["ftm"] / stats["fta"]) * 100, 1)
                    else:
                        pos_stats["ft_pct"] = 0.0
                
                position_stats_formatted[pos] = pos_stats
            
            # Calculate defensive statistics
            # Get all matchups where this player was the defender
            defensive_matchups = db.query(Matchup).filter(
                Matchup.defender_player_id.in_(player_ids)
            ).all()
            
            # Track defensive stats by position
            defensive_stats = {}  # position -> defensive stats dict
            overall_defensive_stats = {
                "matchups": 0,
                "opponent_pts": 0,
                "opponent_fgm": 0,
                "opponent_fga": 0,
                "opponent_tpm": 0,
                "opponent_tpa": 0,
                "opponent_ftm": 0,
                "opponent_fta": 0,
                "opponent_ast": 0,
                "opponent_tov": 0,
                "opponent_reb": 0,
                "steals": 0,
                "blocks": 0,
                # For comparison stats
                "opponent_normal_fgm": 0,
                "opponent_normal_fga": 0,
                "opponent_normal_tpm": 0,
                "opponent_normal_tpa": 0,
                "opponent_normal_games": 0
            }
            
            for matchup in defensive_matchups:
                # Get the defender's position in this matchup
                defender_gp = db.query(GamePlayer).filter_by(
                    game_id=matchup.game_id,
                    player_id=matchup.defender_player_id
                ).first()
                
                if not defender_gp:
                    continue
                
                defender_position = defender_gp.position
                
                # Get the offender's stats in this game
                offender_stats = db.query(PlayerGameStats).filter_by(
                    game_id=matchup.game_id,
                    player_id=matchup.offender_player_id
                ).first()
                
                if not offender_stats:
                    continue
                
                # Initialize defensive stats for this position if not exists
                if defender_position not in defensive_stats:
                    defensive_stats[defender_position] = {
                        "matchups": 0,
                        "opponent_pts": 0,
                        "opponent_fgm": 0,
                        "opponent_fga": 0,
                        "opponent_tpm": 0,
                        "opponent_tpa": 0,
                        "opponent_ftm": 0,
                        "opponent_fta": 0,
                        "opponent_ast": 0,
                        "opponent_tov": 0,
                        "opponent_reb": 0,
                        "steals": 0,
                        "blocks": 0,
                        # For comparison stats
                        "opponent_normal_fgm": 0,
                        "opponent_normal_fga": 0,
                        "opponent_normal_tpm": 0,
                        "opponent_normal_tpa": 0,
                        "opponent_normal_games": 0
                    }
                
                # Get opponent's position in this matchup
                offender_gp = db.query(GamePlayer).filter_by(
                    game_id=matchup.game_id,
                    player_id=matchup.offender_player_id
                ).first()
                
                if not offender_gp:
                    continue
                
                offender_position = offender_gp.position
                
                # Get opponent's stats in OTHER games at the same position (baseline)
                # Exclude the current matchup game
                other_games = db.query(GamePlayer).filter(
                    GamePlayer.player_id == matchup.offender_player_id,
                    GamePlayer.position == offender_position,
                    GamePlayer.game_id != matchup.game_id
                ).all()
                
                # Calculate opponent's normal stats at this position
                normal_fgm = 0
                normal_fga = 0
                normal_tpm = 0
                normal_tpa = 0
                normal_games_count = 0
                
                for other_gp in other_games:
                    other_stats = db.query(PlayerGameStats).filter_by(
                        game_id=other_gp.game_id,
                        player_id=other_gp.player_id
                    ).first()
                    
                    if other_stats:
                        normal_fgm += other_stats.fgm
                        normal_fga += other_stats.fga
                        normal_tpm += other_stats.tpm
                        normal_tpa += other_stats.tpa
                        normal_games_count += 1
                
                # Add to overall comparison stats
                if normal_games_count > 0:
                    overall_defensive_stats["opponent_normal_fgm"] += normal_fgm
                    overall_defensive_stats["opponent_normal_fga"] += normal_fga
                    overall_defensive_stats["opponent_normal_tpm"] += normal_tpm
                    overall_defensive_stats["opponent_normal_tpa"] += normal_tpa
                    overall_defensive_stats["opponent_normal_games"] += normal_games_count
                    
                    # Add to position-specific comparison stats
                    defensive_stats[defender_position]["opponent_normal_fgm"] += normal_fgm
                    defensive_stats[defender_position]["opponent_normal_fga"] += normal_fga
                    defensive_stats[defender_position]["opponent_normal_tpm"] += normal_tpm
                    defensive_stats[defender_position]["opponent_normal_tpa"] += normal_tpa
                    defensive_stats[defender_position]["opponent_normal_games"] += normal_games_count
                
                # Get defender's steals and blocks for this game
                defender_stats = db.query(PlayerGameStats).filter_by(
                    game_id=matchup.game_id,
                    player_id=matchup.defender_player_id
                ).first()
                
                # Add to overall defensive stats
                overall_defensive_stats["matchups"] += 1
                overall_defensive_stats["opponent_pts"] += offender_stats.pts
                overall_defensive_stats["opponent_fgm"] += offender_stats.fgm
                overall_defensive_stats["opponent_fga"] += offender_stats.fga
                overall_defensive_stats["opponent_tpm"] += offender_stats.tpm
                overall_defensive_stats["opponent_tpa"] += offender_stats.tpa
                overall_defensive_stats["opponent_ftm"] += offender_stats.ftm
                overall_defensive_stats["opponent_fta"] += offender_stats.fta
                overall_defensive_stats["opponent_ast"] += offender_stats.ast
                overall_defensive_stats["opponent_tov"] += offender_stats.tov
                overall_defensive_stats["opponent_reb"] += offender_stats.reb
                
                if defender_stats:
                    overall_defensive_stats["steals"] += defender_stats.stl
                    overall_defensive_stats["blocks"] += defender_stats.blk
                
                # Add to position-specific defensive stats
                defensive_stats[defender_position]["matchups"] += 1
                defensive_stats[defender_position]["opponent_pts"] += offender_stats.pts
                defensive_stats[defender_position]["opponent_fgm"] += offender_stats.fgm
                defensive_stats[defender_position]["opponent_fga"] += offender_stats.fga
                defensive_stats[defender_position]["opponent_tpm"] += offender_stats.tpm
                defensive_stats[defender_position]["opponent_tpa"] += offender_stats.tpa
                defensive_stats[defender_position]["opponent_ftm"] += offender_stats.ftm
                defensive_stats[defender_position]["opponent_fta"] += offender_stats.fta
                defensive_stats[defender_position]["opponent_ast"] += offender_stats.ast
                defensive_stats[defender_position]["opponent_tov"] += offender_stats.tov
                defensive_stats[defender_position]["opponent_reb"] += offender_stats.reb
                
                if defender_stats:
                    defensive_stats[defender_position]["steals"] += defender_stats.stl
                    defensive_stats[defender_position]["blocks"] += defender_stats.blk
            
            # Calculate defensive averages and percentages
            defensive_stats_formatted = {}
            if overall_defensive_stats["matchups"] > 0:
                matchups_count = overall_defensive_stats["matchups"]
                overall_defensive_stats["avg_opponent_pts"] = round(overall_defensive_stats["opponent_pts"] / matchups_count, 1)
                overall_defensive_stats["avg_opponent_ast"] = round(overall_defensive_stats["opponent_ast"] / matchups_count, 1)
                overall_defensive_stats["avg_opponent_reb"] = round(overall_defensive_stats["opponent_reb"] / matchups_count, 1)
                overall_defensive_stats["avg_opponent_tov"] = round(overall_defensive_stats["opponent_tov"] / matchups_count, 1)
                overall_defensive_stats["avg_steals"] = round(overall_defensive_stats["steals"] / matchups_count, 1)
                overall_defensive_stats["avg_blocks"] = round(overall_defensive_stats["blocks"] / matchups_count, 1)
                
                if overall_defensive_stats["opponent_fga"] > 0:
                    overall_defensive_stats["opponent_fg_pct"] = round((overall_defensive_stats["opponent_fgm"] / overall_defensive_stats["opponent_fga"]) * 100, 1)
                else:
                    overall_defensive_stats["opponent_fg_pct"] = 0.0
                
                if overall_defensive_stats["opponent_tpa"] > 0:
                    overall_defensive_stats["opponent_tp_pct"] = round((overall_defensive_stats["opponent_tpm"] / overall_defensive_stats["opponent_tpa"]) * 100, 1)
                else:
                    overall_defensive_stats["opponent_tp_pct"] = 0.0
                
                if overall_defensive_stats["opponent_fta"] > 0:
                    overall_defensive_stats["opponent_ft_pct"] = round((overall_defensive_stats["opponent_ftm"] / overall_defensive_stats["opponent_fta"]) * 100, 1)
                else:
                    overall_defensive_stats["opponent_ft_pct"] = 0.0
                
                # Calculate opponent's normal FG% at their position (baseline)
                if overall_defensive_stats["opponent_normal_fga"] > 0:
                    overall_defensive_stats["opponent_normal_fg_pct"] = round((overall_defensive_stats["opponent_normal_fgm"] / overall_defensive_stats["opponent_normal_fga"]) * 100, 1)
                    # Calculate difference (how much better/worse they shoot when guarded)
                    overall_defensive_stats["fg_pct_difference"] = round(overall_defensive_stats["opponent_fg_pct"] - overall_defensive_stats["opponent_normal_fg_pct"], 1)
                else:
                    overall_defensive_stats["opponent_normal_fg_pct"] = None
                    overall_defensive_stats["fg_pct_difference"] = None
                
                # Calculate opponent's normal 3PT% at their position
                if overall_defensive_stats["opponent_normal_tpa"] > 0:
                    overall_defensive_stats["opponent_normal_tp_pct"] = round((overall_defensive_stats["opponent_normal_tpm"] / overall_defensive_stats["opponent_normal_tpa"]) * 100, 1)
                    overall_defensive_stats["tp_pct_difference"] = round(overall_defensive_stats["opponent_tp_pct"] - overall_defensive_stats["opponent_normal_tp_pct"], 1)
                else:
                    overall_defensive_stats["opponent_normal_tp_pct"] = None
                    overall_defensive_stats["tp_pct_difference"] = None
            
            # Format position-specific defensive stats
            for pos in sorted_positions:
                if pos in defensive_stats:
                    pos_def_stats = defensive_stats[pos].copy()
                    matchups_at_pos = pos_def_stats["matchups"]
                    
                    if matchups_at_pos > 0:
                        pos_def_stats["avg_opponent_pts"] = round(pos_def_stats["opponent_pts"] / matchups_at_pos, 1)
                        pos_def_stats["avg_opponent_ast"] = round(pos_def_stats["opponent_ast"] / matchups_at_pos, 1)
                        pos_def_stats["avg_opponent_reb"] = round(pos_def_stats["opponent_reb"] / matchups_at_pos, 1)
                        pos_def_stats["avg_opponent_tov"] = round(pos_def_stats["opponent_tov"] / matchups_at_pos, 1)
                        pos_def_stats["avg_steals"] = round(pos_def_stats["steals"] / matchups_at_pos, 1)
                        pos_def_stats["avg_blocks"] = round(pos_def_stats["blocks"] / matchups_at_pos, 1)
                        
                        if pos_def_stats["opponent_fga"] > 0:
                            pos_def_stats["opponent_fg_pct"] = round((pos_def_stats["opponent_fgm"] / pos_def_stats["opponent_fga"]) * 100, 1)
                        else:
                            pos_def_stats["opponent_fg_pct"] = 0.0
                        
                        if pos_def_stats["opponent_tpa"] > 0:
                            pos_def_stats["opponent_tp_pct"] = round((pos_def_stats["opponent_tpm"] / pos_def_stats["opponent_tpa"]) * 100, 1)
                        else:
                            pos_def_stats["opponent_tp_pct"] = 0.0
                        
                        if pos_def_stats["opponent_fta"] > 0:
                            pos_def_stats["opponent_ft_pct"] = round((pos_def_stats["opponent_ftm"] / pos_def_stats["opponent_fta"]) * 100, 1)
                        else:
                            pos_def_stats["opponent_ft_pct"] = 0.0
                        
                        # Calculate opponent's normal FG% at their position (baseline)
                        if pos_def_stats["opponent_normal_fga"] > 0:
                            pos_def_stats["opponent_normal_fg_pct"] = round((pos_def_stats["opponent_normal_fgm"] / pos_def_stats["opponent_normal_fga"]) * 100, 1)
                            pos_def_stats["fg_pct_difference"] = round(pos_def_stats["opponent_fg_pct"] - pos_def_stats["opponent_normal_fg_pct"], 1)
                        else:
                            pos_def_stats["opponent_normal_fg_pct"] = None
                            pos_def_stats["fg_pct_difference"] = None
                        
                        # Calculate opponent's normal 3PT% at their position
                        if pos_def_stats["opponent_normal_tpa"] > 0:
                            pos_def_stats["opponent_normal_tp_pct"] = round((pos_def_stats["opponent_normal_tpm"] / pos_def_stats["opponent_normal_tpa"]) * 100, 1)
                            pos_def_stats["tp_pct_difference"] = round(pos_def_stats["opponent_tp_pct"] - pos_def_stats["opponent_normal_tp_pct"], 1)
                        else:
                            pos_def_stats["opponent_normal_tp_pct"] = None
                            pos_def_stats["tp_pct_difference"] = None
                    
                    defensive_stats_formatted[pos] = pos_def_stats
            
            # Sort games by date (newest first)
            games_data.sort(key=lambda x: x["created_at"], reverse=True)
            
            total_games = len(games_data)
            total_pages = (total_games + per_page - 1) // per_page if total_games > 0 else 1
            page = min(page, total_pages)
            offset = (page - 1) * per_page
            games_page = games_data[offset : offset + per_page]
            
            # Collect all variant gamertags for display
            variant_gamertags = [p.gamertag for p in matching_players]
            
            return jsonify({
                "player": {
                    "id": display_player.id,
                    "gamertag": display_player.gamertag,
                    "variant_gamertags": variant_gamertags if len(variant_gamertags) > 1 else None
                },
                "games": games_page,
                "total_games": total_games,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "game_version": game_version or "all",
                "aggregated_stats": aggregated_stats,
                "position_stats": position_stats_formatted,
                "defensive_stats": overall_defensive_stats if overall_defensive_stats["matchups"] > 0 else None,
                "defensive_stats_by_position": defensive_stats_formatted if defensive_stats_formatted else None,
                "total_matches": len(players),
                "combined_players": len(matching_players) if len(matching_players) > 1 else None
            }), 200
            
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/players/suggest", methods=["GET"])
def suggest_players():
    """
    Autocomplete: return up to N gamertags matching the query (partial, case-insensitive).
    Query Parameters: q (required), limit (default 10).
    Returns: { "suggestions": [ { "gamertag": "..." }, ... ] }
    """
    query = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 10)), 20)
    if not query:
        return jsonify({"suggestions": []}), 200
    try:
        with get_db_session() as db:
            rows = (
                db.query(Player.gamertag)
                .filter(Player.gamertag.ilike(f"%{query}%"))
                .distinct()
                .limit(limit)
                .all()
            )
            suggestions = [{"gamertag": r[0]} for r in rows]
            return jsonify({"suggestions": suggestions}), 200
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/players/<username>/profile", methods=["GET"])
def get_player_profile_route(username):
    """
    Get player profile with personalized insights, trends, and shareable stat card.
    
    Path Parameters:
    - username: Player gamertag (case-insensitive)
    
    Query Parameters:
    - game_version: NBA 2K title to profile (2K26, 2K27, all) - defaults to 2K27
    
    Returns:
    - JSON with summary stats, recent trends, insights, and share card
    """
    game_version, version_error = parse_game_version_param()
    if version_error:
        return jsonify({"error": version_error}), 400
    cache_key = f"{username.lower()}|{game_version or 'all'}"

    try:
        # Check cache first
        cached = get_cached_profile(cache_key)
        if cached:
            print(f"Returning cached profile for {username}")
            print(f"Cached insights count: {len(cached.get('insights', []))}")
            return jsonify(cached), 200
        
        print(f"No cache for {username}, fetching from database")
        with get_db_session() as db:
            profile_data = get_player_profile(db, username, game_version=game_version)
            print(f"Profile data fetched - gamesPlayed: {profile_data.get('summary', {}).get('gamesPlayed', 0)}")
            print(f"Insights count: {len(profile_data.get('insights', []))}")
            if "error" in profile_data:
                print("error")
                return jsonify(profile_data), 404
            
            # Cache the result
            profile_data["gameVersion"] = game_version or "all"
            set_cached_profile(cache_key, profile_data)
            print(f"Cached profile for {username}")

            return jsonify(profile_data), 200
            
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/players/<username>/chemistry", methods=["GET"])
def get_player_chemistry_route(username):
    """
    Squad chemistry: who this player wins with and plays against most.

    Derived from recorded game lineups — teammates (same side) with win rate
    together, and rivals (opposite side) with the player's record against them.

    Query params:
    - limit: max teammates/rivals to return (default 20, capped at 50)
    """
    try:
        limit = min(int(request.args.get("limit", 20)), 50)
    except (TypeError, ValueError):
        limit = 20
    try:
        with get_db_session() as db:
            data = get_player_chemistry(db, username, limit=limit)
            if "error" in data:
                return jsonify(data), 404
            return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/players/<username>/analysis", methods=["GET"])
def get_player_analysis(username):
    """
    Get AI-powered performance analysis for a player.
    
    Path Parameters:
    - username: Player gamertag (case-insensitive)
    
    Query Parameters:
    - last_n: Number of recent games to analyze (default: 25)
    
    Returns:
    - JSON with comprehensive analysis including strengths, weaknesses, coaching plan, etc.
    """
    try:
        # Get query parameter
        last_n = request.args.get("last_n", type=int)
        if last_n is None:
            last_n = 25
        
        with get_db_session() as db:
            # Build the payload
            payload = build_player_analysis_payload(db, username, last_n)
            
            # Check cache
            payload_hash = get_payload_hash(payload)
            
            # Check for cached result (within 24 hours)
            cache_entry = db.query(PlayerAnalysisCache).filter(
                PlayerAnalysisCache.username == username.lower(),
                PlayerAnalysisCache.last_n == last_n,
                PlayerAnalysisCache.payload_hash == payload_hash
            ).order_by(
                desc(PlayerAnalysisCache.created_at)
            ).first()
            
            if cache_entry:
                # Check if cache is still valid (< 24 hours old)
                cache_time = datetime.fromisoformat(cache_entry.created_at)
                if datetime.utcnow() - cache_time < timedelta(hours=24):
                    # Return cached result
                    return jsonify(json.loads(cache_entry.response_json)), 200
            
            # Generate new analysis
            analysis = analyze_player_with_openai(payload)
            
            # Store in cache
            cache_entry = PlayerAnalysisCache(
                username=username.lower(),
                last_n=last_n,
                payload_hash=payload_hash,
                response_json=json.dumps(analysis)
            )
            db.add(cache_entry)
            db.commit()
            
            return jsonify(analysis), 200
            
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Error generating player analysis: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/leaderboard", methods=["GET"])
def get_leaderboard():
    """
    Get leaderboard data for various statistics.
    
    Query Parameters:
    - stat: statistic to rank by (pts, reb, ast, stl, blk, fg_pct, tp_pct, ft_pct, games)
    - limit: number of players to return (default: 20)
    - min_games: minimum games played to be included (default: 5)
    - position: filter by position (PG, SG, SF, PF, C) or "ALL" for all positions (default: "ALL")
    - game_version: NBA 2K title to rank within (2K26, 2K27, all) - defaults to 2K27
    
    Returns:
    - JSON array of players ranked by the specified stat
    """
    stat = request.args.get("stat", "pts")
    limit = int(request.args.get("limit", 20))
    min_games = int(request.args.get("min_games", 5))
    position = request.args.get("position", "ALL").upper()
    platform = request.args.get("platform", "ALL")  # "PC", "Console", or "ALL"
    game_version, version_error = parse_game_version_param()
    if version_error:
        return jsonify({"error": version_error}), 400

    valid_stats = ["pts", "reb", "ast", "stl", "blk", "fg_pct", "tp_pct", "ft_pct", "games", "avg_pts", "avg_reb", "avg_ast", "avg_tpm", "avg_tpa", "winrate"]
    valid_positions = ["PG", "SG", "SF", "PF", "C", "ALL"]
    valid_platforms = ["PC", "Console", "ALL"]

    if stat not in valid_stats:
        return jsonify({"error": f"Invalid stat. Must be one of: {', '.join(valid_stats)}"}), 400

    if position not in valid_positions:
        return jsonify({"error": f"Invalid position. Must be one of: {', '.join(valid_positions)}"}), 400

    if platform not in valid_platforms:
        return jsonify({"error": f"Invalid platform. Must be one of: {', '.join(valid_platforms)}"}), 400

    cache_key = make_leaderboard_key(stat, limit, min_games, position, platform, game_version)
    cached = get_cached_leaderboard(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    try:
        with get_db_session() as db:
            win_expr = case(
                (and_(GamePlayer.team_side == "HOME", Game.home_score > Game.away_score), 1),
                (and_(GamePlayer.team_side == "AWAY", Game.away_score > Game.home_score), 1),
                else_=0
            )

            q = db.query(
                Player.id.label("player_id"),
                Player.gamertag,
                func.count(PlayerGameStats.id).label("games_played"),
                func.sum(PlayerGameStats.pts).label("pts"),
                func.sum(PlayerGameStats.reb).label("reb"),
                func.sum(PlayerGameStats.ast).label("ast"),
                func.sum(PlayerGameStats.stl).label("stl"),
                func.sum(PlayerGameStats.blk).label("blk"),
                func.sum(PlayerGameStats.fgm).label("fgm"),
                func.sum(PlayerGameStats.fga).label("fga"),
                func.sum(PlayerGameStats.tpm).label("tpm"),
                func.sum(PlayerGameStats.tpa).label("tpa"),
                func.sum(PlayerGameStats.ftm).label("ftm"),
                func.sum(PlayerGameStats.fta).label("fta"),
                func.sum(win_expr).label("wins"),
            ).join(
                PlayerGameStats, PlayerGameStats.player_id == Player.id
            ).join(
                GamePlayer, and_(
                    GamePlayer.game_id == PlayerGameStats.game_id,
                    GamePlayer.player_id == Player.id
                )
            ).join(
                Game, Game.id == PlayerGameStats.game_id
            )

            if position != "ALL":
                q = q.filter(GamePlayer.position == position)

            if platform != "ALL":
                q = q.filter(or_(Game.platform == platform, GamePlayer.platform == platform))

            version_filter = game_version_clause(game_version)
            if version_filter is not None:
                q = q.filter(version_filter)

            q = q.group_by(Player.id, Player.gamertag).having(
                func.count(PlayerGameStats.id) >= min_games
            )

            rows = q.all()

            leaderboard_data = []
            for row in rows:
                gp = row.games_played
                total_pts = row.pts or 0
                total_reb = row.reb or 0
                total_ast = row.ast or 0
                total_stl = row.stl or 0
                total_blk = row.blk or 0
                total_fgm = row.fgm or 0
                total_fga = row.fga or 0
                total_tpm = row.tpm or 0
                total_tpa = row.tpa or 0
                total_ftm = row.ftm or 0
                total_fta = row.fta or 0
                wins = row.wins or 0

                fg_pct = round(total_fgm / total_fga * 100, 1) if total_fga > 0 else 0.0
                tp_pct = round(total_tpm / total_tpa * 100, 1) if total_tpa > 0 else 0.0
                ft_pct = round(total_ftm / total_fta * 100, 1) if total_fta > 0 else 0.0
                winrate = round(wins / gp * 100, 1) if gp > 0 else 0.0
                avg_pts = round(total_pts / gp, 1) if gp > 0 else 0.0
                avg_reb = round(total_reb / gp, 1) if gp > 0 else 0.0
                avg_ast = round(total_ast / gp, 1) if gp > 0 else 0.0
                avg_tpm = round(total_tpm / gp, 1) if gp > 0 else 0.0
                avg_tpa = round(total_tpa / gp, 1) if gp > 0 else 0.0

                rank_value_map = {
                    "pts": total_pts, "reb": total_reb, "ast": total_ast,
                    "stl": total_stl, "blk": total_blk, "fg_pct": fg_pct,
                    "tp_pct": tp_pct, "ft_pct": ft_pct, "games": gp,
                    "avg_pts": avg_pts, "avg_reb": avg_reb, "avg_ast": avg_ast,
                    "avg_tpm": avg_tpm, "avg_tpa": avg_tpa, "winrate": winrate,
                }

                leaderboard_data.append({
                    "gamertag": row.gamertag,
                    "player_id": row.player_id,
                    "games_played": gp,
                    "pts": total_pts,
                    "reb": total_reb,
                    "ast": total_ast,
                    "stl": total_stl,
                    "blk": total_blk,
                    "fg_pct": fg_pct,
                    "tp_pct": tp_pct,
                    "ft_pct": ft_pct,
                    "avg_pts": avg_pts,
                    "avg_reb": avg_reb,
                    "avg_ast": avg_ast,
                    "avg_tpm": avg_tpm,
                    "avg_tpa": avg_tpa,
                    "winrate": winrate,
                    "rank_value": rank_value_map.get(stat, 0),
                })

            leaderboard_data.sort(key=lambda x: x["rank_value"], reverse=True)
            leaderboard_data = leaderboard_data[:limit]
            for idx, entry in enumerate(leaderboard_data, 1):
                entry["rank"] = idx

            response_data = {
                "stat": stat,
                "game_version": game_version or "all",
                "leaderboard": leaderboard_data,
            }
            set_cached_leaderboard(cache_key, response_data)
            return jsonify(response_data), 200

    except Exception as e:
            return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/analytics/rec-impact-rating", methods=["GET"])
def get_rec_impact_rating():
    """
    Calculate Rec Impact Rating (RIR) for all players.
    
    RIR = ((PTS × efficiency_weight) + (AST × 1.25) + ((STL + BLK) × 1.5) + 
           (REB × position_modifier) - (TO × 1.75)) × Usage Adjustment
    
    Query Parameters:
    - min_games: minimum games played to be included (default: 5)
    
    Returns:
    - JSON with RIR and component breakdowns for each player
    """
    min_games = int(request.args.get("min_games", 10))

    cache_key = f"rir|{min_games}"
    cached = get_cached_leaderboard(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    # Position modifiers for rebounds (bigs get more credit)
    position_reb_modifiers = {
        "PG": 0.8,
        "SG": 0.9,
        "SF": 1.0,
        "PF": 1.2,
        "C": 1.3
    }
    
    try:
        with get_db_session() as db:
            all_players = db.query(Player).all()
            
            rir_data = []
            
            for player in all_players:
                game_players = db.query(GamePlayer).filter_by(player_id=player.id).all()
                
                if len(game_players) < min_games:
                    continue
                
                # Aggregate stats
                total_pts = 0
                total_ast = 0
                total_stl = 0
                total_blk = 0
                total_reb = 0
                total_tov = 0
                total_fgm = 0
                total_fga = 0
                total_tpm = 0
                total_tpa = 0
                total_ftm = 0
                total_fta = 0
                games_played = len(game_players)
                
                # Track position distribution for usage calculation
                position_games = {}
                
                for gp in game_players:
                    stats = db.query(PlayerGameStats).filter_by(
                        game_id=gp.game_id,
                        player_id=player.id
                    ).first()
                    
                    if stats:
                        position = gp.position
                        position_games[position] = position_games.get(position, 0) + 1
                        
                        total_pts += stats.pts
                        total_ast += stats.ast
                        total_stl += stats.stl
                        total_blk += stats.blk
                        total_reb += stats.reb
                        total_tov += stats.tov
                        total_fgm += stats.fgm
                        total_fga += stats.fga
                        total_tpm += stats.tpm
                        total_tpa += stats.tpa
                        total_ftm += stats.ftm
                        total_fta += stats.fta
                
                if games_played == 0:
                    continue
                
                # Calculate averages
                avg_pts = total_pts / games_played
                avg_ast = total_ast / games_played
                avg_stl = total_stl / games_played
                avg_blk = total_blk / games_played
                avg_reb = total_reb / games_played
                avg_tov = total_tov / games_played
                
                # Calculate efficiency weight (based on shooting percentages)
                fg_pct = (total_fgm / total_fga * 100) if total_fga > 0 else 0
                tp_pct = (total_tpm / total_tpa * 100) if total_tpa > 0 else 0
                ft_pct = (total_ftm / total_fta * 100) if total_fta > 0 else 0
                
                # Efficiency weight: weighted average of shooting percentages
                # FG% weighted 60%, 3PT% weighted 30%, FT% weighted 10%
                efficiency_weight = (fg_pct * 0.6) + (tp_pct * 0.3) + (ft_pct * 0.1)
                # Normalize to 0.5-1.5 range (50% shooting = 1.0, 30% = 0.6, 70% = 1.4)
                efficiency_weight = 0.5 + (efficiency_weight / 100) * 1.0
                
                # Determine primary position (most games played)
                primary_position = max(position_games.items(), key=lambda x: x[1])[0] if position_games else "SF"
                position_modifier = position_reb_modifiers.get(primary_position, 1.0)
                
                # Calculate base RIR components
                pts_component = avg_pts * efficiency_weight
                ast_component = avg_ast * 1.25
                defensive_component = (avg_stl + avg_blk) * 1.5
                reb_component = avg_reb * position_modifier
                tov_penalty = avg_tov * 1.75
                
                base_rir = pts_component + ast_component + defensive_component + reb_component - tov_penalty
                
                # Usage Adjustment: based on how much they contribute to team stats
                # Get team totals for games this player played in
                total_team_pts = 0
                total_team_ast = 0
                total_team_games = 0
                
                for gp in game_players:
                    team_total = db.query(TeamTotal).filter_by(
                        game_id=gp.game_id,
                        team_side=gp.team_side
                    ).first()
                    
                    if team_total:
                        total_team_pts += team_total.pts
                        total_team_ast += team_total.ast
                        total_team_games += 1
                
                # Usage = player's contribution to team scoring
                avg_team_pts = total_team_pts / total_team_games if total_team_games > 0 else 100
                usage_rate = (avg_pts / avg_team_pts) if avg_team_pts > 0 else 0.2
                # Normalize usage: 0.15 (low usage) to 0.35 (high usage) = 0.7 to 1.3 multiplier
                usage_adjustment = 0.7 + (usage_rate * 2.0)
                usage_adjustment = max(0.7, min(1.3, usage_adjustment))  # Clamp between 0.7 and 1.3
                
                # Calculate Stability Index
                # Stability Index = (AST / (AST + TO)) × (FGM / FGA) × Team Assist Share
                ast_to_ratio = 0.0
                if (total_ast + total_tov) > 0:
                    ast_to_ratio = total_ast / (total_ast + total_tov)
                
                fg_ratio = 0.0
                if total_fga > 0:
                    fg_ratio = total_fgm / total_fga
                
                team_assist_share = 0.0
                avg_team_ast = total_team_ast / total_team_games if total_team_games > 0 else 0
                if avg_team_ast > 0:
                    team_assist_share = avg_ast / avg_team_ast
                    # Cap at 1.0 (player can't have more than 100% of team assists)
                    team_assist_share = min(1.0, team_assist_share)
                
                stability_index = ast_to_ratio * fg_ratio * team_assist_share
                
                # Final RIR
                final_rir = base_rir * usage_adjustment
                
                rir_data.append({
                    "player_id": player.id,
                    "gamertag": player.gamertag,
                    "games_played": games_played,
                    "primary_position": primary_position,
                    "rir": round(final_rir, 2),
                    "base_rir": round(base_rir, 2),
                    "usage_adjustment": round(usage_adjustment, 3),
                    "components": {
                        "pts_component": round(pts_component, 2),
                        "ast_component": round(ast_component, 2),
                        "defensive_component": round(defensive_component, 2),
                        "reb_component": round(reb_component, 2),
                        "tov_penalty": round(tov_penalty, 2)
                    },
                    "efficiency_weight": round(efficiency_weight, 3),
                    "position_modifier": position_modifier,
                    "shooting": {
                        "fg_pct": round(fg_pct, 1),
                        "tp_pct": round(tp_pct, 1),
                        "ft_pct": round(ft_pct, 1)
                    },
                    "averages": {
                        "pts": round(avg_pts, 1),
                        "ast": round(avg_ast, 1),
                        "stl": round(avg_stl, 1),
                        "blk": round(avg_blk, 1),
                        "reb": round(avg_reb, 1),
                        "tov": round(avg_tov, 1)
                    },
                    "stability_index": round(stability_index, 4),
                    "stability_components": {
                        "ast_to_ratio": round(ast_to_ratio, 3),
                        "fg_ratio": round(fg_ratio, 3),
                        "team_assist_share": round(team_assist_share, 3)
                    }
                })
            
            # Sort by RIR (descending)
            rir_data.sort(key=lambda x: x["rir"], reverse=True)
            
            # Add rank
            for idx, player in enumerate(rir_data, 1):
                player["rank"] = idx
            
            response_data = {"rir_leaderboard": rir_data}
            set_cached_leaderboard(cache_key, response_data)
            return jsonify(response_data), 200

    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/analytics/efficiency", methods=["GET"])
def get_efficiency_analytics():
    """
    Get efficiency analytics for all players including team performance metrics.
    
    Query Parameters:
    - min_games: minimum games played to be included (default: 5)
    
    Returns:
    - JSON with efficiency metrics for each player including:
      - Win rate by position
      - Team scoring efficiency by position
      - Player impact on team performance
      - Position efficiency ratings
    """
    min_games = int(request.args.get("min_games", 10))

    cache_key = f"efficiency|{min_games}"
    cached = get_cached_leaderboard(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    try:
        with get_db_session() as db:
            all_players = db.query(Player).all()

            analytics_data = []
            
            for player in all_players:
                game_players = db.query(GamePlayer).filter_by(player_id=player.id).all()
                
                if len(game_players) < min_games:
                    continue
                
                # Track stats by position
                position_metrics = {}
                
                for gp in game_players:
                    game = db.query(Game).filter_by(id=gp.game_id).first()
                    player_stats = db.query(PlayerGameStats).filter_by(
                        game_id=gp.game_id,
                        player_id=player.id
                    ).first()
                    
                    if not game or not player_stats:
                        continue
                    
                    position = gp.position
                    
                    if position not in position_metrics:
                        position_metrics[position] = {
                            "games": 0,
                            "wins": 0,
                            "losses": 0,
                            "team_points": 0,
                            "opponent_points": 0,
                            "player_points": 0,
                            "team_fg_made": 0,
                            "team_fg_attempted": 0,
                            "player_fg_made": 0,
                            "player_fg_attempted": 0,
                            "plus_minus": 0
                        }
                    
                    # Determine win/loss
                    team_score = game.away_score if gp.team_side == "AWAY" else game.home_score
                    opponent_score = game.home_score if gp.team_side == "AWAY" else game.away_score
                    
                    is_win = team_score > opponent_score
                    
                    # Get team totals
                    team_total = db.query(TeamTotal).filter_by(
                        game_id=gp.game_id,
                        team_side=gp.team_side
                    ).first()
                    
                    position_metrics[position]["games"] += 1
                    if is_win:
                        position_metrics[position]["wins"] += 1
                    else:
                        position_metrics[position]["losses"] += 1
                    
                    position_metrics[position]["team_points"] += team_score
                    position_metrics[position]["opponent_points"] += opponent_score
                    position_metrics[position]["player_points"] += player_stats.pts
                    position_metrics[position]["plus_minus"] += (team_score - opponent_score)
                    
                    if team_total:
                        position_metrics[position]["team_fg_made"] += team_total.fgm
                        position_metrics[position]["team_fg_attempted"] += team_total.fga
                    
                    position_metrics[position]["player_fg_made"] += player_stats.fgm
                    position_metrics[position]["player_fg_attempted"] += player_stats.fga
                
                # Calculate efficiency metrics for each position
                position_efficiency = {}
                for pos, metrics in position_metrics.items():
                    games = metrics["games"]
                    if games == 0:
                        continue
                    
                    win_rate = round((metrics["wins"] / games) * 100, 1)
                    avg_team_pts = round(metrics["team_points"] / games, 1)
                    avg_opponent_pts = round(metrics["opponent_points"] / games, 1)
                    avg_player_pts = round(metrics["player_points"] / games, 1)
                    avg_plus_minus = round(metrics["plus_minus"] / games, 1)
                    
                    # Team FG%
                    team_fg_pct = 0.0
                    if metrics["team_fg_attempted"] > 0:
                        team_fg_pct = round((metrics["team_fg_made"] / metrics["team_fg_attempted"]) * 100, 1)
                    
                    # Player FG%
                    player_fg_pct = 0.0
                    if metrics["player_fg_attempted"] > 0:
                        player_fg_pct = round((metrics["player_fg_made"] / metrics["player_fg_attempted"]) * 100, 1)
                    
                    # Scoring efficiency (team points per game when player is at this position)
                    # Impact rating (how much better team performs with player at this position)
                    position_efficiency[pos] = {
                        "games": games,
                        "win_rate": win_rate,
                        "avg_team_points": avg_team_pts,
                        "avg_opponent_points": avg_opponent_pts,
                        "avg_player_points": avg_player_pts,
                        "avg_plus_minus": avg_plus_minus,
                        "team_fg_pct": team_fg_pct,
                        "player_fg_pct": player_fg_pct,
                        "team_scoring_efficiency": avg_team_pts,  # Points per game
                        "defensive_rating": avg_opponent_pts,  # Points allowed per game
                        "net_rating": avg_plus_minus  # Plus/minus per game
                    }
                
                # Calculate overall efficiency
                total_games = sum(m["games"] for m in position_metrics.values())
                total_wins = sum(m["wins"] for m in position_metrics.values())
                total_team_pts = sum(m["team_points"] for m in position_metrics.values())
                total_opponent_pts = sum(m["opponent_points"] for m in position_metrics.values())
                total_plus_minus = sum(m["plus_minus"] for m in position_metrics.values())
                
                overall_win_rate = round((total_wins / total_games) * 100, 1) if total_games > 0 else 0.0
                overall_team_pts = round(total_team_pts / total_games, 1) if total_games > 0 else 0.0
                overall_opponent_pts = round(total_opponent_pts / total_games, 1) if total_games > 0 else 0.0
                overall_plus_minus = round(total_plus_minus / total_games, 1) if total_games > 0 else 0.0
                
                # Find best position (highest win rate with minimum 3 games)
                best_position = None
                best_win_rate = 0
                for pos, eff in position_efficiency.items():
                    if eff["games"] >= 3 and eff["win_rate"] > best_win_rate:
                        best_win_rate = eff["win_rate"]
                        best_position = pos
                
                analytics_data.append({
                    "player_id": player.id,
                    "gamertag": player.gamertag,
                    "total_games": total_games,
                    "total_wins": total_wins,
                    "overall_win_rate": overall_win_rate,
                    "overall_team_points": overall_team_pts,
                    "overall_opponent_points": overall_opponent_pts,
                    "overall_plus_minus": overall_plus_minus,
                    "best_position": best_position,
                    "best_position_win_rate": best_win_rate if best_position else None,
                    "position_efficiency": position_efficiency
                })
            
            # Sort by overall win rate (descending)
            analytics_data.sort(key=lambda x: x["overall_win_rate"], reverse=True)
            
            response_data = {"analytics": analytics_data}
            set_cached_leaderboard(cache_key, response_data)
            return jsonify(response_data), 200

    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.get("/")
def root():
    return {"ok": True, "service": "blueozark-api", "health": "/health"}


# ============================================================================
# Admin Metrics Endpoints (Admin Only)
# ============================================================================

@app.route("/api/admin/players/<player_id>/metrics", methods=["GET"])
def get_admin_player_metrics(player_id):
    """
    Get admin metrics for a player (admin only).
    
    Path params:
        player_id: Player ID (UUID string)
    
    Query params:
        last_n: Optional number of recent games to include (default: all)
    """
    # Check admin access
    is_admin, user_id = require_admin()
    if not is_admin:
        return jsonify({"error": "Admin access required"}), 403
    
    try:
        last_n = request.args.get("last_n", type=int)
        
        with get_db_session() as db:
            # Verify player exists
            player = db.query(Player).filter(Player.id == player_id).first()
            if not player:
                return jsonify({"error": "Player not found"}), 404
            
            # Get metrics
            metrics = get_player_admin_metrics(db, player_id, last_n)
            
            return jsonify(metrics), 200
            
    except Exception as e:
        logger.error(f"Error fetching admin metrics: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# ============================================================================
# Authentication Endpoints
# ============================================================================

@app.route("/api/auth/discord", methods=["GET"])
def discord_auth():
    """
    Initiate Discord OAuth2 flow.
    Redirects user to Discord authorization page.
    """
    try:
        authorize_url, state = get_discord_authorize_url()
        # Store state in session cookie for verification in callback
        # For simplicity, we'll pass it in the redirect and verify in callback
        # In production, you might want to use Flask sessions
        response = redirect(authorize_url)
        return response
    except ValueError as e:
        logger.error(f"Discord OAuth configuration error: {str(e)}")
        return jsonify({"error": "Discord OAuth not configured properly"}), 500
    except Exception as e:
        logger.error(f"Discord OAuth initiation error: {str(e)}")
        return jsonify({"error": f"Failed to initiate Discord OAuth: {str(e)}"}), 500


@app.route("/api/auth/discord/callback", methods=["GET"])
def discord_callback():
    """
    Handle Discord OAuth2 callback.
    Validates state, exchanges code for token, fetches user info, creates/updates user, and sets session.
    """
    code = request.args.get("code")
    state_with_signature = request.args.get("state")
    error = request.args.get("error")
    
    if error:
        logger.warning(f"Discord OAuth error: {error}")
        return jsonify({"error": f"Discord OAuth error: {error}"}), 400
    
    if not code or not state_with_signature:
        logger.warning("Missing code or state in Discord callback")
        return jsonify({"error": "Missing authorization code or state"}), 400
    
    # Verify state to prevent CSRF attacks
    is_valid, state = verify_state(state_with_signature)
    if not is_valid:
        logger.warning("Invalid state signature in Discord callback")
        return jsonify({"error": "Invalid state parameter"}), 400
    
    try:
        # Exchange code for access token
        access_token = exchange_code_for_token(code)
        
        # Fetch user info from Discord
        discord_user = get_discord_user_info(access_token)
        
        discord_id = discord_user.get("id")
        discord_username = discord_user.get("username")
        discord_avatar = discord_user.get("avatar")
        email = discord_user.get("email")
        
        if not discord_id:
            logger.error("Discord API did not return user ID")
            return jsonify({"error": "Failed to get user information from Discord"}), 500
        
        # Create or update user in database
        with get_db_session() as db:
            # Try to find user by discord_id first
            user = db.query(User).filter_by(discord_id=discord_id).first()
            
            if not user:
                # Check if user exists with same email (for migration scenarios)
                if email:
                    user = db.query(User).filter_by(email=email).first()
                
                if user:
                    # Update existing user with Discord info
                    user.discord_id = discord_id
                    user.discord_username = discord_username
                    user.discord_avatar = discord_avatar
                    if not user.email:
                        user.email = email
                else:
                    # Create new user
                    user = User(
                        discord_id=discord_id,
                        discord_username= discord_username,
                        discord_avatar=discord_avatar,
                        email=email,
                        display_name=discord_username
                    )
                    db.add(user)
            else:
                # Update existing user
                user.discord_username = discord_username
                user.discord_avatar = discord_avatar
                if email and not user.email:
                    user.email = email
                if not user.display_name:
                    user.display_name = discord_username
            
            # Update last login
            from datetime import datetime
            user.last_login_at = datetime.utcnow().isoformat()
            
            db.commit()
            db.refresh(user)
            
            # Create session token
            session_token = create_session_token(user.id)
            
            # Determine redirect URL (default to frontend root)
            if os.getenv("FLASK_ENV", "development").lower() == "development":
                frontend_url = "http://localhost:5173"
            else:
                frontend_url = os.getenv("FRONTEND_URL", "https://rec-metrics.com")
            redirect_url = f"{frontend_url}/"
            
            # Create response with redirect
            response = make_response(redirect(redirect_url))
            
            # Set HttpOnly cookie with session token
            # Use SameSite=None; Secure for cross-origin, or SameSite=Lax for same-origin
            # For localhost dev (same origin), use Lax. For cross-origin, use None with Secure
            is_cross_origin = not frontend_url.startswith("http://localhost") and not frontend_url.startswith("http://127.0.0.1")
            same_site = "None" if is_cross_origin else "Lax"
            secure = is_cross_origin or frontend_url.startswith("https://")
            
            response.set_cookie(
                "access_token",
                session_token,
                httponly=True,
                samesite=same_site,
                secure=secure,
                max_age=7 * 24 * 60 * 60  # 7 days
            )
            
            logger.info(f"User logged in: {user.id} ({discord_username})")
            return response
            
    except Exception as e:
        logger.error(f"Discord OAuth callback error: {str(e)}", exc_info=True)
        return jsonify({"error": f"Authentication failed: {str(e)}"}), 500


@app.route("/api/me", methods=["GET"])
def get_current_user():
    """
    Get current authenticated user's profile.
    Returns 401 if not logged in.
    """
    # Get session token from cookie
    session_token = request.cookies.get("access_token")
    print(session_token)
    
    if not session_token:
        print("No session token")
        return jsonify({"error": "Not authenticated"}), 401
    
    # Verify token
    is_valid, user_id = verify_session_token(session_token)
    if not is_valid or not user_id:
        print("Invalid or expired session")
        return jsonify({"error": "Invalid or expired session"}), 401
    
    try:
        with get_db_session() as db:
            user = db.query(User).filter_by(id=user_id).first()
            if not user:
                print("User not found")
                return jsonify({"error": "User not found"}), 404
            
            print(user)
            # Parse roles and permissions from JSON strings
            import json
            roles = []
            permissions = []
            
            if user.roles:
                try:
                    roles = json.loads(user.roles)
                except (json.JSONDecodeError, TypeError):
                    roles = []
            
            if user.permissions:
                try:
                    permissions = json.loads(user.permissions)
                except (json.JSONDecodeError, TypeError):
                    permissions = []
            
            # Return user profile (RBAC-ready structure)
            return jsonify({
                "id": user.id,
                "discord_id": user.discord_id,
                "display_name": user.display_name or user.discord_username,
                "username": user.discord_username,
                "email": user.email,
                "discord_avatar": user.discord_avatar,
                "platform": user.platform,
                "roles": roles,
                "permissions": permissions
            }), 200
            
    except Exception as e:
        logger.error(f"Error fetching user profile: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    """
    Logout endpoint - clears the session cookie.
    """
    response = jsonify({"message": "Logged out successfully"})
    response.set_cookie("access_token", "", expires=0, httponly=True)
    return response, 200


@app.route("/api/me/platform", methods=["PATCH"])
def update_user_platform():
    """
    Update the current user's platform selection.
    
    Body:
    {
        "platform": "PC" or "Console"
    }
    
    Returns:
    - Updated user object
    """
    session_token = request.cookies.get("access_token")
    if not session_token:
        return jsonify({"error": "Not authenticated"}), 401
    
    is_valid, user_id = verify_session_token(session_token)
    if not is_valid or not user_id:
        return jsonify({"error": "Invalid or expired session"}), 401
    
    data = request.get_json() or {}
    platform = data.get("platform")
    
    if platform not in ["PC", "Console"]:
        return jsonify({"error": "Platform must be 'PC' or 'Console'"}), 400
    
    try:
        with get_db_session() as db:
            user = db.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({"error": "User not found"}), 404
            
            user.platform = platform
            db.commit()
            db.refresh(user)
            
            # Parse roles and permissions
            import json
            roles = []
            permissions = []
            
            if user.roles:
                try:
                    roles = json.loads(user.roles)
                except (json.JSONDecodeError, TypeError):
                    roles = []
            
            if user.permissions:
                try:
                    permissions = json.loads(user.permissions)
                except (json.JSONDecodeError, TypeError):
                    permissions = []
            
            return jsonify({
                "id": user.id,
                "discord_id": user.discord_id,
                "display_name": user.display_name or user.discord_username,
                "username": user.discord_username,
                "email": user.email,
                "discord_avatar": user.discord_avatar,
                "platform": user.platform,
                "roles": roles,
                "permissions": permissions
            }), 200
            
    except Exception as e:
        logger.error(f"Error updating user platform: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# ============================================================================
# Identity & Claims Endpoints
# ============================================================================

def get_current_user_id():
    """Helper to get current user ID from session token."""
    session_token = request.cookies.get("access_token")
    if not session_token:
        return None
    is_valid, user_id = verify_session_token(session_token)
    if not is_valid or not user_id:
        return None
    return user_id


@app.route("/api/me/claims", methods=["GET"])
def get_my_claims():
    """
    Get all claims for the current user.
    
    Returns:
        JSON array of claim objects
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        with get_db_session() as db:
            claims = get_user_claims(db, user_id)
            return jsonify(claims), 200
    except Exception as e:
        logger.error(f"Error fetching claims: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/claims", methods=["POST"])
def create_name_claim():
    """
    Create a new name claim.
    
    Body:
        {
            "display_name": "PlayerName123",
            "player_id": 123  // optional, existing player identity ID
        }
    
    Returns:
        Created claim object
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data or "display_name" not in data:
            return jsonify({"error": "Missing display_name"}), 400
        
        display_name = data.get("display_name", "").strip()
        player_id = data.get("player_id")  # Optional
        platform = data.get("platform")  # Optional, will use user's platform if not provided
        
        with get_db_session() as db:
            result = create_claim(db, user_id, display_name, player_id, platform)
            
            if "error" in result:
                return jsonify(result), 400
            
            return jsonify(result), 201
    except Exception as e:
        logger.error(f"Error creating claim: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/claims/<int:claim_id>/request-verification", methods=["POST"])
def request_verification(claim_id):
    """
    Request verification for a claim (user action).
    This creates a verification attempt record.
    
    Returns:
        Success message
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        with get_db_session() as db:
            from models import NameClaim, ClaimVerificationAttempt
            
            claim = db.query(NameClaim).filter(
                NameClaim.id == claim_id,
                NameClaim.user_id == user_id
            ).first()
            
            if not claim:
                return jsonify({"error": "Claim not found"}), 404
            
            # Create verification attempt
            attempt = ClaimVerificationAttempt(
                claim_id=claim.id,
                status='pending',
                reviewed_at=None
            )
            db.add(attempt)
            db.flush()
            
            return jsonify({"success": True, "message": "Verification requested"}), 200
    except Exception as e:
        logger.error(f"Error requesting verification: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/mod/claims/<int:claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    """
    Approve a claim (moderator/admin only).
    
    Body:
        {
            "notes": "Optional notes"
        }
    
    Returns:
        Success message with updated games count
    """
    is_admin, reviewer_id = require_admin()
    if not is_admin:
        return jsonify({"error": "Admin access required"}), 403
    
    try:
        data = request.get_json() or {}
        notes = data.get("notes")
        
        with get_db_session() as db:
            result = verify_claim(db, claim_id, reviewer_id, approve=True, notes=notes)
            
            if "error" in result:
                return jsonify(result), 400
            
            return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error approving claim: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/mod/claims/<int:claim_id>/reject", methods=["POST"])
def reject_claim(claim_id):
    """
    Reject a claim (moderator/admin only).
    
    Body:
        {
            "notes": "Optional rejection reason"
        }
    
    Returns:
        Success message
    """
    is_admin, reviewer_id = require_admin()
    if not is_admin:
        return jsonify({"error": "Admin access required"}), 403
    
    try:
        data = request.get_json() or {}
        notes = data.get("notes")
        
        with get_db_session() as db:
            result = verify_claim(db, claim_id, reviewer_id, approve=False, notes=notes)
            
            if "error" in result:
                return jsonify(result), 400
            
            return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error rejecting claim: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/me/unresolved-games", methods=["GET"])
def get_my_unresolved_games():
    """
    Get unresolved games for the current user.
    Shows detected names that might belong to the user.
    
    Returns:
        JSON array of unresolved game player records
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        with get_db_session() as db:
            unresolved = get_unresolved_games(db, user_id)
            return jsonify(unresolved), 200
    except Exception as e:
        logger.error(f"Error fetching unresolved games: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/games/<game_id>/players/<game_player_id>/confirm", methods=["POST"])
def confirm_game_player_route(game_id, game_player_id):
    """
    Confirm or reject a game player as belonging to the current user.
    
    Body:
        {
            "action": "me" | "not_me",
            "claim_id": 123  // optional, required if action is "me" and no verified claim exists
        }
    
    Returns:
        Success message
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data or "action" not in data:
            return jsonify({"error": "Missing 'action' field"}), 400
        
        action = data.get("action")
        if action not in ["me", "not_me"]:
            return jsonify({"error": "Invalid action. Must be 'me' or 'not_me'"}), 400
        
        claim_id = data.get("claim_id")
        
        with get_db_session() as db:
            result = confirm_game_player(db, game_id, game_player_id, user_id, action, claim_id)
            
            if "error" in result:
                return jsonify(result), 400
            
            return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error confirming game player: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# ============================================================================
# Build System Endpoints
# ============================================================================

@app.route("/api/builds/ingest", methods=["POST"])
def ingest_build():
    """
    Ingest a build sheet screenshot.
    
    Accepts:
    - multipart/form-data with 'image' file field
    - optional 'target_user_id' form field (admin only)
    - optional 'is_public' form field (true/false, default false)
    
    Returns:
    - JSON with build object including attributes grouped by category
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    # Check for required file
    if "image" not in request.files:
        return jsonify({"error": "Missing 'image' file field"}), 400
    
    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    
    # Get optional target_user_id (for admins)
    target_user_id = request.form.get("target_user_id", None)
    # Build visibility (private by default)
    is_public_raw = (request.form.get("is_public", "false") or "false").strip().lower()
    is_public = is_public_raw in ["1", "true", "yes", "on"]
    
    # Validate OpenAI API key
    from openai_client import OPENAI_API_KEY
    if not OPENAI_API_KEY:
        return jsonify({"error": "OPENAI_API_KEY not configured"}), 500
    
    try:
        with get_db_session() as db:
            # Check if admin and target_user_id provided
            if target_user_id:
                is_admin, _ = require_admin()
                if not is_admin:
                    return jsonify({"error": "Admin access required to create builds for other users"}), 403
            
            # Ingest build
            result = ingest_build_sheet(
                db=db,
                file=file,
                upload_dir=UPLOAD_DIR,
                owner_user_id=user_id,
                target_user_id=target_user_id,
                is_public=is_public
            )
            
            return jsonify(result), 201
            
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error ingesting build: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/builds/create", methods=["POST"])
def create_build():
    """
    Create a build from structured planner data (JSON, no screenshot).

    Body:
        {
            display_name, position, archetype, height, wingspan,
            weight_lbs, overall_current, overall_max, is_public,
            attributes: [{ category, name, current, max, order }]
        }

    Returns:
        JSON build object (201).
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    if not data.get("attributes"):
        return jsonify({"error": "Build must include attributes"}), 400

    try:
        with get_db_session() as db:
            result = create_planned_build(db=db, owner_user_id=user_id, data=data)
            return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error creating build: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/users/find-by-username", methods=["GET"])
def find_user_by_username():
    """
    Find a user by username (from name claims).
    Admin only endpoint.
    
    Query Parameters:
    - username: Username to search for (required, case-insensitive)
    
    Returns:
    - JSON with user_id if found, or error if not found
    """
    # Check admin access
    is_admin, user_id = require_admin()
    if not is_admin:
        return jsonify({"error": "Admin access required"}), 403
    
    username = request.args.get("username", "").strip()
    if not username:
        return jsonify({"error": "Missing 'username' query parameter"}), 400
    
    try:
        with get_db_session() as db:
            # Normalize username for search
            normalized_username = username.lower().strip()
            
            # Search for verified name claims matching this username
            from models import NameClaim
            claim = db.query(NameClaim).filter(
                NameClaim.normalized_name == normalized_username,
                NameClaim.status == 'verified'
            ).first()
            
            if claim:
                return jsonify({
                    "user_id": claim.user_id,
                    "display_name": claim.display_name,
                    "normalized_name": claim.normalized_name
                }), 200
            
            # If no verified claim found, return error
            return jsonify({
                "error": f"No verified claim found for username '{username}'",
                "user_id": None
            }), 404
            
    except Exception as e:
        logger.error(f"Error finding user by username: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/builds", methods=["GET"])
def list_builds():
    """
    List builds for current user (or specified user if admin).
    
    Query params:
    - user_id: Optional user ID (admin only)
    
    Returns:
    - Array of build objects
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        # Get target user_id (default to current user)
        target_user_id = request.args.get("user_id", user_id)
        
        # If requesting another user's builds, check admin
        if target_user_id != user_id:
            is_admin, _ = require_admin()
            if not is_admin:
                return jsonify({"error": "Admin access required to view other users' builds"}), 403
        
        with get_db_session() as db:
            builds = get_user_builds(db, target_user_id, user_id)
            return jsonify(builds), 200
            
    except Exception as e:
        logger.error(f"Error listing builds: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/builds/public", methods=["GET"])
def list_public_builds():
    """
    List publicly visible builds from users with verified claims.
    Includes top attributes and usage averages.

    Query params:
    - page: Optional page number (default 1)
    - per_page: Optional page size (default 24, max 100)
    """
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(1, min(100, int(request.args.get("per_page", 24))))
    except ValueError:
        return jsonify({"error": "Invalid pagination params"}), 400

    try:
        with get_db_session() as db:
            payload = get_public_builds_feed(db, page=page, per_page=per_page, requesting_user_id=get_current_user_id())
            return jsonify(payload), 200
    except Exception as e:
        logger.error(f"Error listing public builds: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/builds/templates", methods=["GET"])
def list_template_builds():
    """
    List admin-flagged template builds for the template gallery.

    Public — the gallery is open to everyone (only saving a build needs login).
    Templates are admin-curated, so exposing them anonymously is intended.

    Returns:
    - { "builds": [...] }
    """
    try:
        with get_db_session() as db:
            return jsonify({"builds": get_template_builds(db)}), 200
    except Exception as e:
        logger.error(f"Error listing template builds: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/players/<username>/builds", methods=["GET"])
def get_builds_by_username(username):
    """
    Get builds for a player by username (public endpoint, no auth required).
    
    Path Parameters:
    - username: Player username (case-insensitive)
    
    Returns:
    - Array of build objects for that player
    """
    try:
        with get_db_session() as db:
            from models import NameClaim
            # Find verified claim for this username
            normalized_username = username.lower().strip()
            claim = db.query(NameClaim).filter(
                NameClaim.normalized_name == normalized_username,
                NameClaim.status == 'verified'
            ).first()
            
            if not claim:
                # No verified claim found, return empty array
                return jsonify([]), 200
            
            # Get builds for the user who owns this claim
            builds = get_user_builds(db, claim.user_id, None)  # No requesting_user_id = public access
            return jsonify(builds), 200
            
    except Exception as e:
        logger.error(f"Error getting builds by username: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/builds/<int:build_id>", methods=["GET"])
def get_build(build_id):
    """
    Get a build by ID. Owner or admin can access, or public access if build is from a verified claim.
    
    Returns:
    - Build object with attributes grouped by category
    """
    user_id = get_current_user_id()  # May be None for public access
    
    try:
        with get_db_session() as db:
            # get_build_by_id handles both authenticated and public access
            build = get_build_by_id(db, build_id, user_id)
            
            if not build:
                return jsonify({"error": "Build not found or access denied"}), 404
            
            return jsonify(build), 200
            
    except Exception as e:
        logger.error(f"Error getting build: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/builds/<int:build_id>/usage", methods=["GET"])
def get_build_usage(build_id):
    """
    Get in-game usage stats and per-game stat breakdown for a build.
    Public access follows same policy as /api/builds/<id>.
    """
    user_id = get_current_user_id()  # may be None for public access

    try:
        with get_db_session() as db:
            usage = get_build_usage_breakdown(db, build_id, user_id)
            if not usage:
                return jsonify({"error": "Build not found or access denied"}), 404
            return jsonify(usage), 200
    except Exception as e:
        logger.error(f"Error getting build usage: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/builds/<int:build_id>/votes", methods=["GET"])
def get_build_votes_route(build_id):
    """
    Get vote counts and current user's vote (if authenticated) for a build.
    """
    user_id = get_current_user_id()  # may be None for public access
    try:
        with get_db_session() as db:
            payload = get_build_votes(db, build_id, user_id)
            if not payload:
                return jsonify({"error": "Build not found or access denied"}), 404
            return jsonify(payload), 200
    except Exception as e:
        logger.error(f"Error getting build votes: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/builds/<int:build_id>/vote", methods=["POST"])
def vote_build_route(build_id):
    """
    Set or clear vote for the current user on a build.
    Body: { "vote": "up" | "down" | null }
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    vote = data.get("vote")
    if vote not in ["up", "down", None]:
        return jsonify({"error": "Invalid vote. Must be 'up', 'down', or null"}), 400

    try:
        with get_db_session() as db:
            payload = set_build_vote(db, build_id, user_id, vote)
            if not payload:
                return jsonify({"error": "Build not found or access denied"}), 404
            return jsonify(payload), 200
    except Exception as e:
        logger.error(f"Error voting on build: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/builds/<int:build_id>", methods=["PATCH"])
def patch_build(build_id):
    """
    Update a build. Only owner or admin can update.
    Currently allows updating display_name, position, archetype, and is_public.
    `is_template` (feature it in the template gallery) is admin-only.

    Body:
    {
        "display_name": "New Name",
        "position": "PG",
        "archetype": "New Archetype",
        "is_public": true,
        "is_template": true
    }
    
    Returns:
    - Updated build object
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        data = request.get_json() or {}
        
        with get_db_session() as db:
            build = update_build(db, build_id, user_id, data)
            if not build:
                return jsonify({"error": "Build not found or access denied"}), 404
            
            return jsonify(build), 200
            
    except Exception as e:
        logger.error(f"Error updating build: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/builds/<int:build_id>", methods=["DELETE"])
def delete_build_endpoint(build_id):
    """
    Delete a build. Only owner or admin can delete.
    Cascades to attributes automatically.
    
    Returns:
    - Success message
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        with get_db_session() as db:
            success = delete_build(db, build_id, user_id)
            if not success:
                return jsonify({"error": "Build not found or access denied"}), 404
            
            return jsonify({"success": True, "message": "Build deleted"}), 200
            
    except Exception as e:
        logger.error(f"Error deleting build: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/builds/<int:build_id>/screenshot", methods=["GET"])
def get_build_screenshot(build_id):
    """
    Serve the screenshot image for a build.
    
    Returns:
    - Image file if found, 404 otherwise
    """
    user_id = get_current_user_id()  # may be None for public access
    try:
        with get_db_session() as db:
            build = get_build_by_id(db, build_id, user_id)
            if not build:
                return jsonify({"error": "Build not found or access denied"}), 404

            from models import Build
            build_row = db.query(Build).filter_by(id=build_id).first()
            if not build_row:
                return jsonify({"error": "Build not found"}), 404

            screenshot_path = build_row.source_image_path
            if not screenshot_path or not os.path.exists(screenshot_path):
                return jsonify({"error": "Screenshot not found"}), 404
            
            # Determine content type based on file extension
            file_ext = os.path.splitext(screenshot_path)[1].lower()
            mimetype_map = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }
            mimetype = mimetype_map.get(file_ext, 'image/png')
            
            return send_file(screenshot_path, mimetype=mimetype)
            
    except Exception as e:
        logger.error(f"Error serving build screenshot: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route("/api/games/<game_id>/players/<game_player_row_id>/build", methods=["PATCH"])
def assign_build_to_player(game_id, game_player_row_id):
    """
    Assign a build to a game player row.
    
    Body:
    {
        "build_id": 123  // or null to clear
    }
    
    Returns:
    - Updated game player row
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        data = request.get_json() or {}
        build_id = data.get("build_id")
        
        # Convert to int if not None
        if build_id is not None:
            try:
                build_id = int(build_id)
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid build_id"}), 400
        
        with get_db_session() as db:
            result = assign_build_to_game_player(
                db=db,
                game_id=game_id,
                game_player_row_id=game_player_row_id,
                build_id=build_id,
                requesting_user_id=user_id
            )
            
            if not result:
                return jsonify({"error": "Game player row not found or access denied"}), 404
            
            return jsonify(result), 200
            
    except Exception as e:
        logger.error(f"Error assigning build: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    # Initialize database
    init_db()
    
    # Run Flask app
    # Bind to 127.0.0.1 (localhost only) for security
    # IIS reverse proxy will forward requests from external interface
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "127.0.0.1")
    debug = ENV == "development"
    # NEVER hardcode debug=True here: this entrypoint serves production behind
    # IIS, and Flask's debugger is a remote-code-execution vector plus it leaks
    # stack traces. Honor the ENV-derived flag (dev only). For real production
    # load, prefer a WSGI server (waitress) over app.run — see backend README.
    app.run(host=host, port=port, debug=debug)

