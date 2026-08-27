import sys
import os
import asyncio
import json

# Ensure app is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.pipeline.search_service import SearchService
from app.services.pipeline.schemas import CompoundSearchProfile

async def test_query_expansion():
    # Constructing a dummy profile similar to what LLM generated
    profile_data = {
        "original_input": "Low Acrylonitrile NBR",
        "compound": "Low Acrylonitrile NBR",
        "compound_name": "Low Acrylonitrile Nitrile Butadiene Rubber",
        "synonyms": ["low ACN nitrile rubber", "low acrylonitrile butadiene copolymer", "low ACN NBR", "low nitrile rubber"],
        "abbreviations": ["NBR", "LNBR"],
        "chemical_family": "NBR",
        "major_monomers": ["acrylonitrile", "1,3-butadiene"],
        "alternative_industry_names": ["Buna-N", "Perbunan", "Nipol", "Krynac", "Nancar"],
        "important_constraints": ["low acrylonitrile", "low ACN content", "acrylonitrile content less than 25 percent"],
        "research_intent": "polymerization and preparation of nitrile rubber with low acrylonitrile content",
        "typical_polymerization_routes": ["emulsion polymerization", "cold emulsion polymerization", "free radical emulsion polymerization"],
        "typical_manufacturing_keywords": ["method for manufacturing", "process for producing", "polymerization process", "preparation of nitrile rubber"],
        "typical_cpc": ["C08F236/12", "C08L9/02", "C08F2/22"],
        "typical_ipc": ["C08F236/12", "C08L9/02"],
        "related_chemistry": ["hydrogenated nitrile butadiene rubber", "HNBR", "carboxylated nitrile rubber", "XNBR"],
        "competing_chemistry": ["styrene butadiene rubber", "SBR", "ethylene propylene diene monomer", "EPDM", "chloroprene rubber", "CR"],
        "application_keywords": ["glove", "tire", "film", "battery", "adhesive"],
        "manufacturing_keywords": ["initiator", "emulsifier", "reactor", "conversion", "catalyst", "shortstop", "chain transfer agent"],
        "target_composition_keywords": ["acrylonitrile", "ACN", "bound acrylonitrile"],
        "target_composition_range": "18-24%",
        "search_queries": []
    }
    
    profile = CompoundSearchProfile(**profile_data)
    
    search_service = SearchService()
    queries = search_service.build_queries(profile)
    
    print("============================================================")
    print("QUERY EXPANSION")
    print("============================================================")
    print("Original Input:")
    print(profile.original_input)
    print("\nBase Compound:")
    print(profile.chemical_family)
    print("\nDetected Specificity:")
    print(profile.important_constraints)
    print("\nGenerated Search Concepts:")
    print(profile.target_composition_keywords)
    print("\nExpanded Queries:")
    for i, q in enumerate(queries, 1):
        print(f"{i}. {q['query']} (Field: {q['field']}, Category: {q['category']})")
    print("============================================================")

if __name__ == "__main__":
    asyncio.run(test_query_expansion())
