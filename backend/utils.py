"""
Utility functions for hashing, validation, and helper operations.
"""
import hashlib
import os
import uuid
from pathlib import Path
from typing import List, Dict, Any


def compute_sha256(file_path: str) -> str:
    """
    Compute SHA256 hash of a file.
    
    Args:
        file_path: Path to the file to hash
        
    Returns:
        Hexadecimal SHA256 hash string
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def save_uploaded_file(file, upload_dir: str) -> str:
    """
    Save an uploaded file to the upload directory with a unique name.
    
    Args:
        file: File object from Flask request
        upload_dir: Directory to save the file to
        
    Returns:
        Full path to the saved file
    """
    # Ensure upload directory exists
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    
    # Generate unique filename
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".png"
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(upload_dir, unique_filename)
    
    # Save file
    file.save(file_path)
    
    return file_path


def validate_extraction(extracted_data: Dict[str, Any]) -> tuple[bool, List[str]]:
    """
    Validate the extracted data structure and content.
    
    Args:
        extracted_data: The JSON payload from OpenAI extraction
        
    Returns:
        Tuple of (is_valid, list_of_warnings)
    """
    warnings = []
    
    # Check for required top-level keys
    required_keys = ["game", "teams", "players"]
    for key in required_keys:
        if key not in extracted_data:
            return False, [f"Missing required key: {key}"]
    
    # Validate exactly 10 players (5 per side)
    players = extracted_data.get("players", [])
    if len(players) != 10:
        warnings.append(f"Expected 10 players, found {len(players)}")
    
    # Validate 5 players per side
    away_players = [p for p in players if p.get("side") == "AWAY"]
    home_players = [p for p in players if p.get("side") == "HOME"]
    
    if len(away_players) != 5:
        warnings.append(f"Expected 5 AWAY players, found {len(away_players)}")
    if len(home_players) != 5:
        warnings.append(f"Expected 5 HOME players, found {len(home_players)}")
    
    # Validate row_index uniqueness per side
    away_indices = [p.get("row_index") for p in away_players]
    home_indices = [p.get("row_index") for p in home_players]
    
    if len(away_indices) != len(set(away_indices)):
        warnings.append("Duplicate row_index found in AWAY players")
    if len(home_indices) != len(set(home_indices)):
        warnings.append("Duplicate row_index found in HOME players")
    
    # Validate row_index range (0-4)
    for player in players:
        row_idx = player.get("row_index")
        if row_idx is None or not (0 <= row_idx <= 4):
            warnings.append(f"Invalid row_index {row_idx} for player {player.get('gamertag')}")
    
    # Validate exactly 2 teams
    teams = extracted_data.get("teams", [])
    if len(teams) != 2:
        warnings.append(f"Expected 2 teams, found {len(teams)}")
    
    team_sides = [t.get("side") for t in teams]
    if "AWAY" not in team_sides:
        warnings.append("Missing AWAY team")
    if "HOME" not in team_sides:
        warnings.append("Missing HOME team")
    
    return True, warnings


def validate_integrity(game_data: Dict[str, Any], extracted_data: Dict[str, Any]) -> List[str]:
    """
    Perform integrity checks on the data (warnings only, not failures).
    
    Args:
        game_data: The game record data
        extracted_data: The extracted JSON payload
        
    Returns:
        List of warning messages
    """
    warnings = []
    
    # Check quarter scores sum to final score
    away_quarters = extracted_data.get("game", {}).get("quarters", {}).get("away", [])
    home_quarters = extracted_data.get("game", {}).get("quarters", {}).get("home", [])
    
    if away_quarters and len(away_quarters) == 4:
        away_sum = sum(q for q in away_quarters if q is not None)
        if away_sum != game_data.get("away_score", 0):
            warnings.append(f"AWAY quarter scores sum ({away_sum}) != final score ({game_data.get('away_score')})")
    
    if home_quarters and len(home_quarters) == 4:
        home_sum = sum(q for q in home_quarters if q is not None)
        if home_sum != game_data.get("home_score", 0):
            warnings.append(f"HOME quarter scores sum ({home_sum}) != final score ({game_data.get('home_score')})")
    
    # Check player points sum to team totals
    players = extracted_data.get("players", [])
    teams = extracted_data.get("teams", [])
    
    for team in teams:
        team_side = team.get("side")
        team_pts = team.get("totals", {}).get("pts", 0)
        
        team_players = [p for p in players if p.get("side") == team_side]
        player_pts_sum = sum(p.get("stats", {}).get("pts", 0) for p in team_players)
        
        if player_pts_sum != team_pts:
            warnings.append(
                f"{team_side} team: player points sum ({player_pts_sum}) != team total ({team_pts})"
            )
    
    return warnings


def clean_gamertag(gamertag: str) -> str:
    """
    Clean gamertag by removing unwanted symbols and characters.
    
    Args:
        gamertag: The raw gamertag string
        
    Returns:
        Cleaned gamertag string
    """
    if not gamertag:
        return gamertag
    
    # Remove the 🔊 symbol and any other unwanted characters
    cleaned = gamertag.replace("🔊", "").strip()
    
    return cleaned


def calculate_missing_3pm(pts: int, fgm: int, ftm: int, tpm: int = None) -> int:
    """
    Calculate 3-point field goals made (3PM) if missing, based on points and field goals.
    
    Formula: PTS = 2*2PM + 3*3PM + 1*FTM
    Since FGM = 2PM + 3PM, we get: 3PM = PTS - 2*FGM - FTM
    
    Args:
        pts: Total points scored
        fgm: Total field goals made
        ftm: Free throws made
        tpm: Current 3-point field goals made (if already set, return as-is)
        
    Returns:
        Calculated 3PM, or existing tpm if provided
    """
    # If 3PM is already provided and > 0, use it
    if tpm is not None and tpm > 0:
        return tpm
    
    # Calculate: 3PM = PTS - 2*FGM - FTM
    calculated_3pm = pts - (2 * fgm) - ftm
    
    # Validate the result makes sense
    # 3PM can't be negative, can't exceed FGM, and must be an integer
    if calculated_3pm < 0:
        return 0  # Can't have negative 3PM
    if calculated_3pm > fgm:
        return fgm  # Can't have more 3PM than total FGM
    
    return int(calculated_3pm)


def assign_position(row_index: int) -> str:
    """
    Assign position based on row index (0=PG, 1=SG, 2=SF, 3=PF, 4=C).
    
    Args:
        row_index: The row index (0-4)
        
    Returns:
        Position string (PG, SG, SF, PF, C)
    """
    positions = ["PG", "SG", "SF", "PF", "C"]
    if 0 <= row_index <= 4:
        return positions[row_index]
    raise ValueError(f"Invalid row_index: {row_index}. Must be 0-4.")

