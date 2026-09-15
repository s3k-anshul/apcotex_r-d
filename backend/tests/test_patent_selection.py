"""
tests/test_patent_selection.py

Phase 3: authoritative title/snippet LLM selection replaces deterministic gates.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.research_run import ResearchRun
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.pipeline.schemas import (
    CompoundSearchProfile,
    PatentSelectionCandidate,
    PatentSelectionResult,
    SelectionDecision,
    TechnicalCentrality,
    TitleTriageClassification,
)
from tests.fixtures import load_fixture


def _orch() -> PipelineOrchestrator:
    return PipelineOrchestrator(run_id=uuid.uuid4())


def _profile() -> CompoundSearchProfile:
    data = load_fixture("llm_query_expansion_low_acn_nbr")
    return CompoundSearchProfile(
        original_input=data["original_input"],
        base_material=data["base_material"],
        target_attributes=data["target_attributes"],
        synthesis_transformations=data["synthesis_transformations"],
        downstream_terms=data["downstream_terms"],
        excluded_variants=data["excluded_variants"],
        search_queries=[],
    )


def _run(**kwargs) -> ResearchRun:
    defaults = {
        "compound_name": "Low Acrylonitrile NBR",
        "competitors": [],
        "mentioned_websites": [],
        "publication_filter": None,
        "selected_sources": [],
        "jurisdictions": ["US"],
        "attribute_constraint": None,
        "polymerization_medium": "any",
        "status": "PENDING",
        "cache_key": "test",
        "report_version": 1,
        "created_by": uuid.uuid4(),
    }
    defaults.update(kwargs)
    return ResearchRun(**defaults)


def _candidate(number: str, title: str, snippet: str = "") -> dict:
    return {
        "patent_number": number,
        "title": title,
        "snippet": snippet,
        "url": f"https://patents.google.com/patent/{number}",
        "assignee": "",
        "publication_date": "2015-01-01",
    }


def _verdict(
    number: str,
    classification: TitleTriageClassification,
    decision: SelectionDecision,
    *,
    variant_mismatch: bool = False,
    medium_mismatch: bool = False,
    reason: str = "test",
    confidence: float = 0.9,
    evidence_strength: float = 0.8,
    technical_centrality: TechnicalCentrality = TechnicalCentrality.CENTRAL,
    downstream_only: bool = False,
) -> PatentSelectionCandidate:
    return PatentSelectionCandidate(
        patent_number=number,
        classification=classification,
        variant_mismatch=variant_mismatch,
        polymerization_medium_mismatch=medium_mismatch,
        final_decision=decision,
        confidence=confidence,
        reason=reason,
        technical_centrality=technical_centrality,
        evidence_strength=evidence_strength if decision == SelectionDecision.KEEP else 0.0,
        downstream_only=downstream_only,
    )


@pytest.mark.asyncio
async def test_downstream_tire_is_rejected():
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [
        _candidate(
            "US8888777B2",
            "Pneumatic tire comprising nitrile rubber composition in sidewall",
            "A pneumatic tire sidewall using purchased NBR.",
        ),
        _candidate(
            "US8123456B2",
            "Process for producing low acrylonitrile content nitrile rubber by emulsion polymerization",
            "Aqueous emulsion polymerization of NBR with 15-20 wt% ACN.",
        ),
    ]
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US8888777B2",
                TitleTriageClassification.DOWNSTREAM_APPLICATION,
                SelectionDecision.REJECT,
                reason="Tire is downstream",
            ),
            _verdict(
                "US8123456B2",
                TitleTriageClassification.DIRECT_SYNTHESIS,
                SelectionDecision.KEEP,
                reason="On-target emulsion synthesis",
            ),
        ]
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(candidates, _profile(), _run())

    numbers = [c["patent_number"] for c in selected]
    assert "US8888777B2" not in numbers
    assert "US8123456B2" in numbers
    assert orch._filter_stats["selection_reject_downstream"] == 1


@pytest.mark.asyncio
async def test_wrong_variant_hnbr_rejected_with_flag():
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [
        _candidate(
            "US7654321B2",
            "Process for producing hydrogenated nitrile rubber (HNBR)",
            "Selective hydrogenation of NBR to HNBR.",
        )
    ]
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US7654321B2",
                TitleTriageClassification.TARGET_TRANSFORMATION,
                SelectionDecision.REJECT,
                variant_mismatch=True,
                reason="HNBR excluded",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(candidates, _profile(), _run())

    assert selected == []
    assert orch._filter_stats["selection_reject_variant"] == 1


@pytest.mark.asyncio
async def test_emulsion_title_kept_when_medium_not_constrained():
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [
        _candidate(
            "EP2473281B1",
            "Emulsion polymerization of acrylonitrile-butadiene copolymers",
            "Aqueous-phase NBR latex with ~18 wt% bound ACN.",
        )
    ]
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "EP2473281B1",
                TitleTriageClassification.DIRECT_SYNTHESIS,
                SelectionDecision.KEEP,
                medium_mismatch=False,
                reason="Emulsion synthesis OK without medium constraint",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            candidates, _profile(), _run(polymerization_medium="any")
        )
    assert len(selected) == 1
    assert selected[0]["selection_medium_mismatch"] is False


@pytest.mark.asyncio
async def test_solvent_title_rejected_when_aqueous_required():
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [
        _candidate(
            "US9012345B1",
            "Solution polymerization of nitrile rubber using n-butyllithium in hexane",
            "Anionic solution polymerization in hexane with n-butyllithium and THF.",
        )
    ]
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US9012345B1",
                TitleTriageClassification.DIRECT_SYNTHESIS,
                SelectionDecision.REJECT,
                medium_mismatch=True,
                reason="Solvent route mismatches aqueous constraint",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            candidates, _profile(), _run(polymerization_medium="aqueous")
        )
    assert selected == []
    assert orch._filter_stats["selection_reject_medium"] == 1


@pytest.mark.asyncio
async def test_solvent_title_kept_when_medium_is_any():
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [
        _candidate(
            "US9012345B1",
            "Solution polymerization of nitrile rubber using n-butyllithium in hexane",
            "Anionic solution polymerization in hexane.",
        )
    ]
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US9012345B1",
                TitleTriageClassification.DIRECT_SYNTHESIS,
                SelectionDecision.KEEP,
                medium_mismatch=False,
                reason="No medium constraint — solvent synthesis allowed",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            candidates, _profile(), _run(polymerization_medium="any")
        )
    assert len(selected) == 1
    assert selected[0]["patent_number"] == "US9012345B1"


@pytest.mark.asyncio
async def test_direct_synthesis_kept():
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [
        _candidate(
            "WO2018123456A1",
            "Continuous emulsion polymerization process for acrylonitrile-butadiene rubber",
            "Multi-reactor continuous aqueous emulsion polymerization.",
        )
    ]
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "WO2018123456A1",
                TitleTriageClassification.DIRECT_SYNTHESIS,
                SelectionDecision.KEEP,
                reason="On-target direct synthesis",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(candidates, _profile(), _run())
    assert len(selected) == 1
    assert selected[0]["selection_decision"] == "KEEP"


@pytest.mark.asyncio
async def test_selection_prompt_includes_excluded_variants_and_medium():
    orch = _orch()
    orch._reset_filter_stats()
    captured = {}

    async def _fake(*, prompt, **kwargs):
        captured["prompt"] = prompt
        return PatentSelectionResult(candidates=[]), "mock", {}

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake),
    ):
        await orch._select_patents_via_llm(
            [_candidate("US1", "NBR preparation")],
            _profile(),
            _run(
                attribute_constraint="acrylonitrile content 15-20 wt%",
                polymerization_medium="aqueous",
            ),
        )

    assert "Excluded Variants" in captured["prompt"]
    assert "HNBR" in captured["prompt"]
    assert "Polymerization Medium Constraint: aqueous" in captured["prompt"]
    assert "acrylonitrile content 15-20 wt%" in captured["prompt"]


@pytest.mark.asyncio
async def test_selection_caps_at_ten_keeps_by_rank_not_encounter_order():
    """max_keep is an upper bound after ranking — stronger later KEEP beats weaker early KEEP."""
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [_candidate(f"US{i}", f"Process for preparing target polymer {i}") for i in range(15)]
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                f"US{i}",
                TitleTriageClassification.DIRECT_SYNTHESIS,
                SelectionDecision.KEEP,
                confidence=0.50 + (i * 0.01),  # later patents stronger
                evidence_strength=0.40 + (i * 0.01),
                technical_centrality=(
                    TechnicalCentrality.CENTRAL if i >= 5 else TechnicalCentrality.PARTIAL
                ),
            )
            for i in range(15)
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(candidates, _profile(), _run())
    assert len(selected) == 10
    selected_nums = [c["patent_number"] for c in selected]
    # Strongest should be US14..US5 (CENTRAL + higher scores), not US0..US9
    assert "US14" in selected_nums
    assert "US13" in selected_nums
    assert "US0" not in selected_nums
    assert "US1" not in selected_nums
    assert orch._filter_stats["selection_keep"] == 15  # all evaluated before cap
