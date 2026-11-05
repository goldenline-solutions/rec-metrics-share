"""
Player profile service for generating personalized insights and statistics.
"""
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_
from models import Player, PlayerGameStats, Game, GamePlayer, LEGACY_GAME_VERSION
from datetime import datetime, timedelta
import statistics


def calculate_ts_pct(pts: int, fga: int, fta: int) -> float:
    """Calculate True Shooting Percentage."""
    if fga == 0 and fta == 0:
        return 0.0
    ts_att = 2 * (fga + 0.44 * fta)
    if ts_att == 0:
        return 0.0
    return round((pts / ts_att) * 100, 1)


def calculate_efficiency(pts: int, reb: int, ast: int, stl: int, blk: int, tov: int) -> float:
    """Simple efficiency metric: PTS + REB + AST + STL + BLK - TOV."""
    return pts + reb + ast + stl + blk - tov


def game_version_filter(game_version: Optional[str]):
    """Filter clause for one NBA 2K title, or None for every title.

    Games predating the game_version column count as the legacy title so they
    stay visible instead of dropping out of every view.
    """
    if not game_version:
        return None
    if game_version == LEGACY_GAME_VERSION:
        return or_(Game.game_version == game_version, Game.game_version.is_(None))
    return Game.game_version == game_version


def get_player_games(db: Session, player_id: str, limit: Optional[int] = 100, include_player_ids: Optional[List[str]] = None, game_version: Optional[str] = None) -> List[Tuple[PlayerGameStats, Game, GamePlayer]]:
    """Get player's games with stats, ordered by most recent.
    
    Args:
        player_id: Primary player ID
        limit: Maximum number of games to return (None = no limit, return all)
        include_player_ids: Optional list of additional player IDs to include (for case variants)
        game_version: Restrict to one NBA 2K title ('2K26'/'2K27'); None = all titles
    """
    if include_player_ids:
        # Include games from all player IDs (case variants)
        player_ids = include_player_ids if player_id in include_player_ids else [player_id] + include_player_ids
    else:
        player_ids = [player_id]
    
    query = db.query(
        PlayerGameStats,
        Game,
        GamePlayer
    ).join(
        Game, PlayerGameStats.game_id == Game.id
    ).join(
        GamePlayer,
        (GamePlayer.game_id == PlayerGameStats.game_id) & (GamePlayer.player_id == PlayerGameStats.player_id)
    ).filter(
        PlayerGameStats.player_id.in_(player_ids)
    ).order_by(
        desc(Game.created_at)
    )
    version_clause = game_version_filter(game_version)
    if version_clause is not None:
        query = query.filter(version_clause)
    if limit is not None:
        query = query.limit(limit)
    games_data = query.all()
    
    return games_data


def determine_win(game: Game, game_player: GamePlayer) -> bool:
    """Determine if player's team won."""
    if game_player.team_side == "HOME":
        return game.home_score > game.away_score
    else:
        return game.away_score > game.home_score


def get_quarter_stats(game: Game, game_player: GamePlayer) -> Optional[Dict[str, int]]:
    """Get quarter-by-quarter points for player's team."""
    if game_player.team_side == "HOME":
        return {
            "q1": game.home_q1 or 0,
            "q2": game.home_q2 or 0,
            "q3": game.home_q3 or 0,
            "q4": game.home_q4 or 0
        }
    else:
        return {
            "q1": game.away_q1 or 0,
            "q2": game.away_q2 or 0,
            "q3": game.away_q3 or 0,
            "q4": game.away_q4 or 0
        }


def generate_summary_stats(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]]) -> Dict[str, Any]:
    """Calculate summary statistics from games."""
    if not games_data:
        return {
            "gamesPlayed": 0,
            "winRate": 0.0,
            "wins": 0,
            "losses": 0,
            "ppg": 0.0,
            "apg": 0.0,
            "rpg": 0.0,
            "tsPct": 0.0,
            "fgPct": 0.0,
            "threePct": 0.0,
            "toPerGame": 0.0
        }
    
    total_pts = 0
    total_reb = 0
    total_ast = 0
    total_tov = 0
    total_fgm = 0
    total_fga = 0
    total_tpm = 0
    total_tpa = 0
    total_ftm = 0
    total_fta = 0
    wins = 0
    games_played = len(games_data)
    
    for stats, game, game_player in games_data:
        total_pts += stats.pts
        total_reb += stats.reb
        total_ast += stats.ast
        total_tov += stats.tov
        total_fgm += stats.fgm
        total_fga += stats.fga
        total_tpm += stats.tpm
        total_tpa += stats.tpa
        total_ftm += stats.ftm
        total_fta += stats.fta
        
        if determine_win(game, game_player):
            wins += 1
    
    win_rate = round((wins / games_played) * 100, 1) if games_played > 0 else 0.0
    ppg = round(total_pts / games_played, 1) if games_played > 0 else 0.0
    apg = round(total_ast / games_played, 1) if games_played > 0 else 0.0
    rpg = round(total_reb / games_played, 1) if games_played > 0 else 0.0
    to_per_game = round(total_tov / games_played, 1) if games_played > 0 else 0.0
    
    fg_pct = round((total_fgm / total_fga * 100), 1) if total_fga > 0 else 0.0
    three_pct = round((total_tpm / total_tpa * 100), 1) if total_tpa > 0 else 0.0
    ts_pct = calculate_ts_pct(total_pts, total_fga, total_fta)
    
    losses = games_played - wins
    
    return {
        "gamesPlayed": games_played,
        "winRate": win_rate,
        "wins": wins,
        "losses": losses,
        "ppg": ppg,
        "apg": apg,
        "rpg": rpg,
        "tsPct": ts_pct,
        "fgPct": fg_pct,
        "threePct": three_pct,
        "toPerGame": to_per_game
    }


def generate_recent_trends(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]], limit: int = 10) -> Dict[str, Any]:
    """Generate trend data for last N games."""
    recent_games = games_data[:limit]
    
    if not recent_games:
        return {
            "labels": [],
            "points": [],
            "assists": [],
            "rebounds": [],
            "turnovers": [],
            "efficiency": []
        }
    
    labels = []
    points = []
    assists = []
    rebounds = []
    turnovers = []
    efficiency = []
    
    for idx, (stats, game, game_player) in enumerate(recent_games):
        labels.append(f"Game {len(recent_games) - idx}")
        points.append(stats.pts)
        assists.append(stats.ast)
        rebounds.append(stats.reb)
        turnovers.append(stats.tov)
        efficiency.append(calculate_efficiency(stats.pts, stats.reb, stats.ast, stats.stl, stats.blk, stats.tov))
    
    return {
        "labels": labels,
        "points": points,
        "assists": assists,
        "rebounds": rebounds,
        "turnovers": turnovers,
        "efficiency": efficiency
    }


def generate_insight_shooting_with_assists(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]]) -> Optional[Dict[str, Any]]:
    """Insight: Shooting better when assists are high."""
    if len(games_data) < 10:
        return None

    assist_thresholds = [3, 4, 5, 6, 7, 8, 9]
    best_insight = None
    best_diff = 0

    for threshold in assist_thresholds:
        high_ast_games = []
        low_ast_games = []

        for stats, game, game_player in games_data:
            if stats.ast >= threshold:
                if stats.fga > 0:
                    high_ast_games.append((stats.fgm / stats.fga) * 100)
            else:
                if stats.fga > 0:
                    low_ast_games.append((stats.fgm / stats.fga) * 100)

        if len(high_ast_games) >= 5 and len(low_ast_games) >= 5:
            high_avg = statistics.mean(high_ast_games)
            low_avg = statistics.mean(low_ast_games)
            diff = high_avg - low_avg

            if diff > best_diff and diff > 1.5:
                best_diff = diff
                best_insight = {
                    "id": "best_when_assists_high",
                    "title": "You perform best when…",
                    "text": f"You shoot {round(diff, 1)}% better when you record ≥ {threshold} assists.",
                    "confidence": "medium" if len(high_ast_games) >= 8 else "low",
                    "support": {"n": len(high_ast_games), "note": f"based on last {len(games_data)} games"}
                }

    return best_insight


def generate_insight_win_rate_threshold(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]]) -> Optional[Dict[str, Any]]:
    """Insight: Win rate when taking X shots or keeping turnovers low."""
    if len(games_data) < 15:
        return None
    
    # Try shot threshold
    shot_thresholds = [8, 10, 12, 15]
    best_insight = None
    best_diff = 0
    
    for threshold in shot_thresholds:
        high_shot_games = []
        low_shot_games = []
        
        for stats, game, game_player in games_data:
            won = determine_win(game, game_player)
            if stats.fga >= threshold:
                high_shot_games.append(1 if won else 0)
            else:
                low_shot_games.append(1 if won else 0)
        
        if len(high_shot_games) >= 5 and len(low_shot_games) >= 5:
            high_wr = (sum(high_shot_games) / len(high_shot_games)) * 100
            low_wr = (sum(low_shot_games) / len(low_shot_games)) * 100
            diff = high_wr - low_wr

            if abs(diff) > best_diff and abs(diff) > 5:
                best_diff = abs(diff)
                if diff > 0:
                    best_insight = {
                        "id": "win_when_shots_high",
                        "title": "You perform best when…",
                        "text": f"You win {round(high_wr, 1)}% of games when you take ≥ {threshold} shots (vs {round(low_wr, 1)}% otherwise).",
                        "confidence": "medium" if len(high_shot_games) >= 10 else "low",
                        "support": {"n": len(high_shot_games), "note": f"based on last {len(games_data)} games"}
                    }
    
    # Try turnover threshold
    tov_thresholds = [2, 3, 4, 5]
    for threshold in tov_thresholds:
        low_tov_games = []
        high_tov_games = []
        
        for stats, game, game_player in games_data:
            won = determine_win(game, game_player)
            if stats.tov <= threshold:
                low_tov_games.append(1 if won else 0)
            else:
                high_tov_games.append(1 if won else 0)
        
        if len(low_tov_games) >= 5 and len(high_tov_games) >= 5:
            low_wr = (sum(low_tov_games) / len(low_tov_games)) * 100
            high_wr = (sum(high_tov_games) / len(high_tov_games)) * 100
            diff = low_wr - high_wr

            if diff > best_diff and diff > 5:
                best_diff = diff
                best_insight = {
                    "id": "win_when_tov_low",
                    "title": "You perform best when…",
                    "text": f"You win {round(low_wr, 1)}% of games when you keep turnovers ≤ {threshold} (vs {round(high_wr, 1)}% otherwise).",
                    "confidence": "medium" if len(low_tov_games) >= 10 else "low",
                    "support": {"n": len(low_tov_games), "note": f"based on last {len(games_data)} games"}
                }
    
    return best_insight


def generate_insight_weakest_quarter(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]]) -> Optional[Dict[str, Any]]:
    """Insight: Weakest quarter based on team performance."""
    if len(games_data) < 10:
        return None
    
    quarter_points = {"q1": [], "q2": [], "q3": [], "q4": []}
    games_with_quarters = 0
    
    for stats, game, game_player in games_data:
        q_stats = get_quarter_stats(game, game_player)
        if q_stats and all(q_stats.values()):
            games_with_quarters += 1
            for q, pts in q_stats.items():
                quarter_points[q].append(pts)
    
    if games_with_quarters < 5:
        # Fallback: use weakest stretch from recent games
        if len(games_data) >= 10:
            recent_10 = games_data[:10]
            # Split into two halves
            first_half = recent_10[:5]
            second_half = recent_10[5:]
            
            first_avg_pts = statistics.mean([s[0].pts for s in first_half])
            second_avg_pts = statistics.mean([s[0].pts for s in second_half])
            
            if first_avg_pts < second_avg_pts and (second_avg_pts - first_avg_pts) > 3:
                return {
                    "id": "weakest_stretch",
                    "title": "Your weakest stretch is…",
                    "text": f"Your scoring drops in the first half of recent games (avg {round(first_avg_pts, 1)} pts vs {round(second_avg_pts, 1)} pts in second half).",
                    "confidence": "low",
                    "support": {"n": 10, "note": "based on last 10 games"}
                }
        return None
    
    # Calculate average points per quarter
    quarter_avgs = {}
    for q, pts_list in quarter_points.items():
        if pts_list:
            quarter_avgs[q] = statistics.mean(pts_list)
    
    if not quarter_avgs:
        return None
    
    # Find weakest quarter
    weakest_q = min(quarter_avgs.items(), key=lambda x: x[1])
    strongest_q = max(quarter_avgs.items(), key=lambda x: x[1])
    
    q_names = {"q1": "1st", "q2": "2nd", "q3": "3rd", "q4": "4th"}
    
    if weakest_q[1] < strongest_q[1] - 2:  # At least 2 point difference
        return {
            "id": "weakest_quarter",
            "title": "Your weakest quarter is…",
            "text": f"Your team scores {round(weakest_q[1], 1)} points on average in the {q_names[weakest_q[0]]} quarter (lowest of all quarters).",
            "confidence": "medium" if games_with_quarters >= 15 else "low",
            "support": {"n": games_with_quarters, "note": f"based on last {len(games_data)} games"}
        }
    
    return None


def generate_insight_clutch_performance(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]]) -> Optional[Dict[str, Any]]:
    """Insight: Performance in close games."""
    if len(games_data) < 15:
        return None
    
    close_games = []
    blowout_games = []
    
    for stats, game, game_player in games_data:
        margin = abs(game.home_score - game.away_score)
        won = determine_win(game, game_player)
        
        if margin <= 5:
            close_games.append((stats.pts, won))
        elif margin >= 15:
            blowout_games.append((stats.pts, won))
    
    if len(close_games) >= 5:
        close_avg_pts = statistics.mean([g[0] for g in close_games])
        close_wr = (sum(1 for g in close_games if g[1]) / len(close_games)) * 100

        if len(blowout_games) >= 5:
            blowout_avg_pts = statistics.mean([g[0] for g in blowout_games])
            pts_diff = close_avg_pts - blowout_avg_pts
            label = "clutch" if pts_diff > 0 else "less impactful"
            return {
                "id": "clutch_performer",
                "title": "In close games…",
                "text": f"You average {round(close_avg_pts, 1)} pts and win {round(close_wr, 1)}% of close games (≤5 pt margin), vs {round(blowout_avg_pts, 1)} pts in blowouts.",
                "confidence": "medium" if len(close_games) >= 10 else "low",
                "support": {"n": len(close_games), "note": f"based on last {len(games_data)} games"}
            }
        else:
            return {
                "id": "clutch_performer",
                "title": "In close games…",
                "text": f"You average {round(close_avg_pts, 1)} pts and win {round(close_wr, 1)}% of close games (≤5 pt margin).",
                "confidence": "medium" if len(close_games) >= 10 else "low",
                "support": {"n": len(close_games), "note": f"based on last {len(games_data)} games"}
            }

    return None


def generate_insight_playmaking_vs_scoring(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]]) -> Optional[Dict[str, Any]]:
    """Insight: Higher win rate when assists are high."""
    if len(games_data) < 15:
        return None
    
    assist_thresholds = [6, 7, 8, 9, 10]
    best_insight = None
    best_diff = 0
    
    for threshold in assist_thresholds:
        high_ast_games = []
        low_ast_games = []
        
        for stats, game, game_player in games_data:
            won = determine_win(game, game_player)
            if stats.ast >= threshold:
                high_ast_games.append(1 if won else 0)
            else:
                low_ast_games.append(1 if won else 0)
        
        if len(high_ast_games) >= 5 and len(low_ast_games) >= 5:
            high_wr = (sum(high_ast_games) / len(high_ast_games)) * 100
            low_wr = (sum(low_ast_games) / len(low_ast_games)) * 100
            diff = high_wr - low_wr

            if diff > best_diff and diff > 5:
                best_diff = diff
                best_insight = {
                    "id": "playmaking_wins",
                    "title": "You perform best when…",
                    "text": f"You win {round(high_wr, 1)}% of games when you record ≥ {threshold} assists (vs {round(low_wr, 1)}% otherwise).",
                    "confidence": "medium" if len(high_ast_games) >= 10 else "low",
                    "support": {"n": len(high_ast_games), "note": f"based on last {len(games_data)} games"}
                }
    
    return best_insight


def generate_insight_three_point_volume(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]]) -> Optional[Dict[str, Any]]:
    """Insight: Win rate when attempting more threes."""
    if len(games_data) < 15:
        return None
    
    three_thresholds = [3, 4, 5, 6]
    best_insight = None
    best_diff = 0
    
    for threshold in three_thresholds:
        high_three_games = []
        low_three_games = []
        
        for stats, game, game_player in games_data:
            won = determine_win(game, game_player)
            if stats.tpa >= threshold:
                high_three_games.append(1 if won else 0)
            else:
                low_three_games.append(1 if won else 0)
        
        if len(high_three_games) >= 5 and len(low_three_games) >= 5:
            high_wr = (sum(high_three_games) / len(high_three_games)) * 100
            low_wr = (sum(low_three_games) / len(low_three_games)) * 100
            diff = high_wr - low_wr

            if diff > best_diff and diff > 5:
                best_diff = diff
                best_insight = {
                    "id": "three_volume_wins",
                    "title": "You perform best when…",
                    "text": f"You win {round(high_wr, 1)}% of games when you attempt ≥ {threshold} threes (vs {round(low_wr, 1)}% otherwise).",
                    "confidence": "medium" if len(high_three_games) >= 10 else "low",
                    "support": {"n": len(high_three_games), "note": f"based on last {len(games_data)} games"}
                }
    
    return best_insight


def generate_insight_wins_vs_losses(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]]) -> Optional[Dict[str, Any]]:
    """Insight: Scoring/efficiency difference between wins and losses."""
    if len(games_data) < 10:
        return None

    win_pts = []
    loss_pts = []

    for stats, game, game_player in games_data:
        if determine_win(game, game_player):
            win_pts.append(stats.pts)
        else:
            loss_pts.append(stats.pts)

    if len(win_pts) < 3 or len(loss_pts) < 3:
        return None

    avg_win = round(statistics.mean(win_pts), 1)
    avg_loss = round(statistics.mean(loss_pts), 1)
    diff = avg_win - avg_loss

    if diff > 0:
        text = f"You average {avg_win} pts in wins vs {avg_loss} pts in losses — scoring {round(diff, 1)} more when your team wins."
    else:
        text = f"You average {avg_win} pts in wins vs {avg_loss} pts in losses — consistent regardless of outcome."

    return {
        "id": "wins_vs_losses_scoring",
        "title": "Wins vs losses",
        "text": text,
        "confidence": "medium" if len(win_pts) >= 10 and len(loss_pts) >= 10 else "low",
        "support": {"n": len(games_data), "note": f"{len(win_pts)}W / {len(loss_pts)}L"}
    }


def generate_insight_scoring_consistency(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]]) -> Optional[Dict[str, Any]]:
    """Insight: How consistent the player's scoring is."""
    if len(games_data) < 15:
        return None

    pts_list = [s.pts for s, g, gp in games_data]
    avg = statistics.mean(pts_list)
    stdev = statistics.stdev(pts_list)
    above_avg = sum(1 for p in pts_list if p >= avg)
    pct_above = round((above_avg / len(pts_list)) * 100, 1)
    high_game = max(pts_list)
    low_game = min(pts_list)

    if stdev < 4:
        text = f"You're highly consistent — your scoring rarely strays far from your {round(avg, 1)} pt average (σ={round(stdev, 1)})."
    else:
        text = f"You average {round(avg, 1)} pts with a range of {low_game}–{high_game}. You score at or above your average in {pct_above}% of games."

    return {
        "id": "scoring_consistency",
        "title": "Scoring consistency",
        "text": text,
        "confidence": "medium" if len(games_data) >= 30 else "low",
        "support": {"n": len(games_data), "note": f"based on last {len(games_data)} games"}
    }


def generate_all_insights(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]]) -> List[Dict[str, Any]]:
    """Generate all candidate insights and return top 3-5."""
    candidates = []
    
    insight1 = generate_insight_shooting_with_assists(games_data)
    if insight1:
        candidates.append(insight1)
    
    insight2 = generate_insight_win_rate_threshold(games_data)
    if insight2:
        candidates.append(insight2)
    
    insight3 = generate_insight_weakest_quarter(games_data)
    if insight3:
        candidates.append(insight3)
    
    insight4 = generate_insight_clutch_performance(games_data)
    if insight4:
        candidates.append(insight4)
    
    insight5 = generate_insight_playmaking_vs_scoring(games_data)
    if insight5:
        candidates.append(insight5)
    
    insight6 = generate_insight_three_point_volume(games_data)
    if insight6:
        candidates.append(insight6)

    insight7 = generate_insight_wins_vs_losses(games_data)
    if insight7:
        candidates.append(insight7)

    insight8 = generate_insight_scoring_consistency(games_data)
    if insight8:
        candidates.append(insight8)

    # Sort by confidence (high > medium > low) and limit to top 5
    confidence_order = {"high": 3, "medium": 2, "low": 1}
    candidates.sort(key=lambda x: confidence_order.get(x.get("confidence", "low"), 0), reverse=True)
    
    return candidates[:5]


def generate_share_card(games_data: List[Tuple[PlayerGameStats, Game, GamePlayer]], summary: Dict[str, Any]) -> Dict[str, Any]:
    """Generate shareable stat card data."""
    if not games_data:
        return {
            "headline": "Getting Started",
            "text": "Play more games to unlock your signature stat!",
            "stat": "0 games",
            "footnote": "Start playing to see insights"
        }
    
    # Find best insight for share card
    insights = generate_all_insights(games_data)
    
    if insights and len(insights) > 0:
        best_insight = insights[0]
        # Extract stat from insight text
        stat_text = best_insight.get("text", "")
        return {
            "headline": "Signature Stat",
            "text": stat_text,
            "stat": stat_text.split(".")[0] if "." in stat_text else stat_text,
            "footnote": f"Last {len(games_data)} games"
        }
    
    # Fallback: use win rate or PPG
    if summary.get("winRate", 0) > 50:
        return {
            "headline": "Signature Stat",
            "text": f"You win {summary['winRate']}% of your games.",
            "stat": f"Win rate: {summary['winRate']}%",
            "footnote": f"Last {len(games_data)} games"
        }
    else:
        return {
            "headline": "Signature Stat",
            "text": f"You average {summary['ppg']} points per game.",
            "stat": f"{summary['ppg']} PPG",
            "footnote": f"Last {len(games_data)} games"
        }


def get_player_profile(db: Session, username: str, game_version: Optional[str] = None) -> Dict[str, Any]:
    """Get complete player profile with stats, trends, and insights.

    game_version restricts the profile to a single NBA 2K title ('2K26'/'2K27');
    None profiles every title at once.
    """
    from sqlalchemy import func
    from name_utils import normalize_name
    from models import NameClaim
    
    # Normalize the username for matching
    normalized_username = normalize_name(username)
    print("normalized_username")
    print(normalized_username)
    # First, check if there's a verified claim for this normalized name
    # Note: There can be multiple claims for the same name on different platforms
    # For profile, we'll use the first verified claim found (or could filter by platform if needed)
    verified_claim = db.query(NameClaim).filter(
        NameClaim.normalized_name == normalized_username,
        NameClaim.status == 'verified'
    ).first()
    print("verified_claim")
    print(verified_claim)
    if verified_claim:
        display_username = verified_claim.display_name
        # Always use Player table lookup so we capture ALL games (including pre-claim games
        # that don't have claim_id set on their GamePlayer records)
        players = db.query(Player).filter(
            func.lower(Player.gamertag) == func.lower(verified_claim.display_name)
        ).all()

        if not players:
            # Narrow candidates by prefix before Python-side normalize_name check
            prefix = normalized_username[:5] if len(normalized_username) >= 5 else normalized_username
            candidates = db.query(Player).filter(
                func.lower(Player.gamertag).like(f"{prefix}%")
            ).all()
            players = [p for p in candidates if normalize_name(p.gamertag) == normalized_username]

        print(f"Found {len(players)} Player records matching claim")

        if players:
            all_player_ids = [p.id for p in players]
            games_data = get_player_games(db, players[0].id, limit=None, include_player_ids=all_player_ids, game_version=game_version)
        else:
            print("No Player records found for claim")
            games_data = []
    else:
        print("no verified_claim")
        # Fall back to old Player table lookup
        # Find player by gamertag (case-insensitive search)
        players = db.query(Player).filter(
            func.lower(Player.gamertag) == func.lower(username)
        ).all()
        
        if not players:
            print("no players")
            return {
                "error": "Player not found",
                "username": username
            }
        
        # Use the first matching player (or the one that matches exactly)
        player = players[0]
        for p in players:
            if p.gamertag.lower() == normalized_username:
                player = p
                break
        
        display_username = player.gamertag
        
        # Get games data - combine all players with same normalized name
        # This ensures we get all games even if there are capitalization variants
        all_player_ids = [p.id for p in players]
        games_data = get_player_games(db, player.id, limit=None, include_player_ids=all_player_ids, game_version=game_version)
    
    if not games_data:
        return {
            "username": display_username,
            "summary": {
                "gamesPlayed": 0,
                "winRate": 0.0,
                "ppg": 0.0,
                "apg": 0.0,
                "rpg": 0.0,
                "tsPct": 0.0,
                "fgPct": 0.0,
                "threePct": 0.0,
                "toPerGame": 0.0
            },
            "recentTrends": {
                "labels": [],
                "points": [],
                "assists": [],
                "rebounds": [],
                "turnovers": [],
                "efficiency": []
            },
            "insights": [],
            "shareCard": {
                "headline": "Getting Started",
                "text": "Play more games to unlock your signature stat!",
                "stat": "0 games",
                "footnote": "Start playing to see insights"
            }
        }
    
    # Generate all components
    print(f"Generating profile components from {len(games_data)} games")
    summary = generate_summary_stats(games_data)
    print(f"Summary generated: {summary.get('gamesPlayed', 0)} games")
    trends = generate_recent_trends(games_data, limit=10)
    print(f"Trends generated: {len(trends.get('labels', []))} data points")
    
    # Generate insights with error handling
    try:
        print(f"Attempting to generate insights from {len(games_data)} games")
        if len(games_data) > 0:
            print(f"First game data sample - type: {type(games_data[0])}, length: {len(games_data[0]) if isinstance(games_data[0], tuple) else 'N/A'}")
            if isinstance(games_data[0], tuple) and len(games_data[0]) >= 3:
                print(f"Sample: stats type={type(games_data[0][0])}, game type={type(games_data[0][1])}, gp type={type(games_data[0][2])}")
        insights = generate_all_insights(games_data)
        print(f"Insights generated: {len(insights)} insights")
        if insights:
            print(f"Insight IDs: {[i.get('id') for i in insights]}")
        else:
            print("No insights generated (empty list returned)")
    except Exception as e:
        print(f"ERROR generating insights: {str(e)}")
        import traceback
        traceback.print_exc()
        insights = []
    
    share_card = generate_share_card(games_data, summary)
    
    return {
        "username": display_username,
        "summary": summary,
        "recentTrends": trends,
        "insights": insights,
        "shareCard": share_card
    }

