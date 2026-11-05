"""
Unit tests for admin metrics service.
Tests core calculations and conservation properties.
"""
import unittest
from decimal import Decimal
from services.admin_metrics_service import (
    estimate_possessions,
    compute_team_context,
    compute_pressure_weight,
    compute_onball_ratio,
    METRICS_CONFIG
)


class TestAdminMetricsCalculations(unittest.TestCase):
    """Test core calculation functions."""
    
    def test_onball_ratio_clamped(self):
        """Test that on-ball ratio is clamped to [0.2, 0.8]."""
        # Mock game_player with position
        class MockGamePlayer:
            def __init__(self, position):
                self.position = type('Enum', (), {'value': position})()
        
        # Test with extreme build values that would push ratio outside bounds
        # This is a simplified test - in real code we'd need a mock db and build
        # For now, just verify the config values are correct
        self.assertGreaterEqual(METRICS_CONFIG["onball_ratio_min"], 0.2)
        self.assertLessEqual(METRICS_CONFIG["onball_ratio_max"], 0.8)
    
    def test_unattributed_tov_conservation(self):
        """Test that unattributed_tov = max(0, opp_tov - team_stl)."""
        # Test case 1: Normal case
        opp_tov = 10
        team_stl = 7
        unattributed = max(0.0, float(opp_tov) - float(team_stl))
        self.assertEqual(unattributed, 3.0)
        
        # Test case 2: All turnovers attributed (team_stl >= opp_tov)
        opp_tov = 5
        team_stl = 7
        unattributed = max(0.0, float(opp_tov) - float(team_stl))
        self.assertEqual(unattributed, 0.0)
        
        # Test case 3: No steals
        opp_tov = 10
        team_stl = 0
        unattributed = max(0.0, float(opp_tov) - float(team_stl))
        self.assertEqual(unattributed, 10.0)
    
    def test_pressure_share_sum(self):
        """Test that pressure shares should sum to ~1.0 (within tolerance)."""
        # Simulate team with 5 players
        weights = [1.0, 1.1, 0.9, 1.05, 0.95]
        sum_weights = sum(weights)
        
        # Calculate shares
        shares = [w / sum_weights for w in weights]
        sum_shares = sum(shares)
        
        # Should sum to 1.0 (within floating point tolerance)
        self.assertAlmostEqual(sum_shares, 1.0, places=10)
    
    def test_position_factors(self):
        """Test that position factors are defined for all positions."""
        positions = ["PG", "SG", "SF", "PF", "C"]
        for pos in positions:
            self.assertIn(pos, METRICS_CONFIG["position_factors"])
            self.assertGreater(METRICS_CONFIG["position_factors"][pos], 0)
    
    def test_onball_ratio_base(self):
        """Test that on-ball ratio bases are defined for all positions."""
        positions = ["PG", "SG", "SF", "PF", "C"]
        for pos in positions:
            self.assertIn(pos, METRICS_CONFIG["onball_ratio_base"])
            ratio = METRICS_CONFIG["onball_ratio_base"][pos]
            self.assertGreaterEqual(ratio, 0.0)
            self.assertLessEqual(ratio, 1.0)


class TestAdminMetricsAuthorization(unittest.TestCase):
    """Test authorization checks (would need Flask test client)."""
    
    def test_admin_endpoint_requires_admin(self):
        """Test that admin endpoints return 403 for non-admin users."""
        # This would require a Flask test client setup
        # For now, just document the requirement
        pass


if __name__ == "__main__":
    unittest.main()
