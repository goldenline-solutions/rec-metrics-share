"""
Core ingestion service that orchestrates the box score extraction and database storage.
"""
import os
import logging
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session
from sqlalchemy import and_

from models import (
    Game, Player, GamePlayer, PlayerGameStats, TeamTotal, Matchup,
    CURRENT_GAME_VERSION
)
from openai_client import extract_box_score
from utils import (
    compute_sha256, save_uploaded_file, validate_extraction,
    validate_integrity, assign_position, clean_gamertag, calculate_missing_3pm
)
from identity_resolver import resolve_game_players
from name_utils import normalize_name


def _looks_like_icon_before_name(ch: str) -> bool:
    """
    Return True only for explicit leading symbols that represent platform icons.
    Keep this strict to avoid false positives on normal gamertag punctuation.
    """
    if not ch:
        return False

    icon_like_chars = {
        "0",  # OCR often maps the circular platform icon to zero
    }
    return ch in icon_like_chars


def strip_leading_platform_icons(s: str) -> str:
    """
    Remove leading characters that look like platform icons (e.g. before gamertags).
    Used so we store clean names while still having used the raw string for console detection.
    """
    if not s:
        return s
    s = s.strip()
    while s and _looks_like_icon_before_name(s[0]):
        s = s[1:].lstrip()
    return s


def count_leading_platform_icons_in_players(extracted_data: Dict[str, Any]) -> int:
    """
    Count how many players have a leading platform icon (box/symbol) before their gamertag.
    Used to set Console when more than 4 names had an icon stripped.
    """
    players = extracted_data.get("players", [])
    count = 0
    for player in players:
        raw = (player.get("gamertag") or "").strip()
        if not raw:
            continue
        stripped = strip_leading_platform_icons(raw)
        if stripped != raw:
            count += 1
    return count


def detect_console_platform_from_players(extracted_data: Dict[str, Any]) -> bool:
    """
    Inspect extracted players and return True if this looks like a console
    scoreboard (any non-text icon/symbol in front of most gamertags). Used as
    fallback when the vision model does not set metadata.platform_hint.
    We treat any character that isn't a letter, number, or typical symbol as
    an icon - no specific emoji required.
    """
    players = extracted_data.get("players", [])
    if not players:
        return False

    icon_leading_count = 0
    total_with_names = 0

    for player in players:
        raw = (player.get("gamertag") or "").strip()
        if not raw:
            continue
        total_with_names += 1

        # Look at the first non-space character
        first_non_space = next((c for c in raw if not c.isspace()), "")
        if first_non_space and _looks_like_icon_before_name(first_non_space):
            logger.info("[ingest] Icon detected before name: %r (first char: %r U+%04X)", raw, first_non_space, ord(first_non_space))
            icon_leading_count += 1

    if total_with_names == 0:
        return False

    # Require a strong majority (e.g., at least 7 of 10 players)
    return icon_leading_count >= 7


def check_duplicate_game(
    db: Session,
    extracted_data: Dict[str, Any]
) -> Optional[Game]:
    """
    Check if a game with identical players in same positions and same scores already exists.
    
    Args:
        db: Database session
        extracted_data: Extracted game data from OpenAI
        
    Returns:
        Existing Game object if duplicate found, None otherwise
    """
    game_data = extracted_data.get("game", {})
    players_data = extracted_data.get("players", [])
    
    # Extract scores
    away_score = game_data.get("away_score")
    home_score = game_data.get("home_score")
    
    if away_score is None or home_score is None:
        return None
    
    # Build a signature: list of (gamertag, position, team_side) tuples
    # Strip leading platform icons before normalizing so signature matches stored names
    new_game_signature = []
    for player_data in players_data:
        raw_gamertag = player_data.get("gamertag", "").strip()
        stripped = strip_leading_platform_icons(raw_gamertag)
        gamertag = clean_gamertag(stripped)
        team_side = player_data.get("side")
        row_index = player_data.get("row_index", 0)
        position = assign_position(row_index)
        
        if gamertag and team_side:
            new_game_signature.append((team_side, position, gamertag.lower()))
    
    # Sort for consistent comparison
    new_game_signature.sort()
    
    # Get all games with matching scores
    candidate_games = db.query(Game).filter(
        and_(
            Game.away_score == away_score,
            Game.home_score == home_score
        )
    ).all()
    
    # For each candidate game, check if players match
    for candidate_game in candidate_games:
        # Get all players for this game with their positions (using join to get player data)
        game_players = db.query(GamePlayer, Player).join(
            Player, GamePlayer.player_id == Player.id
        ).filter(
            GamePlayer.game_id == candidate_game.id
        ).all()
        
        if len(game_players) != len(new_game_signature):
            continue  # Different number of players, can't be duplicate
        
        # Build signature for candidate game
        candidate_signature = []
        for gp, player in game_players:
            candidate_signature.append((
                gp.team_side,
                gp.position,
                player.gamertag.lower()
            ))
        
        candidate_signature.sort()
        
        # Compare signatures
        if candidate_signature == new_game_signature:
            return candidate_game
    
    return None


def ingest_box_score(
    db: Session,
    file,
    upload_dir: str,
    season_label: Optional[str] = None,
    mode_label: Optional[str] = None,
    uploader_user_id: Optional[str] = None,
    platform: Optional[str] = None
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Main ingestion function that processes a screenshot and stores the data.
    
    Args:
        db: Database session
        file: Uploaded file object from Flask
        upload_dir: Directory to save uploaded files
        season_label: Optional season label from form data
        mode_label: Optional mode label from form data
        
    Returns:
        Tuple of (response_dict, warnings_list)
    """
    warnings = []
    
    # Step 1: Save image file
    file_path = save_uploaded_file(file, upload_dir)
    
    try:
        # Step 2: Compute SHA256 and check for idempotency
        image_hash = compute_sha256(file_path)
        
        existing_game = db.query(Game).filter(
            Game.source_image_sha256 == image_hash
        ).first()
        
        if existing_game:
            # Delete the file since it's a duplicate (same hash)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            # Return existing game
            return {
                "game_id": existing_game.id,
                "stored": False,
                "message": "Game already ingested with this image hash",
                "payload": _build_payload(db, existing_game.id),
                "platform_from_screenshot": None,
            }, []
        
        # Step 3: Call OpenAI extractor
        extracted_data = extract_box_score(file_path)
        
        # Step 4: Validate extraction
        is_valid, validation_warnings = validate_extraction(extracted_data)
        warnings.extend(validation_warnings)
        
        # Step 4.5: If validation failed, retry extraction with enhanced prompt
        if not is_valid:
            # Retry extraction with validation feedback to help fix the errors
            logger.info("Initial extraction validation failed. Retrying with validation feedback: %s", validation_warnings)
            try:
                extracted_data = extract_box_score(
                    file_path, 
                    retry_on_error=False,  # Don't retry API errors, we're handling validation retry
                    validation_feedback=validation_warnings
                )
                
                # Re-validate the retry attempt
                is_valid, validation_warnings_retry = validate_extraction(extracted_data)
                warnings.extend(validation_warnings_retry)
                
                if not is_valid:
                    # Still failed after retry, raise error
                    raise ValueError(
                        f"Extraction validation failed after retry. "
                        f"Initial errors: {validation_warnings}. "
                        f"Retry errors: {validation_warnings_retry}"
                    )
                else:
                    # Success on retry - add a note to warnings
                    warnings.append("Extraction succeeded on retry after validation feedback")
            except Exception as retry_error:
                # If retry extraction itself fails, raise with original validation errors
                raise ValueError(
                    f"Extraction validation failed: {validation_warnings}. "
                    f"Retry attempt also failed: {str(retry_error)}"
                )
        
        # Step 4.6: Early integrity check - check for data consistency issues before creating game
        # This allows us to retry if there are critical data mismatches
        game_data_preview = {
            "away_score": extracted_data.get("game", {}).get("away_score", 0),
            "home_score": extracted_data.get("game", {}).get("home_score", 0)
        }
        integrity_warnings_early = validate_integrity(game_data_preview, extracted_data)
        
        # Check for critical integrity issues that should trigger a retry
        critical_integrity_issues = [
            warn for warn in integrity_warnings_early 
            if "player points sum" in warn.lower() or "quarter scores sum" in warn.lower()
        ]
        
        if critical_integrity_issues:
            # Retry extraction with integrity feedback
            logger.info("Early integrity check found critical data mismatches. Retrying with feedback: %s", critical_integrity_issues)
            try:
                extracted_data = extract_box_score(
                    file_path,
                    retry_on_error=False,
                    validation_feedback=critical_integrity_issues
                )
                
                # Re-validate both structure and integrity
                is_valid, validation_warnings_retry = validate_extraction(extracted_data)
                warnings.extend(validation_warnings_retry)
                
                if not is_valid:
                    raise ValueError(
                        f"Extraction validation failed after integrity retry. "
                        f"Integrity errors: {critical_integrity_issues}. "
                        f"Validation errors: {validation_warnings_retry}"
                    )
                
                # Re-check integrity after retry
                game_data_preview_retry = {
                    "away_score": extracted_data.get("game", {}).get("away_score", 0),
                    "home_score": extracted_data.get("game", {}).get("home_score", 0)
                }
                integrity_warnings_retry = validate_integrity(game_data_preview_retry, extracted_data)
                
                # Check if critical issues were resolved
                critical_issues_after_retry = [
                    warn for warn in integrity_warnings_retry
                    if "player points sum" in warn.lower() or "quarter scores sum" in warn.lower()
                ]
                
                if critical_issues_after_retry:
                    # Still have critical issues, but continue with warnings
                    warnings.append(f"Critical integrity issues persist after retry: {critical_issues_after_retry}")
                else:
                    warnings.append("Extraction succeeded on retry after integrity feedback")
                
                # Use the retry warnings (may be empty if fixed)
                integrity_warnings_early = integrity_warnings_retry
                
            except Exception as retry_error:
                # If retry fails, continue with original data but add warning
                warnings.append(f"Integrity retry failed: {str(retry_error)}. Continuing with original extraction.")
        
        # Add non-critical integrity warnings
        warnings.extend(integrity_warnings_early)
        
        # Step 5: Check for duplicate game based on players and scores
        duplicate_game = check_duplicate_game(db, extracted_data)
        if duplicate_game:
            # Clean up uploaded file since we're not using it
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            # Return existing game
            meta = extracted_data.get("metadata", {}) or {}
            dup_platform_hint = (meta.get("platform_hint") or "").strip() or None
            return {
                "game_id": duplicate_game.id,
                "stored": False,
                "message": "Duplicate game found: same players in same positions with same scores",
                "payload": _build_payload(db, duplicate_game.id),
                "platform_from_screenshot": dup_platform_hint,
            }, []
        
        # Step 6: Extract metadata and override with form data if provided
        metadata = extracted_data.get("metadata", {})
        final_season_label = season_label or metadata.get("season_label")
        final_mode_label = mode_label or metadata.get("mode_label")

        # Detect platform from screenshot, not uploader profile.
        metadata_for_platform = extracted_data.get("metadata", {}) or {}
        platform_hint_raw = (metadata_for_platform.get("platform_hint") or "").strip() or None
        has_icons_before_names = metadata_for_platform.get("has_platform_icons_before_names")
        stripped_icon_count = count_leading_platform_icons_in_players(extracted_data)

        detected_platform = "Console" if stripped_icon_count > 4 else "PC"
        warnings.append(
            "Platform set to "
            f"{detected_platform} ({stripped_icon_count} names had leading icon stripped; metadata.has_platform_icons_before_names={has_icons_before_names}, metadata.platform_hint={platform_hint_raw})."
        )

        platform = detected_platform
        
        # Step 7: Create game record
        game_data = extracted_data.get("game", {})
        quarters = game_data.get("quarters", {})
        
        game = Game(
            season_label=final_season_label,
            mode_label=final_mode_label,
            away_score=game_data.get("away_score", 0),
            home_score=game_data.get("home_score", 0),
            away_q1=quarters.get("away", [None] * 4)[0] if len(quarters.get("away", [])) > 0 else None,
            away_q2=quarters.get("away", [None] * 4)[1] if len(quarters.get("away", [])) > 1 else None,
            away_q3=quarters.get("away", [None] * 4)[2] if len(quarters.get("away", [])) > 2 else None,
            away_q4=quarters.get("away", [None] * 4)[3] if len(quarters.get("away", [])) > 3 else None,
            home_q1=quarters.get("home", [None] * 4)[0] if len(quarters.get("home", [])) > 0 else None,
            home_q2=quarters.get("home", [None] * 4)[1] if len(quarters.get("home", [])) > 1 else None,
            home_q3=quarters.get("home", [None] * 4)[2] if len(quarters.get("home", [])) > 2 else None,
            home_q4=quarters.get("home", [None] * 4)[3] if len(quarters.get("home", [])) > 3 else None,
            source_image_path=file_path,
            source_image_sha256=image_hash,
            platform=platform,
            game_version=CURRENT_GAME_VERSION,
            uploaded_by_user_id=uploader_user_id
        )
        db.add(game)
        db.flush()  # Get game.id without committing
        
        # Step 8: Upsert players and create game_players + player_stats
        players_data = extracted_data.get("players", [])
        player_map = {}  # gamertag -> Player object
        
        for player_data in players_data:
            raw_gamertag = player_data.get("gamertag")
            if not raw_gamertag:
                continue
            # Strip leading platform icons (e.g. PlayStation) so we store clean names
            raw_stripped = (raw_gamertag or "").strip()
            stripped = strip_leading_platform_icons(raw_stripped)
            if stripped != raw_stripped:
                logger.info("[ingest] Stripped leading icon: %r -> %r", raw_stripped, stripped)
            # Clean the gamertag (remove unwanted symbols)
            gamertag = clean_gamertag(stripped)
            if not gamertag:
                continue
            
            # Upsert player
            player = db.query(Player).filter(Player.gamertag == gamertag).first()
            if not player:
                player = Player(gamertag=gamertag)
                db.add(player)
                db.flush()
            player_map[gamertag] = player
            
            # Assign position based on row_index
            row_index = player_data.get("row_index", 0)
            position = assign_position(row_index)
            team_side = player_data.get("side")
            
            # Create game_player record (store game's platform so players in this game are tagged as Console/PC)
            game_player = GamePlayer(
                game_id=game.id,
                player_id=player.id,
                team_side=team_side,
                position=position,
                row_index=row_index,
                platform=platform
            )
            db.add(game_player)
            
            # Create player_game_stats record
            stats = player_data.get("stats", {})
            
            # Extract base stats
            pts = stats.get("pts", 0)
            fgm = stats.get("fgm", 0)
            ftm = stats.get("ftm", 0)
            tpm = stats.get("tpm", 0)
            
            # Calculate missing 3PM if not detected (blocked in screenshot)
            # Only calculate if tpm is 0 or None and we have the necessary data
            if (tpm is None or tpm == 0) and pts > 0 and fgm > 0:
                calculated_tpm = calculate_missing_3pm(pts, fgm, ftm, tpm)
                if calculated_tpm > 0:
                    tpm = calculated_tpm
                    # Add warning that we calculated this value
                    warnings.append(
                        f"Calculated 3PM ({tpm}) for player {gamertag} based on PTS, FGM, and FTM"
                    )
            
            player_stats = PlayerGameStats(
                game_id=game.id,
                player_id=player.id,
                grade=player_data.get("grade"),
                pts=pts,
                reb=stats.get("reb", 0),
                ast=stats.get("ast", 0),
                stl=stats.get("stl", 0),
                blk=stats.get("blk", 0),
                fouls=stats.get("fouls", 0),
                tov=stats.get("tov", 0),
                fgm=fgm,
                fga=stats.get("fga", 0),
                tpm=tpm,
                tpa=stats.get("tpa", 0),
                ftm=ftm,
                fta=stats.get("fta", 0)
            )
            db.add(player_stats)
        
        # Step 9: Create team_totals records
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
        
        # Step 10: Generate matchups (always ensure exactly 10 positional matchups)
        # Delete any existing matchups first to ensure clean state
        db.query(Matchup).filter(Matchup.game_id == game.id).delete()
        
        # Always generate exactly 10 positional matchups (5 positions x 2 directions)
        # For each position, create two matchups:
        # - HOME defender vs AWAY offender at same position
        # - AWAY defender vs HOME offender at same position
        positions = ["PG", "SG", "SF", "PF", "C"]
        
        for position in positions:
            # Find players at this position for each team
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
                # HOME defender vs AWAY offender
                matchup1 = Matchup(
                    game_id=game.id,
                    defender_player_id=home_player_gp.player_id,
                    offender_player_id=away_player_gp.player_id,
                    defender_position=position,
                    offender_position=position,
                    matchup_type="POSITIONAL"
                )
                db.add(matchup1)
                
                # AWAY defender vs HOME offender
                matchup2 = Matchup(
                    game_id=game.id,
                    defender_player_id=away_player_gp.player_id,
                    offender_player_id=home_player_gp.player_id,
                    defender_position=position,
                    offender_position=position,
                    matchup_type="POSITIONAL"
                )
                db.add(matchup2)
        
        # Step 11: Final integrity check (already done earlier, but verify with final game data)
        # Note: Early integrity check at Step 4.6 already handled retries for critical issues
        game_dict = {
            "away_score": game.away_score,
            "home_score": game.home_score
        }
        integrity_warnings_final = validate_integrity(game_dict, extracted_data)
        # Only add warnings that weren't already caught in the early check
        # (This is mainly for consistency verification with the final stored data)
        for warn in integrity_warnings_final:
            if warn not in warnings:
                warnings.append(warn)
        
        # Step 12: Build response payload
        # Note: db.flush() was called earlier, so data is available in this transaction
        payload = _build_payload(db, game.id, extracted_data)
        
        # Step 13: Delete the screenshot file after successful ingestion
        # The file path is already stored in the database, so we can safely delete it
        # if os.path.exists(file_path):
        #     try:
        #         os.remove(file_path)
        #     except Exception as e:
        #         # Log warning but don't fail the ingestion if file deletion fails
        #         warnings.append(f"Warning: Could not delete uploaded file: {str(e)}")
        
        # Step 14: Transaction will be committed by context manager in app.py
        
        return {
            "game_id": game.id,
            "stored": True,
            "payload": payload,
            "platform_from_screenshot": platform,
        }, warnings
        
    except Exception as e:
        db.rollback()
        # Clean up uploaded file on error
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        raise


def _build_payload(
    db: Session,
    game_id: str,
    extracted_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build the complete payload response including extracted data, positions, and matchups.
    
    Args:
        db: Database session
        game_id: The game ID
        extracted_data: Optional extracted data (if available, use it; otherwise query DB)
        
    Returns:
        Complete payload dictionary
    """
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise ValueError(f"Game {game_id} not found")
    
    # If extracted_data provided, use it as base; otherwise reconstruct from DB
    if extracted_data is None or not extracted_data:
        # Reconstruct full payload from database
        # Get teams
        team_totals = db.query(TeamTotal).filter(TeamTotal.game_id == game_id).all()
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
        game_players = db.query(GamePlayer).filter(GamePlayer.game_id == game_id).all()
        players_data = []
        for gp in game_players:
            player = db.query(Player).filter(Player.id == gp.player_id).first()
            stats = db.query(PlayerGameStats).filter(
                PlayerGameStats.game_id == game_id,
                PlayerGameStats.player_id == gp.player_id
            ).first()
            
            if player and stats:
                players_data.append({
                    "side": gp.team_side,
                    "row_index": gp.row_index,
                    "gamertag": player.gamertag,
                    "grade": stats.grade,
                    "assigned_position": gp.position,
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
        
        # Get matchups
        matchups = db.query(Matchup).filter(Matchup.game_id == game_id).all()
        matchup_list = []
        for matchup in matchups:
            defender = db.query(Player).filter(Player.id == matchup.defender_player_id).first()
            offender = db.query(Player).filter(Player.id == matchup.offender_player_id).first()
            if defender and offender:
                matchup_list.append({
                    "defender_gamertag": defender.gamertag,
                    "offender_gamertag": offender.gamertag,
                    "defender_position": matchup.defender_position,
                    "offender_position": matchup.offender_position,
                    "matchup_type": matchup.matchup_type
                })
        
        # Build complete payload
        payload = {
            "metadata": {
                "season_label": game.season_label,
                "mode_label": game.mode_label,
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
            "matchups": matchup_list
        }
    else:
        # Use provided extracted_data as base
        payload = extracted_data.copy()
        
        # Add positions to players in payload if not already present
        if "players" in payload:
            for player_data in payload["players"]:
                if "assigned_position" not in player_data:
                    row_index = player_data.get("row_index", 0)
                    player_data["assigned_position"] = assign_position(row_index)
        
        # Add matchups to payload (query from DB to ensure we have all matchups)
        matchups = db.query(Matchup).filter(Matchup.game_id == game_id).all()
        matchup_list = []
        for matchup in matchups:
            defender = db.query(Player).filter(Player.id == matchup.defender_player_id).first()
            offender = db.query(Player).filter(Player.id == matchup.offender_player_id).first()
            if defender and offender:
                matchup_list.append({
                    "defender_gamertag": defender.gamertag,
                    "offender_gamertag": offender.gamertag,
                    "defender_position": matchup.defender_position,
                    "offender_position": matchup.offender_position,
                    "matchup_type": matchup.matchup_type
                })
        
        payload["matchups"] = matchup_list
    
    return payload

