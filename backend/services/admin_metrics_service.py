"""
Admin Metrics Service
Computes defensive disruption estimates and related advanced metrics per player per game.

Key concepts:
- We don't know which opponent committed turnovers that led to steals
- We estimate defensive pressure using build attributes and position
- We enforce conservation: sum(tov_forced_est) == unattributed_tov at team level
- Metrics are estimates marked with "(Est.)" in UI

Usage:
1. Run migration manually (if needed):
   cd app/backend
   python run_migrations.py
   
   Note: Migrations also run automatically on app startup.

2. Backfill existing games:
   from services.admin_metrics_service import upsert_player_game_admin_metrics
   from db import SessionLocal
   db = SessionLocal()
   # For a specific game:
   upsert_player_game_admin_metrics(db, game_id)
   # Or loop through all games:
   from models import Game
   for game in db.query(Game).all():
       upsert_player_game_admin_metrics(db, game.id)
   db.close()

3. Metrics can be recomputed via API:
   POST /api/admin/games/<game_id>/recompute-admin-metrics
"""
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_
from datetime import datetime

from models import (
    Game, Player, GamePlayer, PlayerGameStats, TeamTotal,
    Build, BuildAttribute, PlayerGameAdminMetrics, Matchup
)


# Configuration constants - can be tuned later
METRICS_CONFIG = {
    # Pressure weight coefficients
    "steal_weight": 0.45,
    "perimD_weight": 0.25,
    "speed_weight": 0.20,
    "position_weight": 0.10,
    
    # Position factors for pressure weight (base values)
    "position_factors": {
        "PG": 1.15,
        "SG": 1.15,
        "SF": 1.00,
        "PF": 0.90,
        "C": 0.80
    },
    
    # On-ball ratio base by position
    "onball_ratio_base": {
        "PG": 0.65,
        "SG": 0.65,
        "SF": 0.50,
        "PF": 0.40,
        "C": 0.35
    },
    
    # On-ball ratio adjustments from build
    "onball_perimD_threshold": 0.85,
    "onball_perimD_bonus": 0.05,
    "onball_block_threshold": 0.85,
    "onball_block_penalty": -0.05,
    "onball_ratio_min": 0.2,
    "onball_ratio_max": 0.8,
    
    # Disruption score coefficients
    "disruption_stl_coef": 1.0,
    "disruption_blk_coef": 0.7,
    "disruption_tov_coef": 0.6,
    "disruption_pf_penalty": -0.6,
    
    # Matchup-based defense configuration
    "MATCHUP_BASELINE_LAST_N_GAMES": 15,  # Number of recent games to use for baseline
    "MATCHUP_MIN_WEIGHT": 0.1,  # Minimum FGA or minutes share to qualify for matchup
    "DEF_BLEND_A": 0.7,  # Weight for matchup_stop in defensive disruption
    "DEF_BLEND_B": 0.3,  # Weight for stocks_per100 in defensive disruption
    "FALLBACK_TO_TOV_MODEL": True,  # Use turnover allocation if matchup data insufficient
}


def estimate_possessions(db: Session, game_id: str, team_side: str) -> float:
    """
    Estimate team possessions using: FGA + 0.44*FTA + TOV
    
    Args:
        db: Database session
        game_id: Game ID
        team_side: 'AWAY' or 'HOME'
        
    Returns:
        Estimated possessions (float)
    """
    # Get all player stats for this team in this game
    stats = db.query(PlayerGameStats).join(
        GamePlayer,
        (PlayerGameStats.game_id == GamePlayer.game_id) & 
        (PlayerGameStats.player_id == GamePlayer.player_id)
    ).filter(
        PlayerGameStats.game_id == game_id,
        GamePlayer.team_side == team_side
    ).all()
    
    if not stats:
        return 0.0
    
    # Sum FGA, FTA, TOV across all players
    total_fga = sum(s.fga for s in stats)
    total_fta = sum(s.fta for s in stats)
    total_tov = sum(s.tov for s in stats)
    
    # Possessions = FGA + 0.44*FTA + TOV
    possessions = total_fga + 0.44 * total_fta + total_tov
    
    return max(0.0, possessions)


def compute_team_context(db: Session, game_id: str, team_side: str) -> Dict[str, int]:
    """
    Compute team-level context: team steals and opponent turnovers.
    
    Args:
        db: Database session
        game_id: Game ID
        team_side: 'AWAY' or 'HOME'
        
    Returns:
        Dict with 'team_stl' and 'opp_tov'
    """
    # Get team steals (sum of STL for all players on this team)
    team_stats = db.query(PlayerGameStats).join(
        GamePlayer,
        (PlayerGameStats.game_id == GamePlayer.game_id) & 
        (PlayerGameStats.player_id == GamePlayer.player_id)
    ).filter(
        PlayerGameStats.game_id == game_id,
        GamePlayer.team_side == team_side
    ).all()
    
    team_stl = sum(s.stl for s in team_stats)
    
    # Get opponent turnovers (sum of TOV for all players on opposing team)
    opp_side = "HOME" if team_side == "AWAY" else "AWAY"
    opp_stats = db.query(PlayerGameStats).join(
        GamePlayer,
        (PlayerGameStats.game_id == GamePlayer.game_id) & 
        (PlayerGameStats.player_id == GamePlayer.player_id)
    ).filter(
        PlayerGameStats.game_id == game_id,
        GamePlayer.team_side == opp_side
    ).all()
    
    opp_tov = sum(s.tov for s in opp_stats)
    
    return {
        "team_stl": team_stl,
        "opp_tov": opp_tov
    }


def get_build_attribute_value(db: Session, build: Optional[Build], attribute_name: str) -> Optional[float]:
    """
    Get a normalized (0-1) build attribute value.
    
    Args:
        db: Database session
        build: Build object or None
        attribute_name: Name of attribute (e.g., "Steal", "Perimeter Defense")
        
    Returns:
        Normalized value (0-1) or None if not found
    """
    if not build:
        return None
    
    attr = db.query(BuildAttribute).filter(
        BuildAttribute.build_id == build.id,
        BuildAttribute.attribute_name == attribute_name
    ).first()
    
    if not attr or not attr.value_max:
        return None
    
    # Normalize to 0-1: value / max, clamped to [0, 1]
    normalized = max(0.0, min(1.0, float(attr.value_current) / float(attr.value_max)))
    return normalized


def compute_pressure_weight(
    db: Session,
    player: Player,
    game_player: GamePlayer,
    build: Optional[Build]
) -> Tuple[float, bool]:
    """
    Compute pressure weight (w_i) for a player based on build and position.
    
    Formula: w_i = 0.45*steal_norm + 0.25*perimD_norm + 0.20*speed_norm + 0.10*position_factor
    
    If build is missing, use position_factor only.
    
    Args:
        db: Database session
        player: Player object
        game_player: GamePlayer object (has position)
        build: Build object or None
        
    Returns:
        Tuple of (pressure_weight, used_build)
    """
    config = METRICS_CONFIG
    position = game_player.position.value if hasattr(game_player.position, 'value') else str(game_player.position)
    
    # Base position factor
    position_factor = config["position_factors"].get(position, 1.0)
    
    # If no build, return position factor only
    if not build:
        return (position_factor, False)
    
    # Get build attributes
    steal_norm = get_build_attribute_value(db, build, "Steal") or 0.5
    perimD_norm = get_build_attribute_value(db, build, "Perimeter Defense") or 0.5
    speed_norm = get_build_attribute_value(db, build, "Speed") or 0.5
    
    # Compute weighted sum
    w_i = (
        config["steal_weight"] * steal_norm +
        config["perimD_weight"] * perimD_norm +
        config["speed_weight"] * speed_norm +
        config["position_weight"] * position_factor
    )
    
    return (w_i, True)


def compute_onball_ratio(
    db: Session,
    game_player: GamePlayer,
    build: Optional[Build]
) -> float:
    """
    Compute estimated on-ball ratio based on position and build.
    
    Base by position, then adjust by build attributes.
    
    Args:
        db: Database session
        game_player: GamePlayer object (has position)
        build: Build object or None
        
    Returns:
        On-ball ratio (0-1), clamped to [0.2, 0.8]
    """
    config = METRICS_CONFIG
    position = game_player.position.value if hasattr(game_player.position, 'value') else str(game_player.position)
    
    # Base ratio by position
    base_ratio = config["onball_ratio_base"].get(position, 0.5)
    
    # Adjustments from build
    if build:
        perimD_norm = get_build_attribute_value(db, build, "Perimeter Defense") or 0.5
        block_norm = get_build_attribute_value(db, build, "Block") or 0.5
        
        # +0.05 if perimD >= 0.85
        if perimD_norm >= config["onball_perimD_threshold"]:
            base_ratio += config["onball_perimD_bonus"]
        
        # -0.05 if block >= 0.85 (more help-side)
        if block_norm >= config["onball_block_threshold"]:
            base_ratio += config["onball_block_penalty"]
    
    # Clamp to [0.2, 0.8]
    ratio = max(config["onball_ratio_min"], min(config["onball_ratio_max"], base_ratio))
    
    return ratio


def compute_opponent_baseline_fg_pct(
    db: Session,
    opponent_id: str,
    current_game_id: str,
    current_game_date: datetime,
    position: Optional[str] = None
) -> Tuple[float, bool]:
    """
    Compute baseline FG% for an opponent using trailing games.
    
    Strategy (in order of preference):
    1. Trailing average over last N games BEFORE current game
    2. Position baseline (if position provided)
    3. Global baseline for sample window
    
    Args:
        db: Database session
        opponent_id: Opponent player ID
        current_game_id: Current game ID (exclude from baseline)
        current_game_date: Current game date (for ordering)
        position: Optional position for position-specific baseline
        
    Returns:
        Tuple of (baseline_fg_pct, used_matchup_baseline) where:
        - baseline_fg_pct: Baseline field goal percentage (0-1)
        - used_matchup_baseline: True if we used trailing games, False if fallback
    """
    config = METRICS_CONFIG
    n_games = config["MATCHUP_BASELINE_LAST_N_GAMES"]
    
    # Try to get current game date
    if isinstance(current_game_date, str):
        try:
            current_game_date = datetime.fromisoformat(current_game_date.replace('Z', '+00:00'))
        except:
            current_game_date = datetime.fromisoformat(current_game_date)
    
    # Get opponent's recent games BEFORE current game
    recent_games = db.query(Game).join(
        GamePlayer,
        Game.id == GamePlayer.game_id
    ).filter(
        GamePlayer.player_id == opponent_id,
        Game.id != current_game_id
    ).order_by(desc(Game.created_at)).limit(n_games).all()
    
    # Filter to games before current game date
    recent_games = [
        g for g in recent_games
        if datetime.fromisoformat(g.created_at.replace('Z', '+00:00')) < current_game_date
    ]
    
    # Get stats for recent games
    fga_total = 0
    fgm_total = 0
    
    for game in recent_games:
        stats = db.query(PlayerGameStats).filter(
            PlayerGameStats.game_id == game.id,
            PlayerGameStats.player_id == opponent_id
        ).first()
        if stats:
            fga_total += stats.fga
            fgm_total += stats.fgm
    
    # If we have enough data, use trailing average
    if fga_total >= 10:  # Minimum 10 FGA for reliable baseline
        baseline_fg_pct = fgm_total / fga_total if fga_total > 0 else 0.5
        return (baseline_fg_pct, True)
    
    # Fallback: position baseline (if position provided)
    if position:
        # Get all players at this position and their recent FG%
        # Join through GamePlayer to filter by position
        position_stats = db.query(PlayerGameStats).join(
            GamePlayer,
            (PlayerGameStats.game_id == GamePlayer.game_id) &
            (PlayerGameStats.player_id == GamePlayer.player_id)
        ).join(
            Game,
            PlayerGameStats.game_id == Game.id
        ).filter(
            GamePlayer.position == position,
            Game.id != current_game_id
        ).order_by(desc(Game.created_at)).limit(n_games * 10).all()  # Sample more games
        
        pos_fga = sum(s.fga for s in position_stats)
        pos_fgm = sum(s.fgm for s in position_stats)
        
        if pos_fga >= 50:  # Minimum 50 FGA for position baseline
            baseline_fg_pct = pos_fgm / pos_fga if pos_fga > 0 else 0.5
            return (baseline_fg_pct, False)
    
    # Final fallback: global baseline (0.5 = 50% FG%, reasonable default)
    return (0.5, False)


def compute_matchup_stop_metrics(
    db: Session,
    game: Game,
    defender_id: str,
    defender_stats: PlayerGameStats,
    possessions_est: float
) -> Dict[str, Any]:
    """
    Compute matchup-based defensive stop metrics for a defender.
    
    For each opponent guarded (from matchups), compute:
    - fg_delta = (opponent_fg%_vs_defender - baseline_fg%)
    - matchup_stop = -sum(fg_delta * weight)
    
    REC rationale: Matchup data tells us who guarded whom. By comparing opponent
    performance vs this defender to their baseline, we can estimate defensive impact.
    This is more direct than turnover allocation, which is inherently uncertain.
    
    Args:
        db: Database session
        game: Game object
        defender_id: Defender player ID
        defender_stats: Defender's PlayerGameStats for this game
        possessions_est: Estimated team possessions
        
    Returns:
        Dict with:
        - matchup_stop: Raw matchup stop value (negative = good defense)
        - matchup_stop_per100: Matchup stop per 100 possessions
        - used_matchup_baseline: True if used trailing games, False if fallback
        - matchup_count: Number of matchups found
    """
    config = METRICS_CONFIG
    min_weight = config["MATCHUP_MIN_WEIGHT"]
    
    # Get matchups where this player was the defender
    matchups = db.query(Matchup).filter(
        Matchup.game_id == game.id,
        Matchup.defender_player_id == defender_id
    ).all()
    
    if not matchups:
        # No matchup data - return zeros
        return {
            "matchup_stop": 0.0,
            "matchup_stop_per100": 0.0,
            "used_matchup_baseline": False,
            "matchup_count": 0
        }
    
    # Parse game date
    try:
        game_date = datetime.fromisoformat(game.created_at.replace('Z', '+00:00'))
    except:
        try:
            game_date = datetime.fromisoformat(game.created_at)
        except:
            game_date = datetime.utcnow()
    
    # Get opponent team side (opposite of defender's team)
    defender_gp = db.query(GamePlayer).filter(
        GamePlayer.game_id == game.id,
        GamePlayer.player_id == defender_id
    ).first()
    
    if not defender_gp:
        return {
            "matchup_stop": 0.0,
            "matchup_stop_per100": 0.0,
            "used_matchup_baseline": False,
            "matchup_count": 0
        }
    
    defender_side = defender_gp.team_side.value if hasattr(defender_gp.team_side, 'value') else str(defender_gp.team_side)
    opp_side = "HOME" if defender_side == "AWAY" else "AWAY"
    
    # Accumulate matchup stop contributions
    matchup_stop_total = 0.0
    total_weight = 0.0
    used_baseline = True
    
    for matchup in matchups:
        opponent_id = matchup.offender_player_id
        opponent_position = matchup.offender_position.value if hasattr(matchup.offender_position, 'value') else str(matchup.offender_position)
        
        # Get opponent's stats for this game
        opp_stats = db.query(PlayerGameStats).filter(
            PlayerGameStats.game_id == game.id,
            PlayerGameStats.player_id == opponent_id
        ).first()
        
        if not opp_stats or opp_stats.fga == 0:
            continue  # Skip if no shots attempted
        
        # Weight by FGA (more shots = more reliable)
        weight = float(opp_stats.fga)
        
        if weight < min_weight:
            continue  # Skip low-weight matchups
        
        # Compute opponent's FG% vs this defender
        opp_fg_pct_vs_def = float(opp_stats.fgm) / float(opp_stats.fga) if opp_stats.fga > 0 else 0.0
        
        # Get baseline FG%
        baseline_fg_pct, used_trailing = compute_opponent_baseline_fg_pct(
            db, opponent_id, game.id, game_date, opponent_position
        )
        if not used_trailing:
            used_baseline = False
        
        # Compute FG% delta (negative = good defense)
        fg_delta = opp_fg_pct_vs_def - baseline_fg_pct
        
        # Accumulate: matchup_stop = -sum(fg_delta * weight)
        # Negative fg_delta (opponent shot worse) = positive matchup_stop (good defense)
        matchup_stop_total += -fg_delta * weight
        total_weight += weight
    
    # Normalize by total weight
    if total_weight > 0:
        matchup_stop = matchup_stop_total / total_weight
    else:
        matchup_stop = 0.0
    
    # Normalize per 100 possessions
    if possessions_est > 0:
        matchup_stop_per100 = (matchup_stop / possessions_est) * 100.0
    else:
        matchup_stop_per100 = 0.0
    
    return {
        "matchup_stop": matchup_stop,
        "matchup_stop_per100": matchup_stop_per100,
        "used_matchup_baseline": used_baseline,
        "matchup_count": len(matchups)
    }


def compute_player_admin_metrics(
    db: Session,
    game: Game,
    player: Player,
    game_player: GamePlayer,
    player_stats: PlayerGameStats,
    team_context: Dict[str, int],
    possessions_est: float,
    team_pressure_weights: Dict[str, float]
) -> Dict[str, Any]:
    """
    Compute all admin metrics for a single player in a game.
    
    Args:
        db: Database session
        game: Game object
        player: Player object
        game_player: GamePlayer object
        player_stats: PlayerGameStats object
        team_context: Dict with 'team_stl' and 'opp_tov'
        possessions_est: Estimated team possessions
        team_pressure_weights: Dict mapping player_id -> pressure_weight for all team players
        
    Returns:
        Dict with all computed metrics
    """
    config = METRICS_CONFIG
    
    # Get build if available
    build = game_player.build if hasattr(game_player, 'build') else None
    if not build and game_player.build_id:
        build = db.query(Build).filter(Build.id == game_player.build_id).first()
    
    # Compute pressure weight
    pressure_weight, used_build = compute_pressure_weight(db, player, game_player, build)
    
    # Compute pressure share (w_i / sum(w_team))
    team_side = game_player.team_side.value if hasattr(game_player.team_side, 'value') else str(game_player.team_side)
    sum_team_weights = sum(team_pressure_weights.values())
    
    if sum_team_weights == 0:
        pressure_share = 0.0
    else:
        pressure_share = pressure_weight / sum_team_weights
    
    # Compute unattributed turnovers
    unattributed_tov = max(0.0, float(team_context["opp_tov"]) - float(team_context["team_stl"]))
    
    # Compute turnovers forced estimate
    tov_forced_est = unattributed_tov * pressure_share
    
    # Compute on-ball ratio
    onball_ratio_est = compute_onball_ratio(db, game_player, build)
    
    # Compute on-ball and off-ball pressure estimates
    onball_pressure_est = tov_forced_est * onball_ratio_est
    offball_disruption_est = tov_forced_est * (1.0 - onball_ratio_est)
    
    # Compute disruption score (per-game)
    disruption_score = (
        config["disruption_stl_coef"] * float(player_stats.stl) +
        config["disruption_blk_coef"] * float(player_stats.blk) +
        config["disruption_tov_coef"] * tov_forced_est +
        config["disruption_pf_penalty"] * float(player_stats.fouls)
    )
    
    # Compute disruption score per 100 possessions
    if possessions_est > 0:
        disruption_score_100 = (disruption_score / possessions_est) * 100.0
    else:
        disruption_score_100 = 0.0
    
    # Compute matchup-based defensive stop metrics
    matchup_metrics = compute_matchup_stop_metrics(
        db, game, player.id, player_stats, possessions_est
    )
    
    # Compute stocks per 100 possessions (steals + blocks)
    stocks = float(player_stats.stl) + float(player_stats.blk)
    if possessions_est > 0:
        stocks_per100 = (stocks / possessions_est) * 100.0
    else:
        stocks_per100 = 0.0
    
    # Blend defensive disruption: a*matchup_stop + b*stocks_per100
    # Use matchup_stop as primary if available, otherwise fall back to turnover model
    use_matchup = matchup_metrics["matchup_count"] > 0 and config.get("FALLBACK_TO_TOV_MODEL", True)
    
    if use_matchup and matchup_metrics["matchup_stop_per100"] != 0.0:
        # Primary: matchup-based defense
        def_disruption_per100 = (
            config["DEF_BLEND_A"] * matchup_metrics["matchup_stop_per100"] +
            config["DEF_BLEND_B"] * stocks_per100
        )
        used_matchup_primary = True
    else:
        # Fallback: use disruption_score_100 (turnover-based)
        def_disruption_per100 = disruption_score_100
        used_matchup_primary = False
    
    return {
        "game_id": game.id,
        "player_id": player.id,
        "team_side": team_side,
        "possessions_est": possessions_est,
        "opp_tov": team_context["opp_tov"],
        "team_stl": team_context["team_stl"],
        "unattributed_tov": unattributed_tov,
        "pressure_weight": pressure_weight,
        "pressure_share": pressure_share,
        "tov_forced_est": tov_forced_est,
        "onball_ratio_est": onball_ratio_est,
        "onball_pressure_est": onball_pressure_est,
        "offball_disruption_est": offball_disruption_est,
        "disruption_score": disruption_score,
        "disruption_score_100": disruption_score_100,  # Legacy: turnover-based
        "used_build": 1 if used_build else 0,
        # New matchup-based metrics
        "matchup_stop": float(matchup_metrics["matchup_stop"]),
        "matchup_stop_per100": float(matchup_metrics["matchup_stop_per100"]),
        "stocks_per100": float(stocks_per100),
        "def_disruption_per100": float(def_disruption_per100),  # Blended defensive metric
        "used_matchup_baseline": 1 if matchup_metrics["used_matchup_baseline"] else 0,
        "used_matchup_primary": 1 if used_matchup_primary else 0
    }


def upsert_player_game_admin_metrics(db: Session, game_id: str) -> int:
    """
    Compute and upsert admin metrics for all 10 players in a game.
    
    Args:
        db: Database session
        game_id: Game ID
        
    Returns:
        Number of records created/updated
    """
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise ValueError(f"Game {game_id} not found")
    
    # Get all game players with their stats
    game_players = db.query(GamePlayer).filter(GamePlayer.game_id == game_id).all()
    
    if len(game_players) != 10:
        raise ValueError(f"Expected 10 players, found {len(game_players)}")
    
    # Group by team side
    away_players = [gp for gp in game_players if (gp.team_side.value if hasattr(gp.team_side, 'value') else str(gp.team_side)) == "AWAY"]
    home_players = [gp for gp in game_players if (gp.team_side.value if hasattr(gp.team_side, 'value') else str(gp.team_side)) == "HOME"]
    
    # Compute team contexts
    away_context = compute_team_context(db, game_id, "AWAY")
    home_context = compute_team_context(db, game_id, "HOME")
    
    # Compute possessions
    away_possessions = estimate_possessions(db, game_id, "AWAY")
    home_possessions = estimate_possessions(db, game_id, "HOME")
    
    # Compute pressure weights for each team
    away_weights = {}
    home_weights = {}
    
    for gp in away_players:
        player = gp.player
        build = gp.build if hasattr(gp, 'build') else None
        if not build and gp.build_id:
            build = db.query(Build).filter(Build.id == gp.build_id).first()
        weight, _ = compute_pressure_weight(db, player, gp, build)
        away_weights[gp.player_id] = weight
    
    for gp in home_players:
        player = gp.player
        build = gp.build if hasattr(gp, 'build') else None
        if not build and gp.build_id:
            build = db.query(Build).filter(Build.id == gp.build_id).first()
        weight, _ = compute_pressure_weight(db, player, gp, build)
        home_weights[gp.player_id] = weight
    
    # Compute metrics for each player
    records_created = 0
    
    for gp in game_players:
        team_side = gp.team_side.value if hasattr(gp.team_side, 'value') else str(gp.team_side)
        context = away_context if team_side == "AWAY" else home_context
        possessions = away_possessions if team_side == "AWAY" else home_possessions
        team_weights = away_weights if team_side == "AWAY" else home_weights
        
        # Get player stats
        player_stats = db.query(PlayerGameStats).filter(
            PlayerGameStats.game_id == game_id,
            PlayerGameStats.player_id == gp.player_id
        ).first()
        
        if not player_stats:
            continue
        
        # Compute metrics
        metrics_data = compute_player_admin_metrics(
            db, game, gp.player, gp, player_stats,
            context, possessions, team_weights
        )
        
        # Upsert record
        existing = db.query(PlayerGameAdminMetrics).filter(
            PlayerGameAdminMetrics.game_id == game_id,
            PlayerGameAdminMetrics.player_id == gp.player_id
        ).first()
        
        if existing:
            # Update existing
            for key, value in metrics_data.items():
                if key not in ["game_id", "player_id"]:
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow().isoformat()
        else:
            # Create new
            new_metrics = PlayerGameAdminMetrics(**metrics_data)
            new_metrics.created_at = datetime.utcnow().isoformat()
            new_metrics.updated_at = datetime.utcnow().isoformat()
            db.add(new_metrics)
            records_created += 1
    
    db.commit()
    return records_created


def get_player_admin_metrics(
    db: Session,
    player_id: str,
    last_n: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get admin metrics for a player with per-game data and aggregates.
    
    Args:
        db: Database session
        player_id: Player ID
        last_n: Optional limit on number of games (None = all)
        
    Returns:
        Dict with 'per_game' list and 'aggregates' dict
    """
    # Query per-game metrics
    query = db.query(PlayerGameAdminMetrics).join(
        Game,
        PlayerGameAdminMetrics.game_id == Game.id
    ).filter(
        PlayerGameAdminMetrics.player_id == player_id
    ).order_by(desc(Game.created_at))
    
    if last_n:
        query = query.limit(last_n)
    
    metrics_list = query.all()
    
    # Build per-game data
    per_game = []
    for m in metrics_list:
        game = m.game
        if not game:
            continue
        
        # Get player's game_player row to determine team side
        game_player = db.query(GamePlayer).filter(
            GamePlayer.game_id == m.game_id,
            GamePlayer.player_id == player_id
        ).first()
        
        # Determine opponent team name
        opponent = None
        if game_player:
            if (game_player.team_side.value if hasattr(game_player.team_side, 'value') else str(game_player.team_side)) == "HOME":
                opponent = game.away_team_name or "Away"
            else:
                opponent = game.home_team_name or "Home"
        
        # Determine result (win/loss)
        result = None
        if game_player and game:
            if (game_player.team_side.value if hasattr(game_player.team_side, 'value') else str(game_player.team_side)) == "HOME":
                won = game.home_score > game.away_score
            else:
                won = game.away_score > game.home_score
            result = "W" if won else "L"
        
        per_game_dict = {
            "game_id": m.game_id,
            "date": game.created_at if game else None,
            "opponent": opponent,
            "result": result,
            "stl": None,  # Get from player_stats
            "blk": None,
            "pf": None,
            "opp_tov": int(m.opp_tov),
            "team_stl": int(m.team_stl),
            "unattributed_tov": float(m.unattributed_tov),
            "tov_forced_est": float(m.tov_forced_est),
            "onball_pressure_est": float(m.onball_pressure_est),
            "offball_disruption_est": float(m.offball_disruption_est),
            "disruption_score_100": float(m.disruption_score_100),
            "used_build": bool(m.used_build)
        }
        
        # Add new matchup-based fields if available
        if hasattr(m, 'matchup_stop_per100') and m.matchup_stop_per100 is not None:
            per_game_dict["matchup_stop_per100"] = float(m.matchup_stop_per100)
            per_game_dict["stocks_per100"] = float(m.stocks_per100) if m.stocks_per100 is not None else None
            per_game_dict["def_disruption_per100"] = float(m.def_disruption_per100) if m.def_disruption_per100 is not None else None
            per_game_dict["used_matchup_baseline"] = bool(m.used_matchup_baseline) if m.used_matchup_baseline is not None else False
            per_game_dict["used_matchup_primary"] = bool(m.used_matchup_primary) if m.used_matchup_primary is not None else False
        
        per_game.append(per_game_dict)
        
        # Get actual stats from PlayerGameStats
        stats = db.query(PlayerGameStats).filter(
            PlayerGameStats.game_id == m.game_id,
            PlayerGameStats.player_id == player_id
        ).first()
        if stats:
            per_game[-1]["stl"] = stats.stl
            per_game[-1]["blk"] = stats.blk
            per_game[-1]["pf"] = stats.fouls
    
    # Compute aggregates
    if not metrics_list:
        return {
            "per_game": [],
            "aggregates": {}
        }
    
    # Helper to compute mean
    def mean(values):
        return sum(values) / len(values) if values else 0.0
    
    # Get all metrics for aggregates
    all_metrics = db.query(PlayerGameAdminMetrics).filter(
        PlayerGameAdminMetrics.player_id == player_id
    ).all()
    
    # Compute aggregates for different windows
    windows = {
        "last_5": metrics_list[:5] if len(metrics_list) >= 5 else metrics_list,
        "last_10": metrics_list[:10] if len(metrics_list) >= 10 else metrics_list,
        "last_25": metrics_list[:25] if len(metrics_list) >= 25 else metrics_list,
        "all_time": all_metrics
    }
    
    aggregates = {}
    for window_name, window_metrics in windows.items():
        if not window_metrics:
            aggregates[window_name] = {}
            continue
        
        # Get corresponding stats
        window_stats = []
        for m in window_metrics:
            stats = db.query(PlayerGameStats).filter(
                PlayerGameStats.game_id == m.game_id,
                PlayerGameStats.player_id == player_id
            ).first()
            if stats:
                window_stats.append((m, stats))
        
        if not window_stats:
            aggregates[window_name] = {}
            continue
        
        # Compute means
        disruption_scores_100 = [float(m.disruption_score_100) for m, _ in window_stats]
        tov_forced_est_100 = []
        onball_pressure_est_100 = []
        offball_disruption_est_100 = []
        steals_100 = []
        blocks_100 = []
        fouls_100 = []
        total_possessions = 0.0
        
        for m, stats in window_stats:
            poss = float(m.possessions_est)
            if poss > 0:
                tov_forced_est_100.append((float(m.tov_forced_est) / poss) * 100.0)
                onball_pressure_est_100.append((float(m.onball_pressure_est) / poss) * 100.0)
                offball_disruption_est_100.append((float(m.offball_disruption_est) / poss) * 100.0)
                steals_100.append((float(stats.stl) / poss) * 100.0)
                blocks_100.append((float(stats.blk) / poss) * 100.0)
                fouls_100.append((float(stats.fouls) / poss) * 100.0)
            total_possessions += poss
        
        aggregates_dict = {
            "disruption_score_100": mean(disruption_scores_100),
            "tov_forced_est_100": mean(tov_forced_est_100),
            "onball_pressure_est_100": mean(onball_pressure_est_100),
            "offball_disruption_est_100": mean(offball_disruption_est_100),
            "steals_100": mean(steals_100),
            "blocks_100": mean(blocks_100),
            "fouls_100": mean(fouls_100),
            "possessions_est_total": total_possessions
        }
        
        # Add new matchup-based aggregates if available
        matchup_stop_100_list = []
        stocks_100_list = []
        def_disruption_100_list = []
        
        for m, _ in window_stats:
            if hasattr(m, 'matchup_stop_per100') and m.matchup_stop_per100 is not None:
                matchup_stop_100_list.append(float(m.matchup_stop_per100))
                if m.stocks_per100 is not None:
                    stocks_100_list.append(float(m.stocks_per100))
                if m.def_disruption_per100 is not None:
                    def_disruption_100_list.append(float(m.def_disruption_per100))
        
        if matchup_stop_100_list:
            aggregates_dict["matchup_stop_per100"] = mean(matchup_stop_100_list)
        if stocks_100_list:
            aggregates_dict["stocks_per100"] = mean(stocks_100_list)
        if def_disruption_100_list:
            aggregates_dict["def_disruption_per100"] = mean(def_disruption_100_list)
        
        aggregates[window_name] = aggregates_dict
    
    return {
        "per_game": per_game,
        "aggregates": aggregates
    }
