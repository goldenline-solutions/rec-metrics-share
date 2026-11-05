"""
Script to backfill admin metrics for all existing games.
Run this after the migration to compute metrics for all games in the database.
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from db import SessionLocal
from models import Game
from services.admin_metrics_service import upsert_player_game_admin_metrics


def main():
    """Backfill admin metrics for all games."""
    db = SessionLocal()
    
    try:
        # Get all games
        games = db.query(Game).all()
        total_games = len(games)
        
        print(f"Found {total_games} games to process...")
        
        success_count = 0
        error_count = 0
        
        for idx, game in enumerate(games, 1):
            try:
                records_created = upsert_player_game_admin_metrics(db, game.id)
                success_count += 1
                if idx % 10 == 0 or idx == total_games:
                    print(f"Processed {idx}/{total_games} games... ({success_count} successful, {error_count} errors)")
            except Exception as e:
                error_count += 1
                print(f"Error processing game {game.id}: {str(e)}")
                # Continue with next game
                continue
        
        print(f"\n[SUCCESS] Backfill complete!")
        print(f"  - Total games: {total_games}")
        print(f"  - Successful: {success_count}")
        print(f"  - Errors: {error_count}")
        
    except Exception as e:
        print(f"[ERROR] Backfill failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
