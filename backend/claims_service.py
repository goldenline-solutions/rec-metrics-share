"""
Service functions for name claims and verification.
Handles claim creation, verification, and retroactive linking.
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime

from models import NameClaim, PlayerIdentity, PlayerNameVariant, GamePlayer, User, Game
from sqlalchemy import and_
from name_utils import normalize_name


def create_claim(
    db: Session,
    user_id: str,
    display_name: str,
    player_id: Optional[int] = None,
    platform: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new name claim for a user.
    
    Args:
        db: Database session
        user_id: User ID making the claim
        display_name: Display name for the claim
        player_id: Optional existing player identity ID to claim
        platform: Optional platform ('PC' or 'Console'). If not provided, uses user's platform.
        
    Returns:
        Dict with claim data or error
    """
    normalized_name = normalize_name(display_name)
    
    if not normalized_name:
        return {"error": "Invalid display name"}
    
    # Get user's platform if not provided
    if not platform:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.platform:
            return {"error": "Please select your platform first before claiming a username"}
        platform = user.platform
    
    if platform not in ["PC", "Console"]:
        return {"error": "Platform must be 'PC' or 'Console'"}
    
    # Check if user already has ANY verified claim (only one claim allowed per user total)
    existing_verified_claim = db.query(NameClaim).filter(
        NameClaim.user_id == user_id,
        NameClaim.status == 'verified'
    ).first()
    
    if existing_verified_claim:
        return {"error": f"You already have a verified claim ({existing_verified_claim.display_name} on {existing_verified_claim.platform}). Only one username claim is allowed per account."}
    
    # Check if user already has a verified claim for this specific normalized name (on any platform)
    existing_verified_same_name = db.query(NameClaim).filter(
        NameClaim.user_id == user_id,
        NameClaim.normalized_name == normalized_name,
        NameClaim.status == 'verified'
    ).first()
    
    if existing_verified_same_name:
        return {"error": "You already have a verified claim for this name"}
    
    # If player_id provided, use it; otherwise try to find existing player identity
    if player_id:
        player = db.query(PlayerIdentity).filter(PlayerIdentity.id == player_id).first()
        if not player:
            return {"error": "Player identity not found"}
    else:
        # Try to find existing player identity with same normalized name
        # This handles case variations like "HintofLime" vs "HintoFLime"
        existing_player = db.query(PlayerIdentity).filter(
            PlayerIdentity.canonical_norm == normalized_name
        ).first()
        
        if existing_player:
            # Use existing player identity
            player = existing_player
            # Add this display name as a variant if it doesn't exist
            existing_variant = db.query(PlayerNameVariant).filter(
                PlayerNameVariant.player_id == player.id,
                PlayerNameVariant.norm_name == normalized_name
            ).first()
            if not existing_variant:
                variant = PlayerNameVariant(
                    player_id=player.id,
                    raw_name=display_name,
                    norm_name=normalized_name,
                    first_seen_at=datetime.utcnow().isoformat(),
                    last_seen_at=datetime.utcnow().isoformat(),
                    seen_count=1
                )
                db.add(variant)
                db.flush()
        else:
            # Create new player identity
            player = PlayerIdentity(
                canonical_name=display_name,
                canonical_norm=normalized_name,
                created_at=datetime.utcnow().isoformat()
            )
            db.add(player)
            db.flush()
            
            # Add variant
            variant = PlayerNameVariant(
                player_id=player.id,
                raw_name=display_name,
                norm_name=normalized_name,
                first_seen_at=datetime.utcnow().isoformat(),
                last_seen_at=datetime.utcnow().isoformat(),
                seen_count=1
            )
            db.add(variant)
            db.flush()
    
    # Check uniqueness: only one verified claim per normalized_name per platform
    existing_verified = db.query(NameClaim).filter(
        NameClaim.normalized_name == normalized_name,
        NameClaim.platform == platform,
        NameClaim.status == 'verified'
    ).first()
    
    if existing_verified:
        return {"error": f"This username is already claimed by another user on {platform}"}
    
    # Create claim and auto-verify it
    claim = NameClaim(
        user_id=user_id,
        player_id=player.id,
        display_name=display_name,
        normalized_name=normalized_name,
        platform=platform,
        status='verified',  # Auto-verify claims
        verified_at=datetime.utcnow().isoformat(),
        verified_by_user_id=user_id,  # Self-verified
        created_at=datetime.utcnow().isoformat()
    )
    db.add(claim)
    db.flush()
    
    # Backfill historical game_players records - only link games on the same platform
    # Join with Game table to filter by platform
    from sqlalchemy import and_
    updated_count = db.query(GamePlayer).join(
        Game, GamePlayer.game_id == Game.id
    ).filter(
        and_(
            GamePlayer.player_id_identity == player.id,
            GamePlayer.claim_id.is_(None),
            Game.platform == platform
        )
    ).update({
        'claim_id': claim.id,
        'match_method': 'manual',
        'match_confidence': 100
    }, synchronize_session=False)
    db.flush()
    
    return {
        "id": claim.id,
        "user_id": claim.user_id,
        "player_id": claim.player_id,
        "display_name": claim.display_name,
        "normalized_name": claim.normalized_name,
        "platform": claim.platform,
        "status": claim.status,
        "created_at": claim.created_at,
        "updated_games": updated_count
    }


def verify_claim(
    db: Session,
    claim_id: int,
    reviewer_user_id: str,
    approve: bool = True,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Verify or reject a name claim.
    
    When approving:
    1. Check for uniqueness (only one verified claim per normalized_name globally)
    2. Update claim status
    3. Backfill historical game_players records
    
    Args:
        db: Database session
        claim_id: Claim ID to verify
        reviewer_user_id: User ID of reviewer (must be admin/mod)
        approve: True to approve, False to reject
        notes: Optional notes
        
    Returns:
        Dict with result or error
    """
    claim = db.query(NameClaim).filter(NameClaim.id == claim_id).first()
    if not claim:
        return {"error": "Claim not found"}
    
    if approve:
        # Check uniqueness: only one verified claim per normalized_name per platform
        existing_verified = db.query(NameClaim).filter(
            NameClaim.normalized_name == claim.normalized_name,
            NameClaim.platform == claim.platform,
            NameClaim.status == 'verified',
            NameClaim.id != claim_id
        ).first()
        
        if existing_verified:
            # Reject this claim
            claim.status = 'rejected'
            claim.verified_at = datetime.utcnow().isoformat()
            claim.verified_by_user_id = reviewer_user_id
            db.flush()
            return {"error": f"Another verified claim already exists for this name on {claim.platform or 'this platform'}"}
        
        # Approve the claim
        claim.status = 'verified'
        claim.verified_at = datetime.utcnow().isoformat()
        claim.verified_by_user_id = reviewer_user_id
        db.flush()
        
        # Backfill historical game_players records - only link games on the same platform
        # Join with Game table to filter by platform
        from sqlalchemy import and_
        updated_count = db.query(GamePlayer).join(
            Game, GamePlayer.game_id == Game.id
        ).filter(
            and_(
                GamePlayer.player_id_identity == claim.player_id,
                GamePlayer.claim_id.is_(None),
                Game.platform == claim.platform
            )
        ).update({
            'claim_id': claim.id,
            'match_method': 'manual',
            'match_confidence': 100
        }, synchronize_session=False)
        db.flush()
        
        return {
            "success": True,
            "claim_id": claim.id,
            "status": claim.status,
            "updated_games": updated_count
        }
    else:
        # Reject the claim
        claim.status = 'rejected'
        claim.verified_at = datetime.utcnow().isoformat()
        claim.verified_by_user_id = reviewer_user_id
        if notes:
            # Store notes in a verification attempt record
            from models import ClaimVerificationAttempt
            attempt = ClaimVerificationAttempt(
                claim_id=claim.id,
                status='rejected',
                reviewed_by_user_id=reviewer_user_id,
                reviewed_at=datetime.utcnow().isoformat(),
                notes=notes
            )
            db.add(attempt)
        db.flush()
        
        return {
            "success": True,
            "claim_id": claim.id,
            "status": claim.status
        }


def get_user_claims(db: Session, user_id: str) -> List[Dict[str, Any]]:
    """
    Get all claims for a user.
    
    Args:
        db: Database session
        user_id: User ID
        
    Returns:
        List of claim dicts
    """
    claims = db.query(NameClaim).filter(NameClaim.user_id == user_id).all()
    
    result = []
    for claim in claims:
        # Get player info
        player = db.query(PlayerIdentity).filter(PlayerIdentity.id == claim.player_id).first()
        
        # Count games linked to this claim
        games_count = db.query(GamePlayer).filter(GamePlayer.claim_id == claim.id).count()
        
        result.append({
            "id": claim.id,
            "player_id": claim.player_id,
            "display_name": claim.display_name,
            "normalized_name": claim.normalized_name,
            "platform": claim.platform,
            "status": claim.status,
            "verified_at": claim.verified_at,
            "created_at": claim.created_at,
            "games_count": games_count,
            "canonical_name": player.canonical_name if player else None
        })
    
    return result


def get_unresolved_games(db: Session, user_id: str) -> List[Dict[str, Any]]:
    """
    Get games with unresolved player names for a user.
    Shows detected names that might belong to the user.
    Only shows games on platforms where the user has verified claims.
    
    Args:
        db: Database session
        user_id: User ID
        
    Returns:
        List of unresolved game player records
    """
    # Get user's verified claims (grouped by platform)
    verified_claims = db.query(NameClaim).filter(
        NameClaim.user_id == user_id,
        NameClaim.status == 'verified'
    ).all()
    
    verified_player_ids = [claim.player_id for claim in verified_claims]
    verified_platforms = list(set([claim.platform for claim in verified_claims if claim.platform]))
    
    # Find game_players that:
    # 1. Have a player_id_identity that matches user's verified claims, but claim_id is NULL
    # 2. AND the game is on a platform where user has a claim
    # 3. OR have needs_review=True and might match user's names (on user's platform)
    
    unresolved = []
    
    if verified_player_ids:
        # Case 1: Player identity matches but no claim linked
        # Filter by platform if user has platform-specific claims
        game_players_query = db.query(GamePlayer).join(
            Game, GamePlayer.game_id == Game.id
        ).filter(
            GamePlayer.player_id_identity.in_(verified_player_ids),
            GamePlayer.claim_id.is_(None)
        )
        
        # Only show games on platforms where user has claims
        if verified_platforms:
            game_players_query = game_players_query.filter(Game.platform.in_(verified_platforms))
        
        game_players = game_players_query.all()
        
        for gp in game_players:
            game = db.query(Game).filter(Game.id == gp.game_id).first()
            if game:
                unresolved.append({
                    "game_id": gp.game_id,
                    "game_player_id": gp.id,
                    "detected_raw_name": gp.detected_raw_name,
                    "detected_norm_name": gp.detected_norm_name,
                    "player_id_identity": gp.player_id_identity,
                    "match_method": gp.match_method,
                    "match_confidence": gp.match_confidence,
                    "needs_review": gp.needs_review,
                    "game_created_at": game.created_at,
                    "suggested_match": True  # This player identity matches a verified claim
                })
    
    # Case 2: Needs review and might be the user (only on platforms where user has claims)
    needs_review_query = db.query(GamePlayer).join(
        Game, GamePlayer.game_id == Game.id
    ).filter(
        GamePlayer.needs_review == True,
        GamePlayer.claim_id.is_(None)
    )
    
    # Filter by platform if user has platform-specific claims
    if verified_platforms:
        needs_review_query = needs_review_query.filter(Game.platform.in_(verified_platforms))
    
    needs_review = needs_review_query.limit(50).all()
    
    for gp in needs_review:
        # Check if detected name matches any of user's verified claim names
        matches_user = False
        if gp.detected_norm_name:
            for claim in verified_claims:
                if gp.detected_norm_name == claim.normalized_name:
                    matches_user = True
                    break
        
        if matches_user or not verified_player_ids:
            game = db.query(Game).filter(Game.id == gp.game_id).first()
            if game:
                unresolved.append({
                    "game_id": gp.game_id,
                    "game_player_id": gp.id,
                    "detected_raw_name": gp.detected_raw_name,
                    "detected_norm_name": gp.detected_norm_name,
                    "player_id_identity": gp.player_id_identity,
                    "match_method": gp.match_method,
                    "match_confidence": gp.match_confidence,
                    "needs_review": gp.needs_review,
                    "game_created_at": game.created_at,
                    "suggested_match": matches_user
                })
    
    return unresolved


def confirm_game_player(
    db: Session,
    game_id: str,
    game_player_id: str,
    user_id: str,
    action: str,
    claim_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Confirm or reject a game player as belonging to the user.
    
    Args:
        db: Database session
        game_id: Game ID
        game_player_id: GamePlayer ID
        user_id: User ID
        action: "me" or "not_me"
        claim_id: Optional claim ID to link (if action is "me")
        
    Returns:
        Dict with result
    """
    game_player = db.query(GamePlayer).filter(
        GamePlayer.id == game_player_id,
        GamePlayer.game_id == game_id
    ).first()
    
    if not game_player:
        return {"error": "Game player not found"}
    
    if action == "me":
        # User confirms this is them
        # Get the game to check platform
        game = db.query(Game).filter(Game.id == game_id).first()
        game_platform = game.platform if game else None
        
        if claim_id:
            # Link to specific claim (verify it matches the game's platform)
            claim = db.query(NameClaim).filter(
                NameClaim.id == claim_id,
                NameClaim.user_id == user_id,
                NameClaim.status == 'verified'
            ).first()
            
            if not claim:
                return {"error": "Claim not found or not verified"}
            
            # Verify platform matches
            if game_platform and claim.platform and claim.platform != game_platform:
                return {"error": f"Claim is for {claim.platform} but game is on {game_platform}. Claims are platform-specific."}
            
            game_player.claim_id = claim.id
            game_player.match_method = 'manual'
            game_player.match_confidence = 100
            game_player.needs_review = False
            
            # Also update player_id_identity if needed
            if not game_player.player_id_identity:
                game_player.player_id_identity = claim.player_id
        else:
            # Create or find claim for this player identity (filter by platform)
            if game_player.player_id_identity:
                # Check if user has a claim for this player on the game's platform
                claim_query = db.query(NameClaim).filter(
                    NameClaim.player_id == game_player.player_id_identity,
                    NameClaim.user_id == user_id,
                    NameClaim.status == 'verified'
                )
                if game_platform:
                    claim_query = claim_query.filter(NameClaim.platform == game_platform)
                claim = claim_query.first()
                
                if claim:
                    game_player.claim_id = claim.id
                    game_player.match_method = 'manual'
                    game_player.match_confidence = 100
                    game_player.needs_review = False
                else:
                    platform_msg = f" on {game_platform}" if game_platform else ""
                    return {"error": f"No verified claim found for this player identity{platform_msg}. Please create a claim first."}
            else:
                return {"error": "Player identity not resolved. Cannot confirm."}
    elif action == "not_me":
        # User confirms this is NOT them
        # Mark as reviewed but don't link
        game_player.needs_review = False
        # Don't set claim_id - leave it as None
    else:
        return {"error": "Invalid action. Must be 'me' or 'not_me'"}
    
    db.flush()
    
    return {"success": True, "action": action}

