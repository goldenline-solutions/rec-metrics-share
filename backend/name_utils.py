"""
Name normalization utilities for the identity system.
Handles Unicode normalization, whitespace cleanup, and case-insensitive matching.
"""
import unicodedata
import re


def normalize_name(name: str) -> str:
    """
    Normalize a player name for consistent matching.
    
    Steps:
    1. Unicode normalize (NFKC) - combines characters and compatibility forms
    2. Remove zero-width characters
    3. Lowercase
    4. Trim whitespace
    5. Collapse multiple whitespace to single space
    
    Args:
        name: Raw name string
        
    Returns:
        Normalized name string
    """
    if not name:
        return ""
    
    # Step 1: Unicode normalize (NFKC)
    # This combines characters like "é" and "e\u0301", and converts compatibility forms
    normalized = unicodedata.normalize("NFKC", name)
    
    # Step 2: Remove zero-width characters
    # Common zero-width chars: \u200B (zero-width space), \u200C (zero-width non-joiner), etc.
    zero_width_chars = [
        '\u200B',  # Zero-width space
        '\u200C',  # Zero-width non-joiner
        '\u200D',  # Zero-width joiner
        '\uFEFF',  # Zero-width no-break space
        '\u200E',  # Left-to-right mark
        '\u200F',  # Right-to-left mark
        '\u202A',  # Left-to-right embedding
        '\u202B',  # Right-to-left embedding
        '\u202C',  # Pop directional formatting
        '\u202D',  # Left-to-right override
        '\u202E',  # Right-to-left override
    ]
    for char in zero_width_chars:
        normalized = normalized.replace(char, '')
    
    # Step 3: Lowercase
    normalized = normalized.lower()
    
    # Step 4: Trim whitespace
    normalized = normalized.strip()
    
    # Step 5: Collapse multiple whitespace to single space
    # This handles tabs, newlines, multiple spaces, etc.
    normalized = re.sub(r'\s+', ' ', normalized)
    
    return normalized


def are_names_similar(name1: str, name2: str, threshold: float = 0.95) -> bool:
    """
    Check if two normalized names are similar enough.
    This is a simple check - for fuzzy matching, use the identity_resolver.
    
    Args:
        name1: First normalized name
        name2: Second normalized name
        threshold: Similarity threshold (0.0 to 1.0)
        
    Returns:
        True if names are similar enough
    """
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)
    
    if norm1 == norm2:
        return True
    
    # Simple similarity: check if one contains the other (for partial matches)
    if norm1 in norm2 or norm2 in norm1:
        # Calculate simple ratio
        shorter = min(len(norm1), len(norm2))
        longer = max(len(norm1), len(norm2))
        if shorter > 0:
            ratio = shorter / longer
            return ratio >= threshold
    
    return False

