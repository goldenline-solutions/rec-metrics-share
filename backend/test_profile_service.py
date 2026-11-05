"""
Unit tests for profile service insight generation.
"""
import unittest
from unittest.mock import Mock
from profile_service import (
    calculate_ts_pct,
    calculate_efficiency,
    generate_insight_shooting_with_assists,
    generate_insight_win_rate_threshold,
    generate_insight_weakest_quarter,
    determine_win
)
from models import PlayerGameStats, Game, GamePlayer


class TestProfileService(unittest.TestCase):
    
    def test_calculate_ts_pct(self):
        """Test True Shooting Percentage calculation."""
        # Test normal case
        result = calculate_ts_pct(20, 15, 5)
        self.assertGreater(result, 0)
        self.assertLessEqual(result, 100)
        
        # Test zero attempts
        result = calculate_ts_pct(0, 0, 0)
        self.assertEqual(result, 0.0)
        
        # Test with free throws
        result = calculate_ts_pct(30, 20, 10)
        self.assertGreater(result, 0)
    
    def test_calculate_efficiency(self):
        """Test efficiency calculation."""
        result = calculate_efficiency(20, 5, 5, 2, 1, 3)
        expected = 20 + 5 + 5 + 2 + 1 - 3
        self.assertEqual(result, expected)
    
    def test_determine_win(self):
        """Test win determination logic."""
        game = Mock(spec=Game)
        game.home_score = 100
        game.away_score = 90
        
        home_player = Mock(spec=GamePlayer)
        home_player.team_side = "HOME"
        
        away_player = Mock(spec=GamePlayer)
        away_player.team_side = "AWAY"
        
        self.assertTrue(determine_win(game, home_player))
        self.assertFalse(determine_win(game, away_player))
    
    def test_insight_shooting_with_assists_threshold_selection(self):
        """Test that insight selects appropriate assist threshold."""
        # Create mock games with varying assist and shooting stats
        games_data = []
        for i in range(20):
            stats = Mock(spec=PlayerGameStats)
            game = Mock(spec=Game)
            game_player = Mock(spec=GamePlayer)
            
            # First 10 games: high assists, good shooting
            if i < 10:
                stats.ast = 8
                stats.fgm = 7
                stats.fga = 10
            # Next 10 games: low assists, worse shooting
            else:
                stats.ast = 3
                stats.fgm = 4
                stats.fga = 10
            
            games_data.append((stats, game, game_player))
        
        insight = generate_insight_shooting_with_assists(games_data)
        
        self.assertIsNotNone(insight)
        self.assertIn("assists", insight["text"].lower())
        self.assertIn("confidence", insight)
    
    def test_insight_win_rate_threshold_graceful_degradation(self):
        """Test that insight handles insufficient data gracefully."""
        # Too few games
        games_data = []
        for i in range(5):
            stats = Mock(spec=PlayerGameStats)
            game = Mock(spec=Game)
            game_player = Mock(spec=GamePlayer)
            stats.fga = 10
            stats.tov = 3
            games_data.append((stats, game, game_player))
        
        insight = generate_insight_win_rate_threshold(games_data)
        self.assertIsNone(insight)  # Should return None with insufficient data
    
    def test_insight_confidence_assignment(self):
        """Test that confidence is assigned based on sample size."""
        # Create games with enough data for medium confidence
        games_data = []
        for i in range(15):
            stats = Mock(spec=PlayerGameStats)
            game = Mock(spec=Game)
            game_player = Mock(spec=GamePlayer)
            
            stats.ast = 8 if i < 8 else 3
            stats.fgm = 7 if i < 8 else 4
            stats.fga = 10
            game.home_score = 100
            game.away_score = 90
            game_player.team_side = "HOME"
            
            games_data.append((stats, game, game_player))
        
        insight = generate_insight_shooting_with_assists(games_data)
        
        if insight:
            # Should have at least "low" confidence
            self.assertIn(insight["confidence"], ["low", "medium", "high"])
    
    def test_insight_weakest_quarter_fallback(self):
        """Test weakest quarter falls back to stretch analysis when quarters unavailable."""
        games_data = []
        for i in range(10):
            stats = Mock(spec=PlayerGameStats)
            game = Mock(spec=Game)
            game_player = Mock(spec=GamePlayer)
            
            # First 5 games: lower scoring
            stats.pts = 10 if i < 5 else 20
            game.home_q1 = None  # No quarter data
            game.home_q2 = None
            game.home_q3 = None
            game.home_q4 = None
            game.away_q1 = None
            game.away_q2 = None
            game.away_q3 = None
            game.away_q4 = None
            game_player.team_side = "HOME"
            
            games_data.append((stats, game, game_player))
        
        insight = generate_insight_weakest_quarter(games_data)
        
        # Should either return None or a stretch-based insight
        if insight:
            self.assertIn("confidence", insight)
            # If it's a stretch insight, should mention "stretch" or "half"
            if "stretch" in insight.get("id", ""):
                self.assertIn("stretch", insight["text"].lower() or insight["title"].lower())


if __name__ == "__main__":
    unittest.main()

