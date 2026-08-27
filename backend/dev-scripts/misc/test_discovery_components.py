"""
Test discovery components: date utils, competitor service, website service.
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.pipeline.date_utils import get_date_window, normalize_publication_date, is_date_in_window, PublicationFilter
from app.services.pipeline.competitor_service import CompetitorService
from app.services.pipeline.website_service import WebsiteService
from app.services.pipeline.schemas import CompoundSearchProfile

def test_date_window_calculation():
    """Test rolling date window calculation."""
    print("=" * 60)
    print("TEST: Date Window Calculation")
    print("=" * 60)
    
    ref_date = datetime(2024, 8, 1)
    
    # Test ANY_TIME
    start, end = get_date_window("ANY_TIME", ref_date)
    print(f"ANY_TIME: start={start}, end={end}")
    assert start is None and end is None, "ANY_TIME should return None, None"
    
    # Test LAST_3_YEARS
    start, end = get_date_window("LAST_3_YEARS", ref_date)
    print(f"LAST_3_YEARS: start={start}, end={end}")
    expected_start = ref_date - timedelta(days=3*365)
    assert abs((start - expected_start).days) < 5, "LAST_3_YEARS start date incorrect"
    assert end == ref_date, "LAST_3_YEARS end date should be reference date"
    
    # Test LAST_5_YEARS
    start, end = get_date_window("LAST_5_YEARS", ref_date)
    print(f"LAST_5_YEARS: start={start}, end={end}")
    expected_start = ref_date - timedelta(days=5*365)
    assert abs((start - expected_start).days) < 5, "LAST_5_YEARS start date incorrect"
    
    # Test LAST_10_YEARS
    start, end = get_date_window("LAST_10_YEARS", ref_date)
    print(f"LAST_10_YEARS: start={start}, end={end}")
    expected_start = ref_date - timedelta(days=10*365)
    assert abs((start - expected_start).days) < 5, "LAST_10_YEARS start date incorrect"
    
    print("\n✓ Date window calculation tests passed")
    return True

def test_date_normalization():
    """Test publication date normalization."""
    print("\n" + "=" * 60)
    print("TEST: Date Normalization")
    print("=" * 60)
    
    # Test various formats
    test_cases = [
        ("2024-08-01", True),
        ("20240801", True),
        ("2024-08", True),
        ("2024", True),
        ("invalid", False),
    ]
    
    for date_str, should_parse in test_cases:
        result = normalize_publication_date(date_str)
        print(f"{date_str}: {result}")
        if should_parse:
            assert result is not None, f"Should parse {date_str}"
        else:
            assert result is None, f"Should not parse {date_str}"
    
    print("\n✓ Date normalization tests passed")
    return True

def test_date_in_window():
    """Test date window validation."""
    print("\n" + "=" * 60)
    print("TEST: Date in Window Validation")
    print("=" * 60)
    
    start_date = datetime(2020, 1, 1)
    end_date = datetime(2024, 1, 1)
    
    # Test dates
    test_cases = [
        ("2019-12-31", False),  # Before window
        ("2022-06-15", True),   # In window
        ("2024-01-01", True),   # At end
        ("2024-06-01", False),  # After window
        ("invalid", True),      # Invalid date - conservatively included
    ]
    
    for date_str, should_include in test_cases:
        result = is_date_in_window(date_str, start_date, end_date)
        print(f"{date_str}: {result}")
        assert result == should_include, f"Date {date_str} should be {should_include}"
    
    # Test with no window (should always return True)
    assert is_date_in_window("2020-01-01", None, None) == True
    print("\n✓ Date in window tests passed")
    return True

def test_competitor_query_generation():
    """Test competitor query generation."""
    print("\n" + "=" * 60)
    print("TEST: Competitor Query Generation")
    print("=" * 60)
    
    # Create a mock profile with all required fields
    profile = CompoundSearchProfile(
        original_input="Low Acrylonitrile NBR",
        compound="Low Acrylonitrile NBR",
        compound_name="Nitrile Butadiene Rubber",
        synonyms=["Nitrile Rubber", "NBR"],
        abbreviations=["NBR"],
        chemical_family="Synthetic Rubber",
        major_monomers=["acrylonitrile", "butadiene"],
        alternative_industry_names=[],
        important_constraints=["Low Acrylonitrile", "Low ACN"],
        research_intent="polymerization",
        typical_polymerization_routes=[],
        typical_manufacturing_keywords=[],
        typical_cpc=[],
        typical_ipc=[],
        related_chemistry=[],
        competing_chemistry=["ABS", "SBR"],
        application_keywords=["hose", "tire"],
        manufacturing_keywords=[],
        target_composition_keywords=["low ACN"],
        target_composition_range="",
        search_queries=[]
    )
    
    service = CompetitorService()
    queries = service.generate_competitor_queries("Zeon", profile)
    
    print(f"Generated {len(queries)} competitor queries for Zeon")
    for idx, q in enumerate(queries[:5], 1):
        print(f"  {idx}. {q.query} (field: {q.field}, priority: {q.priority})")
    
    # Verify queries contain competitor name
    for q in queries:
        assert "Zeon" in q.query, "All queries should contain competitor name"
    
    # Verify some queries contain compound terms
    compound_queries = [q for q in queries if "Nitrile" in q.query or "NBR" in q.query]
    assert len(compound_queries) > 0, "Some queries should contain compound terms"
    
    # Verify some queries contain production terms
    production_queries = [q for q in queries if any(term in q.query for term in ["polymerization", "production", "preparation"])]
    assert len(production_queries) > 0, "Some queries should contain production terms"
    
    print("\n✓ Competitor query generation tests passed")
    return True

def test_competitor_matching():
    """Test competitor assignee/applicant matching."""
    print("\n" + "=" * 60)
    print("TEST: Competitor Matching")
    print("=" * 60)
    
    service = CompetitorService()
    
    # Test matching cases
    test_cases = [
        ({"assignee": "Zeon Corporation"}, True),
        ({"applicant": "Zeon Corporation"}, True),
        ({"organization": "Zeon"}, True),
        ({"assignee": "Some Other Company"}, False),
        ({"assignee": "LG Chem"}, False),
        ({}, False),
    ]
    
    for patent_data, should_match in test_cases:
        result = service.matches_competitor(patent_data, "Zeon")
        print(f"Patent {patent_data}: {result}")
        assert result == should_match, f"Should match: {should_match}"
    
    print("\n✓ Competitor matching tests passed")
    return True

def test_website_query_generation():
    """Test website query generation."""
    print("\n" + "=" * 60)
    print("TEST: Website Query Generation")
    print("=" * 60)
    
    # Create a mock profile with all required fields
    profile = CompoundSearchProfile(
        original_input="Low Acrylonitrile NBR",
        compound="Low Acrylonitrile NBR",
        compound_name="Nitrile Butadiene Rubber",
        synonyms=["Nitrile Rubber", "NBR"],
        abbreviations=["NBR"],
        chemical_family="Synthetic Rubber",
        major_monomers=["acrylonitrile", "butadiene"],
        alternative_industry_names=[],
        important_constraints=["Low Acrylonitrile", "Low ACN"],
        research_intent="polymerization",
        typical_polymerization_routes=[],
        typical_manufacturing_keywords=[],
        typical_cpc=[],
        typical_ipc=[],
        related_chemistry=[],
        competing_chemistry=["ABS", "SBR"],
        application_keywords=["hose", "tire"],
        manufacturing_keywords=[],
        target_composition_keywords=["low ACN"],
        target_composition_range="",
        search_queries=[]
    )
    
    service = WebsiteService()
    domain, queries = service.generate_website_queries("https://example.com/research", profile)
    
    print(f"Domain: {domain}")
    print(f"Generated {len(queries)} website queries")
    for idx, q in enumerate(queries[:5], 1):
        print(f"  {idx}. {q}")
    
    # Verify domain extraction
    assert domain == "example.com", f"Domain should be example.com, got {domain}"
    
    # Verify all queries are site-restricted
    for q in queries:
        assert "site:example.com" in q, "All queries should be site-restricted"
    
    # Verify some queries contain compound terms
    compound_queries = [q for q in queries if "Nitrile" in q or "NBR" in q]
    assert len(compound_queries) > 0, "Some queries should contain compound terms"
    
    print("\n✓ Website query generation tests passed")
    return True

def test_domain_extraction():
    """Test domain extraction from URLs."""
    print("\n" + "=" * 60)
    print("TEST: Domain Extraction")
    print("=" * 60)
    
    service = WebsiteService()
    
    test_cases = [
        ("https://example.com", "example.com"),
        ("https://example.com/research", "example.com"),
        ("http://company.com/page", "company.com"),
        ("example.com", "example.com"),  # Fallback - returns input as-is
    ]
    
    for url, expected_domain in test_cases:
        result = service.extract_domain(url)
        print(f"{url} -> {result}")
        # For the fallback case, we expect the input to be returned as-is
        if url == "example.com":
            assert result == url, f"Expected {url}, got {result}"
        else:
            assert result == expected_domain, f"Expected {expected_domain}, got {result}"
    
    print("\n✓ Domain extraction tests passed")
    return True

if __name__ == "__main__":
    try:
        all_passed = True
        
        all_passed &= test_date_window_calculation()
        all_passed &= test_date_normalization()
        all_passed &= test_date_in_window()
        all_passed &= test_competitor_query_generation()
        all_passed &= test_competitor_matching()
        all_passed &= test_website_query_generation()
        all_passed &= test_domain_extraction()
        
        print("\n" + "=" * 60)
        if all_passed:
            print("ALL TESTS PASSED")
            print("=" * 60)
            exit(0)
        else:
            print("SOME TESTS FAILED")
            print("=" * 60)
            exit(1)
    except Exception as e:
        print(f"\n\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
