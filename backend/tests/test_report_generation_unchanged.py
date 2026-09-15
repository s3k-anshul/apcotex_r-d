"""
tests/test_report_generation_unchanged.py

Phase 5: report_service.generate_structured_report consumes extracted
evidence and produces a structured report — unchanged by the redesign.
Uses Phase 0 fixtures + a mocked report-generation LLM response.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.pipeline.report_service import ReportService
from app.services.pipeline.schemas import (
    LLMPatentResearchReport,
    PatentResearchReport,
    ReportPatentEvidence,
)
from tests.fixtures import load_fixture


def _evidence_from_selection_keeps() -> list[ReportPatentEvidence]:
    """Build compact evidence for the three KEEP patents from Phase 0 fixtures."""
    selection = load_fixture("llm_patent_selection_low_acn_nbr")
    keep_numbers = {
        c["patent_number"]
        for c in selection["candidates"]
        if c["final_decision"] == "KEEP"
    }
    serper = load_fixture("serper_patents_low_acn_nbr")
    by_number = {p["publicationNumber"]: p for p in serper["patents"]}

    evidence = []
    for number in sorted(keep_numbers):
        patent = by_number[number]
        evidence.append(
            ReportPatentEvidence(
                patent_number=number,
                title=patent["title"],
                jurisdiction=number[:2],
                assignee=patent.get("assignee") or "Unknown",
                publication_year=(patent.get("publicationDate") or "")[:4] or "2015",
                url=patent["link"],
                source_text=patent.get("snippet") or "",
                relevance_tier="PRIMARY",
                relevance_score=100.0,
                technical_findings=[
                    f"Selected as KEEP for low-ACN NBR research: {patent['title'][:80]}"
                ],
            )
        )
    return evidence


@pytest.mark.asyncio
async def test_generate_structured_report_maps_mocked_llm_fixture():
    evidence = _evidence_from_selection_keeps()
    assert {e.patent_number for e in evidence} == {
        "US8123456B2",
        "EP2473281B1",
        "WO2018123456A1",
    }

    llm_report = LLMPatentResearchReport.model_validate(
        load_fixture("llm_report_generation_low_acn_nbr")
    )

    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm_report, "mock", {"input_tokens": 100, "output_tokens": 50})),
    ) as mock_llm:
        service = ReportService()
        report, usage = await service.generate_structured_report(
            compound_name="Low Acrylonitrile NBR",
            extractions=evidence,
            original_input="Low Acrylonitrile NBR",
            research_profile='{"base_material":["NBR"]}',
        )

    assert mock_llm.await_count == 1
    assert isinstance(report, PatentResearchReport)
    assert report.title == llm_report.title
    assert report.abstract == llm_report.abstract
    assert report.conclusion == llm_report.conclusion
    assert len(report.methodology_patents) == 3

    mapped = {p.patent_details.patent_number for p in report.methodology_patents}
    assert mapped == {"US8123456B2", "EP2473281B1", "WO2018123456A1"}

    # LLM per-patent analysis is applied into methodology parameters
    by_pn = {p.patent_details.patent_number: p for p in report.methodology_patents}
    assert any(
        "15-20 wt%" in param or "Synthesis method:" in param
        for param in by_pn["US8123456B2"].polymerization_method.dynamic_parameters
    )
    assert by_pn["EP2473281B1"].experimental_evidence
    assert report.cross_patent_comparison
    assert "US8123456B2" in report.references


@pytest.mark.asyncio
async def test_report_to_markdown_includes_primary_patents():
    evidence = _evidence_from_selection_keeps()
    llm_report = LLMPatentResearchReport.model_validate(
        load_fixture("llm_report_generation_low_acn_nbr")
    )
    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm_report, "mock", {})),
    ):
        service = ReportService()
        report, _ = await service.generate_structured_report(
            compound_name="Low Acrylonitrile NBR",
            extractions=evidence,
        )
        md = service.report_to_markdown(report)

    assert "# " in md
    assert "US8123456B2" in md
    assert "EP2473281B1" in md
    assert "WO2018123456A1" in md
    assert "ABSTRACT" in md.upper() or "1. ABSTRACT" in md
