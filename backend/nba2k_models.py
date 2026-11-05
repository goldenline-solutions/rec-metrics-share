"""
NBA 2K ratings reference data, synced weekly from nba2kapi.com.

Kept deliberately separate from `mynba_players`:

  nba2k_players   what 2K says a player is — ratings, attributes, badges.
                  Rewritten every week by the sync.
  mynba_players   what OUR league says — who is on whose roster.
                  Only ever changed by a trade, signing, or release.

They are joined on `slug`. Keeping them apart is what lets a weekly ratings
refresh run without touching a single roster: if the two were one table, every
sync would undo every trade.
"""
from datetime import datetime

from sqlalchemy import Column, String, Integer, Text, DateTime, Index

from db import Base
from models import generate_uuid


def _utcnow():
    return datetime.utcnow()


# Attribute groups, in the order 2K itself presents them. Used by the player card.
ATTRIBUTE_GROUPS = [
    ("Outside Scoring", [
        "closeShot", "midRangeShot", "threePointShot", "freeThrow",
        "shotIQ", "offensiveConsistency",
    ]),
    ("Inside Scoring", [
        "drivingLayup", "standingDunk", "drivingDunk", "postControl",
        "postHook", "postFade", "drawFoul", "hands",
    ]),
    ("Athleticism", [
        "speed", "agility", "strength", "vertical", "stamina", "hustle", "durability",
    ]),
    ("Playmaking", [
        "passAccuracy", "ballHandle", "speedWithBall", "passIQ", "passVision", "passPerception",
    ]),
    ("Defense", [
        "interiorDefense", "perimeterDefense", "steal", "block",
        "helpDefenseIQ", "defensiveConsistency",
    ]),
    ("Rebounding", ["offensiveRebound", "defensiveRebound"]),
]

# camelCase key -> label shown on the card
ATTRIBUTE_LABELS = {
    "closeShot": "Close Shot", "midRangeShot": "Mid-Range Shot", "threePointShot": "Three-Point Shot",
    "freeThrow": "Free Throw", "shotIQ": "Shot IQ", "offensiveConsistency": "Offensive Consistency",
    "drivingLayup": "Driving Layup", "standingDunk": "Standing Dunk", "drivingDunk": "Driving Dunk",
    "postControl": "Post Control", "postHook": "Post Hook", "postFade": "Post Fade",
    "drawFoul": "Draw Foul", "hands": "Hands",
    "speed": "Speed", "agility": "Agility", "strength": "Strength", "vertical": "Vertical",
    "stamina": "Stamina", "hustle": "Hustle", "durability": "Durability",
    "passAccuracy": "Pass Accuracy", "ballHandle": "Ball Handle", "speedWithBall": "Speed With Ball",
    "passIQ": "Pass IQ", "passVision": "Pass Vision", "passPerception": "Pass Perception",
    "interiorDefense": "Interior Defense", "perimeterDefense": "Perimeter Defense",
    "steal": "Steal", "block": "Block", "helpDefenseIQ": "Help Defense IQ",
    "defensiveConsistency": "Defensive Consistency",
    "offensiveRebound": "Offensive Rebound", "defensiveRebound": "Defensive Rebound",
}


class Nba2kPlayer(Base):
    """One player as 2K rates them. `slug` is the stable identity across syncs."""

    __tablename__ = "nba2k_players"
    __table_args__ = (
        Index("ix_nba2k_players_era_team", "team_type", "team"),
        Index("ix_nba2k_players_namekey", "name_key"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    slug = Column(String, unique=True, nullable=False, index=True)
    source_id = Column(String, nullable=True)

    name = Column(String, nullable=False)
    name_key = Column(String, nullable=False)  # normalized, joins to mynba_players

    team = Column(String, nullable=True)       # real NBA team per 2K, not our league
    team_type = Column(String, nullable=True, default="curr")  # curr | class | allt
    team_img = Column(String, nullable=True)

    overall = Column(Integer, nullable=True, index=True)
    positions = Column(Text, nullable=True)    # JSON list, e.g. ["PG","SG"]
    archetype = Column(String, nullable=True)
    build = Column(String, nullable=True)

    height = Column(String, nullable=True)
    weight = Column(String, nullable=True)
    wingspan = Column(String, nullable=True)
    college = Column(String, nullable=True)

    player_image = Column(String, nullable=True)
    player_url = Column(String, nullable=True)
    game_version = Column(String, nullable=True)

    attributes = Column(Text, nullable=True)       # JSON, 35 keys
    badges = Column(Text, nullable=True)           # JSON, shape as returned
    rating_history = Column(Text, nullable=True)   # JSON list
    season_movement = Column(Text, nullable=True)  # JSON list

    # Whether the detail endpoint (which carries badges) has been fetched for
    # this player, or only the cheaper list endpoint.
    detail_synced_at = Column(DateTime, nullable=True)

    source_updated_at = Column(String, nullable=True)  # `lastUpdated` from the API
    synced_at = Column(DateTime, nullable=False, default=_utcnow)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class Nba2kSyncRun(Base):
    """One sync attempt, so staff can see when ratings last moved and what changed."""

    __tablename__ = "nba2k_sync_runs"

    id = Column(String, primary_key=True, default=generate_uuid)
    era = Column(String, nullable=False, default="curr")
    started_at = Column(DateTime, nullable=False, default=_utcnow)
    finished_at = Column(DateTime, nullable=True)

    created = Column(Integer, nullable=False, default=0)
    updated = Column(Integer, nullable=False, default=0)
    unchanged = Column(Integer, nullable=False, default=0)
    rating_changes = Column(Text, nullable=True)  # JSON: [{name, slug, from, to, delta}]

    ok = Column(Integer, nullable=False, default=0)  # 1 = finished cleanly
    error = Column(Text, nullable=True)
    triggered_by = Column(String, nullable=True)     # discord id, or "schedule"
