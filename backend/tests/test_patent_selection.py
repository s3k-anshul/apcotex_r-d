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


# ---------------------------------------------------------------------------
# Incomplete Gemini structured-output / NO_VERDICT regression
# ---------------------------------------------------------------------------

import json

_INCOMPLETE_GEMINI_OBJ = {
    "patent_number": "US20120201985A1",
    "technical_centrality": "PERIPHERAL",
    "variant_match": "MATCH",
    "variant_mismatch": False,
}


@pytest.mark.asyncio
async def test_incomplete_gemini_candidate_not_mass_rejected():
    """Test case 1: incomplete Gemini object → repair/REVIEW, never silent REJECT."""
    orch = _orch()
    orch._reset_filter_stats()
    pnum = "US20120201985A1"
    candidates = [
        _candidate(
            pnum,
            "Process for producing low acrylonitrile content nitrile rubber by emulsion polymerization",
            "Aqueous emulsion polymerization of NBR with 15-20 wt% ACN.",
        )
    ]
    incomplete_raw = json.dumps({"candidates": [_INCOMPLETE_GEMINI_OBJ]})
    call_count = {"n": 0}

    async def _fake(*, prompt, **kwargs):
        call_count["n"] += 1
        # First call + repair both fail validation → return None with raw
        return None, "mock", {
            "validation_error": "missing classification, final_decision, confidence, reason",
            "raw_response_text": incomplete_raw,
        }

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake),
    ):
        selected = await orch._select_patents_via_llm(candidates, _profile(), _run())

    assert call_count["n"] >= 2  # initial + repair
    assert orch._filter_stats["selection_reject_other"] == 0
    assert orch._filter_stats["selection_unverified"] >= 1
    assert len(selected) >= 1
    assert selected[0]["selection_decision"] == "REVIEW"
    assert "No LLM verdict returned" not in (selected[0].get("selection_reason") or "")


@pytest.mark.asyncio
async def test_complete_gemini_response_applied_normally():
    """Test case 2: complete valid response applies KEEP/REJECT as before."""
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [
        _candidate(
            "US8123456B2",
            "Process for producing low acrylonitrile content nitrile rubber by emulsion polymerization",
            "Aqueous emulsion polymerization of NBR with 15-20 wt% ACN.",
        )
    ]
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US8123456B2",
                TitleTriageClassification.DIRECT_SYNTHESIS,
                SelectionDecision.KEEP,
                reason="Direct emulsion synthesis of NBR",
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
    assert orch._filter_stats["selection_keep"] == 1
    assert orch._filter_stats["selection_unverified"] == 0


@pytest.mark.asyncio
async def test_partial_gemini_response_missing_candidates_become_review():
    """Test case 3: 70/77-style — returned verdicts used; missing → REVIEW not REJECT."""
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [_candidate(f"US{i:07d}B2", f"NBR emulsion polymerization process {i}") for i in range(10)]
    # Only return 7 of 10
    returned = PatentSelectionResult(
        candidates=[
            _verdict(
                f"US{i:07d}B2",
                TitleTriageClassification.DIRECT_SYNTHESIS,
                SelectionDecision.KEEP,
                reason="synthesis",
            )
            for i in range(7)
        ]
    )
    call_n = {"n": 0}

    async def _fake(*, prompt, **kwargs):
        call_n["n"] += 1
        if call_n["n"] == 1:
            return returned, "mock", {}
        # Repair returns nothing useful for the remaining 3
        return None, "mock", {"validation_error": "empty", "raw_response_text": '{"candidates":[]}'}

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake),
    ):
        selected = await orch._select_patents_via_llm(candidates, _profile(), _run())

    assert orch._filter_stats["selection_keep"] == 7
    assert orch._filter_stats["selection_unverified"] == 3
    assert orch._filter_stats["selection_reject_other"] == 0
    assert orch._filter_stats["selection_llm_partial_missing"] == 3
    assert len(selected) >= 1  # KEEP present


@pytest.mark.asyncio
async def test_unknown_patent_number_from_gemini_is_ignored():
    """Test case 4: unknown patent_number logged/excluded; valid continue."""
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [
        _candidate(
            "US8123456B2",
            "Process for producing nitrile rubber by emulsion polymerization",
        )
    ]
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US9999999B2",  # unknown
                TitleTriageClassification.DIRECT_SYNTHESIS,
                SelectionDecision.KEEP,
            ),
            _verdict(
                "US8123456B2",
                TitleTriageClassification.DIRECT_SYNTHESIS,
                SelectionDecision.KEEP,
                reason="valid",
            ),
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(candidates, _profile(), _run())
    assert len(selected) == 1
    assert selected[0]["patent_number"] == "US8123456B2"
    assert orch._filter_stats["selection_invalid_llm_objects"] >= 1


@pytest.mark.asyncio
async def test_gemini_complete_failure_uses_deterministic_fallback():
    """Test case 5: total LLM failure → deterministic REVIEW, not mass REJECT."""
    orch = _orch()
    orch._reset_filter_stats()
    candidates = [
        _candidate(
            "US8123456B2",
            "Process for producing nitrile rubber by emulsion polymerization",
            "NBR latex prepared by aqueous emulsion polymerization.",
        ),
        _candidate(
            "US8888777B2",
            "Pneumatic tire comprising nitrile rubber composition in sidewall",
            "A pneumatic tire sidewall using purchased NBR.",
        ),
    ]

    async def _always_fail(*, prompt, **kwargs):
        return None, "mock", {"validation_error": "total failure"}

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(side_effect=_always_fail),
    ):
        selected = await orch._select_patents_via_llm(candidates, _profile(), _run())

    # Must not mass-reject as NO_VERDICT / reject_other for all
    assert orch._filter_stats["selection_unverified"] + orch._filter_stats[
        "selection_reject_downstream"
    ] + orch._filter_stats["selection_reject_variant"] >= 1
    # At least one REVIEW promoted into selected when no KEEP
    assert len(selected) >= 1
    decisions = {c["selection_decision"] for c in selected}
    assert "REVIEW" in decisions or "KEEP" in decisions
    assert orch._filter_stats["selection_reject_other"] == 0 or any(
        c["selection_decision"] == "REVIEW" for c in selected
    )


def test_selection_prompt_requires_all_fields_explicitly():
    from app.services.prompts.patent_prompts import PATENT_SELECTION_PROMPT

    assert "CRITICAL OUTPUT CONTRACT" in PATENT_SELECTION_PROMPT
    assert "final_decision" in PATENT_SELECTION_PROMPT
    assert "polymerization_medium_mismatch" in PATENT_SELECTION_PROMPT
    assert "Do NOT omit any required field" in PATENT_SELECTION_PROMPT or "never omit" in PATENT_SELECTION_PROMPT.lower()


def test_schema_normalizer_preserves_patent_selection_required():
    from app.services.llm.schema_normalizer import normalize_gemini_schema

    raw = PatentSelectionResult.model_json_schema()
    normalized = normalize_gemini_schema(raw)

    def find_candidate_required(node):
        if isinstance(node, dict):
            props = node.get("properties") or {}
            if "final_decision" in props and "classification" in props and "patent_number" in props:
                return node.get("required")
            for v in node.values():
                found = find_candidate_required(v)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = find_candidate_required(item)
                if found is not None:
                    return found
        return None

    required = find_candidate_required(normalized)
    assert required is not None
    for field in (
        "patent_number",
        "classification",
        "variant_mismatch",
        "polymerization_medium_mismatch",
        "final_decision",
        "confidence",
        "reason",
    ):
        assert field in required
