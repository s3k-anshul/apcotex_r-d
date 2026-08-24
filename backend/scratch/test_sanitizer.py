import sys
import os
import asyncio
from unittest.mock import Mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.pipeline.search_service import SearchService

def test_sanitizer():
    service = SearchService()
    profile = Mock()
    profile.base_chemistry = "nitrile butadiene rubber"
    profile.compound_name = "Nitrile Butadiene Rubber"
    profile.synonyms = ["NBR", "nitrile elastomer"]
    profile.abbreviations = []
    
    # Test cases
    cases = [
        ("nitrile butadiene rubber", '"nitrile butadiene rubber"'),
        ("acrylonitrile butadiene rubber", "acrylonitrile butadiene rubber"), # Should not be split!
        ("High Acrylonitrile NBR", 'High Acrylonitrile "NBR"'),
        ("acrylo\"nitrile", None), # Malformed
        ("\"term\"\"", None), # Malformed
        ("\"\"term", "term"),
        ("polymerization polymerization", "polymerization")
    ]
    
    for q, expected in cases:
        # We need to simulate add_query because it does the sanitization
        # Let's just run _enforce_phrase_anchoring first
        res = service._enforce_phrase_anchoring(q, profile)
        print(f"Original: {q}")
        print(f"Phrase Anchored: {res}")
        print("---")

test_sanitizer()
