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


# ---------------------------------------------------------------------------
# Report generation: malformed JSON / repair / controlled failure
# ---------------------------------------------------------------------------

def test_strip_fenced_json_and_parse_valid_report():
    from app.services.pipeline.report_service import strip_report_json_fences, try_parse_llm_report

    fixture = load_fixture("llm_report_generation_low_acn_nbr")
    import json

    raw = "```json\n" + json.dumps(fixture) + "\n```"
    assert strip_report_json_fences(raw).startswith("{")
    parsed = try_parse_llm_report(raw)
    assert parsed is not None
    assert len(parsed.per_patent_analysis) >= 1


def test_malformed_unterminated_string_not_silently_repaired():
    """Dangerous reconstruction must NOT invent valid science JSON."""
    from app.services.pipeline.report_service import try_parse_llm_report

    bad = '{"title": "x", "per_patent_analysis": [{"patent_number": "US1", "synthesis_method": "unterminated'
    assert try_parse_llm_report(bad) is None
    emptyish = '{"title": "Incomplete Only"}'
    assert try_parse_llm_report(emptyish, expected_patent_count=2) is None


@pytest.mark.asyncio
async def test_malformed_json_triggers_retry_then_success():
    evidence = _evidence_from_selection_keeps()
    good = LLMPatentResearchReport.model_validate(
        load_fixture("llm_report_generation_low_acn_nbr")
    )
    calls = {"n": 0}

    async def _fake(*, prompt, schema=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None, "mock", {
                "invalid_response_error": "MALFORMED_JSON: Unterminated string starting at char 5013",
                "raw_response_text": '{"title": "broken", "per_patent_analysis": [{"patent_number": "US1", "synthesis_method": "oops',
                "response_length": 340906,
                "finish_reason": "STOP",
            }
        return good, "mock", {"input_tokens": 100, "output_tokens": 50}

    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake),
    ):
        service = ReportService()
        report, usage = await service.generate_structured_report(
            compound_name="Low Acrylonitrile NBR",
            extractions=evidence,
            original_input="Low Acrylonitrile NBR",
            research_profile='{"base_material":["NBR"]}',
        )

    assert calls["n"] == 2
    assert isinstance(report, PatentResearchReport)
    assert len(report.methodology_patents) >= 1


@pytest.mark.asyncio
async def test_malformed_json_twice_raises_controlled_failure():
    evidence = _evidence_from_selection_keeps()
    calls = {"n": 0}

    async def _always_bad(*, prompt, **kwargs):
        calls["n"] += 1
        return None, "mock", {
            "invalid_response_error": "MALFORMED_JSON: Unterminated string",
            "raw_response_text": '{"title": "broken',
            "response_length": 100,
            "finish_reason": "MAX_TOKENS",
        }

    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_always_bad),
    ):
        service = ReportService()
        with pytest.raises(ValueError) as exc:
            await service.generate_structured_report(
                compound_name="Low Acrylonitrile NBR",
                extractions=evidence,
            )

    # 2 report attempts + sectional attempted (may fail before further LLM calls)
    assert calls["n"] >= 2
    assert "REPORT_GENERATION_FAILED" in str(exc.value)
    assert "LLM returned None instead of structured object" not in str(exc.value)


@pytest.mark.asyncio
async def test_missing_required_fields_triggers_retry():
    evidence = _evidence_from_selection_keeps()
    good = LLMPatentResearchReport.model_validate(
        load_fixture("llm_report_generation_low_acn_nbr")
    )
    calls = {"n": 0}

    async def _fake(*, prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None, "mock", {
                "validation_error": "per_patent_analysis field required",
                "raw_response_text": '{"title": "Incomplete Only"}',
            }
        assert "REPAIR" in prompt or "compact" in prompt.lower() or "RETRY" in prompt
        return good, "mock", {}

    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Low Acrylonitrile NBR",
            extractions=evidence,
        )
    assert calls["n"] == 2
    assert isinstance(report, PatentResearchReport)


@pytest.mark.asyncio
async def test_safe_parse_recovers_fenced_json_without_retry():
    evidence = _evidence_from_selection_keeps()
    fixture = load_fixture("llm_report_generation_low_acn_nbr")
    import json

    fenced = "```json\n" + json.dumps(fixture) + "\n```"
    calls = {"n": 0}

    async def _fake(*, prompt, **kwargs):
        calls["n"] += 1
        # First call "fails" structured validate but raw is valid fenced JSON
        return None, "mock", {
            "invalid_response_error": "MALFORMED_JSON: unexpected preamble",
            "raw_response_text": fenced,
            "response_length": len(fenced),
        }

    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Low Acrylonitrile NBR",
            extractions=evidence,
        )
    assert calls["n"] == 1  # recovered without retry
    assert isinstance(report, PatentResearchReport)


@pytest.mark.asyncio
async def test_extremely_large_malformed_response_no_silent_none():
    """Huge unterminated dump must not become empty report / silent None."""
    evidence = _evidence_from_selection_keeps()
    huge = '{"title": "x", "abstract": "' + ("A" * 340000)
    calls = {"n": 0}

    async def _always_huge(*, prompt, **kwargs):
        calls["n"] += 1
        return None, "mock", {
            "invalid_response_error": "MALFORMED_JSON: Unterminated string",
            "raw_response_text": huge,
            "response_length": len(huge),
            "finish_reason": "STOP",
        }

    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_always_huge),
    ):
        with pytest.raises(ValueError) as exc:
            await ReportService().generate_structured_report(
                compound_name="Low Acrylonitrile NBR",
                extractions=evidence,
            )
    assert calls["n"] >= 2
    assert "REPORT_GENERATION_FAILED" in str(exc.value)
    assert "340" in str(exc.value) or "first_response_length" in str(exc.value)


def test_report_prompt_has_output_size_constraints():
    from app.services.prompts.patent_prompts import REPORT_GENERATION_SYSTEM_PROMPT

    assert "OUTPUT SIZE CONSTRAINTS" in REPORT_GENERATION_SYSTEM_PROMPT
    assert any(term in REPORT_GENERATION_SYSTEM_PROMPT for term in ("Up to 35", "MAX 35", "Up to 6", "MAX 12", "MAX 3"))


@pytest.mark.asyncio
async def test_sectional_fallback_after_two_malformed_responses():
    """After single-shot + compact retry fail, per-patent LLMPatentAnalysis succeeds."""
    from app.services.pipeline.schemas import LLMPatentAnalysis

    evidence = _evidence_from_selection_keeps()
    calls = {"n": 0}

    async def _fake(*, prompt, schema=None, **kwargs):
        calls["n"] += 1
        name = getattr(schema, "__name__", "") or ""
        if name == "LLMPatentResearchReport" or calls["n"] <= 2:
            if name == "LLMPatentResearchReport":
                return None, "mock", {
                    "invalid_response_error": "MALFORMED_JSON: Unterminated string",
                    "raw_response_text": '{"title": "broken',
                    "response_length": 50,
                    "finish_reason": "MAX_TOKENS",
                }
        # Sectional path uses LLMPatentAnalysis
        pn = "US8123456B2"
        for e in evidence:
            if e.patent_number in prompt:
                pn = e.patent_number
                break
        analysis = LLMPatentAnalysis(
            patent_number=pn,
            synthesis_method="Emulsion polymerization (test).",
            disclosed_parameters=["Temp: 50 C — Example 1"],
            example_highlights=["Example 1: latex prepared"],
            technical_relevance="Relevant test patent.",
        )
        return analysis, "mock", {"input_tokens": 10, "output_tokens": 20}

    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Low Acrylonitrile NBR",
            extractions=evidence,
        )
    assert calls["n"] >= 3  # 2 report attempts + >=1 sectional
    assert isinstance(report, PatentResearchReport)
    assert len(report.methodology_patents) >= 1


def test_gemini_sets_max_output_tokens_for_report_schema():
    from app.core.config import settings

    assert getattr(settings, "REPORT_MAX_OUTPUT_TOKENS", 0) >= 16384
