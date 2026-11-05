"""
MyNBA league models — rosters, trades, and the transaction log.

Deliberately separate from the Rec box-score domain in models.py. The `players`
table there holds Rec gamertags matched from screenshots; `mynba_players` holds
NBA players on MyNBA franchise rosters. Same word, different things — keeping
them apart is what stops a fuzzy gamertag match from ever touching a roster.

Every table is prefixed `mynba_`.
"""
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Boolean, Date, DateTime, Text, ForeignKey,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from db import Base
from models import generate_uuid


# ---------------------------------------------------------------------------
# Trade lifecycle
# ---------------------------------------------------------------------------
# Rosters do not move until EXECUTED. Approval opens a protest window instead of
# applying the swap, so a successful league protest never has to un-trade anyone.
#
#   PENDING_GM ──accept──> PENDING_COMMISSIONER ──approve──> APPROVED_WINDOW
#                                                                 │
#                              (window elapses, or commish skips) │
#                                                                 ▼
#                                                             EXECUTED
#   APPROVED_WINDOW ──protest──> PROTESTED ──vote upholds──> EXECUTED
#                                          ──vote overturns──> OVERTURNED
#
TRADE_PENDING_GM = "PENDING_GM"
TRADE_PENDING_COMMISSIONER = "PENDING_COMMISSIONER"
TRADE_APPROVED_WINDOW = "APPROVED_WINDOW"
TRADE_PROTESTED = "PROTESTED"
TRADE_EXECUTED = "EXECUTED"
TRADE_DECLINED = "DECLINED"
TRADE_VETOED = "VETOED"
TRADE_CANCELLED = "CANCELLED"
TRADE_EXPIRED = "EXPIRED"
TRADE_VOIDED = "VOIDED"          # a player in the package moved before execution
TRADE_OVERTURNED = "OVERTURNED"  # league vote killed it during the protest window

TRADE_OPEN_STATUSES = (
    TRADE_PENDING_GM,
    TRADE_PENDING_COMMISSIONER,
    TRADE_APPROVED_WINDOW,
    TRADE_PROTESTED,
)
TRADE_TERMINAL_STATUSES = (
    TRADE_EXECUTED, TRADE_DECLINED, TRADE_VETOED, TRADE_CANCELLED,
    TRADE_EXPIRED, TRADE_VOIDED, TRADE_OVERTURNED,
)

# mynba_transactions.kind
TXN_TRADE = "TRADE"
TXN_SIGN = "SIGN"
TXN_RELEASE = "RELEASE"
TXN_IMPORT = "IMPORT"
TXN_ADMIN_MOVE = "ADMIN_MOVE"


def _utcnow():
    return datetime.utcnow()


class MynbaLeague(Base):
    """One league per Discord guild. Holds the rules the bot enforces."""

    __tablename__ = "mynba_leagues"

    id = Column(String, primary_key=True, default=generate_uuid)
    guild_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False, default="MyNBA League")
    game_version = Column(String, nullable=True, default="2K27")

    # Discord wiring
    commissioner_role_id = Column(String, nullable=True)
    gm_role_id = Column(String, nullable=True)
    trade_channel_id = Column(String, nullable=True)
    approvals_channel_id = Column(String, nullable=True)

    # Roster rules — 8-man rosters, blocking is opt-in per the admin meeting.
    roster_size = Column(Integer, nullable=False, default=8)
    enforce_roster_size = Column(Boolean, nullable=False, default=False)
    # Players a GM can mark untradeable.
    untouchables_per_team = Column(Integer, nullable=False, default=2)
    # Most teams allowed in one trade (MyNBA's own limit is 3).
    max_trade_teams = Column(Integer, nullable=False, default=3)

    # Salary cap is scaffolded but dormant until the league decides it runs one.
    salary_cap = Column(Integer, nullable=True)
    enforce_salary_cap = Column(Boolean, nullable=False, default=False)

    # Trading window — commissioner toggle, not a fixed date.
    trades_locked = Column(Boolean, nullable=False, default=False)
    trades_locked_reason = Column(String, nullable=True)

    # Approved trades sit here before executing, so the league can protest.
    protest_window_hours = Column(Integer, nullable=False, default=24)
    proposal_ttl_hours = Column(Integer, nullable=False, default=72)

    # The weekly lock. Sims run on `sim_weekday` (Mon=0 … Sat=5). GMs can edit
    # gameplans until `gameplan_lock_minute` (minutes after midnight, Eastern)
    # on the day `gameplan_lock_days` before the sim (0 = sim day), and stay
    # locked through the end of sim day. Commissioners can always edit.
    # See mynba_schedule.py.
    sim_weekday = Column(Integer, nullable=False, default=5)
    sim_hour = Column(Integer, nullable=False, default=20)   # Eastern, 24h; shown on the Rules tab
    gameplan_lock_days = Column(Integer, nullable=False, default=2)
    gameplan_lock_minute = Column(Integer, nullable=False, default=23 * 60 + 59)
    # Trades, signings and releases follow the same lock.
    lock_roster_moves = Column(Boolean, nullable=False, default=True)
    # NULL follows the schedule; True / False forces locked / open (skipped weeks, playoffs).
    gameplan_lock_override = Column(Boolean, nullable=True)
    gameplan_channel_id = Column(String, nullable=True)
    # Rotation minimums: slot 6 and slots 7+.
    sixth_man_min_minutes = Column(Integer, nullable=False, default=20)
    bench_min_minutes = Column(Integer, nullable=False, default=10)

    # The written rulebook: JSON [{"id", "title", "body"}]. NULL means the
    # default text in mynba_rules.py. Bodies may use {tokens} filled from the
    # settings above, so the text never disagrees with what's enforced.
    rulebook = Column(Text, nullable=True)
    rulebook_version = Column(Integer, nullable=False, default=0)
    rulebook_updated_at = Column(DateTime, nullable=True)
    rulebook_updated_by = Column(String, nullable=True)

    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    teams = relationship("MynbaTeam", back_populates="league", cascade="all, delete-orphan")
    commissioners = relationship("MynbaCommissioner", back_populates="league", cascade="all, delete-orphan")


class MynbaCommissioner(Base):
    """A league can have two or more commissioners; one cannot approve their own trade."""

    __tablename__ = "mynba_commissioners"
    __table_args__ = (
        UniqueConstraint("league_id", "discord_id", name="uq_mynba_commish_league_discord"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    league_id = Column(String, ForeignKey("mynba_leagues.id", ondelete="CASCADE"), nullable=False, index=True)
    discord_id = Column(String, nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    display_name = Column(String, nullable=True)
    is_trade_commissioner = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    league = relationship("MynbaLeague", back_populates="commissioners")


class MynbaTeam(Base):
    """A franchise. `is_cpu` teams have no GM, so their side auto-accepts to the commissioner."""

    __tablename__ = "mynba_teams"
    __table_args__ = (
        UniqueConstraint("league_id", "name", name="uq_mynba_team_league_name"),
        UniqueConstraint("league_id", "abbrev", name="uq_mynba_team_league_abbrev"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    league_id = Column(String, ForeignKey("mynba_leagues.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)          # "Timberwolves"
    full_name = Column(String, nullable=True)      # "Minnesota Timberwolves"
    abbrev = Column(String, nullable=False)        # "MIN"
    conference = Column(String, nullable=True)     # "East" / "West"

    is_cpu = Column(Boolean, nullable=False, default=True)
    gm_discord_id = Column(String, nullable=True, index=True)
    gm_user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    gm_display_name = Column(String, nullable=True)
    discord_role_id = Column(String, nullable=True)

    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    league = relationship("MynbaLeague", back_populates="teams")
    players = relationship("MynbaPlayer", back_populates="team", foreign_keys="MynbaPlayer.team_id")


class MynbaPlayer(Base):
    """A player on a roster. team_id NULL means free agent."""

    __tablename__ = "mynba_players"
    __table_args__ = (
        UniqueConstraint("league_id", "name_key", name="uq_mynba_player_league_namekey"),
        Index("ix_mynba_players_league_team", "league_id", "team_id"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    league_id = Column(String, ForeignKey("mynba_leagues.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String, nullable=False)      # exact in-game spelling
    name_key = Column(String, nullable=False)  # normalized, for lookup + uniqueness
    team_id = Column(String, ForeignKey("mynba_teams.id", ondelete="SET NULL"), nullable=True, index=True)

    position = Column(String, nullable=True)
    secondary_position = Column(String, nullable=True)
    ovr = Column(Integer, nullable=True)
    age = Column(Integer, nullable=True)
    salary = Column(Integer, nullable=True)          # dormant until enforce_salary_cap
    contract_years = Column(Integer, nullable=True)  # dormant until enforce_salary_cap
    jersey = Column(String, nullable=True)
    is_rookie = Column(Boolean, nullable=False, default=False)
    # Can't be traded. Cleared whenever the player changes teams.
    is_untouchable = Column(Boolean, nullable=False, default=False)
    extra = Column(Text, nullable=True)              # JSON: unmapped CSV columns, kept verbatim

    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    team = relationship("MynbaTeam", back_populates="players", foreign_keys=[team_id])


class MynbaTrade(Base):
    """One proposal. Players are in mynba_trade_assets; nothing moves until EXECUTED."""

    __tablename__ = "mynba_trades"
    __table_args__ = (
        Index("ix_mynba_trades_league_status", "league_id", "status"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    league_id = Column(String, ForeignKey("mynba_leagues.id", ondelete="CASCADE"), nullable=False, index=True)
    # Short human-facing handle used in Discord and the portal, e.g. "T-0042".
    ref = Column(String, nullable=False, index=True)

    status = Column(String, nullable=False, default=TRADE_PENDING_GM, index=True)

    proposer_team_id = Column(String, ForeignKey("mynba_teams.id"), nullable=False)
    # The other side for a two-team trade. For three-team deals this is the first
    # partner, kept for a readable title; `mynba_trade_teams` is authoritative.
    counterparty_team_id = Column(String, ForeignKey("mynba_teams.id"), nullable=False)
    team_count = Column(Integer, nullable=False, default=2)

    proposer_discord_id = Column(String, nullable=True, index=True)
    proposer_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    note = Column(Text, nullable=True)

    accepted_by_discord_id = Column(String, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    approved_by_discord_id = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    executed_at = Column(DateTime, nullable=True)

    # Why it ended, when it ended badly.
    resolution_reason = Column(Text, nullable=True)
    resolved_by_discord_id = Column(String, nullable=True)

    # Discord message handles so the bot can edit the cards in place.
    channel_id = Column(String, nullable=True)
    message_id = Column(String, nullable=True)
    approvals_channel_id = Column(String, nullable=True)
    approvals_message_id = Column(String, nullable=True)

    expires_at = Column(DateTime, nullable=True)         # proposal TTL
    execute_after = Column(DateTime, nullable=True)      # end of the protest window
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    assets = relationship("MynbaTradeAsset", back_populates="trade", cascade="all, delete-orphan")
    votes = relationship("MynbaTradeVote", back_populates="trade", cascade="all, delete-orphan")
    teams = relationship("MynbaTradeTeam", back_populates="trade", cascade="all, delete-orphan")


class MynbaTradeTeam(Base):
    """One team's seat in a trade, and whether its GM has signed off.

    Two-team trades have two rows, three-team trades have three. The trade only
    reaches a commissioner once every human-run team here has accepted, so the
    accept step scales past two without a special case.
    """

    __tablename__ = "mynba_trade_teams"
    __table_args__ = (
        UniqueConstraint("trade_id", "team_id", name="uq_mynba_tradeteam_trade_team"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    trade_id = Column(String, ForeignKey("mynba_trades.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(String, ForeignKey("mynba_teams.id"), nullable=False, index=True)

    is_proposer = Column(Boolean, nullable=False, default=False)
    # A CPU team has no GM to click, so it is accepted the moment it is added.
    is_cpu = Column(Boolean, nullable=False, default=False)

    accepted_at = Column(DateTime, nullable=True)
    accepted_by_discord_id = Column(String, nullable=True)
    declined_at = Column(DateTime, nullable=True)

    trade = relationship("MynbaTrade", back_populates="teams")


class MynbaTradeAsset(Base):
    """One player moving in one trade. N rows makes N-for-M packages work."""

    __tablename__ = "mynba_trade_assets"
    __table_args__ = (
        UniqueConstraint("trade_id", "player_id", name="uq_mynba_asset_trade_player"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    trade_id = Column(String, ForeignKey("mynba_trades.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(String, ForeignKey("mynba_players.id", ondelete="CASCADE"), nullable=False, index=True)

    from_team_id = Column(String, ForeignKey("mynba_teams.id"), nullable=False)
    to_team_id = Column(String, ForeignKey("mynba_teams.id"), nullable=False)

    # Snapshot at proposal time, so a card still reads correctly after execution.
    player_name = Column(String, nullable=False)

    trade = relationship("MynbaTrade", back_populates="assets")


class MynbaTradeVote(Base):
    """A GM's vote on a protested trade. One vote per team."""

    __tablename__ = "mynba_trade_votes"
    __table_args__ = (
        UniqueConstraint("trade_id", "team_id", name="uq_mynba_vote_trade_team"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    trade_id = Column(String, ForeignKey("mynba_trades.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(String, ForeignKey("mynba_teams.id"), nullable=False)
    discord_id = Column(String, nullable=True)
    # True = let the trade stand, False = overturn it.
    uphold = Column(Boolean, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    trade = relationship("MynbaTrade", back_populates="votes")


class MynbaTransaction(Base):
    """Append-only history. One row per player movement, whatever caused it."""

    __tablename__ = "mynba_transactions"
    __table_args__ = (
        Index("ix_mynba_txn_league_created", "league_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    league_id = Column(String, ForeignKey("mynba_leagues.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String, nullable=False, default=TXN_TRADE)

    player_id = Column(String, ForeignKey("mynba_players.id", ondelete="SET NULL"), nullable=True, index=True)
    player_name = Column(String, nullable=False)
    from_team_id = Column(String, ForeignKey("mynba_teams.id"), nullable=True)
    from_team_name = Column(String, nullable=True)
    to_team_id = Column(String, ForeignKey("mynba_teams.id"), nullable=True)
    to_team_name = Column(String, nullable=True)

    trade_id = Column(String, ForeignKey("mynba_trades.id", ondelete="SET NULL"), nullable=True, index=True)
    trade_ref = Column(String, nullable=True)
    actor_discord_id = Column(String, nullable=True)
    actor_display_name = Column(String, nullable=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=_utcnow, index=True)


class MynbaGameplan(Base):
    """A team's current weekly gameplan: coaching settings plus the rotation.

    One row per team, overwritten on each save; the history lives in
    mynba_gameplan_changes. Valid keys and values come from
    mynba_gameplan_options.json.
    """

    __tablename__ = "mynba_gameplans"
    __table_args__ = (
        UniqueConstraint("team_id", name="uq_mynba_gameplan_team"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    league_id = Column(String, ForeignKey("mynba_leagues.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(String, ForeignKey("mynba_teams.id", ondelete="CASCADE"), nullable=False, index=True)

    settings = Column(Text, nullable=True)   # JSON: {"offensive_focus": "Feed The Post", "help_defense": 68, ...}
    rotation = Column(Text, nullable=True)   # JSON: [{"player_id": ..., "minutes": 32}, ...] in slot order
    # Bumped on every save so two editors can't silently overwrite each other.
    version = Column(Integer, nullable=False, default=0)

    updated_by_discord_id = Column(String, nullable=True)
    updated_by_name = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class MynbaGameplanChange(Base):
    """One field a commissioner has to change in 2K. The activity feed.

    Repeated edits to the same field before it's marked done collapse into one
    row that keeps the original old value, so the feed shows the net change.
    """

    __tablename__ = "mynba_gameplan_changes"
    __table_args__ = (
        Index("ix_mynba_gpchange_league_done", "league_id", "done_at"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    league_id = Column(String, ForeignKey("mynba_leagues.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(String, ForeignKey("mynba_teams.id", ondelete="CASCADE"), nullable=False, index=True)
    team_name = Column(String, nullable=True)

    field_key = Column(String, nullable=False)     # "offensive_focus", "rotation:<player_id>"
    field_label = Column(String, nullable=False)   # "Offensive Focus", "J. Embiid"
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)

    actor_discord_id = Column(String, nullable=True)
    actor_display_name = Column(String, nullable=True)
    by_commissioner = Column(Boolean, nullable=False, default=False)

    done_at = Column(DateTime, nullable=True)
    done_by_discord_id = Column(String, nullable=True)
    notified_at = Column(DateTime, nullable=True)  # posted to the Discord gameplan channel

    created_at = Column(DateTime, nullable=False, default=_utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class MynbaGame(Base):
    """One simmed game, entered from box-score screenshots.

    Standings are computed from these rows, never typed in. "Away" is the team
    listed on top of the 2K score panel, "home" the one below it.
    """

    __tablename__ = "mynba_games"
    __table_args__ = (
        Index("ix_mynba_games_league_played", "league_id", "played_on"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    league_id = Column(String, ForeignKey("mynba_leagues.id", ondelete="CASCADE"), nullable=False, index=True)
    played_on = Column(Date, nullable=False)

    away_team_id = Column(String, ForeignKey("mynba_teams.id", ondelete="CASCADE"), nullable=False, index=True)
    home_team_id = Column(String, ForeignKey("mynba_teams.id", ondelete="CASCADE"), nullable=False, index=True)
    away_score = Column(Integer, nullable=False)
    home_score = Column(Integer, nullable=False)
    away_quarters = Column(Text, nullable=True)  # JSON: [28, 33, 27, 36] (+ OT periods)
    home_quarters = Column(Text, nullable=True)

    created_by_discord_id = Column(String, nullable=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    lines = relationship("MynbaGameLine", back_populates="game", cascade="all, delete-orphan",
                         order_by="MynbaGameLine.row")


class MynbaGameLine(Base):
    """One player's box-score line. DNPs are not stored.

    player_id is NULL when the 2K name ("K. Peat") matches nobody in the league;
    the line still counts, under that name and the team it played for.
    """

    __tablename__ = "mynba_game_lines"
    __table_args__ = (
        Index("ix_mynba_gamelines_league_player", "league_id", "player_id"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    game_id = Column(String, ForeignKey("mynba_games.id", ondelete="CASCADE"), nullable=False, index=True)
    league_id = Column(String, ForeignKey("mynba_leagues.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(String, ForeignKey("mynba_teams.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id = Column(String, ForeignKey("mynba_players.id", ondelete="SET NULL"), nullable=True)
    player_name = Column(String, nullable=False)  # as 2K printed it
    row = Column(Integer, nullable=False, default=0)

    minutes = Column(Integer, nullable=False, default=0)
    pts = Column(Integer, nullable=False, default=0)
    reb = Column(Integer, nullable=False, default=0)
    ast = Column(Integer, nullable=False, default=0)
    stl = Column(Integer, nullable=False, default=0)
    blk = Column(Integer, nullable=False, default=0)
    tov = Column(Integer, nullable=False, default=0)
    fgm = Column(Integer, nullable=False, default=0)
    fga = Column(Integer, nullable=False, default=0)
    tpm = Column(Integer, nullable=False, default=0)
    tpa = Column(Integer, nullable=False, default=0)
    ftm = Column(Integer, nullable=False, default=0)
    fta = Column(Integer, nullable=False, default=0)
    oreb = Column(Integer, nullable=False, default=0)
    fouls = Column(Integer, nullable=False, default=0)

    game = relationship("MynbaGame", back_populates="lines")
