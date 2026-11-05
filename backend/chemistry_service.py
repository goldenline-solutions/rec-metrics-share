"""
Squad chemistry — teammate co-occurrence stats derived from recorded games.

Rec games are one-off lineups, so there are no persistent teams to track. But
the game_players table already records who was on which side of every game, so
"who do you win with" is a query, not a new data model.

For a target player this computes, per other player they've shared a court with:
  - games together (same team_side) and win rate together
  - games against (opposite sides) and record against

Grouping is by NORMALIZED gamertag (matching how the profile service resolves a
player's own identity across capitalisation variants), never by the raw per-game
player_id — otherwise "Toz" and "toz" would look like two different teammates.

The stat is only as good as identity resolution, so results carry a `confidence`
signal and rows whose linkage is weak are excluded (see MIN_CONFIDENCE).
"""
from typing import Dict, List, Any, Optional
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import Player, Game, GamePlayer
from name_utils import normalize_name
from profile_service import determine_win

# game_players.match_confidence is 0-100 (how sure the resolver is that a
# detected name maps to an identity). Rows below this — or with no confidence
# recorded AND a fuzzy match method — are too shaky to attribute to a specific
# teammate, so they're dropped rather than risk crediting the wrong person.
MIN_CONFIDENCE = 60

# Don't surface a "chemistry" claim off a single shared game — one game is noise.
MIN_GAMES_TOGETHER = 2

# Placeholder / non-player names the OCR pipeline produces for empty or
# AI-controlled slots. These aren't real teammates and would pollute the list.
_JUNK_NORMS = {normalize_name(n) for n in (
    "AI Player", "AI", "NN", "N/A", "NA", "None", "Player", "Unknown", "-", "--",
)}


def _is_junk(norm: str) -> bool:
    return not norm or norm in _JUNK_NORMS or len(norm) <= 1


def _resolve_player_ids(db: Session, username: str) -> tuple[Optional[str], List[str]]:
    """Resolve a username to (display_name, [player_id, …]) across name variants.

    Mirrors get_player_profile's resolution so chemistry counts the same games
    the profile does.
    """
    normalized = normalize_name(username)
    players = db.query(Player).filter(
        func.lower(Player.gamertag) == func.lower(username)
    ).all()
    if not players:
        prefix = normalized[:5] if len(normalized) >= 5 else normalized
        candidates = db.query(Player).filter(
            func.lower(Player.gamertag).like(f"{prefix}%")
        ).all()
        players = [p for p in candidates if normalize_name(p.gamertag) == normalized]
    if not players:
        return None, []
    return players[0].gamertag, [p.id for p in players]


def _confident(gp: GamePlayer) -> bool:
    """Whether a game_players row is trustworthy enough to attribute."""
    if gp.match_confidence is not None:
        return gp.match_confidence >= MIN_CONFIDENCE
    # No score recorded: trust exact/manual matches, distrust fuzzy/none.
    return gp.match_method in ("exact", "variant", "manual", None)


def get_player_chemistry(
    db: Session, username: str, limit: int = 20
) -> Dict[str, Any]:
    """Teammate + opponent co-occurrence stats for a player.

    Returns { username, gamesAnalyzed, teammates: [...], rivals: [...] }, each
    entry sorted by games shared, richest first.
    """
    display_name, player_ids = _resolve_player_ids(db, username)
    if not player_ids:
        return {"error": "Player not found", "username": username}

    # Every game this player appears in, with their side. A player can in
    # principle appear once per game; take the first row per game.
    my_rows = (
        db.query(GamePlayer)
        .filter(GamePlayer.player_id.in_(player_ids))
        .all()
    )
    my_side_by_game: Dict[str, str] = {}
    for gp in my_rows:
        my_side_by_game.setdefault(gp.game_id, gp.team_side)

    game_ids = list(my_side_by_game.keys())
    if not game_ids:
        return {
            "username": display_name,
            "gamesAnalyzed": 0,
            "teammates": [],
            "rivals": [],
        }

    # All participants of those games, plus the game (for win calc) and the
    # participant's gamertag (for identity grouping).
    rows = (
        db.query(GamePlayer, Game, Player.gamertag)
        .join(Game, GamePlayer.game_id == Game.id)
        .join(Player, GamePlayer.player_id == Player.id)
        .filter(GamePlayer.game_id.in_(game_ids))
        .all()
    )

    my_gamertags = [
        r[0] for r in db.query(Player.gamertag).filter(Player.id.in_(player_ids)).all()
    ]
    my_norms = {normalize_name(n) for n in my_gamertags}

    # norm_name -> aggregate
    agg: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "displayName": None,
        "withGames": 0, "withWins": 0,
        "vsGames": 0, "vsWins": 0,
        "lowConfidence": 0,
    })

    for gp, game, gamertag in rows:
        norm = normalize_name(gamertag)
        if norm in my_norms:
            continue  # that's the player themselves
        if _is_junk(norm):
            continue  # AI/placeholder slot, not a real teammate
        my_side = my_side_by_game.get(gp.game_id)
        if my_side is None:
            continue

        entry = agg[norm]
        if entry["displayName"] is None:
            entry["displayName"] = gamertag

        if not _confident(gp):
            entry["lowConfidence"] += 1
            continue

        # Did MY team win this game? (win-together is from the target's side.)
        my_team_won = (
            game.home_score > game.away_score if my_side == "HOME"
            else game.away_score > game.home_score
        )

        if gp.team_side == my_side:
            entry["withGames"] += 1
            if my_team_won:
                entry["withWins"] += 1
        else:
            entry["vsGames"] += 1
            # "wins against" them = games where they were the opponent and I won.
            if my_team_won:
                entry["vsWins"] += 1

    teammates = []
    rivals = []
    for norm, e in agg.items():
        if e["displayName"] is None:
            continue
        if e["withGames"] >= MIN_GAMES_TOGETHER:
            teammates.append({
                "gamertag": e["displayName"],
                "games": e["withGames"],
                "wins": e["withWins"],
                "losses": e["withGames"] - e["withWins"],
                "winRate": round(100 * e["withWins"] / e["withGames"], 1),
            })
        if e["vsGames"] >= MIN_GAMES_TOGETHER:
            rivals.append({
                "gamertag": e["displayName"],
                "games": e["vsGames"],
                "wins": e["vsWins"],       # target's wins vs this opponent
                "losses": e["vsGames"] - e["vsWins"],
                "winRate": round(100 * e["vsWins"] / e["vsGames"], 1),
            })

    teammates.sort(key=lambda t: (t["games"], t["winRate"]), reverse=True)
    rivals.sort(key=lambda r: (r["games"], r["winRate"]), reverse=True)

    return {
        "username": display_name,
        "gamesAnalyzed": len(game_ids),
        "teammates": teammates[:limit],
        "rivals": rivals[:limit],
    }
