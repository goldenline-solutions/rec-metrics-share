"""
Script to auto-generate matchups for all games that don't have exactly 10 matchups.

This script will:
1. Find all games in the database
2. Check if each game has exactly 10 matchups
3. If not, generate 10 matchups based on player positions (5 positions × 2 directions)
4. Save the generated matchups to the database

Usage:
    python scripts/generate_matchups.py
"""
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal, init_db
from models import Game, Player, GamePlayer, Matchup

def generate_matchups_for_game(db, game):
    """
    Generate 10 matchups for a game based on player positions.
    
    Returns:
        tuple: (created_count, deleted_count)
    """
    # Get all game players with their positions
    game_players = db.query(GamePlayer).filter_by(game_id=game.id).all()
    
    # Create maps of position -> player for each team
    home_players_by_pos = {}
    away_players_by_pos = {}
    
    for gp in game_players:
        player = db.query(Player).filter_by(id=gp.player_id).first()
        if not player:
            continue
        
        if gp.team_side == "HOME":
            home_players_by_pos[gp.position] = player
        elif gp.team_side == "AWAY":
            away_players_by_pos[gp.position] = player
    
    # Positions in order
    positions = ["PG", "SG", "SF", "PF", "C"]
    
    # Delete existing matchups for this game
    deleted_count = db.query(Matchup).filter_by(game_id=game.id).delete()
    
    created_count = 0
    
    # Generate 10 matchups: 5 positions × 2 directions
    for position in positions:
        home_player = home_players_by_pos.get(position)
        away_player = away_players_by_pos.get(position)
        
        if not home_player or not away_player:
            # Skip if we don't have players at this position for both teams
            continue
        
        # HOME defender vs AWAY offender
        matchup1 = Matchup(
            game_id=game.id,
            defender_player_id=home_player.id,
            offender_player_id=away_player.id,
            defender_position=position,
            offender_position=position,
            matchup_type="POSITIONAL"
        )
        db.add(matchup1)
        created_count += 1
        
        # AWAY defender vs HOME offender
        matchup2 = Matchup(
            game_id=game.id,
            defender_player_id=away_player.id,
            offender_player_id=home_player.id,
            defender_position=position,
            offender_position=position,
            matchup_type="POSITIONAL"
        )
        db.add(matchup2)
        created_count += 1
    
    return created_count, deleted_count

def main():
    """Main function to process all games."""
    print("=" * 60)
    print("Matchup Generation Script")
    print("=" * 60)
    print("\nThis script will:")
    print("  1. Find all games in the database")
    print("  2. Check if each game has exactly 10 matchups")
    print("  3. Generate missing matchups based on player positions")
    print("  4. Save the generated matchups")
    print("\n" + "=" * 60)
    
    # Confirm before proceeding
    response = input("\nProceed with matchup generation? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("Operation cancelled.")
        return
    
    # Initialize database
    init_db()
    
    db = SessionLocal()
    
    try:
        # Get all games
        all_games = db.query(Game).all()
        print(f"\nFound {len(all_games)} games in database.")
        
        games_processed = 0
        games_updated = 0
        total_matchups_created = 0
        total_matchups_deleted = 0
        
        for game in all_games:
            games_processed += 1
            
            # Count existing matchups
            existing_matchups = db.query(Matchup).filter_by(game_id=game.id).count()
            
            if existing_matchups == 10:
                print(f"  Game {game.id[:8]}...: Already has 10 matchups ✓")
                continue
            
            print(f"  Game {game.id[:8]}...: Has {existing_matchups} matchups (expected 10)")
            
            # Generate matchups
            try:
                created, deleted = generate_matchups_for_game(db, game)
                db.commit()
                
                games_updated += 1
                total_matchups_created += created
                total_matchups_deleted += deleted
                
                if created == 10:
                    print(f"    ✓ Generated {created} matchups")
                else:
                    print(f"    ⚠ Generated {created} matchups (expected 10 - may be missing players at some positions)")
                    
            except Exception as e:
                db.rollback()
                print(f"    ✗ Error generating matchups: {e}")
                continue
        
        print("\n" + "=" * 60)
        print("Summary:")
        print(f"  Games processed: {games_processed}")
        print(f"  Games updated: {games_updated}")
        print(f"  Matchups created: {total_matchups_created}")
        print(f"  Matchups deleted: {total_matchups_deleted}")
        print("=" * 60)
        print("✓ Matchup generation completed!")
        
    except Exception as e:
        db.rollback()
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

