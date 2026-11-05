"""
Script to find games with data verification errors and retry extraction using their screenshots.

This script:
1. Finds all games with data verification errors (player points don't match team totals, etc.)
2. For each game with a screenshot, retries extraction with enhanced prompts
3. Updates the game data if the retry fixes the errors
4. Skips games without screenshots
"""
import os
import sys
from pathlib import Path

# Add parent directory to path to import backend modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from db import SessionLocal
from models import Game, Player, GamePlayer, PlayerGameStats, TeamTotal, Matchup
from app import validate_game_data
from openai_client import extract_box_score
from utils import validate_extraction, validate_integrity, assign_position
from ingest_service import _build_payload
from sqlalchemy import and_

def reconstruct_extracted_data(db, game):
    """
    Reconstruct extracted_data format from database for a game.
    This is used to check integrity before retrying.
    """
    # Get game data
    game_data = {
        "away_score": game.away_score,
        "home_score": game.home_score,
        "quarters": {
            "away": [game.away_q1, game.away_q2, game.away_q3, game.away_q4],
            "home": [game.home_q1, game.home_q2, game.home_q3, game.home_q4]
        }
    }
    
    # Get teams
    team_totals = db.query(TeamTotal).filter(TeamTotal.game_id == game.id).all()
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
    
    # Get players with stats
    game_players = db.query(GamePlayer).filter(GamePlayer.game_id == game.id).all()
    players_data = []
    for gp in game_players:
        player = db.query(Player).filter(Player.id == gp.player_id).first()
        stats = db.query(PlayerGameStats).filter(
            PlayerGameStats.game_id == game.id,
            PlayerGameStats.player_id == gp.player_id
        ).first()
        
        if player and stats:
            players_data.append({
                "side": gp.team_side,
                "row_index": gp.row_index,
                "gamertag": player.gamertag,
                "grade": stats.grade,
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
    
    return {
        "metadata": {
            "season_label": game.season_label,
            "mode_label": game.mode_label,
            "extracted_from": "nba2k_rec_boxscore_screenshot"
        },
        "game": game_data,
        "teams": teams_data,
        "players": players_data
    }


def update_game_from_extracted_data(db, game, extracted_data):
    """
    Update a game's data from newly extracted data.
    This deletes and recreates player stats, team totals, and matchups.
    """
    # Update game scores and quarters
    game_data = extracted_data.get("game", {})
    quarters = game_data.get("quarters", {})
    
    game.away_score = game_data.get("away_score", 0)
    game.home_score = game_data.get("home_score", 0)
    game.away_q1 = quarters.get("away", [None] * 4)[0] if len(quarters.get("away", [])) > 0 else None
    game.away_q2 = quarters.get("away", [None] * 4)[1] if len(quarters.get("away", [])) > 1 else None
    game.away_q3 = quarters.get("away", [None] * 4)[2] if len(quarters.get("away", [])) > 2 else None
    game.away_q4 = quarters.get("away", [None] * 4)[3] if len(quarters.get("away", [])) > 3 else None
    game.home_q1 = quarters.get("home", [None] * 4)[0] if len(quarters.get("home", [])) > 0 else None
    game.home_q2 = quarters.get("home", [None] * 4)[1] if len(quarters.get("home", [])) > 1 else None
    game.home_q3 = quarters.get("home", [None] * 4)[2] if len(quarters.get("home", [])) > 2 else None
    game.home_q4 = quarters.get("home", [None] * 4)[3] if len(quarters.get("home", [])) > 3 else None
    
    # Update metadata if provided
    metadata = extracted_data.get("metadata", {})
    if metadata.get("season_label"):
        game.season_label = metadata.get("season_label")
    if metadata.get("mode_label"):
        game.mode_label = metadata.get("mode_label")
    
    # Delete existing player stats, team totals, and matchups
    db.query(PlayerGameStats).filter(PlayerGameStats.game_id == game.id).delete()
    db.query(TeamTotal).filter(TeamTotal.game_id == game.id).delete()
    db.query(Matchup).filter(Matchup.game_id == game.id).delete()
    
    # Recreate team totals
    teams_data = extracted_data.get("teams", [])
    for team_data in teams_data:
        team_side = team_data.get("side")
        totals = team_data.get("totals", {})
        
        team_total = TeamTotal(
            game_id=game.id,
            team_side=team_side,
            grade=team_data.get("grade"),
            pts=totals.get("pts", 0),
            reb=totals.get("reb", 0),
            ast=totals.get("ast", 0),
            stl=totals.get("stl", 0),
            blk=totals.get("blk", 0),
            fouls=totals.get("fouls", 0),
            tov=totals.get("tov", 0),
            fgm=totals.get("fgm", 0),
            fga=totals.get("fga", 0),
            tpm=totals.get("tpm", 0),
            tpa=totals.get("tpa", 0),
            ftm=totals.get("ftm", 0),
            fta=totals.get("fta", 0)
        )
        db.add(team_total)
    
    # Recreate player stats (keep existing game_players, just update stats)
    players_data = extracted_data.get("players", [])
    for player_data in players_data:
        gamertag = player_data.get("gamertag")
        if not gamertag:
            continue
        
        # Find or create player
        player = db.query(Player).filter(Player.gamertag == gamertag).first()
        if not player:
            continue
        
        # Find existing game_player (should exist, but create if not)
        team_side = player_data.get("side")
        row_index = player_data.get("row_index", 0)
        game_player = db.query(GamePlayer).filter(
            and_(
                GamePlayer.game_id == game.id,
                GamePlayer.player_id == player.id,
                GamePlayer.team_side == team_side
            )
        ).first()
        
        if not game_player:
            # Create game_player if missing
            try:
                position = assign_position(row_index)
            except:
                # Fallback if row_index is invalid
                positions = ["PG", "SG", "SF", "PF", "C"]
                position = positions[row_index] if 0 <= row_index <= 4 else "PG"
            game_player = GamePlayer(
                game_id=game.id,
                player_id=player.id,
                team_side=team_side,
                position=position,
                row_index=row_index
            )
            db.add(game_player)
        
        # Create player stats
        stats = player_data.get("stats", {})
        player_stats = PlayerGameStats(
            game_id=game.id,
            player_id=player.id,
            grade=player_data.get("grade"),
            pts=stats.get("pts", 0),
            reb=stats.get("reb", 0),
            ast=stats.get("ast", 0),
            stl=stats.get("stl", 0),
            blk=stats.get("blk", 0),
            fouls=stats.get("fouls", 0),
            tov=stats.get("tov", 0),
            fgm=stats.get("fgm", 0),
            fga=stats.get("fga", 0),
            tpm=stats.get("tpm", 0),
            tpa=stats.get("tpa", 0),
            ftm=stats.get("ftm", 0),
            fta=stats.get("fta", 0)
        )
        db.add(player_stats)
    
    # Recreate matchups
    positions = ["PG", "SG", "SF", "PF", "C"]
    for position in positions:
        home_player_gp = db.query(GamePlayer).filter(
            and_(
                GamePlayer.game_id == game.id,
                GamePlayer.team_side == "HOME",
                GamePlayer.position == position
            )
        ).first()
        
        away_player_gp = db.query(GamePlayer).filter(
            and_(
                GamePlayer.game_id == game.id,
                GamePlayer.team_side == "AWAY",
                GamePlayer.position == position
            )
        ).first()
        
        if home_player_gp and away_player_gp:
            matchup1 = Matchup(
                game_id=game.id,
                defender_player_id=home_player_gp.player_id,
                offender_player_id=away_player_gp.player_id,
                defender_position=position,
                offender_position=position,
                matchup_type="POSITIONAL"
            )
            db.add(matchup1)
            
            matchup2 = Matchup(
                game_id=game.id,
                defender_player_id=away_player_gp.player_id,
                offender_player_id=home_player_gp.player_id,
                defender_position=position,
                offender_position=position,
                matchup_type="POSITIONAL"
            )
            db.add(matchup2)


def fix_game_errors(game_id, dry_run=False, max_retries=3):
    """
    Fix data verification errors for a single game.
    Will retry if new errors appear after a fix, up to max_retries times.
    
    Args:
        game_id: The game ID to fix
        dry_run: If True, don't actually update games
        max_retries: Maximum number of retry attempts (default 3)
    
    Returns:
        dict with 'success', 'fixed', 'skipped', 'error', 'retry_count' keys
    """
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            return {"success": False, "error": f"Game {game_id} not found"}
        
        # Check if game has errors
        validation = validate_game_data(db, game.id)
        if not validation["needs_verification"]:
            return {"success": True, "fixed": False, "skipped": True, "reason": "No errors found", "retry_count": 0}
        
        # Check if screenshot exists
        screenshot_path = game.source_image_path
        if not screenshot_path or not os.path.exists(screenshot_path):
            return {
                "success": True,
                "fixed": False,
                "skipped": True,
                "reason": f"Screenshot not found: {screenshot_path}",
                "retry_count": 0
            }
        
        print(f"\n{'[DRY RUN] ' if dry_run else ''}Processing game {game.id}")
        print(f"  Initial errors found: {len(validation['warnings'])}")
        for warning in validation['warnings']:
            print(f"    - {warning}")
        
        if dry_run:
            return {
                "success": True,
                "fixed": False,
                "skipped": False,
                "reason": "Dry run - would retry extraction",
                "retry_count": 0
            }
        
        # Track retry attempts
        retry_count = 0
        previous_errors = set()  # Track errors we've already tried to fix
        all_errors_seen = set()
        
        while retry_count < max_retries:
            # Get current validation state
            current_validation = validate_game_data(db, game.id)
            if not current_validation["needs_verification"]:
                # No errors! Success!
                print(f"  ✓ All errors resolved after {retry_count} retry(ies)!")
                return {
                    "success": True,
                    "fixed": True,
                    "skipped": False,
                    "retry_count": retry_count,
                    "errors_before": len(validation["warnings"]),
                    "errors_after": 0
                }
            
            # Reconstruct current data to check integrity
            current_data = reconstruct_extracted_data(db, game)
            game_data_preview = {
                "away_score": game.away_score,
                "home_score": game.home_score
            }
            integrity_warnings = validate_integrity(game_data_preview, current_data)
            
            # Build list of critical errors for retry prompt
            critical_errors = []
            for warning in current_validation["warnings"]:
                if any(keyword in warning.lower() for keyword in [
                    "player points", "team total", "quarter scores", "final score",
                    "don't match", "exceeds", "missing stats"
                ]):
                    critical_errors.append(warning)
                    all_errors_seen.add(warning)
            
            # Also add integrity warnings
            for warning in integrity_warnings:
                if any(keyword in warning.lower() for keyword in [
                    "player points sum", "quarter scores sum"
                ]):
                    critical_errors.append(warning)
                    all_errors_seen.add(warning)
            
            if not critical_errors:
                # No critical errors that we can fix with retry
                print(f"  - No fixable errors found (retry {retry_count + 1}/{max_retries})")
                return {
                    "success": True,
                    "fixed": False,
                    "skipped": True,
                    "reason": "Errors found but not fixable with retry",
                    "retry_count": retry_count
                }
            
            # Check if we've seen these exact errors before (to avoid infinite loops)
            current_errors_set = set(critical_errors)
            if current_errors_set == previous_errors:
                print(f"  - Same errors persist after retry {retry_count}, stopping to avoid loop")
                break
            
            previous_errors = current_errors_set.copy()
            
            if retry_count == 0:
                print(f"  Retrying extraction with {len(critical_errors)} critical errors...")
            else:
                print(f"  Retry {retry_count + 1}/{max_retries}: Found {len(critical_errors)} new/fixed errors, retrying...")
                for error in critical_errors:
                    print(f"    - {error}")
            
            # Retry extraction
            try:
                extracted_data = extract_box_score(
                    screenshot_path,
                    retry_on_error=False,
                    validation_feedback=critical_errors
                )
                
                # Validate the new extraction
                is_valid, validation_warnings_new = validate_extraction(extracted_data)
                if not is_valid:
                    return {
                        "success": False,
                        "error": f"Retry extraction failed validation: {validation_warnings_new}",
                        "retry_count": retry_count
                    }
                
                # Check integrity of new data
                game_data_new = {
                    "away_score": extracted_data.get("game", {}).get("away_score", 0),
                    "home_score": extracted_data.get("game", {}).get("home_score", 0)
                }
                integrity_warnings_new = validate_integrity(game_data_new, extracted_data)
                
                # Update game with new data
                update_game_from_extracted_data(db, game, extracted_data)
                db.commit()
                
                # Re-validate to check for new errors
                validation_after = validate_game_data(db, game.id)
                
                if not validation_after["needs_verification"]:
                    # All errors fixed!
                    print(f"  ✓ All errors resolved after {retry_count + 1} retry(ies)!")
                    return {
                        "success": True,
                        "fixed": True,
                        "skipped": False,
                        "retry_count": retry_count + 1,
                        "errors_before": len(validation["warnings"]),
                        "errors_after": 0
                    }
                
                # Check if we have new errors (not just the same ones)
                new_errors = []
                for warning in validation_after["warnings"]:
                    if warning not in all_errors_seen:
                        new_errors.append(warning)
                
                if new_errors:
                    print(f"  ⚠ Found {len(new_errors)} new errors after retry:")
                    for error in new_errors:
                        print(f"    - {error}")
                    all_errors_seen.update(new_errors)
                
                retry_count += 1
                
                # If we've hit max retries, return current state
                if retry_count >= max_retries:
                    print(f"  - Reached max retries ({max_retries}), stopping")
                    return {
                        "success": True,
                        "fixed": len(validation_after["warnings"]) < len(validation["warnings"]),
                        "skipped": False,
                        "retry_count": retry_count,
                        "errors_before": len(validation["warnings"]),
                        "errors_after": len(validation_after["warnings"]),
                        "warnings_after": validation_after["warnings"]
                    }
                
                # Continue loop to retry with new errors
                continue
                
            except Exception as e:
                db.rollback()
                return {
                    "success": False,
                    "error": f"Retry extraction failed: {str(e)}",
                    "retry_count": retry_count
                }
        
        # If we exit the loop, check final state
        final_validation = validate_game_data(db, game.id)
        return {
            "success": True,
            "fixed": not final_validation["needs_verification"],
            "skipped": False,
            "retry_count": retry_count,
            "errors_before": len(validation["warnings"]),
            "errors_after": len(final_validation["warnings"]),
            "warnings_after": final_validation["warnings"]
        }
            
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e), "retry_count": 0}
    finally:
        db.close()


def main():
    """
    Main function to process all games with data verification errors.
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Fix data verification errors in games by retrying extraction"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually update games, just show what would be fixed"
    )
    parser.add_argument(
        "--game-id",
        type=str,
        help="Process only a specific game ID"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of games to process"
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum number of retry attempts per game (default: 3)"
    )
    
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        if args.game_id:
            # Process single game
            games = [db.query(Game).filter(Game.id == args.game_id).first()]
            if not games[0]:
                print(f"Game {args.game_id} not found")
                return
        else:
            # Get all games
            games = db.query(Game).all()
            if args.limit:
                games = games[:args.limit]
        
        print(f"Found {len(games)} games to check")
        
        # Find games with errors
        games_with_errors = []
        for game in games:
            validation = validate_game_data(db, game.id)
            if validation["needs_verification"]:
                games_with_errors.append((game, validation))
        
        print(f"Found {len(games_with_errors)} games with verification errors")
        
        if not games_with_errors:
            print("No games with errors found!")
            return
        
        # Process each game
        results = {
            "total": len(games_with_errors),
            "fixed": 0,
            "skipped": 0,
            "failed": 0
        }
        
        for game, validation in games_with_errors:
            result = fix_game_errors(game.id, dry_run=args.dry_run, max_retries=args.max_retries)
            
            if result["success"]:
                if result.get("fixed"):
                    results["fixed"] += 1
                    retry_info = f" ({result.get('retry_count', 0)} retries)" if result.get('retry_count', 0) > 0 else ""
                    print(f"✓ Game {game.id}: FIXED{retry_info} ({result.get('errors_before', 0)} → {result.get('errors_after', 0)} errors)")
                elif result.get("skipped"):
                    results["skipped"] += 1
                    print(f"- Game {game.id}: SKIPPED ({result.get('reason', 'unknown')})")
                else:
                    results["skipped"] += 1
                    retry_info = f" ({result.get('retry_count', 0)} retries)" if result.get('retry_count', 0) > 0 else ""
                    print(f"- Game {game.id}: PARTIALLY FIXED{retry_info} ({result.get('errors_before', 0)} → {result.get('errors_after', 0)} errors)")
            else:
                results["failed"] += 1
                retry_info = f" (after {result.get('retry_count', 0)} retries)" if result.get('retry_count', 0) > 0 else ""
                print(f"✗ Game {game.id}: FAILED{retry_info} - {result.get('error', 'unknown error')}")
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Total games checked: {results['total']}")
        print(f"Fixed: {results['fixed']}")
        print(f"Skipped: {results['skipped']}")
        print(f"Failed: {results['failed']}")
        
    finally:
        db.close()


if __name__ == "__main__":
    main()
