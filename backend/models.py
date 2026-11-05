"""
SQLAlchemy models for NBA2K Rec box score ingestion.
All models use UUID strings as primary keys for better distribution.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, ForeignKey, Enum, Text, Numeric, UniqueConstraint
from sqlalchemy.orm import relationship
from db import Base


def generate_uuid():
    """Generate a UUID string for primary keys."""
    return str(uuid.uuid4())


# NBA 2K title a game belongs to. Everything ingested before the 2K27 cutover is
# 2K26; new uploads are stamped with CURRENT_GAME_VERSION.
LEGACY_GAME_VERSION = "2K26"
CURRENT_GAME_VERSION = "2K27"
GAME_VERSIONS = (LEGACY_GAME_VERSION, CURRENT_GAME_VERSION)


class Game(Base):
    """
    Main game record storing metadata and final scores.
    """
    __tablename__ = "games"

    id = Column(String, primary_key=True, default=generate_uuid)
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    season_label = Column(String, nullable=True)
    mode_label = Column(String, nullable=True)
    away_team_name = Column(String, nullable=True)
    home_team_name = Column(String, nullable=True)
    away_score = Column(Integer, nullable=False)
    home_score = Column(Integer, nullable=False)
    away_q1 = Column(Integer, nullable=True)
    away_q2 = Column(Integer, nullable=True)
    away_q3 = Column(Integer, nullable=True)
    away_q4 = Column(Integer, nullable=True)
    home_q1 = Column(Integer, nullable=True)
    home_q2 = Column(Integer, nullable=True)
    home_q3 = Column(Integer, nullable=True)
    home_q4 = Column(Integer, nullable=True)
    source_image_path = Column(String, nullable=False)
    source_image_sha256 = Column(String, unique=True, nullable=False, index=True)
    platform = Column(String, nullable=True)  # 'PC' or 'Console' - platform the game was played on
    game_version = Column(String, nullable=True, default=CURRENT_GAME_VERSION, index=True)  # '2K26' or '2K27' - which NBA 2K title this game is from
    uploaded_by_user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)  # User who uploaded the screenshot

    # Relationships
    game_players = relationship("GamePlayer", back_populates="game", cascade="all, delete-orphan")
    player_stats = relationship("PlayerGameStats", back_populates="game", cascade="all, delete-orphan")
    team_totals = relationship("TeamTotal", back_populates="game", cascade="all, delete-orphan")
    matchups = relationship("Matchup", back_populates="game", cascade="all, delete-orphan")
    uploaded_by_user = relationship("User", foreign_keys=[uploaded_by_user_id])


class Player(Base):
    """
    Player master table storing unique gamertags.
    """
    __tablename__ = "players"

    id = Column(String, primary_key=True, default=generate_uuid)
    gamertag = Column(String, unique=True, nullable=False, index=True)

    # Relationships
    game_players = relationship("GamePlayer", back_populates="player")
    player_stats = relationship("PlayerGameStats", back_populates="player")
    defender_matchups = relationship("Matchup", foreign_keys="Matchup.defender_player_id", back_populates="defender_player")
    offender_matchups = relationship("Matchup", foreign_keys="Matchup.offender_player_id", back_populates="offender_player")


class GamePlayer(Base):
    """
    Junction table linking games to players with team side and position.
    Extended with identity resolution fields.
    """
    __tablename__ = "game_players"

    id = Column(String, primary_key=True, default=generate_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False)
    player_id = Column(String, ForeignKey("players.id"), nullable=False)  # Original player reference
    team_side = Column(Enum("AWAY", "HOME", name="team_side"), nullable=False)
    position = Column(Enum("PG", "SG", "SF", "PF", "C", name="player_position"), nullable=False)
    row_index = Column(Integer, nullable=False)  # 0-4 within team
    platform = Column(String, nullable=True)  # 'PC' or 'Console' - platform this game was played on (denormalized from Game)

    # Identity resolution fields (added by migration)
    detected_raw_name = Column(String, nullable=True)
    detected_norm_name = Column(String, nullable=True, index=True)
    player_id_identity = Column(Integer, ForeignKey("players_identity.id"), nullable=True, index=True)
    claim_id = Column(Integer, ForeignKey("name_claims.id"), nullable=True, index=True)
    match_confidence = Column(Integer, nullable=True)  # 0-100
    match_method = Column(String, nullable=True)  # exact, variant, fuzzy, manual, none
    needs_review = Column(Integer, default=0)  # SQLite boolean: 0 = False, 1 = True
    
    # Build assignment
    build_id = Column(Integer, ForeignKey("builds.id", ondelete="SET NULL"), nullable=True, index=True)

    # Relationships
    game = relationship("Game", back_populates="game_players")
    player = relationship("Player", back_populates="game_players")
    player_identity = relationship("PlayerIdentity", foreign_keys=[player_id_identity])
    claim = relationship("NameClaim", foreign_keys=[claim_id])
    build = relationship("Build", foreign_keys=[build_id])


class PlayerGameStats(Base):
    """
    Individual player statistics for a specific game.
    """
    __tablename__ = "player_game_stats"

    id = Column(String, primary_key=True, default=generate_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False)
    player_id = Column(String, ForeignKey("players.id"), nullable=False)
    grade = Column(String, nullable=True)
    pts = Column(Integer, default=0)
    reb = Column(Integer, default=0)
    ast = Column(Integer, default=0)
    stl = Column(Integer, default=0)
    blk = Column(Integer, default=0)
    fouls = Column(Integer, default=0)
    tov = Column(Integer, default=0)
    fgm = Column(Integer, default=0)  # Field goals made
    fga = Column(Integer, default=0)  # Field goals attempted
    tpm = Column(Integer, default=0)  # Three pointers made
    tpa = Column(Integer, default=0)  # Three pointers attempted
    ftm = Column(Integer, default=0)  # Free throws made
    fta = Column(Integer, default=0)  # Free throws attempted

    # Relationships
    game = relationship("Game", back_populates="player_stats")
    player = relationship("Player", back_populates="player_stats")


class TeamTotal(Base):
    """
    Team-level totals for a game.
    """
    __tablename__ = "team_totals"

    id = Column(String, primary_key=True, default=generate_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False)
    team_side = Column(Enum("AWAY", "HOME", name="team_side"), nullable=False)
    grade = Column(String, nullable=True)
    pts = Column(Integer, default=0)
    reb = Column(Integer, default=0)
    ast = Column(Integer, default=0)
    stl = Column(Integer, default=0)
    blk = Column(Integer, default=0)
    fouls = Column(Integer, default=0)
    tov = Column(Integer, default=0)
    fgm = Column(Integer, default=0)
    fga = Column(Integer, default=0)
    tpm = Column(Integer, default=0)
    tpa = Column(Integer, default=0)
    ftm = Column(Integer, default=0)
    fta = Column(Integer, default=0)

    # Relationships
    game = relationship("Game", back_populates="team_totals")


class Matchup(Base):
    """
    Positional matchups between players.
    For MVP, all matchups are positional (PG guards PG, etc.).
    """
    __tablename__ = "matchups"

    id = Column(String, primary_key=True, default=generate_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False)
    defender_player_id = Column(String, ForeignKey("players.id"), nullable=False)
    offender_player_id = Column(String, ForeignKey("players.id"), nullable=False)
    defender_position = Column(Enum("PG", "SG", "SF", "PF", "C", name="player_position"), nullable=False)
    offender_position = Column(Enum("PG", "SG", "SF", "PF", "C", name="player_position"), nullable=False)
    matchup_type = Column(String, default="POSITIONAL")

    # Relationships
    game = relationship("Game", back_populates="matchups")
    defender_player = relationship("Player", foreign_keys=[defender_player_id], back_populates="defender_matchups")
    offender_player = relationship("Player", foreign_keys=[offender_player_id], back_populates="offender_matchups")


class User(Base):
    """
    User account table for authentication and user profiles.
    Supports Discord OAuth2 authentication.
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    discord_id = Column(String, unique=True, nullable=True, index=True)
    discord_username = Column(String, nullable=True)
    discord_avatar = Column(String, nullable=True)
    email = Column(String, nullable=True, index=True)
    display_name = Column(String, nullable=True)  # Can be set separately from Discord username
    roles = Column(Text, nullable=True)  # JSON array of role names, e.g. '["admin", "moderator"]'
    permissions = Column(Text, nullable=True)  # JSON array of permission names, e.g. '["upload", "delete"]'
    platform = Column(String, nullable=True)  # 'PC' or 'Console' - user's selected platform
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    last_login_at = Column(Text, nullable=True)
    
    # Relationships for identity system
    name_claims = relationship("NameClaim", foreign_keys="NameClaim.user_id", back_populates="user", cascade="all, delete-orphan")


# ============================================================================
# Identity System Models
# ============================================================================

class PlayerIdentity(Base):
    """
    Global identity bucket for players.
    Tracks canonical name and normalized form for identity resolution.
    """
    __tablename__ = "players_identity"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(String, nullable=False)
    canonical_norm = Column(String, nullable=False, index=True)
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    
    # Relationships
    name_variants = relationship("PlayerNameVariant", back_populates="player", cascade="all, delete-orphan")
    name_claims = relationship("NameClaim", back_populates="player", cascade="all, delete-orphan")


class PlayerNameVariant(Base):
    """
    Stores all name variants seen for a player identity.
    Tracks raw names, normalized names, and frequency.
    """
    __tablename__ = "player_name_variants"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players_identity.id", ondelete="CASCADE"), nullable=False)
    raw_name = Column(String, nullable=False)
    norm_name = Column(String, nullable=False, index=True)
    first_seen_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    last_seen_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    seen_count = Column(Integer, default=1)
    
    # Relationships
    player = relationship("PlayerIdentity", back_populates="name_variants")
    
    # Unique constraint on (player_id, norm_name)
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class NameClaim(Base):
    """
    User claims to a player identity.
    Tracks verification status and links users to player identities.
    """
    __tablename__ = "name_claims"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players_identity.id", ondelete="CASCADE"), nullable=False)
    display_name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False, index=True)
    platform = Column(String, nullable=True)  # 'PC' or 'Console' - platform for this claim
    status = Column(String, nullable=False, default="unverified")  # unverified, verified, revoked, rejected
    verified_at = Column(Text, nullable=True)
    verified_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="name_claims")
    verified_by = relationship("User", foreign_keys=[verified_by_user_id])  # User who verified this claim
    player = relationship("PlayerIdentity", back_populates="name_claims")
    verification_attempts = relationship("ClaimVerificationAttempt", back_populates="claim", cascade="all, delete-orphan")


class ClaimVerificationAttempt(Base):
    """
    Tracks verification attempts for name claims.
    Stores uploads, review status, and notes.
    """
    __tablename__ = "claim_verification_attempts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("name_claims.id", ondelete="CASCADE"), nullable=False)
    upload_id = Column(String, nullable=True)  # References game or upload (flexible)
    status = Column(String, nullable=False, default="pending")  # pending, approved, rejected
    reviewed_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    
    # Relationships
    claim = relationship("NameClaim", back_populates="verification_attempts")
    reviewer = relationship("User", foreign_keys=[reviewed_by_user_id])  # User who reviewed this attempt


# ============================================================================
# Build System Models
# ============================================================================

class Build(Base):
    """
    Build records extracted from NBA 2K "Attribute Upgrades - Simple View" screenshots.
    """
    __tablename__ = "builds"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = Column(String, nullable=False)
    build_position = Column(String, nullable=True)
    archetype = Column(String, nullable=True)
    height = Column(String, nullable=True)  # Store as displayed (e.g., "6'8\"")
    weight_lbs = Column(Integer, nullable=True)
    wingspan = Column(String, nullable=True)  # Store as displayed (e.g., "6'9\"")
    overall_current = Column(Integer, nullable=True)
    overall_max = Column(Integer, nullable=True)
    is_public = Column(Integer, default=0)  # SQLite boolean: 0 = private (default), 1 = public
    is_template = Column(Integer, default=0)  # 1 = featured in the template gallery (admin-set)
    source_image_path = Column(String, nullable=True)  # Path to uploaded build sheet screenshot
    cap_breakers = Column(Text, nullable=True)  # JSON {attributeKey: tierCount} for planner builds
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    updated_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_user_id])
    attributes = relationship("BuildAttribute", back_populates="build", cascade="all, delete-orphan")
    
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class BuildAttribute(Base):
    """
    Normalized attribute rows for builds.
    Each build has multiple attributes organized by category.
    """
    __tablename__ = "build_attributes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    build_id = Column(Integer, ForeignKey("builds.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String, nullable=False)  # e.g., "Finishing", "Shooting", "Playmaking", "Defense", "Physicals"
    attribute_name = Column(String, nullable=False)  # e.g., "Driving Dunk"
    value_current = Column(Integer, nullable=False)  # Bottom number
    value_max = Column(Integer, nullable=True)  # Top "Max" number
    display_order = Column(Integer, nullable=True)  # Order on screen to preserve UI
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    
    # Relationships
    build = relationship("Build", back_populates="attributes")
    
    # Unique constraint to avoid duplicates per build
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class BuildVote(Base):
    """
    Per-user vote on a build.
    vote_value: 1 for upvote, -1 for downvote.
    """
    __tablename__ = "build_votes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    build_id = Column(Integer, ForeignKey("builds.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    vote_value = Column(Integer, nullable=False)  # 1 or -1
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    updated_at = Column(Text, default=lambda: datetime.utcnow().isoformat())

    __table_args__ = (
        UniqueConstraint("build_id", "user_id", name="uq_build_votes_build_user"),
        {"sqlite_autoincrement": True},
    )


class PlayerAnalysisCache(Base):
    """
    Cache table for OpenAI-generated player analysis results.
    """
    __tablename__ = "player_analysis_cache"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, index=True)
    last_n = Column(Integer, nullable=True)
    payload_hash = Column(String, nullable=False, index=True)
    response_json = Column(Text, nullable=False)
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class PlayerGameAdminMetrics(Base):
    """
    Admin-only defensive disruption metrics computed per player per game.
    Stores estimates for turnovers forced, on-ball/off-ball pressure, and disruption scores.
    """
    __tablename__ = "player_game_admin_metrics"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    game_id = Column(String, ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(String, ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    team_side = Column(Enum("AWAY", "HOME", name="team_side"), nullable=False)
    possessions_est = Column(Numeric, nullable=False)
    opp_tov = Column(Integer, nullable=False)
    team_stl = Column(Integer, nullable=False)
    unattributed_tov = Column(Numeric, nullable=False)
    pressure_weight = Column(Numeric, nullable=False)
    pressure_share = Column(Numeric, nullable=False)
    tov_forced_est = Column(Numeric, nullable=False)
    onball_ratio_est = Column(Numeric, nullable=False)
    onball_pressure_est = Column(Numeric, nullable=False)
    offball_disruption_est = Column(Numeric, nullable=False)
    disruption_score = Column(Numeric, nullable=False)
    disruption_score_100 = Column(Numeric, nullable=False)
    used_build = Column(Integer, default=0)  # SQLite boolean: 0 = False, 1 = True
    # New matchup-based defensive metrics (nullable for backward compatibility)
    matchup_stop = Column(Numeric, nullable=True)
    matchup_stop_per100 = Column(Numeric, nullable=True)
    stocks_per100 = Column(Numeric, nullable=True)
    def_disruption_per100 = Column(Numeric, nullable=True)
    used_matchup_baseline = Column(Integer, nullable=True)  # SQLite boolean: 0 = False, 1 = True
    used_matchup_primary = Column(Integer, nullable=True)  # SQLite boolean: 0 = False, 1 = True
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    updated_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    
    # Relationships
    game = relationship("Game")
    player = relationship("Player")
    
    # Unique constraint
    __table_args__ = (
        {"sqlite_autoincrement": False},
    )


class Event(Base):
    """
    First-party product/marketing event log (pageviews + conversions).

    Written by POST /api/events from the frontend beacon. Intentionally holds no
    raw PII: params/attribution are app-controlled JSON, user_id is set only when
    the visitor is authenticated.
    """
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, index=True)
    path = Column(String, nullable=True)
    params = Column(Text, nullable=True)        # JSON string
    attribution = Column(Text, nullable=True)   # JSON string (utm_*, gclid, ...)
    referrer = Column(String, nullable=True)
    user_id = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat(), index=True)


class DiscordUploadChannel(Base):
    """
    Tracks Discord guild/channel pairs where the bot accepts screenshot uploads.
    One channel per guild (upserted by guild_id). Populated via slash command.
    """
    __tablename__ = "discord_upload_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(String, nullable=False, unique=True, index=True)
    channel_id = Column(String, nullable=False, index=True)
    registered_by_discord_id = Column(String, nullable=True)
    created_at = Column(Text, default=lambda: datetime.utcnow().isoformat())
    updated_at = Column(Text, default=lambda: datetime.utcnow().isoformat())

