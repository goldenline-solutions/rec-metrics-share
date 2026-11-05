"""
Unit tests for player analysis service.
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from player_analysis_service import (
    build_player_analysis_payload,
    get_payload_hash,
    calculate_aggregates,
    calculate_splits,
    determine_win,
    calculate_derived_metrics,
    calculate_teammate_synergy,
    calculate_opponent_difficulty,
    calculate_build_impact,
    generate_claim_candidates
)
from models import PlayerGameStats, Game, GamePlayer, Build, Player, BuildAttribute


class TestPlayerAnalysisService(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_db = Mock()
        self.mock_player = Mock(spec=Player)
        self.mock_player.id = "player-123"
        self.mock_player.gamertag = "HintofLime"
    
    def test_get_payload_hash(self):
        """Test payload hash generation."""
        payload1 = {"username": "test", "games": 10}
        payload2 = {"username": "test", "games": 10}
        payload3 = {"username": "test", "games": 20}
        
        hash1 = get_payload_hash(payload1)
        hash2 = get_payload_hash(payload2)
        hash3 = get_payload_hash(payload3)
        
        # Same payload should produce same hash
        self.assertEqual(hash1, hash2)
        # Different payload should produce different hash
        self.assertNotEqual(hash1, hash3)
    
    def test_calculate_aggregates_empty(self):
        """Test aggregate calculation with no games."""
        result = calculate_aggregates([])
        
        self.assertEqual(result["games_count"], 0)
        self.assertEqual(result["totals"], {})
        self.assertEqual(result["per_game_averages"], {})
    
    def test_calculate_aggregates_with_games(self):
        """Test aggregate calculation with sample games."""
        # Create mock game data
        stats1 = Mock(spec=PlayerGameStats)
        stats1.pts = 20
        stats1.reb = 5
        stats1.ast = 5
        stats1.stl = 2
        stats1.blk = 1
        stats1.tov = 3
        stats1.fgm = 8
        stats1.fga = 15
        stats1.tpm = 2
        stats1.tpa = 5
        stats1.ftm = 2
        stats1.fta = 2
        
        stats2 = Mock(spec=PlayerGameStats)
        stats2.pts = 15
        stats2.reb = 3
        stats2.ast = 7
        stats2.stl = 1
        stats2.blk = 0
        stats2.tov = 2
        stats2.fgm = 6
        stats2.fga = 12
        stats2.tpm = 1
        stats2.tpa = 4
        stats2.ftm = 2
        stats2.fta = 2
        
        game1 = Mock(spec=Game)
        game2 = Mock(spec=Game)
        gp1 = Mock(spec=GamePlayer)
        gp2 = Mock(spec=GamePlayer)
        build1 = None
        build2 = None
        
        games_data = [
            (stats1, game1, gp1, build1),
            (stats2, game2, gp2, build2)
        ]
        
        result = calculate_aggregates(games_data)
        
        self.assertEqual(result["games_count"], 2)
        self.assertEqual(result["totals"]["pts"], 35)
        self.assertEqual(result["totals"]["reb"], 8)
        self.assertEqual(result["per_game_averages"]["pts"], 17.5)
        self.assertGreater(result["per_game_averages"]["fg_pct"], 0)
    
    def test_calculate_splits_with_build_vs_without(self):
        """Test split calculation for games with vs without build."""
        # Create mock games with and without builds
        stats1 = Mock(spec=PlayerGameStats)
        stats1.pts = 20
        stats1.reb = 5
        stats1.ast = 5
        stats1.stl = 2
        stats1.blk = 1
        stats1.tov = 3
        stats1.fgm = 8
        stats1.fga = 15
        stats1.tpm = 2
        stats1.tpa = 5
        stats1.ftm = 2
        stats1.fta = 2
        
        stats2 = Mock(spec=PlayerGameStats)
        stats2.pts = 15
        stats2.reb = 3
        stats2.ast = 7
        stats2.stl = 1
        stats2.blk = 0
        stats2.tov = 2
        stats2.fgm = 6
        stats2.fga = 12
        stats2.tpm = 1
        stats2.tpa = 4
        stats2.ftm = 2
        stats2.fta = 2
        
        game1 = Mock(spec=Game)
        game2 = Mock(spec=Game)
        gp1 = Mock(spec=GamePlayer)
        gp2 = Mock(spec=GamePlayer)
        
        build1 = Mock(spec=Build)
        build1.display_name = "Test Build"
        build2 = None
        
        games_data = [
            (stats1, game1, gp1, build1),  # With build
            (stats2, game2, gp2, build2)   # Without build
        ]
        
        result = calculate_splits(games_data)
        
        # Should have with_build_vs_without_build split
        self.assertIn("with_build_vs_without_build", result)
        self.assertEqual(result["with_build_vs_without_build"]["with_build"]["games"], 1)
        self.assertEqual(result["with_build_vs_without_build"]["without_build"]["games"], 1)
    
    def test_determine_win(self):
        """Test win determination logic."""
        game = Mock(spec=Game)
        game.home_score = 100
        game.away_score = 90
        
        home_player = Mock(spec=GamePlayer)
        home_player.team_side = "HOME"
        
        away_player = Mock(spec=GamePlayer)
        away_player.team_side = "AWAY"
        
        # Home player should win
        self.assertTrue(determine_win(game, home_player))
        # Away player should lose
        self.assertFalse(determine_win(game, away_player))
        
        # Reverse scores
        game.home_score = 90
        game.away_score = 100
        
        # Home player should lose
        self.assertFalse(determine_win(game, home_player))
        # Away player should win
        self.assertTrue(determine_win(game, away_player))
    
    @patch('player_analysis_service.get_player_by_username')
    @patch('player_analysis_service.get_player_games_with_context')
    @patch('player_analysis_service.get_other_players_in_games')
    def test_build_player_analysis_payload_no_games(self, mock_other_players, mock_get_games, mock_get_player):
        """Test payload builder with no games."""
        mock_get_player.return_value = self.mock_player
        mock_get_games.return_value = []
        mock_other_players.return_value = {}
        
        payload = build_player_analysis_payload(self.mock_db, "HintofLime", 25)
        
        self.assertEqual(payload["meta"]["username"], "HintofLime")
        self.assertEqual(payload["meta"]["total_games"], 0)
        self.assertEqual(payload["meta"]["build_coverage"]["games_with_build"], 0)
        self.assertEqual(payload["meta"]["build_coverage"]["games_without_build"], 0)
        self.assertEqual(len(payload["per_game"]), 0)
    
    @patch('player_analysis_service.get_player_by_username')
    def test_build_player_analysis_payload_player_not_found(self, mock_get_player):
        """Test payload builder when player is not found."""
        mock_get_player.return_value = None
        
        with self.assertRaises(ValueError) as context:
            build_player_analysis_payload(self.mock_db, "NonExistent", 25)
        
        self.assertIn("not found", str(context.exception).lower())
    
    def test_calculate_derived_metrics(self):
        """Test derived metrics calculation."""
        stats1 = Mock(spec=PlayerGameStats)
        stats1.pts = 20
        stats1.reb = 5
        stats1.ast = 10
        stats1.stl = 2
        stats1.blk = 1
        stats1.tov = 2
        stats1.fgm = 8
        stats1.fga = 15
        stats1.tpm = 3
        stats1.tpa = 6
        stats1.ftm = 1
        stats1.fta = 2
        
        stats2 = Mock(spec=PlayerGameStats)
        stats2.pts = 15
        stats2.reb = 3
        stats2.ast = 8
        stats2.stl = 1
        stats2.blk = 0
        stats2.tov = 3
        stats2.fgm = 6
        stats2.fga = 12
        stats2.tpm = 1
        stats2.tpa = 4
        stats2.ftm = 2
        stats2.fta = 2
        
        game1 = Mock(spec=Game)
        game2 = Mock(spec=Game)
        gp1 = Mock(spec=GamePlayer)
        gp2 = Mock(spec=GamePlayer)
        build1 = None
        build2 = None
        
        games_data = [
            (stats1, game1, gp1, build1),
            (stats2, game2, gp2, build2)
        ]
        
        result = calculate_derived_metrics(games_data)
        
        # Check overall metrics exist
        self.assertIn("overall", result)
        self.assertIn("last_10", result)
        
        overall = result["overall"]
        self.assertIn("ast_to", overall)
        self.assertIn("efg_pct", overall)
        self.assertIn("pass_first_index", overall)
        self.assertIn("usage_proxy", overall)
        self.assertIn("points_per_shot", overall)
        self.assertIn("involvement_proxy", overall)
        
        # AST/TO should be calculated
        self.assertGreater(overall["ast_to"], 0)
        
        # eFG% should be calculated
        self.assertGreater(overall["efg_pct"], 0)
    
    def test_calculate_teammate_synergy(self):
        """Test teammate synergy calculation."""
        # Create mock games with teammates
        stats1 = Mock(spec=PlayerGameStats)
        stats1.pts = 20
        stats1.ast = 5
        stats1.reb = 5
        stats1.tov = 2
        stats1.fgm = 8
        stats1.fga = 15
        stats1.tpm = 2
        stats1.tpa = 5
        stats1.stl = 1
        stats1.blk = 0
        
        stats2 = Mock(spec=PlayerGameStats)
        stats2.pts = 15
        stats2.ast = 3
        stats2.reb = 3
        stats2.tov = 3
        stats2.fgm = 6
        stats2.fga = 12
        stats2.tpm = 1
        stats2.tpa = 4
        stats2.stl = 0
        stats2.blk = 0
        
        game1 = Mock(spec=Game)
        game1.id = "game-1"
        game2 = Mock(spec=Game)
        game2.id = "game-2"
        gp1 = Mock(spec=GamePlayer)
        gp1.team_side = Mock()
        gp1.team_side.value = "HOME"
        gp2 = Mock(spec=GamePlayer)
        gp2.team_side = Mock()
        gp2.team_side.value = "HOME"
        build1 = None
        build2 = None
        
        games_data = [
            (stats1, game1, gp1, build1),
            (stats2, game2, gp2, build2)
        ]
        
        # Mock other players (teammates)
        other_players_by_game = {
            "game-1": [
                {"username": "Teammate1", "team_side": "HOME", "pts": 15, "ast": 3, "reb": 4}
            ],
            "game-2": [
                {"username": "Teammate1", "team_side": "HOME", "pts": 12, "ast": 2, "reb": 3}
            ]
        }
        
        result = calculate_teammate_synergy(self.mock_db, "player-123", games_data, other_players_by_game)
        
        # Should return empty dict if not enough games (need >=5 shared games)
        # But structure should be correct
        self.assertIsInstance(result, dict)
    
    def test_calculate_opponent_difficulty(self):
        """Test opponent difficulty calculation."""
        stats1 = Mock(spec=PlayerGameStats)
        stats1.pts = 20
        stats1.ast = 5
        stats1.reb = 5
        stats1.tov = 2
        stats1.fgm = 8
        stats1.fga = 15
        stats1.tpm = 2
        stats1.tpa = 5
        
        game1 = Mock(spec=Game)
        game1.id = "game-1"
        gp1 = Mock(spec=GamePlayer)
        gp1.team_side = Mock()
        gp1.team_side.value = "HOME"
        build1 = None
        
        games_data = [
            (stats1, game1, gp1, build1)
        ]
        
        other_players_by_game = {
            "game-1": [
                {"username": "Opponent1", "team_side": "AWAY", "pts": 18, "ast": 4, "reb": 6}
            ]
        }
        
        result = calculate_opponent_difficulty(self.mock_db, "player-123", games_data, other_players_by_game)
        
        # Should return empty dict if not enough games (need >=5)
        self.assertIsInstance(result, dict)
    
    def test_calculate_build_impact(self):
        """Test build impact calculation."""
        stats1 = Mock(spec=PlayerGameStats)
        stats1.pts = 20
        stats1.ast = 5
        stats1.reb = 5
        stats1.tov = 2
        stats1.fgm = 8
        stats1.fga = 15
        stats1.tpm = 2
        stats1.tpa = 5
        stats1.stl = 1
        stats1.blk = 0
        
        game1 = Mock(spec=Game)
        gp1 = Mock(spec=GamePlayer)
        build1 = Mock(spec=Build)
        build1.display_name = "Test Build"
        build1.id = 1
        
        games_data = [
            (stats1, game1, gp1, build1)
        ]
        
        # Mock build attributes query
        mock_attr = Mock(spec=BuildAttribute)
        mock_attr.attribute_name = "Three-Point Shot"
        mock_attr.category = "Shooting"
        mock_attr.value_current = 85
        mock_attr.value_max = 99
        mock_attr.display_order = 1
        
        self.mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_attr]
        
        result = calculate_build_impact(self.mock_db, games_data)
        
        # Should return empty dict if not enough games (need >=5)
        self.assertIsInstance(result, dict)
    
    def test_generate_claim_candidates(self):
        """Test claim candidates generation."""
        payload = {
            "meta": {
                "username": "HintofLime",
                "total_games": 25
            },
            "defensive_matchups": {}
        }
        
        derived_metrics = {
            "overall": {
                "ast_to": 2.5,
                "efg_pct": 58.0,
                "pass_first_index": 45.0
            },
            "last_10": {
                "pts": 18.5,
                "ast": 6.0
            },
            "consistency": {
                "pts": {"mean": 17.0, "stddev": 3.5}
            },
            "floor_ceiling": {}
        }
        
        teammate_synergy = {}
        opponent_difficulty = {}
        build_impact = {}
        
        candidates = generate_claim_candidates(
            payload, derived_metrics, teammate_synergy, opponent_difficulty, build_impact
        )
        
        # Should generate some candidates
        self.assertIsInstance(candidates, list)
        
        # Check structure of candidates
        if len(candidates) > 0:
            candidate = candidates[0]
            self.assertIn("id", candidate)
            self.assertIn("type", candidate)
            self.assertIn("claim", candidate)
            self.assertIn("evidence", candidate)
            self.assertIn("reliability", candidate)
            self.assertIn("sample_size", candidate["evidence"])
    
    def test_claim_candidates_sorted_by_reliability(self):
        """Test that claim candidates are sorted by reliability."""
        payload = {
            "meta": {
                "username": "HintofLime",
                "total_games": 25
            },
            "defensive_matchups": {}
        }
        
        derived_metrics = {
            "overall": {
                "ast_to": 2.5,
                "efg_pct": 58.0
            },
            "last_10": {},
            "consistency": {},
            "floor_ceiling": {}
        }
        
        candidates = generate_claim_candidates(
            payload, derived_metrics, {}, {}, {}
        )
        
        # If we have multiple candidates, they should be sorted by reliability (descending)
        if len(candidates) > 1:
            for i in range(len(candidates) - 1):
                self.assertGreaterEqual(
                    candidates[i]["reliability"],
                    candidates[i + 1]["reliability"]
                )
    
    def test_synergy_respects_min_sample_filter(self):
        """Test that synergy analysis respects minimum sample size (>=5 games)."""
        # Create 4 games with same teammate (should be filtered out)
        games_data = []
        other_players_by_game = {}
        
        for i in range(4):
            stats = Mock(spec=PlayerGameStats)
            stats.pts = 20
            stats.ast = 5
            stats.reb = 5
            stats.tov = 2
            stats.fgm = 8
            stats.fga = 15
            stats.tpm = 2
            stats.tpa = 5
            stats.stl = 1
            stats.blk = 0
            
            game = Mock(spec=Game)
            game.id = f"game-{i}"
            gp = Mock(spec=GamePlayer)
            gp.team_side = Mock()
            gp.team_side.value = "HOME"
            
            games_data.append((stats, game, gp, None))
            other_players_by_game[f"game-{i}"] = [
                {"username": "Teammate1", "team_side": "HOME", "pts": 15, "ast": 3, "reb": 4}
            ]
        
        result = calculate_teammate_synergy(self.mock_db, "player-123", games_data, other_players_by_game)
        
        # Should return empty dict because we need >=5 shared games
        self.assertEqual(result, {})
    
    def test_build_impact_handles_missing_builds(self):
        """Test that build impact handles missing builds without crashing."""
        stats1 = Mock(spec=PlayerGameStats)
        stats1.pts = 20
        stats1.ast = 5
        stats1.reb = 5
        stats1.tov = 2
        stats1.fgm = 8
        stats1.fga = 15
        stats1.tpm = 2
        stats1.tpa = 5
        stats1.stl = 1
        stats1.blk = 0
        
        game1 = Mock(spec=Game)
        gp1 = Mock(spec=GamePlayer)
        build1 = None  # No build
        
        games_data = [
            (stats1, game1, gp1, build1)
        ]
        
        # Should not crash
        result = calculate_build_impact(self.mock_db, games_data)
        self.assertIsInstance(result, dict)


if __name__ == '__main__':
    unittest.main()

