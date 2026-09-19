"""
tests/test_pipeline_fixtures.py

Phase 0 foundation: load and validate each pipeline fixture against
the appropriate Pydantic schema (or structural contract for Serper).
Later phases reuse these fixtures via tests.fixtures.load_fixture.
"""
from tests.fixtures import load_fixture
from tests.fixtures.selection_schema import PatentSelectionResult

from app.services.pipeline.schemas import (
    LLMCompoundSearchProfile,
    LLMPatentResearchReport,
)


REQUIRED_SERPER_PATENT_KEYS = {
    "title",
    "link",
    "snippet",
    "publicationNumber",
}


def test_serper_patents_fixture_structure():
    data = load_fixture("serper_patents_low_acn_nbr")
    assert "patents" in data
    patents = data["patents"]
    assert len(patents) >= 8

    titles = [p["title"].lower() for p in patents]
    assert any("tire" in t or "adhesive" in t for t in titles), "need downstream titles"
    assert any("hydrogenated" in t or "hnbr" in t for t in titles), "need wrong-variant titles"
    assert any("emulsion" in t for t in titles), "need emulsion/aqueous titles"
    assert any("solution" in t or "n-butyllithium" in t or "hexane" in " ".join(titles) for t in titles), (
        "need solvent-based titles"
    )
    assert any("water" in t and "purif" in t for t in titles) or any(
        "unrelated" in (p.get("snippet") or "").lower() for p in patents
    ), "need clearly unrelated patents"

    for patent in patents:
        missing = REQUIRED_SERPER_PATENT_KEYS - set(patent.keys())
        assert not missing, f"{patent.get('publicationNumber')}: missing {missing}"


def test_query_expansion_fixture_parses_as_llm_compound_search_profile():
    data = load_fixture("llm_query_expansion_low_acn_nbr")
    profile = LLMCompoundSearchProfile.model_validate(data)
    assert profile.original_input == "Low Acrylonitrile NBR"
    assert len(profile.search_queries) == 15
    assert profile.excluded_variants
    assert profile.downstream_terms
    assert all(q.scope in ("title", "full_text") for q in profile.search_queries)


def test_patent_selection_fixture_parses_as_patent_selection_result():
    data = load_fixture("llm_patent_selection_low_acn_nbr")
    result = PatentSelectionResult.model_validate(data)
    assert len(result.candidates) == 10

    by_number = {c.patent_number: c for c in result.candidates}
    assert by_number["US8888777B2"].final_decision.value == "REJECT"
    assert by_number["US8888777B2"].classification.value == "DOWNSTREAM_APPLICATION"
    assert by_number["US7654321B2"].variant_mismatch is True
    assert by_number["US7654321B2"].final_decision.value == "REJECT"
    assert by_number["US9012345B1"].polymerization_medium_mismatch is True
    assert by_number["US9012345B1"].final_decision.value == "REJECT"
    assert by_number["US8123456B2"].final_decision.value == "KEEP"
    assert by_number["EP2473281B1"].final_decision.value == "KEEP"
    assert by_number["WO2018123456A1"].final_decision.value == "KEEP"


def test_report_generation_fixture_parses_as_llm_patent_research_report():
    data = load_fixture("llm_report_generation_low_acn_nbr")
    report = LLMPatentResearchReport.model_validate(data)
    assert report.title
    assert len(report.per_patent_analysis) == 3
    numbers = {p.patent_number for p in report.per_patent_analysis}
    assert numbers == {"US8123456B2", "EP2473281B1", "WO2018123456A1"}
    assert report.references
    assert report.cross_patent_comparison
