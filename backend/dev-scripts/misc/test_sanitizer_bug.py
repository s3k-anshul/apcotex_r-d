import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.pipeline.search_service import SearchService

class MockProfile:
    def __init__(self):
        self.compound = "Nitrile Butadiene Rubber"
        self.compound_name = "Nitrile Butadiene Rubber"
        self.base_chemistry = "nitrile butadiene rubber"
        self.synonyms = ["NBR"]
        self.abbreviations = ["NBR"]

def test_sanitizer():
    service = SearchService()
    profile = MockProfile()
    
    # Simulate add_query directly
    def sanitize(raw_query):
        import re
        q = service._enforce_phrase_anchoring(raw_query, profile)
        q = re.sub(r'(?<=\w)"(?=\w)', '', q)
        q = q.replace('""', '')
        if q.count('"') % 2 != 0:
            q = q.replace('"', '')
        if q.count('(') != q.count(')'):
            q = q.replace('(', '').replace(')', '')
        q = re.sub(r'\s+', ' ', q).strip()
        q = re.sub(r'("[^"]+")(?:\s+\1)+', r'\1', q, flags=re.IGNORECASE)
        q = re.sub(r'\b(\w+)(?:\s+\1\b)+', r'\1', q, flags=re.IGNORECASE)
        q = re.sub(r'\b(AND|OR)\s+(AND|OR)\b', r'\1', q, flags=re.IGNORECASE)
        return q

    print(f"Sanitized: {sanitize('Nitrile Butadiene Rubber')}")
    print(f"Sanitized 2x: {sanitize(sanitize('Nitrile Butadiene Rubber'))}")
    print(f"Sanitized: {sanitize('Nitrile Butadiene Rubber polymerization')}")
    print(f"Sanitized: {sanitize('Low Acrylonitrile Nitrile Butadiene Rubber polymerization')}")
    print(f"Sanitized: {sanitize('\"nitrile butadiene rubber\" polymerization')}")
    
test_sanitizer()
