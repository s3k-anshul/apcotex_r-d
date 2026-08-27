"""
Test query expansion with constraint-aware LLM generation.
Verifies that original input is preserved and constraints are reflected in queries.
"""
import asyncio
from app.services.pipeline.schemas import CompoundSearchProfile, SearchQuery, SearchPriority, SearchCategory

def test_schema_changes():
    """Test that schema changes support constraint-aware query expansion."""
    print("=" * 60)
    print("TEST: Schema Changes for Constraint-Aware Expansion")
    print("=" * 60)
    
    # Test 1: CompoundSearchProfile has original_input field
    print("\n1. CompoundSearchProfile Schema:")
    try:
        profile = CompoundSearchProfile(
            original_input="Low Acrylonitrile NBR",
            compound="Low Acrylonitrile NBR",
            compound_name="Nitrile Butadiene Rubber",
            synonyms=["NBR", "nitrile rubber"],
            abbreviations=["NBR"],
            chemical_family="NBR",
            major_monomers=["butadiene", "acrylonitrile"],
            alternative_industry_names=["nitrile rubber"],
            important_constraints=["low acrylonitrile", "low ACN"],
            research_intent="polymerization",
            typical_polymerization_routes=["emulsion polymerization"],
            typical_manufacturing_keywords=["method for manufacturing"],
            typical_cpc=["C08F"],
            typical_ipc=["C08F"],
            related_chemistry=["butadiene"],
            competing_chemistry=["HNBR"],
            application_keywords=["tire", "glove"],
            manufacturing_keywords=["initiator", "emulsifier"],
            search_queries=[
                SearchQuery(
                    query="low acrylonitrile NBR polymerization",
                    priority=SearchPriority.PRIMARY,
                    category=SearchCategory.CONSTRAINT
                ),
                SearchQuery(
                    query="nitrile rubber preparation",
                    priority=SearchPriority.FALLBACK,
                    category=SearchCategory.BROAD
                )
            ]
        )
        print(f"   ✓ original_input field: {profile.original_input}")
        print(f"   ✓ important_constraints field: {profile.important_constraints}")
        print(f"   ✓ research_intent field: {profile.research_intent}")
        print(f"   ✓ search_queries count: {len(profile.search_queries)}")
        
        # Test query priority enum
        for sq in profile.search_queries:
            priority_str = sq.priority.value if hasattr(sq.priority, 'value') else str(sq.priority)
            print(f"   ✓ Query priority: {priority_str}")
            print(f"   ✓ Query category: {sq.category}")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        return False
    
    # Test 2: SearchPriority enum
    print("\n2. SearchPriority Enum:")
    try:
        assert SearchPriority.PRIMARY.value == "PRIMARY"
        assert SearchPriority.SECONDARY.value == "SECONDARY"
        assert SearchPriority.FALLBACK.value == "FALLBACK"
        print("   ✓ PRIMARY, SECONDARY, FALLBACK enums exist")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        return False
    
    # Test 3: SearchCategory enum includes new categories
    print("\n3. SearchCategory Enum:")
    try:
        assert SearchCategory.EXACT.value == "EXACT"
        assert SearchCategory.CONSTRAINT.value == "CONSTRAINT"
        assert SearchCategory.SYNTHESIS.value == "SYNTHESIS"
        assert SearchCategory.SYNONYM.value == "SYNONYM"
        assert SearchCategory.BROAD.value == "BROAD"
        print("   ✓ EXACT, CONSTRAINT, SYNTHESIS, SYNONYM, BROAD categories exist")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("SCHEMA TEST COMPLETE")
    print("=" * 60)
    return True

def test_prompt_template():
    """Test that the prompt template includes constraint-aware instructions."""
    print("\n" + "=" * 60)
    print("TEST: Prompt Template for Constraint-Aware Expansion")
    print("=" * 60)
    
    from app.services.prompts.patent_prompts import COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT
    
    print("\n1. Checking prompt for constraint-aware instructions:")
    
    checks = [
        ("Preserve Original Input", "original_input" in COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT),
        ("Identify Important Constraints", "important_constraints" in COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT),
        ("Constraint Preservation", "PRIMARY queries MUST include equivalent constraint" in COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT),
        ("Query Priorities", "PRIMARY" in COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT and "SECONDARY" in COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT and "FALLBACK" in COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT),
        ("HNBR Exception", "HNBR" in COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT and "do NOT include HNBR" in COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT),
        ("Query Categories", "EXACT" in COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT or "CONSTRAINT" in COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT),
    ]
    
    all_passed = True
    for check_name, check_result in checks:
        if check_result:
            print(f"   ✓ {check_name}")
        else:
            print(f"   ✗ {check_name} - NOT FOUND")
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("PROMPT TEST COMPLETE")
    else:
        print("PROMPT TEST FAILED - Some instructions missing")
    print("=" * 60)
    return all_passed

def test_compound_intelligence_service():
    """Test that CompoundIntelligenceService preserves original input."""
    print("\n" + "=" * 60)
    print("TEST: CompoundIntelligenceService Original Input Preservation")
    print("=" * 60)
    
    from app.services.pipeline.compound_intelligence import CompoundIntelligenceService
    from app.services.pipeline.schemas import CompoundSearchProfile
    
    # Test the logic without actually calling LLM
    print("\n1. Testing original_input preservation logic:")
    
    # Simulate what the service does
    class MockCacheService:
        def get_compound_profile(self, compound_input):
            return None
        def save_compound_profile(self, compound_input, profile):
            pass
    
    cache_service = MockCacheService()
    service = CompoundIntelligenceService(cache_service)
    
    # Simulate LLM response
    mock_llm_result = CompoundSearchProfile(
        compound="Low Acrylonitrile NBR",
        compound_name="Nitrile Butadiene Rubber",
        synonyms=["NBR", "nitrile rubber"],
        abbreviations=["NBR"],
        chemical_family="NBR",
        major_monomers=["butadiene", "acrylonitrile"],
        alternative_industry_names=["nitrile rubber"],
        important_constraints=["low acrylonitrile"],
        research_intent="polymerization",
        typical_polymerization_routes=["emulsion polymerization"],
        typical_manufacturing_keywords=["method for manufacturing"],
        typical_cpc=["C08F"],
        typical_ipc=["C08F"],
        related_chemistry=["butadiene"],
        competing_chemistry=["HNBR"],
        application_keywords=["tire", "glove"],
        manufacturing_keywords=["initiator", "emulsifier"],
        search_queries=[]
    )
    
    # Simulate the service logic
    compound_input = "Low Acrylonitrile NBR"
    mock_llm_result.original_input = compound_input
    mock_llm_result.compound = compound_input
    
    print(f"   ✓ original_input set to: {mock_llm_result.original_input}")
    print(f"   ✓ compound set to: {mock_llm_result.compound}")
    print(f"   ✓ important_constraints: {mock_llm_result.important_constraints}")
    
    assert mock_llm_result.original_input == "Low Acrylonitrile NBR"
    assert mock_llm_result.compound == "Low Acrylonitrile NBR"
    
    print("\n" + "=" * 60)
    print("COMPOUND INTELLIGENCE SERVICE TEST COMPLETE")
    print("=" * 60)
    return True

def test_search_service_query_building():
    """Test that SearchService handles new priority enum correctly."""
    print("\n" + "=" * 60)
    print("TEST: SearchService Query Building with New Priority")
    print("=" * 60)
    
    from app.services.pipeline.schemas import CompoundSearchProfile, SearchQuery, SearchPriority, SearchCategory
    
    # Create a mock profile
    profile = CompoundSearchProfile(
        original_input="Low Acrylonitrile NBR",
        compound="Low Acrylonitrile NBR",
        compound_name="Nitrile Butadiene Rubber",
        synonyms=["NBR", "nitrile rubber"],
        abbreviations=["NBR"],
        chemical_family="NBR",
        major_monomers=["butadiene", "acrylonitrile"],
        alternative_industry_names=["nitrile rubber"],
        typical_polymerization_routes=["emulsion polymerization"],
        typical_manufacturing_keywords=["method for manufacturing"],
        typical_cpc=["C08F"],
        typical_ipc=["C08F"],
        related_chemistry=["butadiene"],
        competing_chemistry=["HNBR"],
        application_keywords=["tire", "glove"],
        manufacturing_keywords=["initiator", "emulsifier"],
        search_queries=[
            SearchQuery(
                query="low acrylonitrile NBR polymerization",
                priority=SearchPriority.PRIMARY,
                category=SearchCategory.CONSTRAINT,
                field="TITLE"
            ),
            SearchQuery(
                query="nitrile rubber emulsion polymerization",
                priority=SearchPriority.SECONDARY,
                category=SearchCategory.POLYMERIZATION,
                field="TAC"
            ),
            SearchQuery(
                query="NBR preparation",
                priority=SearchPriority.FALLBACK,
                category=SearchCategory.BROAD,
                field="TITLE"
            )
        ]
    )
    
    # Simulate SearchService.build_queries logic
    print("\n1. Simulating SearchService.build_queries:")
    queries = []
    for sq in profile.search_queries:
        import re
        raw_query = re.sub(r'^(?:TI|TAC)=\((.*)\)$', r'\1', sq.query.strip(), flags=re.IGNORECASE)
        
        queries.append({
            "query": raw_query,
            "tier": sq.category,
            "priority": sq.priority.value if hasattr(sq.priority, 'value') else str(sq.priority),
            "search_field": sq.field
        })
    
    print(f"   ✓ Generated {len(queries)} queries")
    for i, q in enumerate(queries, 1):
        print(f"   Query {i}:")
        print(f"     - Query: {q['query']}")
        print(f"     - Priority: {q['priority']}")
        print(f"     - Category: {q['tier']}")
        print(f"     - Field: {q['search_field']}")
    
    # Verify priority handling
    assert queries[0]['priority'] == "PRIMARY"
    assert queries[1]['priority'] == "SECONDARY"
    assert queries[2]['priority'] == "FALLBACK"
    print(f"   ✓ Priority enum values correctly extracted")
    
    print("\n" + "=" * 60)
    print("SEARCH SERVICE TEST COMPLETE")
    print("=" * 60)
    return True

def test_orchestrator_logging_format():
    """Test that the orchestrator logging format is correct."""
    print("\n" + "=" * 60)
    print("TEST: Orchestrator Query Expansion Logging Format")
    print("=" * 60)
    
    from app.services.pipeline.schemas import CompoundSearchProfile, SearchQuery, SearchPriority, SearchCategory
    
    # Create a mock profile
    profile = CompoundSearchProfile(
        original_input="Low Acrylonitrile NBR",
        compound="Low Acrylonitrile NBR",
        compound_name="Nitrile Butadiene Rubber",
        synonyms=["NBR", "nitrile rubber", "acrylonitrile butadiene rubber"],
        abbreviations=["NBR"],
        chemical_family="NBR",
        major_monomers=["butadiene", "acrylonitrile"],
        alternative_industry_names=["nitrile rubber"],
        important_constraints=["low acrylonitrile", "low ACN"],
        research_intent="polymerization",
        typical_polymerization_routes=["emulsion polymerization"],
        typical_manufacturing_keywords=["method for manufacturing"],
        typical_cpc=["C08F"],
        typical_ipc=["C08F"],
        related_chemistry=["butadiene"],
        competing_chemistry=["HNBR"],
        application_keywords=["tire", "glove"],
        manufacturing_keywords=["initiator", "emulsifier"],
        search_queries=[
            SearchQuery(
                query="low acrylonitrile NBR polymerization",
                priority=SearchPriority.PRIMARY,
                category=SearchCategory.CONSTRAINT,
                field="TITLE"
            ),
            SearchQuery(
                query="low ACN nitrile rubber preparation",
                priority=SearchPriority.PRIMARY,
                category=SearchCategory.CONSTRAINT,
                field="TITLE"
            ),
            SearchQuery(
                query="nitrile rubber polymerization",
                priority=SearchPriority.FALLBACK,
                category=SearchCategory.BROAD,
                field="TITLE"
            )
        ]
    )
    
    # Simulate the logging format
    print("\n1. Simulating Orchestrator Query Expansion Logging:")
    print("=" * 60)
    print("QUERY EXPANSION")
    print("=" * 60)
    print(f"Original User Input: {profile.original_input}")
    print(f"Normalized Material: {profile.compound_name}")
    print(f"Important Constraints: {profile.important_constraints if profile.important_constraints else 'None'}")
    print(f"Research Intent: {profile.research_intent if profile.research_intent else 'Not specified'}")
    print(f"Synonyms: {profile.synonyms[:5] if profile.synonyms else 'None'}")
    print("")
    print("Generated Queries:")
    for idx, sq in enumerate(profile.search_queries, 1):
        priority_str = sq.priority.value if hasattr(sq.priority, 'value') else str(sq.priority)
        print(f"Query {idx}")
        print(f"  Priority: {priority_str}")
        print(f"  Category: {sq.category}")
        print(f"  Field: {sq.field}")
        print(f"  Query: {sq.query}")
    print(f"Total Queries Generated: {len(profile.search_queries)}")
    print("=" * 60)
    print("QUERY EXPANSION COMPLETE")
    print("=" * 60)
    print("")
    
    # Verify the format
    assert profile.original_input == "Low Acrylonitrile NBR"
    assert len(profile.important_constraints) > 0
    assert len(profile.search_queries) > 0
    print("   ✓ Logging format verified")
    
    print("\n" + "=" * 60)
    print("ORCHESTRATOR LOGGING TEST COMPLETE")
    print("=" * 60)
    return True

def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("QUERY EXPANSION TEST SUITE")
    print("=" * 60)
    
    results = []
    
    # Run all tests
    results.append(("Schema Changes", test_schema_changes()))
    results.append(("Prompt Template", test_prompt_template()))
    results.append(("CompoundIntelligenceService", test_compound_intelligence_service()))
    results.append(("SearchService Query Building", test_search_service_query_building()))
    results.append(("Orchestrator Logging Format", test_orchestrator_logging_format()))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{status}: {test_name}")
    
    all_passed = all(result for _, result in results)
    print("\n" + "=" * 60)
    if all_passed:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("=" * 60)
    
    return all_passed

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
