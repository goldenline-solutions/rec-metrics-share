"""
Script to find games where players are missing stats.

This script will:
1. Find all games in the database
2. Check each game for players that have GamePlayer entries but no PlayerGameStats
3. Report which games and players are affected

Usage:
    python scripts/find_missing_stats.py
"""
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal, init_db
from models import Game, Player, GamePlayer, PlayerGameStats

def find_games_with_missing_stats(db):
    """
    Find all games where players are missing stats.
    
    Returns:
        list: List of dicts with game info and missing players
    """
    games_with_issues = []
    
    # Get all games
    all_games = db.query(Game).order_by(Game.created_at.desc()).all()
    
    print(f"Checking {len(all_games)} games for missing player stats...\n")
    
    for game in all_games:
        # Get all game players for this game
        game_players = db.query(GamePlayer).filter_by(game_id=game.id).all()
        
        missing_players = []
        
        for gp in game_players:
            # Check if stats exist
            stats = db.query(PlayerGameStats).filter_by(
                game_id=game.id,
                player_id=gp.player_id
            ).first()
            
            if not stats:
                player = db.query(Player).filter_by(id=gp.player_id).first()
                if player:
                    missing_players.append({
                        "gamertag": player.gamertag,
                        "position": gp.position,
                        "team_side": gp.team_side
                    })
        
        if missing_players:
            games_with_issues.append({
                "game_id": game.id,
                "created_at": game.created_at,
                "home_team": game.home_team_name or "Unknown",
                "away_team": game.away_team_name or "Unknown",
                "score": f"{game.away_score}-{game.home_score}",
                "missing_players": missing_players
            })
    
    return games_with_issues

def main():
    """Main function to run the script."""
    # Initialize database
    init_db()
    
    # Create database session
    db = SessionLocal()
    
    try:
        games_with_issues = find_games_with_missing_stats(db)
        
        if not games_with_issues:
            print("✅ No games found with missing player stats!")
            return
        
        print(f"⚠️  Found {len(games_with_issues)} games with missing player stats:\n")
        print("=" * 80)
        
        total_missing = 0
        for game_info in games_with_issues:
            missing_count = len(game_info["missing_players"])
            total_missing += missing_count
            
            print(f"\nGame ID: {game_info['game_id']}")
            print(f"Date: {game_info['created_at']}")
            print(f"Match: {game_info['away_team']} @ {game_info['home_team']} ({game_info['score']})")
            print(f"Missing Stats: {missing_count} player(s)")
            
            for player in game_info["missing_players"]:
                print(f"  - {player['gamertag']} ({player['position']}, {player['team_side']})")
            
            print("-" * 80)
        
        print(f"\n📊 Summary:")
        print(f"   Total games with issues: {len(games_with_issues)}")
        print(f"   Total players missing stats: {total_missing}")
        print(f"\n💡 These games will now show warnings when viewed.")
        print(f"   You can fix them by editing the games and adding the missing stats.")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

