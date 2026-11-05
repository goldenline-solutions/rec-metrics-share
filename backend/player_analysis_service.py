"""
Player analysis service for generating AI-powered performance analysis.
Uses OpenAI to analyze player stats, builds, and game patterns.
"""
import os
import json
import hashlib
import statistics
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_
from models import (
    Player, PlayerGameStats, Game, GamePlayer, Build, BuildAttribute,
    NameClaim, Matchup
)
from name_utils import normalize_name
from openai_client import client, OPENAI_MODEL


# Key attributes to include in analysis (top ~20 most relevant)
KEY_ATTRIBUTES = [
    "Close Shot", "Driving Layup", "Driving Dunk", "Standing Dunk",
    "Mid-Range Shot", "Three-Point Shot", "Free Throw",
    "Pass Accuracy", "Ball Handle", "Speed With Ball",
    "Interior Defense", "Perimeter Defense", "Steal", "Block",
    "Offensive Rebound", "Defensive Rebound",
    "Speed", "Agility", "Strength", "Vertical"
]


def get_player_by_username(db: Session, username: str) -> Optional[Player]:
    """Get player by username (gamertag), handling case-insensitive matching."""
    normalized_username = normalize_name(username)
    
    # First check for verified claim
    verified_claim = db.query(NameClaim).filter(
        NameClaim.normalized_name == normalized_username,
        NameClaim.status == 'verified'
    ).first()
    
    if verified_claim:
        # Find players matching the claim's display name
        players = db.query(Player).filter(
            func.lower(Player.gamertag) == func.lower(verified_claim.display_name)
        ).all()
        
        if not players:
            # Try normalized matching
            all_players = db.query(Player).all()
            players = [p for p in all_players if normalize_name(p.gamertag) == normalized_username]
        
        return players[0] if players else None
    
    # Fall back to direct player lookup
    players = db.query(Player).filter(
        func.lower(Player.gamertag) == func.lower(username)
    ).all()
    
    if not players:
        return None
    
    # Prefer exact match
    for p in players:
        if normalize_name(p.gamertag) == normalized_username:
            return p
    
    return players[0]


def get_player_games_with_context(
    db: Session,
    player_id: str,
    last_n: Optional[int] = None
) -> List[Tuple[PlayerGameStats, Game, GamePlayer, Optional[Build]]]:
    """
    Get player's games with stats, game info, game_player info, and build (if assigned).
    Returns games ordered newest to oldest.
    """
    query = db.query(
        PlayerGameStats,
        Game,
        GamePlayer,
        Build
    ).join(
        Game, PlayerGameStats.game_id == Game.id
    ).join(
        GamePlayer,
        (GamePlayer.game_id == Game.id) & (GamePlayer.player_id == player_id)
    ).outerjoin(
        Build, GamePlayer.build_id == Build.id
    ).filter(
        PlayerGameStats.player_id == player_id
    ).order_by(
        desc(Game.created_at)
    )
    
    if last_n:
        query = query.limit(last_n)
    
    results = query.all()
    
    # Convert to list of tuples (stats, game, game_player, build)
    games_data = []
    for stats, game, game_player, build in results:
        games_data.append((stats, game, game_player, build))
    
    return games_data


def get_opponent_average_stats(
    db: Session,
    opponent_player_ids: List[str]
) -> Dict[str, Dict[str, Any]]:
    """
    Get average stats for opponents across all their games in the system.
    Returns dict mapping player_id -> average stats.
    """
    if not opponent_player_ids:
        return {}
    
    # Get all stats for these opponents
    all_opponent_stats = db.query(
        PlayerGameStats.player_id,
        func.avg(PlayerGameStats.pts).label('avg_pts'),
        func.avg(PlayerGameStats.reb).label('avg_reb'),
        func.avg(PlayerGameStats.ast).label('avg_ast'),
        func.avg(PlayerGameStats.stl).label('avg_stl'),
        func.avg(PlayerGameStats.blk).label('avg_blk'),
        func.avg(PlayerGameStats.tov).label('avg_tov'),
        func.avg(PlayerGameStats.fgm).label('avg_fgm'),
        func.avg(PlayerGameStats.fga).label('avg_fga'),
        func.avg(PlayerGameStats.tpm).label('avg_tpm'),
        func.avg(PlayerGameStats.tpa).label('avg_tpa'),
        func.avg(PlayerGameStats.ftm).label('avg_ftm'),
        func.avg(PlayerGameStats.fta).label('avg_fta'),
        func.count(PlayerGameStats.id).label('game_count')
    ).filter(
        PlayerGameStats.player_id.in_(opponent_player_ids)
    ).group_by(
        PlayerGameStats.player_id
    ).all()
    
    opponent_averages = {}
    for row in all_opponent_stats:
        player_id = row.player_id
        game_count = row.game_count
        
        if game_count < 3:  # Only include if they have at least 3 games (more reliable average)
            continue
        
        avg_fg_pct = round((row.avg_fgm / row.avg_fga * 100), 1) if row.avg_fga and row.avg_fga > 0 else 0
        avg_three_pct = round((row.avg_tpm / row.avg_tpa * 100), 1) if row.avg_tpa and row.avg_tpa > 0 else 0
        avg_ft_pct = round((row.avg_ftm / row.avg_fta * 100), 1) if row.avg_fta and row.avg_fta > 0 else 0
        
        opponent_averages[player_id] = {
            "game_count": game_count,
            "avg_pts": round(row.avg_pts, 1) if row.avg_pts else 0,
            "avg_reb": round(row.avg_reb, 1) if row.avg_reb else 0,
            "avg_ast": round(row.avg_ast, 1) if row.avg_ast else 0,
            "avg_stl": round(row.avg_stl, 1) if row.avg_stl else 0,
            "avg_blk": round(row.avg_blk, 1) if row.avg_blk else 0,
            "avg_tov": round(row.avg_tov, 1) if row.avg_tov else 0,
            "avg_fgm": round(row.avg_fgm, 1) if row.avg_fgm else 0,
            "avg_fga": round(row.avg_fga, 1) if row.avg_fga else 0,
            "avg_tpm": round(row.avg_tpm, 1) if row.avg_tpm else 0,
            "avg_tpa": round(row.avg_tpa, 1) if row.avg_tpa else 0,
            "avg_ftm": round(row.avg_ftm, 1) if row.avg_ftm else 0,
            "avg_fta": round(row.avg_fta, 1) if row.avg_fta else 0,
            "avg_fg_pct": avg_fg_pct,
            "avg_three_pct": avg_three_pct,
            "avg_ft_pct": avg_ft_pct
        }
    
    return opponent_averages


def get_defensive_matchup_stats(
    db: Session,
    player_id: str,
    game_ids: List[str]
) -> Dict[str, Any]:
    """
    Get defensive matchup statistics for the player.
    Returns aggregated stats showing how well they defend their position,
    including comparison to opponent averages.
    """
    if not game_ids:
        return {}
    
    # Get all matchups where this player was the defender
    matchups = db.query(
        Matchup,
        PlayerGameStats
    ).join(
        PlayerGameStats,
        (PlayerGameStats.game_id == Matchup.game_id) &
        (PlayerGameStats.player_id == Matchup.offender_player_id)
    ).filter(
        Matchup.defender_player_id == player_id,
        Matchup.game_id.in_(game_ids)
    ).all()
    
    if not matchups:
        return {}
    
    # Collect opponent player IDs to get their averages
    opponent_player_ids = list(set([matchup.offender_player_id for matchup, _ in matchups]))
    opponent_averages = get_opponent_average_stats(db, opponent_player_ids)
    
    # Aggregate stats
    total_matchups = len(matchups)
    opponent_pts = 0
    opponent_fgm = 0
    opponent_fga = 0
    opponent_tpm = 0
    opponent_tpa = 0
    opponent_ast = 0
    opponent_tov = 0
    opponent_reb = 0
    
    # For comparison against averages
    matchups_with_averages = 0
    pts_vs_average = 0
    fg_pct_vs_average = 0
    three_pct_vs_average = 0
    ast_vs_average = 0
    tov_vs_average = 0
    
    # Position breakdown
    position_matchups = {}
    
    for matchup, opponent_stats in matchups:
        pos = matchup.defender_position.value if hasattr(matchup.defender_position, 'value') else str(matchup.defender_position)
        opponent_id = matchup.offender_player_id
        
        if pos not in position_matchups:
            position_matchups[pos] = {
                "count": 0,
                "opponent_pts": 0,
                "opponent_fgm": 0,
                "opponent_fga": 0,
                "opponent_tpm": 0,
                "opponent_tpa": 0,
                "opponent_ast": 0,
                "opponent_tov": 0,
                "opponent_reb": 0
            }
        
        position_matchups[pos]["count"] += 1
        position_matchups[pos]["opponent_pts"] += opponent_stats.pts
        position_matchups[pos]["opponent_fgm"] += opponent_stats.fgm
        position_matchups[pos]["opponent_fga"] += opponent_stats.fga
        position_matchups[pos]["opponent_tpm"] += opponent_stats.tpm
        position_matchups[pos]["opponent_tpa"] += opponent_stats.tpa
        position_matchups[pos]["opponent_ast"] += opponent_stats.ast
        position_matchups[pos]["opponent_tov"] += opponent_stats.tov
        position_matchups[pos]["opponent_reb"] += opponent_stats.reb
        
        opponent_pts += opponent_stats.pts
        opponent_fgm += opponent_stats.fgm
        opponent_fga += opponent_stats.fga
        opponent_tpm += opponent_stats.tpm
        opponent_tpa += opponent_stats.tpa
        opponent_ast += opponent_stats.ast
        opponent_tov += opponent_stats.tov
        opponent_reb += opponent_stats.reb
        
        # Compare against opponent's average if available
        if opponent_id in opponent_averages:
            matchups_with_averages += 1
            opp_avg = opponent_averages[opponent_id]
            
            # Calculate differences
            pts_vs_average += (opponent_stats.pts - opp_avg["avg_pts"])
            
            opp_fg_pct = (opponent_stats.fgm / opponent_stats.fga * 100) if opponent_stats.fga > 0 else 0
            fg_pct_vs_average += (opp_fg_pct - opp_avg["avg_fg_pct"])
            
            opp_three_pct = (opponent_stats.tpm / opponent_stats.tpa * 100) if opponent_stats.tpa > 0 else 0
            three_pct_vs_average += (opp_three_pct - opp_avg["avg_three_pct"])
            
            ast_vs_average += (opponent_stats.ast - opp_avg["avg_ast"])
            tov_vs_average += (opponent_stats.tov - opp_avg["avg_tov"])
    
    # Calculate averages
    avg_opponent_pts = round(opponent_pts / total_matchups, 1) if total_matchups > 0 else 0
    opponent_fg_pct = round((opponent_fgm / opponent_fga * 100), 1) if opponent_fga > 0 else 0
    opponent_three_pct = round((opponent_tpm / opponent_tpa * 100), 1) if opponent_tpa > 0 else 0
    
    # Calculate per-position averages
    position_averages = {}
    for pos, data in position_matchups.items():
        if data["count"] > 0:
            position_averages[pos] = {
                "matchups": data["count"],
                "avg_opponent_pts": round(data["opponent_pts"] / data["count"], 1),
                "opponent_fg_pct": round((data["opponent_fgm"] / data["opponent_fga"] * 100), 1) if data["opponent_fga"] > 0 else 0,
                "opponent_three_pct": round((data["opponent_tpm"] / data["opponent_tpa"] * 100), 1) if data["opponent_tpa"] > 0 else 0,
                "avg_opponent_ast": round(data["opponent_ast"] / data["count"], 1),
                "avg_opponent_tov": round(data["opponent_tov"] / data["count"], 1),
                "avg_opponent_reb": round(data["opponent_reb"] / data["count"], 1)
            }
    
    # Calculate comparison to opponent averages
    comparison_to_averages = {}
    if matchups_with_averages > 0:
        comparison_to_averages = {
            "matchups_with_opponent_data": matchups_with_averages,
            "pts_vs_opponent_avg": round(pts_vs_average / matchups_with_averages, 1),
            "fg_pct_vs_opponent_avg": round(fg_pct_vs_average / matchups_with_averages, 1),
            "three_pct_vs_opponent_avg": round(three_pct_vs_average / matchups_with_averages, 1),
            "ast_vs_opponent_avg": round(ast_vs_average / matchups_with_averages, 1),
            "tov_vs_opponent_avg": round(tov_vs_average / matchups_with_averages, 1)
        }
        # Note: Negative values mean opponent performed WORSE than average (good defense)
        # Positive values mean opponent performed BETTER than average (poor defense)
    
    return {
        "total_matchups": total_matchups,
        "avg_opponent_pts": avg_opponent_pts,
        "opponent_fg_pct": opponent_fg_pct,
        "opponent_three_pct": opponent_three_pct,
        "avg_opponent_ast": round(opponent_ast / total_matchups, 1) if total_matchups > 0 else 0,
        "avg_opponent_tov": round(opponent_tov / total_matchups, 1) if total_matchups > 0 else 0,
        "avg_opponent_reb": round(opponent_reb / total_matchups, 1) if total_matchups > 0 else 0,
        "by_position": position_averages,
        "vs_opponent_averages": comparison_to_averages
    }


def get_other_players_in_games(
    db: Session,
    game_ids: List[str],
    exclude_player_id: str
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get all other players' stats for the given games.
    Returns dict mapping game_id -> list of player summaries.
    """
    if not game_ids:
        return {}
    
    # Get all game_players for these games, excluding the target player
    game_players = db.query(
        GamePlayer,
        Player,
        PlayerGameStats
    ).join(
        Player, GamePlayer.player_id == Player.id
    ).join(
        PlayerGameStats,
        (PlayerGameStats.game_id == GamePlayer.game_id) &
        (PlayerGameStats.player_id == GamePlayer.player_id)
    ).filter(
        GamePlayer.game_id.in_(game_ids),
        GamePlayer.player_id != exclude_player_id
    ).all()
    
    # Group by game_id
    players_by_game = {}
    for gp, player, stats in game_players:
        game_id = gp.game_id
        if game_id not in players_by_game:
            players_by_game[game_id] = []
        
        players_by_game[game_id].append({
            "username": player.gamertag,
            "team_side": gp.team_side.value if hasattr(gp.team_side, 'value') else str(gp.team_side),
            "position": gp.position.value if hasattr(gp.position, 'value') else str(gp.position),
            "pts": stats.pts,
            "reb": stats.reb,
            "ast": stats.ast,
            "stl": stats.stl,
            "blk": stats.blk,
            "tov": stats.tov,
            "fgm": stats.fgm,
            "fga": stats.fga,
            "tpm": stats.tpm,
            "tpa": stats.tpa
        })
    
    return players_by_game


def get_build_attributes_summary(db: Session, build: Build) -> Dict[str, Any]:
    """Get summary of build attributes, including only key attributes."""
    if not build:
        return None
    
    # Get all attributes
    all_attrs = db.query(BuildAttribute).filter(
        BuildAttribute.build_id == build.id
    ).order_by(BuildAttribute.display_order).all()
    
    # Filter to key attributes
    key_attrs = {}
    for attr in all_attrs:
        attr_name = attr.attribute_name
        # Check if this attribute matches any key attribute (case-insensitive, partial match)
        for key_attr in KEY_ATTRIBUTES:
            if key_attr.lower() in attr_name.lower() or attr_name.lower() in key_attr.lower():
                key_attrs[attr_name] = {
                    "name": attr_name,
                    "category": attr.category,
                    "current": attr.value_current,
                    "max": attr.value_max
                }
                break
    
    # If we have fewer than 10 key attributes, include top attributes by value
    if len(key_attrs) < 10:
        # Sort remaining by current value descending
        remaining = [
            {
                "name": attr.attribute_name,
                "category": attr.category,
                "current": attr.value_current,
                "max": attr.value_max
            }
            for attr in all_attrs
            if attr.attribute_name not in key_attrs
        ]
        remaining.sort(key=lambda x: x["current"], reverse=True)
        
        # Add top remaining until we have 20 total
        for attr_data in remaining[:20 - len(key_attrs)]:
            key_attrs[attr_data["name"]] = attr_data
    
    return {
        "build_name": build.display_name,
        "position": build.build_position,
        "archetype": build.archetype,
        "physicals": {
            "height": build.height,
            "weight_lbs": build.weight_lbs,
            "wingspan": build.wingspan
        },
        "overall": {
            "current": build.overall_current,
            "max": build.overall_max
        },
        "key_attributes": list(key_attrs.values())[:20]  # Limit to 20
    }


def calculate_derived_metrics(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer, Optional[Build]]]) -> Dict[str, Any]:
    """
    Calculate derived metrics (eFG%, AST/TO, pass-first index, usage proxy, etc.)
    for overall and last_10 games.
    """
    if not games_data:
        return {}
    
    def compute_metrics_for_games(games_subset: List[Tuple[PlayerGameStats, Game, GamePlayer, Optional[Build]]]) -> Dict[str, Any]:
        if not games_subset:
            return {}
        
        metrics = {}
        totals = {"fgm": 0, "fga": 0, "tpm": 0, "tpa": 0, "ast": 0, "tov": 0, "pts": 0, "reb": 0, "stl": 0, "blk": 0, "fta": 0}
        
        for stats, _, _, _ in games_subset:
            totals["fgm"] += stats.fgm or 0
            totals["fga"] += stats.fga or 0
            totals["tpm"] += stats.tpm or 0
            totals["tpa"] += stats.tpa or 0
            totals["ast"] += stats.ast or 0
            totals["tov"] += stats.tov or 0
            totals["pts"] += stats.pts or 0
            totals["reb"] += stats.reb or 0
            totals["stl"] += stats.stl or 0
            totals["blk"] += stats.blk or 0
            totals["fta"] += stats.fta or 0
        
        n = len(games_subset)
        if n == 0:
            return {}
        
        # Basic shooting metrics
        if totals["fga"] > 0:
            metrics["fg_pct"] = round((totals["fgm"] / totals["fga"]) * 100, 1)
            # eFG% = (FGM + 0.5*3PM) / FGA
            if totals["tpm"] is not None:
                metrics["efg_pct"] = round(((totals["fgm"] + 0.5 * totals["tpm"]) / totals["fga"]) * 100, 1)
        else:
            metrics["fg_pct"] = 0.0
            metrics["efg_pct"] = 0.0
        
        if totals["tpa"] > 0:
            metrics["three_pct"] = round((totals["tpm"] / totals["tpa"]) * 100, 1)
        else:
            metrics["three_pct"] = 0.0
        
        # AST/TO ratio
        if totals["tov"] > 0:
            metrics["ast_to"] = round(totals["ast"] / totals["tov"], 2)
        else:
            metrics["ast_to"] = totals["ast"] if totals["ast"] > 0 else 0.0
        
        # Pass-first index = AST / (FGA + AST), guard against 0
        denominator = totals["fga"] + totals["ast"]
        if denominator > 0:
            metrics["pass_first_index"] = round((totals["ast"] / denominator) * 100, 1)
        else:
            metrics["pass_first_index"] = 0.0
        
        # Usage proxy = FGA + 0.44*FTA + TOV (if FTA exists)
        if totals["fta"] is not None and totals["fta"] > 0:
            metrics["usage_proxy"] = round(totals["fga"] + 0.44 * totals["fta"] + totals["tov"], 1)
        else:
            metrics["usage_proxy"] = round(totals["fga"] + totals["tov"], 1)
        
        # Points per shot
        if totals["fga"] > 0:
            metrics["points_per_shot"] = round(totals["pts"] / totals["fga"], 2)
        else:
            metrics["points_per_shot"] = 0.0
        
        # Involvement proxy = PTS + AST*1.5 + REB*0.7 + STL*1.5 + BLK*1.2 - TOV*1.3
        metrics["involvement_proxy"] = round(
            totals["pts"] + totals["ast"] * 1.5 + totals["reb"] * 0.7 + 
            totals["stl"] * 1.5 + totals["blk"] * 1.2 - totals["tov"] * 1.3, 
            1
        )
        
        # Per-game averages for consistency calculation
        metrics["avg_pts"] = round(totals["pts"] / n, 1)
        metrics["avg_ast"] = round(totals["ast"] / n, 1)
        metrics["avg_reb"] = round(totals["reb"] / n, 1)
        metrics["avg_fga"] = round(totals["fga"] / n, 1)
        metrics["avg_ast_to"] = metrics["ast_to"]
        metrics["avg_efg_pct"] = metrics["efg_pct"]
        
        return metrics
    
    # Overall metrics
    overall_metrics = compute_metrics_for_games(games_data)
    
    # Last 10 metrics
    last_10 = games_data[:10] if len(games_data) >= 10 else games_data
    last_10_metrics = compute_metrics_for_games(last_10)
    
    # Consistency stats (mean + stddev for PTS/AST/REB and shooting efficiency)
    consistency = {}
    if len(games_data) >= 3:
        pts_values = [stats.pts for stats, _, _, _ in games_data]
        ast_values = [stats.ast for stats, _, _, _ in games_data]
        reb_values = [stats.reb for stats, _, _, _ in games_data]
        
        consistency["pts"] = {
            "mean": round(statistics.mean(pts_values), 1),
            "stddev": round(statistics.stdev(pts_values) if len(pts_values) > 1 else 0, 1)
        }
        consistency["ast"] = {
            "mean": round(statistics.mean(ast_values), 1),
            "stddev": round(statistics.stdev(ast_values) if len(ast_values) > 1 else 0, 1)
        }
        consistency["reb"] = {
            "mean": round(statistics.mean(reb_values), 1),
            "stddev": round(statistics.stdev(reb_values) if len(reb_values) > 1 else 0, 1)
        }
        
        # Shooting efficiency consistency (eFG% per game)
        efg_values = []
        for stats, _, _, _ in games_data:
            if stats.fga and stats.fga > 0:
                fgm = stats.fgm or 0
                tpm = stats.tpm or 0
                efg = ((fgm + 0.5 * tpm) / stats.fga) * 100
                efg_values.append(efg)
        
        if len(efg_values) >= 3:
            consistency["efg_pct"] = {
                "mean": round(statistics.mean(efg_values), 1),
                "stddev": round(statistics.stdev(efg_values) if len(efg_values) > 1 else 0, 1)
            }
    
    # Floor/ceiling games (bottom 20% and top 20% by involvement proxy)
    floor_ceiling = {}
    if len(games_data) >= 5:
        involvement_scores = []
        for stats, game, game_player, build in games_data:
            involvement = (
                stats.pts + stats.ast * 1.5 + stats.reb * 0.7 + 
                stats.stl * 1.5 + stats.blk * 1.2 - stats.tov * 1.3
            )
            involvement_scores.append((involvement, stats, game, game_player))
        
        involvement_scores.sort(key=lambda x: x[0])
        bottom_20_pct = int(len(involvement_scores) * 0.2)
        top_20_pct = int(len(involvement_scores) * 0.2)
        
        floor_games = involvement_scores[:max(1, bottom_20_pct)]
        ceiling_games = involvement_scores[-max(1, top_20_pct):]
        
        # Calculate averages for floor vs ceiling
        floor_avg = compute_metrics_for_games([(s, g, gp, None) for _, s, g, gp in floor_games])
        ceiling_avg = compute_metrics_for_games([(s, g, gp, None) for _, s, g, gp in ceiling_games])
        
        floor_ceiling = {
            "floor_games_count": len(floor_games),
            "ceiling_games_count": len(ceiling_games),
            "floor_avg": floor_avg,
            "ceiling_avg": ceiling_avg,
            "key_differences": {}
        }
        
        # Identify key differences
        if floor_avg and ceiling_avg:
            for key in ["pts", "ast", "reb", "efg_pct", "ast_to", "tov"]:
                if key in floor_avg and key in ceiling_avg:
                    diff = ceiling_avg[key] - floor_avg[key]
                    if abs(diff) > 0.1:  # Only include meaningful differences
                        floor_ceiling["key_differences"][key] = round(diff, 1)
    
    return {
        "overall": overall_metrics,
        "last_10": last_10_metrics,
        "consistency": consistency,
        "floor_ceiling": floor_ceiling
    }


def calculate_aggregates(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer, Optional[Build]]]) -> Dict[str, Any]:
    """Calculate aggregate statistics from games."""
    if not games_data:
        return {
            "totals": {},
            "per_game_averages": {},
            "games_count": 0
        }
    
    totals = {
        "pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0,
        "tov": 0, "fgm": 0, "fga": 0, "tpm": 0, "tpa": 0,
        "ftm": 0, "fta": 0
    }
    
    for stats, game, game_player, build in games_data:
        totals["pts"] += stats.pts
        totals["reb"] += stats.reb
        totals["ast"] += stats.ast
        totals["stl"] += stats.stl
        totals["blk"] += stats.blk
        totals["tov"] += stats.tov
        totals["fgm"] += stats.fgm
        totals["fga"] += stats.fga
        totals["tpm"] += stats.tpm
        totals["tpa"] += stats.tpa
        totals["ftm"] += stats.ftm
        totals["fta"] += stats.fta
    
    games_count = len(games_data)
    averages = {
        k: round(v / games_count, 1) if games_count > 0 else 0.0
        for k, v in totals.items()
    }
    
    # Calculate percentages
    if totals["fga"] > 0:
        averages["fg_pct"] = round((totals["fgm"] / totals["fga"]) * 100, 1)
    else:
        averages["fg_pct"] = 0.0
    
    if totals["tpa"] > 0:
        averages["three_pct"] = round((totals["tpm"] / totals["tpa"]) * 100, 1)
    else:
        averages["three_pct"] = 0.0
    
    if totals["fta"] > 0:
        averages["ft_pct"] = round((totals["ftm"] / totals["fta"]) * 100, 1)
    else:
        averages["ft_pct"] = 0.0
    
    return {
        "totals": totals,
        "per_game_averages": averages,
        "games_count": games_count
    }


def calculate_teammate_synergy(
    db: Session,
    player_id: str,
    games_data: List[Tuple[PlayerGameStats, Game, GamePlayer, Optional[Build]]],
    other_players_by_game: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, Any]:
    """
    Calculate teammate synergy (top 8 teammates by shared games, min sample >=5).
    For each teammate: shared_games, my_avg_with, my_avg_without, deltas.
    """
    if not games_data or not other_players_by_game:
        return {}
    
    # Build teammate frequency map
    teammate_counts = {}  # teammate_username -> list of game_ids where they played together
    game_ids = [game.id for _, game, _, _ in games_data]
    
    for stats, game, game_player, _ in games_data:
        game_id = game.id
        other_players = other_players_by_game.get(game_id, [])
        team_side = game_player.team_side.value if hasattr(game_player.team_side, 'value') else str(game_player.team_side)
        
        teammates = [p for p in other_players if p["team_side"] == team_side]
        
        for teammate in teammates:
            username = teammate["username"]
            if username not in teammate_counts:
                teammate_counts[username] = []
            teammate_counts[username].append(game_id)
    
    # Filter to teammates with >=5 shared games
    valid_teammates = {username: game_ids for username, game_ids in teammate_counts.items() if len(game_ids) >= 5}
    
    if not valid_teammates:
        return {}
    
    # Sort by shared games count and take top 8
    sorted_teammates = sorted(valid_teammates.items(), key=lambda x: len(x[1]), reverse=True)[:8]
    
    synergy_results = []
    
    for teammate_username, shared_game_ids in sorted_teammates:
        # Get games WITH this teammate
        games_with = [
            (stats, game, game_player, build)
            for stats, game, game_player, build in games_data
            if game.id in shared_game_ids
        ]
        
        # Get games WITHOUT this teammate (from the same dataset)
        games_without = [
            (stats, game, game_player, build)
            for stats, game, game_player, build in games_data
            if game.id not in shared_game_ids
        ]
        
        if not games_with or not games_without:
            continue
        
        # Calculate averages
        def compute_avg_metrics(games_subset):
            if not games_subset:
                return {}
            totals = {"pts": 0, "ast": 0, "reb": 0, "tov": 0, "fgm": 0, "fga": 0, "tpm": 0, "tpa": 0}
            n = len(games_subset)
            for stats, _, _, _ in games_subset:
                totals["pts"] += stats.pts or 0
                totals["ast"] += stats.ast or 0
                totals["reb"] += stats.reb or 0
                totals["tov"] += stats.tov or 0
                totals["fgm"] += stats.fgm or 0
                totals["fga"] += stats.fga or 0
                totals["tpm"] += stats.tpm or 0
                totals["tpa"] += stats.tpa or 0
            
            metrics = {
                "pts": round(totals["pts"] / n, 1) if n > 0 else 0,
                "ast": round(totals["ast"] / n, 1) if n > 0 else 0,
                "reb": round(totals["reb"] / n, 1) if n > 0 else 0,
                "tov": round(totals["tov"] / n, 1) if n > 0 else 0,
            }
            
            if totals["fga"] > 0:
                metrics["fg_pct"] = round((totals["fgm"] / totals["fga"]) * 100, 1)
                if totals["tpm"] is not None:
                    metrics["efg_pct"] = round(((totals["fgm"] + 0.5 * totals["tpm"]) / totals["fga"]) * 100, 1)
            else:
                metrics["fg_pct"] = 0.0
                metrics["efg_pct"] = 0.0
            
            # Involvement proxy
            involvement = 0
            for stats, _, _, _ in games_subset:
                involvement += (
                    (stats.pts or 0) + (stats.ast or 0) * 1.5 + (stats.reb or 0) * 0.7 + 
                    (stats.stl or 0) * 1.5 + (stats.blk or 0) * 1.2 - (stats.tov or 0) * 1.3
                )
            metrics["involvement_proxy"] = round(involvement / n, 1) if n > 0 else 0
            
            return metrics
        
        avg_with = compute_avg_metrics(games_with)
        avg_without = compute_avg_metrics(games_without)
        
        # Calculate deltas
        deltas = {}
        for key in ["pts", "ast", "reb", "tov", "fg_pct", "efg_pct", "involvement_proxy"]:
            if key in avg_with and key in avg_without:
                deltas[key] = round(avg_with[key] - avg_without[key], 1)
        
        synergy_results.append({
            "teammate_username": teammate_username,
            "shared_games": len(shared_game_ids),
            "my_avg_with": avg_with,
            "my_avg_without": avg_without,
            "deltas": deltas
        })
    
    # Rank by strongest positive and negative impact (by involvement proxy delta)
    if synergy_results:
        synergy_results.sort(key=lambda x: x["deltas"].get("involvement_proxy", 0), reverse=True)
        top_positive = [s for s in synergy_results if s["deltas"].get("involvement_proxy", 0) > 0][:3]
        top_negative = [s for s in synergy_results if s["deltas"].get("involvement_proxy", 0) < 0][:3]
        top_negative.reverse()  # Most negative first
        
        return {
            "all_teammates": synergy_results,
            "top_positive_impact": top_positive,
            "top_negative_impact": top_negative
        }
    
    return {}


def calculate_opponent_difficulty(
    db: Session,
    player_id: str,
    games_data: List[Tuple[PlayerGameStats, Game, GamePlayer, Optional[Build]]],
    other_players_by_game: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, Any]:
    """
    Calculate opponent/matchup difficulty (top 8 opponents, min sample >=5).
    Compare my performance vs them to my overall (delta metrics).
    """
    if not games_data or not other_players_by_game:
        return {}
    
    # Build opponent frequency map
    opponent_counts = {}  # opponent_username -> list of game_ids where we faced them
    
    for stats, game, game_player, _ in games_data:
        game_id = game.id
        other_players = other_players_by_game.get(game_id, [])
        team_side = game_player.team_side.value if hasattr(game_player.team_side, 'value') else str(game_player.team_side)
        
        opponents = [p for p in other_players if p["team_side"] != team_side]
        
        for opponent in opponents:
            username = opponent["username"]
            if username not in opponent_counts:
                opponent_counts[username] = []
            opponent_counts[username].append(game_id)
    
    # Filter to opponents with >=5 games
    valid_opponents = {username: game_ids for username, game_ids in opponent_counts.items() if len(game_ids) >= 5}
    
    if not valid_opponents:
        return {}
    
    # Sort by shared games count and take top 8
    sorted_opponents = sorted(valid_opponents.items(), key=lambda x: len(x[1]), reverse=True)[:8]
    
    # Calculate overall averages for comparison
    overall_aggregates = calculate_aggregates(games_data)
    overall_avg = overall_aggregates.get("per_game_averages", {})
    
    opponent_results = []
    
    for opponent_username, shared_game_ids in sorted_opponents:
        # Get games vs this opponent
        games_vs = [
            (stats, game, game_player, build)
            for stats, game, game_player, build in games_data
            if game.id in shared_game_ids
        ]
        
        if not games_vs:
            continue
        
        # Calculate my averages vs this opponent
        totals = {"pts": 0, "ast": 0, "reb": 0, "tov": 0, "fgm": 0, "fga": 0, "tpm": 0, "tpa": 0}
        n = len(games_vs)
        
        for stats, _, _, _ in games_vs:
            totals["pts"] += stats.pts or 0
            totals["ast"] += stats.ast or 0
            totals["reb"] += stats.reb or 0
            totals["tov"] += stats.tov or 0
            totals["fgm"] += stats.fgm or 0
            totals["fga"] += stats.fga or 0
            totals["tpm"] += stats.tpm or 0
            totals["tpa"] += stats.tpa or 0
        
        vs_avg = {
            "pts": round(totals["pts"] / n, 1) if n > 0 else 0,
            "ast": round(totals["ast"] / n, 1) if n > 0 else 0,
            "reb": round(totals["reb"] / n, 1) if n > 0 else 0,
            "tov": round(totals["tov"] / n, 1) if n > 0 else 0,
        }
        
        if totals["fga"] > 0:
            vs_avg["fg_pct"] = round((totals["fgm"] / totals["fga"]) * 100, 1)
            if totals["tpm"] is not None:
                vs_avg["efg_pct"] = round(((totals["fgm"] + 0.5 * totals["tpm"]) / totals["fga"]) * 100, 1)
        else:
            vs_avg["fg_pct"] = 0.0
            vs_avg["efg_pct"] = 0.0
        
        # Calculate deltas vs overall
        deltas = {}
        for key in ["pts", "ast", "reb", "tov", "fg_pct", "efg_pct"]:
            if key in vs_avg and key in overall_avg:
                deltas[key] = round(vs_avg[key] - overall_avg[key], 1)
        
        opponent_results.append({
            "opponent_username": opponent_username,
            "games_vs": n,
            "my_avg_vs_them": vs_avg,
            "deltas_vs_overall": deltas
        })
    
    # Get defensive matchup stats if available
    game_ids = [game.id for _, game, _, _ in games_data]
    defensive_matchups = get_defensive_matchup_stats(db, player_id, game_ids)
    
    return {
        "opponents": opponent_results,
        "defensive_matchup_stats": defensive_matchups,
        "sample_size_note": f"Analysis based on {len(games_data)} games. Opponent data reliability depends on sample size."
    }


def determine_win(game: Game, game_player: GamePlayer) -> bool:
    """Determine if player's team won."""
    if game_player.team_side == "HOME":
        return game.home_score > game.away_score
    else:
        return game.away_score > game.home_score


def build_player_analysis_payload(
    db: Session,
    username: str,
    last_n: Optional[int] = None
) -> Dict[str, Any]:
    """
    Build the analysis payload for a player.
    
    Args:
        db: Database session
        username: Player username (gamertag)
        last_n: Optional limit on number of games to analyze (defaults to 25)
    
    Returns:
        Dictionary containing structured payload for OpenAI analysis
    """
    if last_n is None:
        last_n = 25
    
    # Get player
    player = get_player_by_username(db, username)
    if not player:
        raise ValueError(f"Player '{username}' not found")
    
    # Get player's games
    games_data = get_player_games_with_context(db, player.id, last_n)
    
    if not games_data:
        return {
            "meta": {
                "username": username,
                "total_games": 0,
                "primary_position": None,
                "position_distribution": {},
                "date_range": None,
                "build_coverage": {
                    "games_with_build": 0,
                    "games_without_build": 0,
                    "coverage_pct": 0.0
                },
                "data_quality": []
            },
            "per_game": [],
            "aggregates": {
                "my_totals": {},
                "per_game_averages": {},
                "splits": {},
                "trends": {}
            },
            "defensive_matchups": {}
        }
    
    # Extract game IDs for fetching other players
    game_ids = [game.id for _, game, _, _ in games_data]
    
    # Get most common position played
    position_counts = {}
    for _, _, game_player, _ in games_data:
        pos = game_player.position.value if hasattr(game_player.position, 'value') else str(game_player.position)
        position_counts[pos] = position_counts.get(pos, 0) + 1
    primary_position = max(position_counts.items(), key=lambda x: x[1])[0] if position_counts else None
    
    # Get defensive matchup statistics
    defensive_matchups = get_defensive_matchup_stats(db, player.id, game_ids)
    
    # Get other players in these games
    other_players_by_game = get_other_players_in_games(db, game_ids, player.id)
    
    # Build per-game data
    per_game = []
    games_with_build = 0
    games_without_build = 0
    date_strings = []
    
    for stats, game, game_player, build in games_data:
        # Determine win/loss
        won = determine_win(game, game_player)
        
        # Get teammates and opponents
        other_players = other_players_by_game.get(game.id, [])
        teammates = [
            p for p in other_players
            if p["team_side"] == (game_player.team_side.value if hasattr(game_player.team_side, 'value') else str(game_player.team_side))
        ]
        opponents = [
            p for p in other_players
            if p["team_side"] != (game_player.team_side.value if hasattr(game_player.team_side, 'value') else str(game_player.team_side))
        ]
        
        # Summarize teammates/opponents (keep it compact)
        teammate_summaries = [
            {
                "username": p["username"],
                "pts": p["pts"],
                "ast": p["ast"],
                "reb": p["reb"]
            }
            for p in teammates[:5]  # Top 5 by points
        ]
        opponent_summaries = [
            {
                "username": p["username"],
                "pts": p["pts"],
                "ast": p["ast"],
                "reb": p["reb"]
            }
            for p in opponents[:5]  # Top 5 by points
        ]
        
        # Build info
        build_used = None
        if build:
            games_with_build += 1
            build_used = get_build_attributes_summary(db, build)
        else:
            games_without_build += 1
        
        # Game date
        if game.created_at:
            date_strings.append(game.created_at)
        
        per_game.append({
            "game_id": game.id,
            "played_at": game.created_at,
            "opponent_team": "AWAY" if game_player.team_side == "HOME" else "HOME",
            "won": won,
            "my_stats": {
                "pts": stats.pts,
                "reb": stats.reb,
                "ast": stats.ast,
                "stl": stats.stl,
                "blk": stats.blk,
                "tov": stats.tov,
                "fgm": stats.fgm,
                "fga": stats.fga,
                "tpm": stats.tpm,
                "tpa": stats.tpa,
                "ftm": stats.ftm,
                "fta": stats.fta
            },
            "team_context": {
                "teammate_summaries": teammate_summaries,
                "opponent_summaries": opponent_summaries
            },
            "build_used": build_used
        })
    
    # Calculate aggregates
    aggregates = calculate_aggregates(games_data)
    
    # Calculate derived metrics (NEW)
    derived_metrics = calculate_derived_metrics(games_data)
    
    # Calculate splits
    splits = calculate_splits(games_data)
    
    # Calculate trends
    trends = calculate_trends(games_data)
    
    # Calculate teammate synergy (NEW)
    teammate_synergy = calculate_teammate_synergy(db, player.id, games_data, other_players_by_game)
    
    # Calculate opponent difficulty (NEW)
    opponent_difficulty = calculate_opponent_difficulty(db, player.id, games_data, other_players_by_game)
    
    # Calculate improved build impact (NEW)
    build_impact = calculate_build_impact(db, games_data)
    
    # Date range
    date_range = None
    if date_strings:
        date_range = {
            "min": min(date_strings),
            "max": max(date_strings)
        }
    
    # Build coverage
    total_games = len(games_data)
    coverage_pct = round((games_with_build / total_games * 100), 1) if total_games > 0 else 0.0
    
    # Data quality flags
    data_quality = []
    if games_without_build > 0:
        data_quality.append(f"{games_without_build} games missing build data")
    
    # Check for suspicious zeros
    zero_fga_count = sum(1 for stats, _, _, _ in games_data if stats.fga == 0)
    if zero_fga_count > total_games * 0.5:  # More than 50% with 0 FGA
        data_quality.append(f"{zero_fga_count} games with 0 field goal attempts (may indicate incomplete data)")
    
    # Build initial payload
    payload = {
        "meta": {
            "username": username,
            "total_games": total_games,
            "primary_position": primary_position,
            "position_distribution": position_counts,
            "date_range": date_range,
            "build_coverage": {
                "games_with_build": games_with_build,
                "games_without_build": games_without_build,
                "coverage_pct": coverage_pct
            },
            "data_quality": data_quality
        },
        "per_game": per_game,
        "aggregates": {
            "my_totals": aggregates["totals"],
            "per_game_averages": aggregates["per_game_averages"],
            "splits": splits,
            "trends": trends
        },
        "defensive_matchups": defensive_matchups,
        "derived_metrics": derived_metrics,
        "teammate_synergy": teammate_synergy,
        "opponent_difficulty": opponent_difficulty,
        "build_impact": build_impact
    }
    
    # Generate claim candidates (NEW - CRITICAL)
    claim_candidates = generate_claim_candidates(
        payload, derived_metrics, teammate_synergy, opponent_difficulty, build_impact
    )
    payload["claim_candidates"] = claim_candidates
    
    return payload


def calculate_build_impact(
    db: Session,
    games_data: List[Tuple[PlayerGameStats, Game, GamePlayer, Optional[Build]]]
) -> Dict[str, Any]:
    """
    Improved build impact analysis.
    For each build_name with >=5 games:
    - my metrics averages (PTS, AST/TO, eFG/FG, involvement proxy)
    - build_signature: top_6 attributes by current_value, bottom_3 among key categories
    - with_build vs without_build deltas
    """
    if not games_data:
        return {}
    
    # Group by build_name
    builds_by_name = {}
    for stats, game, game_player, build in games_data:
        if build:
            build_name = build.display_name
            if build_name not in builds_by_name:
                builds_by_name[build_name] = []
            builds_by_name[build_name].append((stats, game, game_player, build))
    
    build_impact_results = []
    
    for build_name, build_games in builds_by_name.items():
        if len(build_games) < 5:  # Min 5 games
            continue
        
        # Get a representative build (first one)
        _, _, _, representative_build = build_games[0]
        
        # Calculate my metrics with this build
        build_aggregates = calculate_aggregates(build_games)
        build_avg = build_aggregates["per_game_averages"]
        
        # Calculate derived metrics for this build
        build_derived = calculate_derived_metrics(build_games)
        build_overall = build_derived.get("overall", {})
        
        # Get build signature (top 6 attributes by current_value, bottom 3 among key categories)
        build_signature = {}
        if representative_build:
            all_attrs = db.query(BuildAttribute).filter(
                BuildAttribute.build_id == representative_build.id
            ).order_by(BuildAttribute.display_order).all()
            
            # Top 6 by current_value
            sorted_by_value = sorted(all_attrs, key=lambda a: a.value_current, reverse=True)
            build_signature["top_6_attributes"] = [
                {
                    "name": attr.attribute_name,
                    "category": attr.category,
                    "current": attr.value_current,
                    "max": attr.value_max
                }
                for attr in sorted_by_value[:6]
            ]
            
            # Bottom 3 among key categories (if categories exist)
            key_categories = ["Finishing", "Shooting", "Playmaking", "Defense", "Physicals"]
            bottom_by_category = {}
            for category in key_categories:
                category_attrs = [a for a in all_attrs if a.category == category]
                if category_attrs:
                    sorted_cat = sorted(category_attrs, key=lambda a: a.value_current)
                    bottom_by_category[category] = [
                        {
                            "name": attr.attribute_name,
                            "current": attr.value_current,
                            "max": attr.value_max
                        }
                        for attr in sorted_cat[:3]
                    ]
            build_signature["bottom_3_by_category"] = bottom_by_category
        
        # Calculate with_build vs without_build deltas
        without_build_games = [g for g in games_data if g[3] is None or g[3].display_name != build_name]
        
        deltas = {}
        if without_build_games:
            without_aggregates = calculate_aggregates(without_build_games)
            without_avg = without_aggregates["per_game_averages"]
            without_derived = calculate_derived_metrics(without_build_games)
            without_overall = without_derived.get("overall", {})
            
            for key in ["pts", "ast", "reb", "tov", "fg_pct", "efg_pct"]:
                if key in build_avg and key in without_avg:
                    deltas[key] = round(build_avg[key] - without_avg[key], 1)
            
            if "ast_to" in build_overall and "ast_to" in without_overall:
                deltas["ast_to"] = round(build_overall["ast_to"] - without_overall["ast_to"], 2)
            
            if "involvement_proxy" in build_overall and "involvement_proxy" in without_overall:
                deltas["involvement_proxy"] = round(
                    build_overall["involvement_proxy"] - without_overall["involvement_proxy"], 1
                )
        
        build_impact_results.append({
            "build_name": build_name,
            "games": len(build_games),
            "my_metrics": {
                "pts": build_avg.get("pts", 0),
                "ast_to": build_overall.get("ast_to", 0),
                "efg_pct": build_overall.get("efg_pct", 0),
                "fg_pct": build_avg.get("fg_pct", 0),
                "involvement_proxy": build_overall.get("involvement_proxy", 0)
            },
            "build_signature": build_signature,
            "deltas_vs_without_build": deltas
        })
    
    # Overall with_build vs without_build comparison
    with_build_games = [g for g in games_data if g[3] is not None]
    without_build_games = [g for g in games_data if g[3] is None]
    
    with_vs_without = {}
    if with_build_games and without_build_games:
        with_derived = calculate_derived_metrics(with_build_games)
        without_derived = calculate_derived_metrics(without_build_games)
        with_overall = with_derived.get("overall", {})
        without_overall = without_derived.get("overall", {})
        
        with_vs_without = {
            "with_build_games": len(with_build_games),
            "without_build_games": len(without_build_games),
            "deltas": {}
        }
        
        for key in ["pts", "ast_to", "efg_pct", "fg_pct", "involvement_proxy"]:
            if key in with_overall and key in without_overall:
                with_vs_without["deltas"][key] = round(with_overall[key] - without_overall[key], 1)
    
    return {
        "by_build": build_impact_results,
        "with_vs_without_build": with_vs_without
    }


def calculate_splits(
    games_data: List[Tuple[PlayerGameStats, Game, GamePlayer, Optional[Build]]]
) -> Dict[str, Any]:
    """Calculate performance splits (with/without build, by build, by teammate, etc.)."""
    splits = {}
    
    if not games_data:
        return splits
    
    # Split: with_build vs without_build
    with_build_games = [g for g in games_data if g[3] is not None]
    without_build_games = [g for g in games_data if g[3] is None]
    
    if with_build_games and without_build_games:
        with_build_avg = calculate_aggregates(with_build_games)["per_game_averages"]
        without_build_avg = calculate_aggregates(without_build_games)["per_game_averages"]
        
        splits["with_build_vs_without_build"] = {
            "with_build": {
                "games": len(with_build_games),
                "averages": with_build_avg
            },
            "without_build": {
                "games": len(without_build_games),
                "averages": without_build_avg
            }
        }
    
    # Split: by build_name
    builds_by_name = {}
    for stats, game, game_player, build in games_data:
        if build:
            build_name = build.display_name
            if build_name not in builds_by_name:
                builds_by_name[build_name] = []
            builds_by_name[build_name].append((stats, game, game_player, build))
    
    if len(builds_by_name) > 1:
        splits["by_build_name"] = {}
        for build_name, build_games in builds_by_name.items():
            if len(build_games) >= 3:  # Only include if at least 3 games
                splits["by_build_name"][build_name] = {
                    "games": len(build_games),
                    "averages": calculate_aggregates(build_games)["per_game_averages"]
                }
    
    # Split: by teammate presence (top 5 most common teammates)
    teammate_counts = {}
    for stats, game, game_player, build in games_data:
        # Get teammates for this game (would need to query, but for now skip)
        # This is complex and requires additional queries, so we'll skip it for now
        pass
    
    # Split: by opponent presence (top 5 most common opponents)
    # Similar complexity, skip for now
    
    # Split: by game outcome
    win_games = [g for g in games_data if determine_win(g[1], g[2])]
    loss_games = [g for g in games_data if not determine_win(g[1], g[2])]
    
    if win_games and loss_games:
        splits["by_outcome"] = {
            "wins": {
                "games": len(win_games),
                "averages": calculate_aggregates(win_games)["per_game_averages"]
            },
            "losses": {
                "games": len(loss_games),
                "averages": calculate_aggregates(loss_games)["per_game_averages"]
            }
        }
    
    # Split: by shot volume buckets
    high_fga_games = [g for g in games_data if g[0].fga >= 10]
    low_fga_games = [g for g in games_data if g[0].fga < 10]
    
    if high_fga_games and low_fga_games:
        splits["by_shot_volume"] = {
            "high_volume": {
                "games": len(high_fga_games),
                "threshold": ">=10 FGA",
                "averages": calculate_aggregates(high_fga_games)["per_game_averages"]
            },
            "low_volume": {
                "games": len(low_fga_games),
                "threshold": "<10 FGA",
                "averages": calculate_aggregates(low_fga_games)["per_game_averages"]
            }
        }
    
    return splits


def calculate_trends(
    games_data: List[Tuple[PlayerGameStats, Game, GamePlayer, Optional[Build]]]
) -> Dict[str, Any]:
    """Calculate trend data (last 10 vs season avg, rolling changes)."""
    trends = {}
    
    if not games_data:
        return trends
    
    # Last 10 games
    last_10 = games_data[:10] if len(games_data) >= 10 else games_data
    last_10_avg = calculate_aggregates(last_10)["per_game_averages"]
    
    # Season average (all games)
    season_avg = calculate_aggregates(games_data)["per_game_averages"]
    
    # Calculate deltas
    deltas = {}
    for key in ["pts", "reb", "ast", "stl", "blk", "tov"]:
        if key in last_10_avg and key in season_avg:
            deltas[key] = round(last_10_avg[key] - season_avg[key], 1)
    
    trends["last_10_vs_season"] = {
        "last_10_games": len(last_10),
        "last_10_averages": last_10_avg,
        "season_averages": season_avg,
        "deltas": deltas
    }
    
    return trends


def generate_claim_candidates(
    payload: Dict[str, Any],
    derived_metrics: Dict[str, Any],
    teammate_synergy: Dict[str, Any],
    opponent_difficulty: Dict[str, Any],
    build_impact: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Generate ranked list of claim candidates (25-40 items) with evidence.
    Each claim includes: id, type, claim (sentence), evidence object, reliability score.
    """
    candidates = []
    claim_id_counter = 1
    
    def calculate_reliability(sample_size: int, effect_size: float) -> float:
        """Calculate reliability score from sample_size and effect_size."""
        # Base reliability on sample size (more games = more reliable)
        size_score = min(1.0, sample_size / 10.0)  # 10+ games = max size score
        
        # Effect size score (larger effects = more reliable signal)
        effect_score = min(1.0, abs(effect_size) / 5.0)  # Effect of 5+ = max effect score
        
        # Combined reliability (weighted average)
        reliability = (size_score * 0.6) + (effect_score * 0.4)
        return round(reliability, 2)
    
    # STRENGTH claims from derived metrics
    overall = derived_metrics.get("overall", {})
    last_10 = derived_metrics.get("last_10", {})
    consistency = derived_metrics.get("consistency", {})
    floor_ceiling = derived_metrics.get("floor_ceiling", {})
    
    if overall.get("ast_to", 0) > 2.0:
        candidates.append({
            "id": f"claim_{claim_id_counter}",
            "type": "strength",
            "claim": f"Strong assist-to-turnover ratio of {overall['ast_to']} indicates excellent playmaking decision-making.",
            "evidence": {
                "metrics": [{"name": "AST/TO", "value": overall["ast_to"]}],
                "sample_size": payload["meta"]["total_games"],
                "time_window": "overall"
            },
            "reliability": calculate_reliability(payload["meta"]["total_games"], overall["ast_to"] - 2.0)
        })
        claim_id_counter += 1
    
    if overall.get("efg_pct", 0) > 55:
        candidates.append({
            "id": f"claim_{claim_id_counter}",
            "type": "strength",
            "claim": f"Efficient shooting with {overall['efg_pct']}% eFG% shows strong shot selection and accuracy.",
            "evidence": {
                "metrics": [{"name": "eFG%", "value": overall["efg_pct"]}],
                "sample_size": payload["meta"]["total_games"],
                "time_window": "overall"
            },
            "reliability": calculate_reliability(payload["meta"]["total_games"], overall["efg_pct"] - 50)
        })
        claim_id_counter += 1
    
    if overall.get("pass_first_index", 0) > 40:
        candidates.append({
            "id": f"claim_{claim_id_counter}",
            "type": "strength",
            "claim": f"Pass-first playstyle with {overall['pass_first_index']}% pass-first index prioritizes ball movement.",
            "evidence": {
                "metrics": [{"name": "Pass-first index", "value": overall["pass_first_index"]}],
                "sample_size": payload["meta"]["total_games"],
                "time_window": "overall"
            },
            "reliability": calculate_reliability(payload["meta"]["total_games"], overall["pass_first_index"] - 30)
        })
        claim_id_counter += 1
    
    # WEAKNESS claims
    if overall.get("ast_to", 0) < 1.0 and overall.get("ast_to", 0) > 0:
        candidates.append({
            "id": f"claim_{claim_id_counter}",
            "type": "weakness",
            "claim": f"Low assist-to-turnover ratio of {overall['ast_to']} suggests turnover-prone playmaking.",
            "evidence": {
                "metrics": [{"name": "AST/TO", "value": overall["ast_to"]}],
                "sample_size": payload["meta"]["total_games"],
                "time_window": "overall"
            },
            "reliability": calculate_reliability(payload["meta"]["total_games"], 1.0 - overall["ast_to"])
        })
        claim_id_counter += 1
    
    if overall.get("efg_pct", 0) < 45 and overall.get("efg_pct", 0) > 0:
        candidates.append({
            "id": f"claim_{claim_id_counter}",
            "type": "weakness",
            "claim": f"Inefficient shooting with {overall['efg_pct']}% eFG% indicates poor shot selection or accuracy.",
            "evidence": {
                "metrics": [{"name": "eFG%", "value": overall["efg_pct"]}],
                "sample_size": payload["meta"]["total_games"],
                "time_window": "overall"
            },
            "reliability": calculate_reliability(payload["meta"]["total_games"], 50 - overall["efg_pct"])
        })
        claim_id_counter += 1
    
    # TREND claims (last 10 vs overall)
    if last_10 and overall:
        for key in ["pts", "ast", "reb", "efg_pct", "ast_to"]:
            if key in last_10 and key in overall:
                delta = last_10[key] - overall[key]
                if abs(delta) > 1.0:  # Meaningful change
                    direction = "improving" if delta > 0 else "declining"
                    candidates.append({
                        "id": f"claim_{claim_id_counter}",
                        "type": "trend",
                        "claim": f"{key.upper()} is {direction}: {last_10[key]} in last 10 games vs {overall[key]} overall ({delta:+.1f} delta).",
                        "evidence": {
                            "metrics": [
                                {"name": f"{key} (last_10)", "value": last_10[key]},
                                {"name": f"{key} (overall)", "value": overall[key]},
                                {"name": "delta", "value": delta}
                            ],
                            "sample_size": min(10, payload["meta"]["total_games"]),
                            "time_window": "last_10"
                        },
                        "reliability": calculate_reliability(min(10, payload["meta"]["total_games"]), abs(delta))
                    })
                    claim_id_counter += 1
    
    # CONSISTENCY claims
    if consistency:
        for key in ["pts", "ast", "reb"]:
            if key in consistency:
                stddev = consistency[key].get("stddev", 0)
                mean = consistency[key].get("mean", 0)
                if mean > 0:
                    cv = stddev / mean  # Coefficient of variation
                    if cv > 0.5:  # High variance
                        candidates.append({
                            "id": f"claim_{claim_id_counter}",
                            "type": "consistency",
                            "claim": f"Inconsistent {key.upper()} production: {mean:.1f} avg with {stddev:.1f} stddev (high variance).",
                            "evidence": {
                                "metrics": [
                                    {"name": f"{key} mean", "value": mean},
                                    {"name": f"{key} stddev", "value": stddev},
                                    {"name": "coefficient_of_variation", "value": round(cv, 2)}
                                ],
                                "sample_size": payload["meta"]["total_games"],
                                "time_window": "overall"
                            },
                            "reliability": calculate_reliability(payload["meta"]["total_games"], cv * 10)
                        })
                        claim_id_counter += 1
    
    # FLOOR/CEILING claims
    if floor_ceiling and floor_ceiling.get("key_differences"):
        diffs = floor_ceiling["key_differences"]
        if diffs:
            candidates.append({
                "id": f"claim_{claim_id_counter}",
                "type": "consistency",
                "claim": f"Performance variance: ceiling games show {', '.join([f'{k}: +{v}' for k, v in list(diffs.items())[:3]])} vs floor games.",
                "evidence": {
                    "metrics": [
                        {"name": "floor_games_count", "value": floor_ceiling["floor_games_count"]},
                        {"name": "ceiling_games_count", "value": floor_ceiling["ceiling_games_count"]},
                        {"name": "key_differences", "value": diffs}
                    ],
                    "sample_size": payload["meta"]["total_games"],
                    "time_window": "overall"
                },
                "reliability": calculate_reliability(payload["meta"]["total_games"], max(diffs.values()) if diffs else 0)
            })
            claim_id_counter += 1
    
    # SYNERGY claims
    if teammate_synergy:
        top_positive = teammate_synergy.get("top_positive_impact", [])
        for synergy in top_positive[:3]:
            delta = synergy["deltas"].get("involvement_proxy", 0)
            if delta > 2.0:
                candidates.append({
                    "id": f"claim_{claim_id_counter}",
                    "type": "synergy",
                    "claim": f"Strong positive synergy with {synergy['teammate_username']}: +{delta:.1f} involvement proxy in {synergy['shared_games']} shared games.",
                    "evidence": {
                        "metrics": [
                            {"name": "teammate", "value": synergy["teammate_username"]},
                            {"name": "involvement_proxy_delta", "value": delta},
                            {"name": "shared_games", "value": synergy["shared_games"]}
                        ],
                        "sample_size": synergy["shared_games"],
                        "time_window": "overall"
                    },
                    "reliability": calculate_reliability(synergy["shared_games"], delta)
                })
                claim_id_counter += 1
        
        top_negative = teammate_synergy.get("top_negative_impact", [])
        for synergy in top_negative[:3]:
            delta = synergy["deltas"].get("involvement_proxy", 0)
            if delta < -2.0:
                candidates.append({
                    "id": f"claim_{claim_id_counter}",
                    "type": "synergy",
                    "claim": f"Negative synergy with {synergy['teammate_username']}: {delta:.1f} involvement proxy in {synergy['shared_games']} shared games.",
                    "evidence": {
                        "metrics": [
                            {"name": "teammate", "value": synergy["teammate_username"]},
                            {"name": "involvement_proxy_delta", "value": delta},
                            {"name": "shared_games", "value": synergy["shared_games"]}
                        ],
                        "sample_size": synergy["shared_games"],
                        "time_window": "overall"
                    },
                    "reliability": calculate_reliability(synergy["shared_games"], abs(delta))
                })
                claim_id_counter += 1
    
    # OPPONENT/MATCHUP claims
    if opponent_difficulty:
        opponents = opponent_difficulty.get("opponents", [])
        for opp in opponents[:5]:
            pts_delta = opp["deltas_vs_overall"].get("pts", 0)
            if abs(pts_delta) > 2.0:
                direction = "struggles" if pts_delta < 0 else "excels"
                candidates.append({
                    "id": f"claim_{claim_id_counter}",
                    "type": "matchup",
                    "claim": f"{direction.capitalize()} against {opp['opponent_username']}: {pts_delta:+.1f} PTS delta in {opp['games_vs']} games.",
                    "evidence": {
                        "metrics": [
                            {"name": "opponent", "value": opp["opponent_username"]},
                            {"name": "pts_delta", "value": pts_delta},
                            {"name": "games_vs", "value": opp["games_vs"]}
                        ],
                        "sample_size": opp["games_vs"],
                        "time_window": "overall"
                    },
                    "reliability": calculate_reliability(opp["games_vs"], abs(pts_delta))
                })
                claim_id_counter += 1
    
    # BUILD IMPACT claims
    if build_impact:
        by_build = build_impact.get("by_build", [])
        for build_data in by_build:
            involvement_delta = build_data.get("deltas_vs_without_build", {}).get("involvement_proxy", 0)
            if abs(involvement_delta) > 2.0:
                direction = "improves" if involvement_delta > 0 else "hurts"
                candidates.append({
                    "id": f"claim_{claim_id_counter}",
                    "type": "build_impact",
                    "claim": f"Build '{build_data['build_name']}' {direction} performance: {involvement_delta:+.1f} involvement proxy delta in {build_data['games']} games.",
                    "evidence": {
                        "metrics": [
                            {"name": "build_name", "value": build_data["build_name"]},
                            {"name": "involvement_proxy_delta", "value": involvement_delta},
                            {"name": "games", "value": build_data["games"]}
                        ],
                        "sample_size": build_data["games"],
                        "time_window": "overall"
                    },
                    "reliability": calculate_reliability(build_data["games"], abs(involvement_delta))
                })
                claim_id_counter += 1
        
        with_vs_without = build_impact.get("with_vs_without_build", {})
        if with_vs_without and with_vs_without.get("deltas"):
            involvement_delta = with_vs_without["deltas"].get("involvement_proxy", 0)
            if abs(involvement_delta) > 1.0:
                direction = "better" if involvement_delta > 0 else "worse"
                candidates.append({
                    "id": f"claim_{claim_id_counter}",
                    "type": "build_impact",
                    "claim": f"Performance is {direction} with build assigned: {involvement_delta:+.1f} involvement proxy delta.",
                    "evidence": {
                        "metrics": [
                            {"name": "involvement_proxy_delta", "value": involvement_delta},
                            {"name": "with_build_games", "value": with_vs_without.get("with_build_games", 0)},
                            {"name": "without_build_games", "value": with_vs_without.get("without_build_games", 0)}
                        ],
                        "sample_size": with_vs_without.get("with_build_games", 0) + with_vs_without.get("without_build_games", 0),
                        "time_window": "overall"
                    },
                    "reliability": calculate_reliability(
                        with_vs_without.get("with_build_games", 0) + with_vs_without.get("without_build_games", 0),
                        abs(involvement_delta)
                    )
                })
                claim_id_counter += 1
    
    # DEFENSIVE MATCHUP claims (if available)
    defensive_matchups = payload.get("defensive_matchups", {})
    if defensive_matchups:
        vs_avg = defensive_matchups.get("vs_opponent_averages", {})
        if vs_avg:
            pts_vs_avg = vs_avg.get("pts_vs_opponent_avg", 0)
            if pts_vs_avg < -2.0:  # Negative = good defense
                candidates.append({
                    "id": f"claim_{claim_id_counter}",
                    "type": "strength",
                    "claim": f"Strong defensive impact: held opponents to {pts_vs_avg:.1f} PPG below their average.",
                    "evidence": {
                        "metrics": [
                            {"name": "pts_vs_opponent_avg", "value": pts_vs_avg},
                            {"name": "matchups_with_opponent_data", "value": vs_avg.get("matchups_with_opponent_data", 0)}
                        ],
                        "sample_size": vs_avg.get("matchups_with_opponent_data", 0),
                        "time_window": "overall"
                    },
                    "reliability": calculate_reliability(vs_avg.get("matchups_with_opponent_data", 0), abs(pts_vs_avg))
                })
                claim_id_counter += 1
            elif pts_vs_avg > 2.0:  # Positive = poor defense
                candidates.append({
                    "id": f"claim_{claim_id_counter}",
                    "type": "weakness",
                    "claim": f"Defensive struggles: opponents score {pts_vs_avg:.1f} PPG above their average.",
                    "evidence": {
                        "metrics": [
                            {"name": "pts_vs_opponent_avg", "value": pts_vs_avg},
                            {"name": "matchups_with_opponent_data", "value": vs_avg.get("matchups_with_opponent_data", 0)}
                        ],
                        "sample_size": vs_avg.get("matchups_with_opponent_data", 0),
                        "time_window": "overall"
                    },
                    "reliability": calculate_reliability(vs_avg.get("matchups_with_opponent_data", 0), abs(pts_vs_avg))
                })
                claim_id_counter += 1
    
    # Sort by reliability (highest first) and limit to 40
    candidates.sort(key=lambda x: x["reliability"], reverse=True)
    
    # Mark low confidence but interesting claims
    for candidate in candidates:
        if candidate["reliability"] < 0.5:
            candidate["low_confidence"] = True
        else:
            candidate["low_confidence"] = False
    
    return candidates[:40]  # Limit to 40 claims


def analyze_player_with_openai(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call OpenAI API to analyze player performance.
    
    Args:
        payload: The analysis payload dictionary
    
    Returns:
        Structured JSON response with analysis
    """
    # Build the prompt
    system_prompt = """You are an expert basketball analyst specializing in NBA 2K26 Rec game mode performance analysis. 
Your role is to provide grounded, evidence-based analysis using ONLY the data provided.

CRITICAL CONTEXT:
- This is NBA 2K26 REC MODE (5v5 online competitive play), NOT real NBA basketball
- Position context is CRITICAL: Guards (PG/SG) have different expectations than Forwards (SF/PF) and Centers (C)
- Stats must be evaluated relative to position norms in Rec mode
- Look for deeper patterns, not just surface-level observations

CRITICAL RULES - ANTI-FLUFF ENFORCEMENT:
1. You MUST only use claim_candidates and payload aggregates. NO invented claims.
2. Every bullet point in strengths/weaknesses/tendencies MUST reference a claim_candidate id and sample size.
3. If something is missing (no win/loss, no contest %, no tipped passes), explicitly state "Not available in dataset".
4. Do NOT make generic statements like "work on shooting" without citing a specific claim_candidate.
5. Prefer uncertainty over making unsupported claims.
6. Acknowledge data limitations (e.g., missing build data for some games).
7. Output must be valid JSON matching the required schema exactly.
8. Each strength/weakness/tendency MUST include "claim_id" and "sample_size" fields.

POSITION-AWARE ANALYSIS:
- Guards (PG/SG): Low rebounds are NORMAL. Focus on assists, turnovers, shooting efficiency, steals. High turnovers are concerning.
- Forwards (SF/PF): Balanced expectations. Look at versatility, defensive impact, shooting from multiple ranges.
- Centers (C): High rebounds expected. Blocks and interior defense matter more. Low assists are normal.

DEEPER ANALYSIS REQUIRED:
- Don't just say "1.5 rebounds per game, work on rebounding" for a guard - that's normal!
- Instead, find patterns like: "Despite low rebounding (normal for guards), your defensive matchup data shows opponents shooting X% when you guard them, suggesting..."
- Use matchup statistics to identify defensive strengths/weaknesses
- Look for correlations: e.g., "When you record 5+ assists, your team wins X% more often"
- Identify role fit: "Your stats suggest you're playing more like a [role] than a typical [position]"
- Find efficiency patterns: "You take X shots per game but only Y% are quality looks based on your build attributes"

REC MODE SPECIFICS:
- Rec mode emphasizes team play, spacing, and role execution
- Individual stats matter less than team success and role fulfillment
- Build attributes should align with actual playstyle patterns
- Defensive matchups show how well you guard your position"""

    # Get claim candidates (CRITICAL - these are precomputed evidence-backed claims)
    claim_candidates = payload.get('claim_candidates', [])
    claim_candidates_json = json.dumps(claim_candidates, indent=2) if claim_candidates else "[]"
    
    user_prompt = f"""Analyze the following player performance data for {payload['meta']['username']} in NBA 2K26 Rec mode.

META INFORMATION:
- Total games analyzed: {payload['meta']['total_games']}
- Primary position: {payload['meta'].get('primary_position', 'Unknown')}
- Position distribution: {payload['meta'].get('position_distribution', {})}
- Date range: {payload['meta']['date_range']}
- Build coverage: {payload['meta']['build_coverage']['coverage_pct']}% ({payload['meta']['build_coverage']['games_with_build']} with build, {payload['meta']['build_coverage']['games_without_build']} without)
- Data quality notes: {', '.join(payload['meta']['data_quality']) if payload['meta']['data_quality'] else 'None'}

CLAIM CANDIDATES (PRE-COMPUTED EVIDENCE-BACKED CLAIMS - YOU MUST USE THESE):
{claim_candidates_json}

CRITICAL: You MUST base your analysis on these claim_candidates. Each claim has:
- id: reference this in your analysis
- type: strength, weakness, trend, synergy, matchup, build_impact, consistency
- claim: the evidence-backed statement
- evidence: metrics, sample_size, time_window
- reliability: confidence score (0-1)

DEFENSIVE MATCHUP STATISTICS:
{json.dumps(payload.get('defensive_matchups', {}), indent=2) if payload.get('defensive_matchups') else 'No matchup data available'}

IMPORTANT: The "vs_opponent_averages" section shows how opponents performed against this player compared to their overall averages.
- NEGATIVE values (e.g., -3.5 pts_vs_opponent_avg) = GOOD DEFENSE (opponent scored less than usual)
- POSITIVE values (e.g., +2.1 pts_vs_opponent_avg) = POOR DEFENSE (opponent scored more than usual)
- Use this to identify defensive impact beyond raw stats

DERIVED METRICS (NEW - COMPUTED INSIGHTS):
{json.dumps(payload.get('derived_metrics', {}), indent=2)}

TEAMMATE SYNERGY (NEW):
{json.dumps(payload.get('teammate_synergy', {}), indent=2)}

OPPONENT DIFFICULTY (NEW):
{json.dumps(payload.get('opponent_difficulty', {}), indent=2)}

BUILD IMPACT (NEW):
{json.dumps(payload.get('build_impact', {}), indent=2)}

AGGREGATE STATISTICS:
{json.dumps(payload['aggregates']['per_game_averages'], indent=2)}

PERFORMANCE SPLITS:
{json.dumps(payload['aggregates']['splits'], indent=2)}

TRENDS:
{json.dumps(payload['aggregates']['trends'], indent=2)}

PER-GAME DATA (last {min(10, len(payload['per_game']))} games shown):
{json.dumps(payload['per_game'][:10], indent=2)}

ANALYSIS REQUIREMENTS:
1. POSITION CONTEXT IS CRITICAL: Evaluate stats relative to {payload['meta'].get('primary_position', 'their position')} expectations in Rec mode
   - If they're a guard with low rebounds, that's NORMAL - don't criticize it
   - If they're a center with low assists, that's NORMAL - don't criticize it
   - Focus on position-appropriate metrics

2. USE DEFENSIVE MATCHUP DATA: The defensive_matchups section shows how opponents perform when guarded by this player
   - Lower opponent FG% = better defense
   - Higher opponent turnovers = better defense
   - The "vs_opponent_averages" data is CRITICAL: it shows defensive impact relative to opponent skill level
   - Example: "You held opponents to 3.5 PPG below their average, indicating strong defensive impact"
   - Example: "Opponents shot 5% worse from 3PT against you than their average, showing perimeter defense strength"
   - Negative values in vs_opponent_averages = good defense (you're making them worse than usual)
   - Positive values = poor defense (you're letting them exceed their averages)
   - Use this to identify defensive strengths/weaknesses beyond just steals/blocks

3. FIND DEEPER PATTERNS: Look beyond surface stats
   - Correlations: "When X happens, Y follows"
   - Efficiency: "You take X shots but only Y% are quality looks"
   - Role fit: "Your playstyle suggests you're more of a [role] than typical [position]"
   - Build alignment: "Your build attributes suggest X, but your stats show Y - this indicates..."

4. REC MODE SPECIFIC INSIGHTS:
   - Team success patterns (win rate correlations)
   - Role execution (are they playing their position's role?)
   - Spacing and ball movement impact
   - Clutch performance in close games

5. MANDATORY: For each insight, you MUST reference a claim_candidate id. Format: "Based on claim_candidate [id] (sample_size: N games): [claim text]"

6. If something is missing (win/loss data, contest %, etc.), explicitly state "Not available in dataset"

7. If build data is missing for games, explicitly mention this limitation

8. Provide actionable coaching advice that's position-appropriate and Rec-mode relevant, referencing claim_candidates

9. Identify player identity/archetype based on actual performance patterns from claim_candidates, not invented observations

OUTPUT SCHEMA (must match exactly):
{{
  "player_summary": {{
    "archetype": "string describing player archetype based on stats",
    "one_liner": "one sentence summary",
    "confidence": 0.0-1.0,
    "data_coverage_notes": ["array of strings noting data limitations"]
  }},
  "strengths": [
    {{
      "title": "string",
      "evidence": "string citing specific metric and claim_candidate",
      "claim_id": "claim_X (REQUIRED - reference to claim_candidate id)",
      "sample_size": number (REQUIRED - from claim_candidate evidence),
      "supporting_metrics": [{{"name": "string", "value": "number or string"}}]
    }}
  ],
  "weaknesses": [
    {{
      "title": "string",
      "evidence": "string citing specific metric and claim_candidate",
      "claim_id": "claim_X (REQUIRED - reference to claim_candidate id)",
      "sample_size": number (REQUIRED - from claim_candidate evidence),
      "supporting_metrics": [{{"name": "string", "value": "number or string"}}],
      "fix": ["array of actionable fix suggestions"]
    }}
  ],
  "tendencies": [
    {{
      "title": "string",
      "evidence": "string citing specific metric and claim_candidate",
      "claim_id": "claim_X (REQUIRED - reference to claim_candidate id)",
      "sample_size": number (REQUIRED - from claim_candidate evidence),
      "supporting_metrics": [{{"name": "string", "value": "number or string"}}]
    }}
  ],
  "synergy": {{
    "best_teammate_profiles": [
      {{"description": "string", "evidence": "string"}}
    ],
    "problem_teammate_profiles": [
      {{"description": "string", "evidence": "string"}}
    ]
  }},
  "matchups": {{
    "best_against": [
      {{"opponent": "string or 'N/A' if insufficient data", "evidence": "string"}}
    ],
    "worst_against": [
      {{"opponent": "string or 'N/A' if insufficient data", "evidence": "string"}}
    ]
  }},
  "build_impact": {{
    "by_build": [
      {{"build_name": "string", "impact_summary": "string", "evidence": "string"}}
    ],
    "with_vs_without_build": {{"impact_summary": "string", "evidence": "string"}}
  }},
  "coaching_plan": {{
    "top_3_adjustments": [
      {{"adjustment": "string", "why": "string (must reference weakness claim_id)", "weakness_claim_id": "claim_X (REQUIRED)", "how_to_practice": ["array of strings"]}}
    ],
    "do_more_of": ["array of strings"],
    "do_less_of": ["array of strings"]
  }},
  "receipts": [
    {{
      "claim_id": "claim_X",
      "sample_size": number,
      "metrics": [{{"name": "string", "value": "number or string", "comparison_value": "number or string (optional)", "delta": "number (optional)"}}]
    }}
  ],
  "data_truthfulness_checks": ["array of strings calling out missing dimensions (contest %, dunk/layup split, off/def reb, etc.)"],
  "shareable_card": {{
    "headline": "string",
    "stat": "string",
    "context": "string"
  }}
}}

Return ONLY valid JSON matching this schema. Do not include any markdown formatting or code blocks."""

    # Define the response schema for structured output
    response_schema = {
        "type": "object",
        "properties": {
            "player_summary": {
                "type": "object",
                "properties": {
                    "archetype": {"type": "string"},
                    "one_liner": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "data_coverage_notes": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["archetype", "one_liner", "confidence", "data_coverage_notes"],
                "additionalProperties": False
            },
            "strengths": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "evidence": {"type": "string"},
                        "claim_id": {"type": "string"},
                        "sample_size": {"type": "number"},
                        "supporting_metrics": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "value": {"type": ["number", "string"]}
                                },
                                "required": ["name", "value"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["title", "evidence", "claim_id", "sample_size", "supporting_metrics"],
                    "additionalProperties": False
                }
            },
            "weaknesses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "evidence": {"type": "string"},
                        "claim_id": {"type": "string"},
                        "sample_size": {"type": "number"},
                        "supporting_metrics": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "value": {"type": ["number", "string"]}
                                },
                                "required": ["name", "value"],
                                "additionalProperties": False
                            }
                        },
                        "fix": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["title", "evidence", "claim_id", "sample_size", "supporting_metrics", "fix"],
                    "additionalProperties": False
                }
            },
            "tendencies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "evidence": {"type": "string"},
                        "claim_id": {"type": "string"},
                        "sample_size": {"type": "number"},
                        "supporting_metrics": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "value": {"type": ["number", "string"]}
                                },
                                "required": ["name", "value"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["title", "evidence", "claim_id", "sample_size", "supporting_metrics"],
                    "additionalProperties": False
                }
            },
            "synergy": {
                "type": "object",
                "properties": {
                    "best_teammate_profiles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "evidence": {"type": "string"}
                            },
                            "required": ["description", "evidence"],
                            "additionalProperties": False
                        }
                    },
                    "problem_teammate_profiles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "evidence": {"type": "string"}
                            },
                            "required": ["description", "evidence"],
                            "additionalProperties": False
                        }
                    }
                },
                "required": ["best_teammate_profiles", "problem_teammate_profiles"],
                "additionalProperties": False
            },
            "matchups": {
                "type": "object",
                "properties": {
                    "best_against": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "opponent": {"type": "string"},
                                "evidence": {"type": "string"}
                            },
                            "required": ["opponent", "evidence"],
                            "additionalProperties": False
                        }
                    },
                    "worst_against": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "opponent": {"type": "string"},
                                "evidence": {"type": "string"}
                            },
                            "required": ["opponent", "evidence"],
                            "additionalProperties": False
                        }
                    }
                },
                "required": ["best_against", "worst_against"],
                "additionalProperties": False
            },
            "build_impact": {
                "type": "object",
                "properties": {
                    "by_build": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "build_name": {"type": "string"},
                                "impact_summary": {"type": "string"},
                                "evidence": {"type": "string"}
                            },
                            "required": ["build_name", "impact_summary", "evidence"],
                            "additionalProperties": False
                        }
                    },
                    "with_vs_without_build": {
                        "type": "object",
                        "properties": {
                            "impact_summary": {"type": "string"},
                            "evidence": {"type": "string"}
                        },
                        "required": ["impact_summary", "evidence"],
                        "additionalProperties": False
                    }
                },
                "required": ["by_build", "with_vs_without_build"],
                "additionalProperties": False
            },
            "coaching_plan": {
                "type": "object",
                "properties": {
                    "top_3_adjustments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "adjustment": {"type": "string"},
                                "why": {"type": "string"},
                                "weakness_claim_id": {"type": "string"},
                                "how_to_practice": {"type": "array", "items": {"type": "string"}}
                            },
                            "required": ["adjustment", "why", "weakness_claim_id", "how_to_practice"],
                            "additionalProperties": False
                        }
                    },
                    "do_more_of": {"type": "array", "items": {"type": "string"}},
                    "do_less_of": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["top_3_adjustments", "do_more_of", "do_less_of"],
                "additionalProperties": False
            },
            "receipts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string"},
                        "sample_size": {"type": "number"},
                        "metrics": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "value": {"type": ["number", "string"]}
                                },
                                "required": ["name", "value"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["claim_id", "sample_size", "metrics"],
                    "additionalProperties": False
                }
            },
            "data_truthfulness_checks": {
                "type": "array",
                "items": {"type": "string"}
            },
            "shareable_card": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "stat": {"type": "string"},
                    "context": {"type": "string"}
                },
                "required": ["headline", "stat", "context"],
                "additionalProperties": False
            }
        },
        "required": [
            "player_summary", "strengths", "weaknesses", "tendencies",
            "synergy", "matchups", "build_impact", "coaching_plan", "shareable_card"
        ],
        "additionalProperties": False
    }
    
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "PlayerAnalysis",
                    "strict": True,
                    "schema": response_schema
                }
            },
            temperature=0.3  # Low temperature for more consistent, grounded output
        )
        
        content = response.choices[0].message.content
        analysis = json.loads(content)
        
        return analysis
        
    except Exception as e:
        raise Exception(f"OpenAI analysis failed: {str(e)}")


def get_payload_hash(payload: Dict[str, Any]) -> str:
    """Generate a hash of the payload for caching."""
    payload_str = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(payload_str.encode()).hexdigest()

