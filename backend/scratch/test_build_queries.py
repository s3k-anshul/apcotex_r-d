import sys
import os
import asyncio
from unittest.mock import Mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.pipeline.search_service import SearchService

def test_queries():
    service = SearchService()
    profile = Mock()
    profile.compound = "Nitrile Butadiene Rubber"
    profile.compound_name = "Nitrile Butadiene Rubber"
    profile.base_chemistry = "nitrile butadiene rubber"
    profile.synonyms = ["NBR", "nitrile elastomer"]
    profile.abbreviations = ["NBR"]
    profile.synthesis_terms = ["polymerization", "emulsion polymerization", "synthesis"]
    profile.transformation_terms = ["hydrogenation"]
    profile.target_attributes = ["High Acrylonitrile", "low temp"]
    profile.material_aliases = ["Buna-N"]
    profile.precursor_terms = ["acrylonitrile", "butadiene"]
    profile.search_queries = []
    
    queries = service.build_queries(profile)
    print(f"Generated {len(queries)} queries:")
    for i, q in enumerate(queries):
        print(f"{i+1}. {q['tier']} : {q['query']}")

test_queries()
