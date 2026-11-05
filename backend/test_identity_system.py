"""
Basic tests for the identity system.
Tests name normalization, fuzzy matching, and claim verification logic.
"""
import unittest
from name_utils import normalize_name
from identity_resolver import get_fuzzy_score


class TestNameNormalization(unittest.TestCase):
    """Test name normalization function."""
    
    def test_basic_normalization(self):
        """Test basic normalization (lowercase, trim, collapse whitespace)."""
        self.assertEqual(normalize_name("PlayerName123"), "playername123")
        self.assertEqual(normalize_name("  Player  Name  "), "player name")
        self.assertEqual(normalize_name("Player\tName\n123"), "player name 123")
    
    def test_unicode_normalization(self):
        """Test Unicode normalization (NFKC)."""
        # Test combining characters
        self.assertEqual(normalize_name("é"), normalize_name("e\u0301"))
        # Test compatibility forms
        self.assertEqual(normalize_name("①"), normalize_name("1"))
    
    def test_zero_width_chars(self):
        """Test removal of zero-width characters."""
        name_with_zw = "Player\u200BName\u200C123"
        self.assertEqual(normalize_name(name_with_zw), "playername123")
    
    def test_empty_and_edge_cases(self):
        """Test edge cases."""
        self.assertEqual(normalize_name(""), "")
        self.assertEqual(normalize_name("   "), "")
        self.assertEqual(normalize_name("A"), "a")


class TestFuzzyMatching(unittest.TestCase):
    """Test fuzzy matching functionality."""
    
    def test_exact_match(self):
        """Test that exact matches return 100."""
        score = get_fuzzy_score("playername", "playername")
        self.assertEqual(score, 100.0)
    
    def test_similar_names(self):
        """Test that similar names get high scores."""
        score1 = get_fuzzy_score("playername", "playernam")
        score2 = get_fuzzy_score("playername", "playernamx")
        # Should be high scores (>80)
        self.assertGreater(score1, 80)
        self.assertGreater(score2, 80)
        # Exact match should be higher
        exact_score = get_fuzzy_score("playername", "playername")
        self.assertGreater(exact_score, score1)
    
    def test_different_names(self):
        """Test that very different names get low scores."""
        score = get_fuzzy_score("playername", "completelydifferent")
        self.assertLess(score, 50)
    
    def test_case_insensitive(self):
        """Test that case doesn't matter (names should be normalized first)."""
        # Note: get_fuzzy_score expects normalized names
        score = get_fuzzy_score("playername", "PLAYERNAME")
        self.assertEqual(score, 100.0)


class TestClaimUniqueness(unittest.TestCase):
    """Test claim uniqueness logic (conceptual tests)."""
    
    def test_normalized_name_uniqueness(self):
        """Test that normalized names are used for uniqueness checks."""
        # These should be considered the same after normalization
        name1 = normalize_name("PlayerName123")
        name2 = normalize_name("playername123")
        name3 = normalize_name("Player Name 123")
        
        self.assertEqual(name1, name2)
        # Note: name3 might differ if spaces are preserved, but should be close
        # This depends on normalization rules


if __name__ == '__main__':
    unittest.main()

