"""
Identity resolution service for matching detected player names to known identities.
Uses exact matching, variant matching, and fuzzy matching to link names to players.
"""
from typing import Dict, Any, Optional, Tuple, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from name_utils import normalize_name
from models import GamePlayer, PlayerIdentity, PlayerNameVariant, NameClaim

# Try to import rapidfuzz, fallback to difflib
try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
except ImportError:
    try:
        from difflib import SequenceMatcher
        HAS_RAPIDFUZZ = False
    except ImportError:
        HAS_RAPIDFUZZ = False
        SequenceMatcher = None


def get_fuzzy_score(name1: str, name2: str) -> float:
    """
    Calculate fuzzy matching score between two names.
    Returns a score from 0.0 to 100.0.
    
    Args:
        name1: First name (normalized)
        name2: Second name (normalized)
        
    Returns:
        Similarity score (0.0 to 100.0)
    """
    if HAS_RAPIDFUZZ:
        # Use rapidfuzz for better performance
        return fuzz.ratio(name1, name2)
    elif SequenceMatcher:
        # Fallback to difflib
        return SequenceMatcher(None, name1, name2).ratio() * 100.0
    else:
        # Last resort: simple character matching
        if name1 == name2:
            return 100.0
        # Simple Levenshtein-like calculation
        return 0.0


def find_player_identity(
    db: Session,
    detected_raw_name: str,
    uploader_user_id: Optional[str] = None,
    platform: Optional[str] = None
) -> Tuple[Optional[int], Optional[int], str, int, bool]:
    """
    Resolve a detected player name to a player identity.
    
    This function:
    1. Normalizes the detected name
    2. Tries exact match in player_name_variants
    3. Tries fuzzy match if no exact match
    4. Creates new player identity if no match found
    5. Optionally tries to match against user's verified claims (filtered by platform)
    
    Args:
        db: Database session
        detected_raw_name: Raw name as detected from OCR
        uploader_user_id: Optional user ID of the uploader (for claim matching)
        platform: Optional platform ('PC' or 'Console') to filter claims by
        
    Returns:
        Tuple of:
        - player_id_identity: ID of matched player identity (or None)
        - claim_id: ID of matched claim (or None)
        - match_method: 'exact', 'variant', 'fuzzy', 'manual', or 'none'
        - match_confidence: 0-100 confidence score
        - needs_review: Whether this match needs manual review
    """
    # Normalize the detected name
    detected_norm = normalize_name(detected_raw_name)
    
    if not detected_norm:
        return None, None, 'none', 0, False
    
    # Step 1: Try exact match in player_name_variants
    exact_match = db.query(PlayerNameVariant).filter(
        PlayerNameVariant.norm_name == detected_norm
    ).first()
    
    if exact_match:
        player_id = exact_match.player_id
        # Update variant seen_count and last_seen_at
        from datetime import datetime
        exact_match.seen_count += 1
        exact_match.last_seen_at = datetime.utcnow().isoformat()
        db.flush()
        
        # Check if there's a verified claim for this player (filtered by platform if provided)
        claim_id = None
        if uploader_user_id:
            claim_query = db.query(NameClaim).filter(
                NameClaim.player_id == player_id,
                NameClaim.user_id == uploader_user_id,
                NameClaim.status == 'verified'
            )
            if platform:
                claim_query = claim_query.filter(NameClaim.platform == platform)
            claim = claim_query.first()
            if claim:
                claim_id = claim.id
        
        return player_id, claim_id, 'exact', 100, False
    
    # Step 2: Try fuzzy match
    # First, narrow candidates by prefix (first 2-3 chars)
    prefix = detected_norm[:3] if len(detected_norm) >= 3 else detected_norm
    
    candidates = db.query(PlayerNameVariant).filter(
        PlayerNameVariant.norm_name.like(f"{prefix}%")
    ).limit(200).all()
    
    if candidates:
        # Calculate fuzzy scores for all candidates
        scored_candidates = []
        for candidate in candidates:
            score = get_fuzzy_score(detected_norm, candidate.norm_name)
            scored_candidates.append((score, candidate.player_id, candidate.norm_name, candidate.raw_name))
        
        # Sort by score (descending)
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        
        if scored_candidates:
            top_score, top_player_id, top_norm, top_raw = scored_candidates[0]
            
            # Acceptance rules:
            # - score >= 95
            # - top score is at least 3 points higher than second best
            if top_score >= 95:
                second_score = scored_candidates[1][0] if len(scored_candidates) > 1 else 0
                score_diff = top_score - second_score
                
                if score_diff >= 3:
                    # Good match! Add this variant to the player
                    from datetime import datetime
                    new_variant = PlayerNameVariant(
                        player_id=top_player_id,
                        raw_name=detected_raw_name,
                        norm_name=detected_norm,
                        first_seen_at=datetime.utcnow().isoformat(),
                        last_seen_at=datetime.utcnow().isoformat(),
                        seen_count=1
                    )
                    db.add(new_variant)
                    db.flush()
                    
                    # Check for verified claim (filtered by platform if provided)
                    claim_id = None
                    if uploader_user_id:
                        claim_query = db.query(NameClaim).filter(
                            NameClaim.player_id == top_player_id,
                            NameClaim.user_id == uploader_user_id,
                            NameClaim.status == 'verified'
                        )
                        if platform:
                            claim_query = claim_query.filter(NameClaim.platform == platform)
                        claim = claim_query.first()
                        if claim:
                            claim_id = claim.id
                    
                    return top_player_id, claim_id, 'fuzzy', int(top_score), False
                else:
                    # Ambiguous match - needs review
                    return None, None, 'none', int(top_score), True
    
    # Step 3: No match found - create new player identity
    from datetime import datetime
    new_player = PlayerIdentity(
        canonical_name=detected_raw_name,
        canonical_norm=detected_norm,
        created_at=datetime.utcnow().isoformat()
    )
    db.add(new_player)
    db.flush()
    new_player_id = new_player.id
    
    # Insert into player_name_variants
    new_variant = PlayerNameVariant(
        player_id=new_player_id,
        raw_name=detected_raw_name,
        norm_name=detected_norm,
        first_seen_at=datetime.utcnow().isoformat(),
        last_seen_at=datetime.utcnow().isoformat(),
        seen_count=1
    )
    db.add(new_variant)
    db.flush()
    
    return new_player_id, None, 'none', 0, False


def resolve_game_players(
    db: Session,
    game_id: str,
    detected_names: List[Dict[str, Any]],
    uploader_user_id: Optional[str] = None,
    platform: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Resolve all detected player names for a game.
    
    Args:
        db: Database session
        game_id: Game ID
        detected_names: List of dicts with 'raw_name', 'slot_index', etc.
        uploader_user_id: Optional user ID of uploader
        platform: Optional platform ('PC' or 'Console') to filter claims by
        
    Returns:
        List of resolution results with player_id_identity, claim_id, etc.
    """
    results = []
    
    # If platform not provided, try to get it from the game
    if not platform:
        from models import Game
        game = db.query(Game).filter(Game.id == game_id).first()
        if game:
            platform = game.platform
    
    for name_data in detected_names:
        raw_name = name_data.get('raw_name', '')
        slot_index = name_data.get('slot_index', 0)
        
        if not raw_name:
            continue
        
        # Resolve identity (with platform filtering for claims)
        player_id_identity, claim_id, match_method, match_confidence, needs_review = \
            find_player_identity(db, raw_name, uploader_user_id, platform)
        
        # Update or create game_players record
        # First, check if game_players record exists for this game and slot
        existing = db.execute(
            """
            SELECT id FROM game_players
            WHERE game_id = ? AND row_index = ?
            """,
            (game_id, slot_index)
        ).fetchone()
        
        detected_norm = normalize_name(raw_name)
        
        if existing:
            # Update existing record
            db.execute(
                """
                UPDATE game_players
                SET detected_raw_name = ?,
                    detected_norm_name = ?,
                    player_id_identity = ?,
                    claim_id = ?,
                    match_confidence = ?,
                    match_method = ?,
                    needs_review = ?
                WHERE id = ?
                """,
                (raw_name, detected_norm, player_id_identity, claim_id,
                 match_confidence, match_method, 1 if needs_review else 0, existing[0])
            )
        else:
            # This shouldn't happen if ingestion already created game_players,
            # but handle it gracefully
            pass
        
        results.append({
            'slot_index': slot_index,
            'raw_name': raw_name,
            'player_id_identity': player_id_identity,
            'claim_id': claim_id,
            'match_method': match_method,
            'match_confidence': match_confidence,
            'needs_review': needs_review
        })
    
    return results

