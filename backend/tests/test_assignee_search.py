"""Assignee autocomplete, sequential discovery, jurisdiction, and report marking."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.pipeline.assignee_search import (
    allocate_assignee_patents,
    build_assignee_queries,
    discover_assignee_patents,
    family_key,
    jurisdiction_allowed,
    names_are_same_entity,
    patents_allowed,
)
from app.services.pipeline.assignee_suggestions import (
    clear_suggestion_cache,
    gather_assignee_suggestions,
    merge_suggestions,
    AssigneeSuggestionService,
)
from app.services.pipeline.report_evidence_service import ReportEvidenceService
from app.services.pipeline.schemas import PatentExtraction, PatentMetadata


def _patent(number, assignee, title, snippet, year="2020", priority="2019-01-01"):
    return {
        "patent_number": number,
        "assignee": assignee,
        "title": title,
        "snippet": snippet,
        "publication_date": year,
        "priority_date": priority,
        "inventor": "A. Inventor",
        "url": f"https://patents.google.com/patent/{number}",
    }


NBR = "nitrile rubber emulsion polymerization of butadiene and acrylonitrile"


def test_suggestions_keep_distinct_legal_names():
    names = merge_suggestions(
        ["LG Chem", "LG Chem"],
        ["LG Energy Solution", "lg chem"],
        query="lg",
        limit=10,
    )
    assert names == ["LG Chem", "LG Energy Solution"]
    assert len(names) <= 10


def test_no_assignee_quota_is_zero_and_single_assignee_default_is_one():
    assert patents_allowed(0) == 0
    assert patents_allowed(1, 1) == 1
    assert patents_allowed(1, 2) == 2
    assert patents_allowed(3, 2) == 1


def test_queries_include_compound_and_exact_assignee():
    queries = build_assignee_queries(
        "Low Acrylonitrile NBR",
        "LG Chem",
        ["nitrile rubber"],
        ["US", "EP"],
    )
    assert 1 <= len(queries) <= 2
    assert all('"LG Chem"' in query for query in queries)
    assert all("Low Acrylonitrile NBR" in query or "nitrile rubber" in query for query in queries)
    assert all("polymerization" in query or "monomer" in query for query in queries)


def test_suffix_matches_but_subsidiary_does_not():
    assert names_are_same_entity("LG Chem", "LG Chem, Ltd.")
    assert names_are_same_entity("Synthomer", "Synthomer plc")
    assert not names_are_same_entity("LG Chem", "LG Energy Solution")
    assert not names_are_same_entity("LG Chem", "LG Chem America")
    assert not names_are_same_entity("LG Chem", "")


def test_jurisdiction_is_the_publication_office():
    assert jurisdiction_allowed("US2020123456A1", ["US"])
    assert not jurisdiction_allowed("EP3456789A1", ["US"])
    assert not jurisdiction_allowed("WO2020123456A1", ["US"])
    assert not jurisdiction_allowed("CN109999999A", ["US", "EP"])
    assert jurisdiction_allowed("EP3456789A1", ["EP"])
    assert jurisdiction_allowed("US2020123456A1", ["US", "EP"])
    assert jurisdiction_allowed("IN2020112345A", ["IN"])


def test_date_assignee_and_relevance_rejections():
    old = _patent("US2005000001A1", "LG Chem Ltd", "Nitrile rubber polymerization", NBR, year="2005")
    wrong_owner = _patent("US2020000002A1", "Other Chemical Co", "Nitrile rubber polymerization", NBR)
    unrelated = _patent("US2020000003A1", "LG Chem", "Battery separator film", "electrode coating")
    good = _patent("US2020000004A1", "LG Chem, Ltd.", "Emulsion polymerization of nitrile rubber", NBR)
    result = allocate_assignee_patents(
        [old, wrong_owner, unrelated, good],
        "LG Chem",
        jurisdictions=["US"],
        min_year=2015,
        material_terms=["nitrile rubber"],
        quota=1,
    )
    assert [item["reason"] for item in result["rejected"]] == ["date", "assignee", "relevance"]
    assert [item["patent_number"] for item in result["accepted"]] == ["US2020000004A1"]


def test_no_qualifying_patent_does_not_invent_one():
    result = allocate_assignee_patents(
        [_patent("WO2020000001A1", "LG Chem", "Nitrile rubber polymerization", NBR)],
        "LG Chem",
        jurisdictions=["US"],
        material_terms=["nitrile rubber"],
        quota=1,
    )
    assert result["accepted"] == []
    assert result["satisfied_by_existing"] == []


def test_family_duplicate_is_not_added_again():
    existing = _patent("US2020000004A1", "LG Chem", "Emulsion polymerization of nitrile rubber", NBR)
    sibling = _patent("US2020000099A1", "LG Chem Ltd", "Emulsion polymerization of nitrile rubber", NBR)
    result = allocate_assignee_patents(
        [sibling],
        "LG Chem",
        jurisdictions=["US"],
        material_terms=["nitrile rubber"],
        already_selected=set(),
        already_families={family_key(existing)},
        quota=1,
    )
    assert result["accepted"] == []
    assert result["satisfied_by_existing"] == ["US2020000099A1"]


@pytest.mark.asyncio
async def test_sequential_multi_assignee_and_partial_failure():
    calls = []

    async def search(queries):
        text = queries[0]["query"]
        calls.append(text)
        if "Synthomer" in text:
            raise RuntimeError("upstream")
        if "LG Chem" in text:
            return [_patent("US2020000004A1", "LG Chem Ltd", "Nitrile rubber emulsion polymerization", NBR)]
        if "Company C" in text:
            return [_patent("EP3000001A1", "Company C GmbH", "Nitrile rubber polymerization", NBR)]
        return []

    general = [_patent("US2019000001A1", "Unrelated Co", "Other nitrile rubber polymerization", NBR)]
    result = await discover_assignee_patents(
        search,
        ["LG Chem", "Synthomer", "Company C"],
        compound_name="Low Acrylonitrile NBR",
        material_terms=["nitrile rubber"],
        jurisdictions=["US", "EP"],
        publication_filter={"date_range": "Last 10 Years"},
        selected_candidates=general,
        single_max=2,
        current_year=2024,
    )
    assert calls[0].startswith('"LG Chem"')
    assert "Synthomer" in calls[1]
    assert calls[2].startswith('"Company C"')
    assert [item["patent_number"] for item in result.added] == ["US2020000004A1", "EP3000001A1"]
    assert result.notes[1]["status"] == "search_failed"
    assert all(item["discovery_source"] == "COMPETITOR" for item in result.added)
    assert result.added[0]["competitor_name"] == "LG Chem"
    assert result.added[1]["competitor_name"] == "Company C"


@pytest.mark.asyncio
async def test_one_assignee_respects_configured_maximum_of_two():
    async def search(_queries):
        return [
            _patent("US2020000004A1", "LG Chem", "Nitrile rubber polymerization", NBR, priority="2018-01-01"),
            _patent("US2021000005A1", "LG Chem Ltd", "Emulsion copolymerization of nitrile rubber", NBR, priority="2019-02-02"),
            _patent("US2022000006A1", "LG Chem", "Further nitrile rubber polymerization", NBR, priority="2020-03-03"),
        ]

    result = await discover_assignee_patents(
        search,
        ["LG Chem"],
        compound_name="nitrile rubber",
        material_terms=["nitrile rubber"],
        jurisdictions=["US"],
        publication_filter=None,
        selected_candidates=[],
        single_max=2,
        current_year=2024,
    )
    assert len(result.added) == 2


@pytest.mark.asyncio
async def test_general_duplicate_satisfies_allocation_without_a_second_copy():
    general = [_patent("US2020000004A1", "LG Chem", "Nitrile rubber polymerization", NBR)]
    general[0]["discovery_sources"] = ["GENERAL"]

    async def search(_queries):
        return [general[0]]

    result = await discover_assignee_patents(
        search,
        ["LG Chem"],
        compound_name="nitrile rubber",
        material_terms=["nitrile rubber"],
        jurisdictions=["US"],
        publication_filter=None,
        selected_candidates=general,
        single_max=1,
        current_year=2024,
    )
    assert result.added == []
    assert general[0]["discovery_sources"] == ["GENERAL", "ASSIGNEE"]
    assert general[0]["competitor_name"] == "LG Chem"
    assert result.notes[0]["status"] == "selected"


@pytest.mark.asyncio
async def test_no_assignees_does_not_call_search():
    search = AsyncMock()
    result = await discover_assignee_patents(
        search,
        [],
        compound_name="nitrile rubber",
        material_terms=["nitrile rubber"],
        jurisdictions=["US"],
        publication_filter=None,
        selected_candidates=[],
        current_year=2024,
    )
    search.assert_not_called()
    assert result.added == []


def test_combined_report_marks_assignee_and_keeps_missing_parameters():
    extraction = PatentExtraction(
        metadata=PatentMetadata(
            patent_number="US2020000004A1",
            patent_title="Emulsion polymerization of nitrile rubber",
            assignee="LG Chem, Ltd.",
            jurisdiction="US",
            publication_year="2020",
            url="https://patents.google.com/patent/US2020000004A1",
        ),
        parameters=[],
        examples=[],
    )
    evidence = ReportEvidenceService().build_compact_evidence(
        extraction,
        discovery_source="COMPETITOR",
        competitor_name="LG Chem",
    )
    assert evidence.discovery_source == "COMPETITOR"
    assert evidence.competitor_name == "LG Chem"
    assert evidence.assignee == "LG Chem, Ltd."
    assert evidence.patent_number == "US2020000004A1"
    assert evidence.overall_patent_parameters == []


@pytest.mark.asyncio
async def test_suggestions_read_stored_patent_assignees():
    from app.services.pipeline.assignee_suggestions import AssigneeSuggestionService

    stored = ["LG Chem, Ltd.", "Synthomer plc", "LG Energy Solution"]
    result = MagicMock()
    result.scalars.return_value.all.return_value = stored
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    service = AssigneeSuggestionService(session, remote_lookup=AsyncMock(return_value=["Zeon Corporation"]))
    names = await service.suggest("lg")
    assert names == ["LG Chem, Ltd.", "LG Energy Solution"]
    assert len(names) <= 10
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_company_lookup_reads_later_pages_and_keeps_legal_entities():
    async def fetch_page(query, page):
        assert "nitrile" not in query.lower()
        assert "polymer" not in query.lower()
        if page == 1:
            return 200, [{"assignee": "United States Gypsum Company"}, {"assignee": ""}]
        if page == 2:
            return 200, [
                {"assignee": "Synthomer (UK) Limited"},
                {"assignee": "Synthomer Adhesive Technologies LLC"},
                {"assignee": "Synthomer USA LLC"},
                {"assignee": "Synthomer Deutschland GmbH"},
                {"assignee": "LG Chem, Ltd."},
                {"assignee": "Lg Chem Ltd."},
            ]
        return 200, []

    synthomer = await gather_assignee_suggestions("Synthomer", fetch_page, max_pages=3)
    assert synthomer == [
        "Synthomer (UK) Limited",
        "Synthomer Adhesive Technologies LLC",
        "Synthomer USA LLC",
        "Synthomer Deutschland GmbH",
    ]
    lg = await gather_assignee_suggestions("LG Chem", fetch_page, max_pages=3)
    assert lg == ["LG Chem, Ltd."]


@pytest.mark.asyncio
async def test_empty_local_index_uses_remote_names():
    clear_suggestion_cache()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    async def remote(_query):
        return ["Synthomer (UK) Limited", "Synthomer USA LLC"]

    service = AssigneeSuggestionService(session, remote_lookup=remote)
    names = await service.suggest("Synthomer")
    assert names == ["Synthomer (UK) Limited", "Synthomer USA LLC"]


@pytest.mark.asyncio
async def test_external_provider_failure_does_not_raise():
    clear_suggestion_cache()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    async def remote(_query):
        raise RuntimeError("down")

    service = AssigneeSuggestionService(session, remote_lookup=remote)
    assert await service.suggest("Synthomer") == []


@pytest.mark.asyncio
async def test_snippet_gap_can_qualify_after_document_check():
    async def search(_queries):
        return [_patent(
            "US2020000010A1",
            "Synthomer (UK) Limited",
            "Coating composition",
            "a polymer binder",
        )]

    async def evidence(_url):
        return {
            "assignee": "Synthomer (UK) Limited",
            "title": "Nitrile rubber emulsion polymerization",
            "abstract": NBR,
            "claims_excerpt": "The polymerization uses an initiator.",
            "jurisdiction": "US",
        }

    result = await discover_assignee_patents(
        search,
        ["Synthomer (UK) Limited"],
        compound_name="nitrile rubber",
        material_terms=["nitrile rubber"],
        jurisdictions=["US"],
        publication_filter=None,
        selected_candidates=[],
        single_max=1,
        current_year=2024,
        evidence_fn=evidence,
        document_budget=3,
    )
    assert [item["patent_number"] for item in result.added] == ["US2020000010A1"]


@pytest.mark.asyncio
async def test_unrelated_patent_is_rejected_after_document_check():
    async def search(_queries):
        return [_patent(
            "US2020000011A1",
            "Synthomer (UK) Limited",
            "Coating composition",
            "a polymer binder",
        )]

    async def evidence(_url):
        return {
            "assignee": "Synthomer (UK) Limited",
            "title": "Battery separator",
            "abstract": "electrode coating for a lithium cell",
            "claims_excerpt": "a porous film",
            "jurisdiction": "US",
        }

    result = await discover_assignee_patents(
        search,
        ["Synthomer (UK) Limited"],
        compound_name="nitrile rubber",
        material_terms=["nitrile rubber"],
        jurisdictions=["US"],
        publication_filter=None,
        selected_candidates=[],
        single_max=1,
        current_year=2024,
        evidence_fn=evidence,
        document_budget=3,
    )
    assert result.added == []
    assert result.notes[0]["status"] == "no_qualifying_patent"
