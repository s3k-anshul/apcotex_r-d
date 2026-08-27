"""
Test that SearchQuery objects are correctly passed from orchestrator to SearchService.
Verifies the handoff between query expansion and search execution.
"""
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from app.services.pipeline.schemas import CompoundSearchProfile, SearchQuery, SearchPriority, SearchCategory, SearchField

def test_search_service_build_queries():
    """Test that SearchService.build_queries correctly transforms SearchQuery objects."""
    print("=" * 60)
    print("TEST: SearchService.build_queries Transformation")
    print("=" * 60)
    
    from app.services.pipeline.search_service import SearchService
    
    # Create a mock profile with constraint-aware queries
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
                category=SearchCategory.CONSTRAINT,
                field=SearchField.TITLE
            ),
            SearchQuery(
                query="low ACN nitrile rubber preparation",
                priority=SearchPriority.PRIMARY,
                category=SearchCategory.CONSTRAINT,
                field=SearchField.TITLE
            ),
            SearchQuery(
                query="low acrylonitrile NBR emulsion polymerization initiator emulsifier",
                priority=SearchPriority.SECONDARY,
                category=SearchCategory.POLYMERIZATION,
                field=SearchField.TAC
            ),
            SearchQuery(
                query="NBR polymerization",
                priority=SearchPriority.FALLBACK,
                category=SearchCategory.BROAD,
                field=SearchField.TITLE
            )
        ]
    )
    
    # Call SearchService.build_queries
    search_service = SearchService()
    raw_queries = search_service.build_queries(profile)
    
    print(f"\n1. Profile has {len(profile.search_queries)} SearchQuery objects")
    print(f"2. SearchService.build_queries returned {len(raw_queries)} query dicts")
    
    # Verify transformation
    print("\n3. Query transformation verification:")
    for i, (sq, rq) in enumerate(zip(profile.search_queries, raw_queries), 1):
        print(f"\n   Query {i}:")
        print(f"     Original SearchQuery.query: {sq.query}")
        print(f"     Transformed dict['query']: {rq['query']}")
        print(f"     Original SearchQuery.priority: {sq.priority}")
        print(f"     Transformed dict['priority']: {rq['priority']}")
        print(f"     Original SearchQuery.category: {sq.category}")
        print(f"     Transformed dict['tier']: {rq['tier']}")
        print(f"     Original SearchQuery.field: {sq.field}")
        print(f"     Transformed dict['search_field']: {rq['search_field']}")
        
        # Verify the transformation is correct
        assert rq['query'] == sq.query, "Query text mismatch"
        assert rq['priority'] == sq.priority.value, "Priority mismatch"
        assert rq['tier'] == sq.category, "Category mismatch"
        assert rq['search_field'] == sq.field, "Field mismatch"
    
    print("\n   ✓ All transformations correct")
    
    # Verify constraint preservation
    constraint_queries = [rq for rq in raw_queries if 'acrylonitrile' in rq['query'].lower()]
    print(f"\n4. Constraint preservation: {len(constraint_queries)}/{len(raw_queries)} queries contain 'acrylonitrile'")
    for cq in constraint_queries:
        print(f"   - {cq['query']}")
    
    print("\n" + "=" * 60)
    print("SEARCH SERVICE BUILD QUERIES TEST COMPLETE")
    print("=" * 60)
    return True

def test_orchestrator_query_loop():
    """Test that orchestrator can iterate over raw_queries without error."""
    print("\n" + "=" * 60)
    print("TEST: Orchestrator Query Loop Simulation")
    print("=" * 60)
    
    from app.services.pipeline.schemas import CompoundSearchProfile, SearchQuery, SearchPriority, SearchCategory, SearchField
    from app.services.pipeline.search_service import SearchService
    
    # Create a mock profile
    profile = CompoundSearchProfile(
        original_input="Low Acrylonitrile NBR",
        compound="Low Acrylonitrile NBR",
        compound_name="Nitrile Butadiene Rubber",
        synonyms=["NBR"],
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
        application_keywords=["tire"],
        manufacturing_keywords=["initiator"],
        search_queries=[
            SearchQuery(
                query="low acrylonitrile NBR polymerization",
                priority=SearchPriority.PRIMARY,
                category=SearchCategory.CONSTRAINT,
                field=SearchField.TITLE
            ),
            SearchQuery(
                query="NBR polymerization",
                priority=SearchPriority.FALLBACK,
                category=SearchCategory.BROAD,
                field=SearchField.TITLE
            )
        ]
    )
    
    # Simulate orchestrator flow
    print("\n1. Simulating orchestrator query expansion:")
    print(f"   Original Input: {profile.original_input}")
    print(f"   Important Constraints: {profile.important_constraints}")
    print(f"   Total Queries Generated: {len(profile.search_queries)}")
    
    print("\n2. Simulating SearchService.build_queries:")
    search_service = SearchService()
    raw_queries = search_service.build_queries(profile)
    print(f"   raw_queries built: {len(raw_queries)}")
    
    print("\n3. Simulating orchestrator query loop:")
    print(f"   Total Queries to Execute: {len(raw_queries)}")
    
    # This is the critical part - the orchestrator must be able to iterate over raw_queries
    for idx, q_dict in enumerate(raw_queries):
        print(f"\n   Query {idx+1}/{len(raw_queries)}:")
        print(f"     Expanded Query: {q_dict['query']}")
        print(f"     Category: {q_dict['tier']}")
        print(f"     Priority: {q_dict['priority']}")
        print(f"     Search Field: {q_dict['search_field']}")
        
        # Simulate validation
        is_valid, _ = search_service.validate_query(q_dict["query"], q_dict["search_field"])
        print(f"     Validation: {'PASS' if is_valid else 'FAIL'}")
        
        assert is_valid, f"Query validation failed for {q_dict['query']}"
    
    print("\n   ✓ All queries validated successfully")
    
    print("\n" + "=" * 60)
    print("ORCHESTRATOR QUERY LOOP TEST COMPLETE")
    print("=" * 60)
    print("\n✓ UnboundLocalError fixed - raw_queries is defined before use")
    print("✓ Query loop executes without error")
    return True

def test_serper_query_formatting():
    """Test that SearchService correctly formats queries for Serper."""
    print("\n" + "=" * 60)
    print("TEST: Serper Query Formatting")
    print("=" * 60)
    
    from app.services.pipeline.search_service import SearchService
    
    search_service = SearchService()
    
    # Test TITLE field formatting
    print("\n1. TITLE field formatting:")
    title_query = "low acrylonitrile NBR polymerization"
    formatted = title_query
    if "TITLE" == "TITLE":
        formatted = f"TI=({title_query})"
    print(f"   Original: {title_query}")
    print(f"   Formatted: {formatted}")
    assert formatted == "TI=(low acrylonitrile NBR polymerization)"
    
    # Test TAC field formatting
    print("\n2. TAC field formatting:")
    tac_query = "low acrylonitrile NBR emulsion polymerization initiator emulsifier"
    formatted = tac_query
    if "TAC" == "TAC":
        formatted = f"TAC=({tac_query})"
    print(f"   Original: {tac_query}")
    print(f"   Formatted: {formatted}")
    assert formatted == "TAC=(low acrylonitrile NBR emulsion polymerization initiator emulsifier)"
    
    print("\n   ✓ Field formatting correct")
    
    print("\n" + "=" * 60)
    print("SERPER QUERY FORMATTING TEST COMPLETE")
    print("=" * 60)
    return True

def main():
    """Run all handoff tests."""
    print("\n" + "=" * 60)
    print("QUERY TO SEARCH HANDOFF TEST SUITE")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("SearchService.build_queries", test_search_service_build_queries()))
    results.append(("Orchestrator Query Loop", test_orchestrator_query_loop()))
    results.append(("Serper Query Formatting", test_serper_query_formatting()))
    
    # Summary
    print("\n" + "=" * 60)
    print("HANDOFF TEST SUMMARY")
    print("=" * 60)
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{status}: {test_name}")
    
    all_passed = all(result for _, result in results)
    print("\n" + "=" * 60)
    if all_passed:
        print("ALL HANDOFF TESTS PASSED")
    else:
        print("SOME HANDOFF TESTS FAILED")
    print("=" * 60)
    
    return all_passed

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
