"""
Script to fix gamertag typos in the database.
This can be used to correct OCR/extraction errors.
"""
import sys
from db import SessionLocal, init_db
from models import Player, GamePlayer, PlayerGameStats, Matchup


def fix_gamertag_typos(typo_map: dict, dry_run: bool = True) -> dict:
    """
    Fix gamertag typos by renaming players.
    
    Args:
        typo_map: Dictionary mapping incorrect gamertags to correct ones
                  e.g., {"hintolime": "Hintoflime"}
        dry_run: If True, only show what would be changed without making changes
        
    Returns:
        Dictionary with fix statistics
    """
    db = SessionLocal()
    stats = {
        "total_players": 0,
        "players_to_fix": 0,
        "fixed": 0,
        "duplicates_found": 0,
        "merged": 0,
        "errors": 0
    }
    
    try:
        # Get all players
        all_players = db.query(Player).all()
        stats["total_players"] = len(all_players)
        
        players_to_fix = []
        
        # Find players with typos (case-insensitive match)
        for player in all_players:
            player_gamertag_lower = player.gamertag.lower()
            for typo, correct in typo_map.items():
                if player_gamertag_lower == typo.lower():
                    players_to_fix.append((player, typo, correct))
                    break
        
        stats["players_to_fix"] = len(players_to_fix)
        
        if dry_run:
            print(f"DRY RUN MODE - No changes will be made")
            print("=" * 60)
        
        print(f"Total players in database: {stats['total_players']}")
        print(f"Players to fix: {stats['players_to_fix']}")
        print()
        
        if not players_to_fix:
            print("No players need fixing!")
            return stats
        
        # Process each player
        for player, typo, correct in players_to_fix:
            original_gamertag = player.gamertag
            
            # Check if a player with the correct gamertag already exists
            existing_player = db.query(Player).filter(
                Player.gamertag == correct
            ).first()
            
            if existing_player and existing_player.id != player.id:
                # Duplicate found - we need to merge
                print(f"🔄 Duplicate found:")
                print(f"   Typo:     {original_gamertag} (ID: {player.id})")
                print(f"   Correct:  {correct} (ID: {existing_player.id})")
                
                if not dry_run:
                    # Merge: Update all references from player.id to existing_player.id
                    # Then delete the duplicate player
                    
                    # Count references
                    game_players_count = db.query(GamePlayer).filter(
                        GamePlayer.player_id == player.id
                    ).count()
                    player_stats_count = db.query(PlayerGameStats).filter(
                        PlayerGameStats.player_id == player.id
                    ).count()
                    defender_matchups_count = db.query(Matchup).filter(
                        Matchup.defender_player_id == player.id
                    ).count()
                    offender_matchups_count = db.query(Matchup).filter(
                        Matchup.offender_player_id == player.id
                    ).count()
                    
                    total_refs = game_players_count + player_stats_count + defender_matchups_count + offender_matchups_count
                    
                    if total_refs > 0:
                        print(f"   Merging {total_refs} reference(s)...")
                        
                        # Update GamePlayer references
                        if game_players_count > 0:
                            db.query(GamePlayer).filter(
                                GamePlayer.player_id == player.id
                            ).update({"player_id": existing_player.id})
                        
                        # Update PlayerGameStats references
                        if player_stats_count > 0:
                            db.query(PlayerGameStats).filter(
                                PlayerGameStats.player_id == player.id
                            ).update({"player_id": existing_player.id})
                        
                        # Update Matchup defender references
                        if defender_matchups_count > 0:
                            db.query(Matchup).filter(
                                Matchup.defender_player_id == player.id
                            ).update({"defender_player_id": existing_player.id})
                        
                        # Update Matchup offender references
                        if offender_matchups_count > 0:
                            db.query(Matchup).filter(
                                Matchup.offender_player_id == player.id
                            ).update({"offender_player_id": existing_player.id})
                        
                        print(f"   ✓ Updated {total_refs} reference(s)")
                    
                    # Delete the duplicate player
                    db.delete(player)
                    print(f"   ✓ Deleted duplicate player")
                    stats["merged"] += 1
                else:
                    # Dry run - just count references
                    game_players_count = db.query(GamePlayer).filter(
                        GamePlayer.player_id == player.id
                    ).count()
                    player_stats_count = db.query(PlayerGameStats).filter(
                        PlayerGameStats.player_id == player.id
                    ).count()
                    defender_matchups_count = db.query(Matchup).filter(
                        Matchup.defender_player_id == player.id
                    ).count()
                    offender_matchups_count = db.query(Matchup).filter(
                        Matchup.offender_player_id == player.id
                    ).count()
                    total_refs = game_players_count + player_stats_count + defender_matchups_count + offender_matchups_count
                    print(f"   Would merge {total_refs} reference(s) and delete duplicate")
                    stats["duplicates_found"] += 1
            else:
                # No duplicate - safe to rename
                print(f"✓ {original_gamertag} → {correct}")
                
                if not dry_run:
                    player.gamertag = correct
                    stats["fixed"] += 1
                else:
                    stats["fixed"] += 1
        
        if not dry_run:
            db.commit()
            print()
            print("✓ Changes committed to database")
        else:
            print()
            print("DRY RUN - No changes made. Run with --execute to apply changes.")
        
        return stats
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {str(e)}")
        stats["errors"] += 1
        raise
    finally:
        db.close()


def main():
    """Main entry point for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Fix gamertag typos in the database"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the fixes (default is dry-run)"
    )
    
    args = parser.parse_args()
    
    # Define typo corrections
    # Format: {"incorrect_gamertag": "correct_gamertag"}
    typo_map = {
        "hintolime": "Hintoflime",
        "WockySlush": "BBL Wocky",
        "cheeksDCheeks": "cheeksDcheeks",
        "DG🔒": "DG",
        "Dan": "Peak Chaos",
        # Add more typos here as needed
        # "anothertypo": "CorrectName",
    }
    
    try:
        # Initialize database
        init_db()
        
        # Run fix
        stats = fix_gamertag_typos(typo_map, dry_run=not args.execute)
        
        # Print summary
        print()
        print("=" * 60)
        print("FIX SUMMARY")
        print("=" * 60)
        print(f"Total players:        {stats['total_players']}")
        print(f"Players to fix:       {stats['players_to_fix']}")
        print(f"Fixed:                {stats['fixed']}")
        print(f"Duplicates found:     {stats['duplicates_found']}")
        print(f"Merged:               {stats['merged']}")
        print(f"Errors:               {stats['errors']}")
        print("=" * 60)
        
        if stats["duplicates_found"] > 0:
            print()
            print("⚠️  WARNING: Duplicates found!")
            print("   Some players have both typo and correct versions.")
            print("   These will be merged automatically if --execute is used.")
        
        sys.exit(0)
        
    except KeyboardInterrupt:
        print("\n\nFix interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"Fatal error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

