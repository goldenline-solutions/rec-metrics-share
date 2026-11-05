"""
Script to clean up gamertags in the database by removing the 🔊 symbol.
This should be run once to clean existing data.
"""
import sys
from db import SessionLocal, init_db
from models import Player, GamePlayer, PlayerGameStats, Matchup
from utils import clean_gamertag


def cleanup_gamertags(dry_run: bool = True) -> dict:
    """
    Clean up gamertags in the database by removing the 🔊 symbol.
    
    Args:
        dry_run: If True, only show what would be changed without making changes
        
    Returns:
        Dictionary with cleanup statistics
    """
    db = SessionLocal()
    stats = {
        "total_players": 0,
        "players_with_symbol": 0,
        "cleaned": 0,
        "duplicates_found": 0,
        "merged": 0,
        "errors": 0
    }
    
    try:
        # Get all players
        all_players = db.query(Player).all()
        stats["total_players"] = len(all_players)
        
        players_to_clean = []
        
        # Find players with the 🔊 symbol
        for player in all_players:
            if "🔊" in player.gamertag:
                players_to_clean.append(player)
            elif "DG🔒" in player.gamertag:
                players_to_clean.append(player)
        
        stats["players_with_symbol"] = len(players_to_clean)
        
        if dry_run:
            print(f"DRY RUN MODE - No changes will be made")
            print("=" * 60)
        
        print(f"Total players in database: {stats['total_players']}")
        print(f"Players with 🔊 symbol: {stats['players_with_symbol']}")
        print()
        
        if not players_to_clean:
            print("No players need cleaning!")
            return stats
        
        # Process each player
        for player in players_to_clean:
            original_gamertag = player.gamertag
            cleaned_gamertag = clean_gamertag(original_gamertag)
            
            if not cleaned_gamertag:
                print(f"⚠️  Warning: Player {original_gamertag} would become empty after cleaning - skipping")
                stats["errors"] += 1
                continue
            
            # Check if a player with the cleaned gamertag already exists
            existing_player = db.query(Player).filter(
                Player.gamertag == cleaned_gamertag
            ).first()
            
            if existing_player and existing_player.id != player.id:
                # Duplicate found - we need to merge
                print(f"🔄 Duplicate found:")
                print(f"   Original: {original_gamertag} (ID: {player.id})")
                print(f"   Cleaned:  {cleaned_gamertag} (ID: {existing_player.id})")
                
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
                # No duplicate - safe to update
                print(f"✓ {original_gamertag} → {cleaned_gamertag}")
                
                if not dry_run:
                    player.gamertag = cleaned_gamertag
                    stats["cleaned"] += 1
                else:
                    stats["cleaned"] += 1
        
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
        description="Clean up gamertags in the database by removing 🔊 symbol"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the cleanup (default is dry-run)"
    )
    
    args = parser.parse_args()
    
    try:
        # Initialize database
        init_db()
        
        # Run cleanup
        stats = cleanup_gamertags(dry_run=not args.execute)
        
        # Print summary
        print()
        print("=" * 60)
        print("CLEANUP SUMMARY")
        print("=" * 60)
        print(f"Total players:        {stats['total_players']}")
        print(f"Players with 🔊:      {stats['players_with_symbol']}")
        print(f"Cleaned:              {stats['cleaned']}")
        print(f"Duplicates found:     {stats['duplicates_found']}")
        print(f"Merged:               {stats['merged']}")
        print(f"Errors:               {stats['errors']}")
        print("=" * 60)
        
        if stats["duplicates_found"] > 0:
            print()
            print("⚠️  WARNING: Duplicates found!")
            print("   Some players have both 'PlayerName🔊' and 'PlayerName' versions.")
            print("   These need manual merging to avoid data loss.")
            print("   Check the output above for details.")
        
        sys.exit(0)
        
    except KeyboardInterrupt:
        print("\n\nCleanup interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"Fatal error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

