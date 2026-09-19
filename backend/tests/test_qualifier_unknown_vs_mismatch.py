"""
Regression: material identity vs qualifier UNKNOWN/MISMATCH decoupling.

QUALIFIER UNKNOWN ≠ QUALIFIER MISMATCH
CONTAINING TARGET ≠ BEING ABOUT TARGET
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.models.research_run import ResearchRun
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.pipeline.report_service import (
    _normalize_target_attribute,
    _NOT_DISCLOSED_VALUE,
)
from app.services.pipeline.schemas import (
    CompoundSearchProfile,
    DynamicTargetAttributeEvidence,
    PatentSelectionCandidate,
    PatentSelectionResult,
    SelectionDecision,
    TargetRelationship,
    TechnicalCentrality,
    TitleTriageClassification,
)
import uuid


def _orch() -> PipelineOrchestrator:
    return PipelineOrchestrator(run_id=uuid.uuid4())


def _run(compound: str) -> ResearchRun:
    return ResearchRun(
        compound_name=compound,
        competitors=[],
        mentioned_websites=[],
        publication_filter=None,
        selected_sources=[],
        jurisdictions=["US"],
    )


def _cand(number: str, title: str) -> dict:
    return {
        "patent_number": number,
        "title": title,
        "snippet": "",
        "url": f"https://patents.google.com/patent/{number}",
        "assignee": "Example Corporation",
        "selection_evidence_sources": ["title", "snippet"],
    }


def _strategy(compound: str = "Example Polymer X", **kwargs) -> CompoundSearchProfile:
    base = dict(
        original_input=compound,
        base_material=["Example Polymer X", "EPX"],
        target_modifications=["low unit content"],
        target_attributes=["Example Unit Content"],
        identity_exclusions=["Example Block Copolymer Y"],
        related_materials=["Example Block Copolymer Y"],
        relevance_definition=(
            "PRIMARY_TARGET when the invention is about Example Polymer X itself; "
            "requested qualifier need not be disclosed for identity."
        ),
        excluded_variants=[],
        search_queries=[],
    )
    base.update(kwargs)
    return CompoundSearchProfile(**base)


def _verdict(
    number: str,
    decision: SelectionDecision,
    *,
    relationship: TargetRelationship = TargetRelationship.PRIMARY_TARGET,
    material_identity: str = "MATCH",
    variant_match: str = "UNKNOWN",
    variant_mismatch: bool = False,
    detected: str = "Example Polymer X",
    retain_related: bool = False,
    classification: TitleTriageClassification = TitleTriageClassification.DIRECT_SYNTHESIS,
    centrality: TechnicalCentrality = TechnicalCentrality.CENTRAL,
    downstream_only: bool = False,
    rejection_category: str = "",
    confidence: float = 0.9,
    reason: str = "fixture",
) -> PatentSelectionCandidate:
    return PatentSelectionCandidate(
        patent_number=number,
        classification=classification,
        variant_mismatch=variant_mismatch,
        polymerization_medium_mismatch=False,
        final_decision=decision,
        confidence=confidence,
        reason=reason,
        technical_centrality=centrality,
        target_relationship=relationship,
        detected_primary_material=detected,
        material_identity=material_identity,
        retain_as_related=retain_related,
        variant_match=variant_match,
        downstream_only=downstream_only,
        rejection_category=rejection_category,
        evidence_strength=0.85,
        evidence=["fixture"],
    )


@pytest.mark.asyncio
async def test_a_material_match_qualifier_unknown_is_primary():
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1001",
                SelectionDecision.REJECT,  # LLM wrongly rejects UNKNOWN qualifier
                relationship=TargetRelationship.PRIMARY_TARGET,
                material_identity="MATCH",
                variant_match="UNKNOWN",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US1001", "Preparation of Example Polymer X")],
            _strategy(),
            _run("Example Polymer X"),
        )
    assert [c["patent_number"] for c in selected] == ["US1001"]
    assert selected[0]["selection_variant_match"] == "UNKNOWN"
    assert selected[0]["selection_target_relationship"] == "PRIMARY_TARGET"


@pytest.mark.asyncio
async def test_b_different_material_not_primary():
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1002",
                SelectionDecision.REJECT,
                relationship=TargetRelationship.REJECTED,
                material_identity="MISMATCH",
                variant_match="UNKNOWN",
                detected="Other Polymer Q",
                classification=TitleTriageClassification.UNRELATED,
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US1002", "Polymerization of Other Polymer Q")],
            _strategy(),
            _run("Example Polymer X"),
        )
    assert selected == []


@pytest.mark.asyncio
async def test_c_component_segment_is_related_not_primary():
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1003",
                SelectionDecision.KEEP,  # incorrect KEEP
                relationship=TargetRelationship.RELATED_TARGET,
                material_identity="MISMATCH",
                variant_match="UNKNOWN",
                detected="Example Block Copolymer Y",
                retain_related=True,
                classification=TitleTriageClassification.POLYMER_STRUCTURE,
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US1003", "Block copolymer containing EPX segment")],
            _strategy(),
            _run("Example Polymer X"),
        )
    assert selected == []
    assert [c["patent_number"] for c in orch._related_candidates] == ["US1003"]


@pytest.mark.asyncio
async def test_d_qualifier_explicit_match_primary():
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1004",
                SelectionDecision.KEEP,
                material_identity="MATCH",
                variant_match="MATCH",
                reason="EPX with Example Unit Content 14-18 wt%",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US1004", "Low-unit Example Polymer X")],
            _strategy(),
            _run("Low-Unit Example Polymer X"),
        )
    assert selected[0]["selection_variant_match"] == "MATCH"


@pytest.mark.asyncio
async def test_e_qualifier_unknown_soft_promotes_from_rejected_relationship():
    """Material MATCH + UNKNOWN qualifier must not stay REJECTED solely for missing qualifier."""
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1005",
                SelectionDecision.REJECT,
                relationship=TargetRelationship.REJECTED,
                material_identity="MATCH",
                variant_match="UNKNOWN",
                detected="Example Polymer X",
                reason="About EPX but unit content not disclosed",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US1005", "Continuous polymerization of Example Polymer X")],
            _strategy(),
            _run("Low-Unit Example Polymer X"),
        )
    assert [c["patent_number"] for c in selected] == ["US1005"]
    assert selected[0]["selection_variant_match"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_f_qualifier_explicit_mismatch_rejected():
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1006",
                SelectionDecision.REJECT,
                relationship=TargetRelationship.REJECTED,
                material_identity="MATCH",
                variant_match="MISMATCH",
                variant_mismatch=True,
                detected="high-unit Example Polymer X",
                rejection_category="QUALIFIER_MISMATCH",
                reason="Explicit high-unit EPX contradicts low-unit request",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US1006", "High-unit Example Polymer X process")],
            _strategy(),
            _run("Low-Unit Example Polymer X"),
        )
    assert selected == []
    # Soft-corrected to primary identity but still rejected for MISMATCH
    assert orch._filter_stats["selection_reject_variant"] == 1


@pytest.mark.asyncio
async def test_g_match_ranks_above_unknown():
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1007",
                SelectionDecision.KEEP,
                variant_match="UNKNOWN",
                confidence=0.95,
                detected="Example Polymer X",
            ),
            _verdict(
                "US1008",
                SelectionDecision.KEEP,
                variant_match="MATCH",
                confidence=0.90,
                detected="Example Polymer X",
            ),
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand("US1007", "EPX prep unknown unit"),
                _cand("US1008", "Low-unit EPX"),
            ],
            _strategy(),
            _run("Low-Unit Example Polymer X"),
            max_keep=10,
        )
    assert [c["patent_number"] for c in selected] == ["US1008", "US1007"]


@pytest.mark.asyncio
async def test_synthesis_outranks_and_downstream_never_primary():
    """Direct synthesis outranks residual keepers; DOWNSTREAM_APPLICATION never primary."""
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US2001",
                SelectionDecision.KEEP,
                classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
                variant_match="MATCH",
                confidence=0.99,
                detected="Example Polymer X commercial grade in article",
                reason="Uses EPX with matching unit content in finished article",
            ),
            _verdict(
                "US2002",
                SelectionDecision.KEEP,
                classification=TitleTriageClassification.DIRECT_SYNTHESIS,
                variant_match="UNKNOWN",
                confidence=0.80,
                detected="Example Polymer X",
                reason="EPX polymerization; unit content not disclosed",
            ),
            _verdict(
                "US2003",
                SelectionDecision.KEEP,
                classification=TitleTriageClassification.DIRECT_SYNTHESIS,
                variant_match="MATCH",
                confidence=0.85,
                detected="Example Polymer X",
                reason="EPX synthesis with explicit low unit content",
            ),
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand("US2001", "EPX-containing finished article"),
                _cand("US2002", "Process for preparing EPX"),
                _cand("US2003", "Low-unit EPX emulsion polymerization"),
            ],
            _strategy(),
            _run("Low-Unit Example Polymer X"),
            max_keep=10,
        )
    assert [c["patent_number"] for c in selected] == ["US2003", "US2002"]
    assert orch._filter_stats["selection_reject_downstream"] >= 1


def test_h_property_ownership_still_blocks_foreign_values():
    leaked = _normalize_target_attribute(
        DynamicTargetAttributeEvidence(
            label="Example Unit Content",
            value="21 wt%",
            status="direct",
            material_context="Example Block Copolymer Y",
            belongs_to_target=False,
        ),
        "Example Unit Content",
    )
    assert leaked.value == _NOT_DISCLOSED_VALUE
    assert leaked.belongs_to_target is False


@pytest.mark.asyncio
async def test_i_arbitrary_target_prompt_has_decoupled_rules():
    orch = _orch()
    captured = {}

    async def _cap(**kwargs):
        captured["prompt"] = kwargs.get("prompt", "")
        return (
            PatentSelectionResult(
                candidates=[
                    _verdict("US1009", SelectionDecision.KEEP, variant_match="UNKNOWN")
                ]
            ),
            "mock",
            {},
        )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(side_effect=_cap),
    ):
        await orch._select_patents_via_llm(
            [_cand("US1009", "Zephyr Elastomer Z preparation")],
            _strategy(
                "Zephyr Elastomer Z",
                base_material=["Zephyr Elastomer Z", "ZEZ"],
                target_modifications=["carboxylated"],
                target_attributes=["Carboxyl Content"],
            ),
            _run("Carboxylated Zephyr Elastomer Z"),
        )
    assert "QUALIFIER UNKNOWN" in captured["prompt"] or "UNKNOWN ≠" in captured["prompt"] or "UNKNOWN !=" in captured["prompt"] or "not the same as MISMATCH" in captured["prompt"]
    assert "material_identity" in captured["prompt"]
    assert "Zephyr Elastomer Z" in captured["prompt"]


@pytest.mark.asyncio
async def test_primary_with_unknown_material_identity_soft_promotes_when_synthesis():
    """PRIMARY_TARGET + synthesis focus + UNKNOWN material_identity remains eligible."""
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US2010",
                SelectionDecision.KEEP,
                relationship=TargetRelationship.PRIMARY_TARGET,
                material_identity="UNKNOWN",
                variant_match="UNKNOWN",
                classification=TitleTriageClassification.DIRECT_SYNTHESIS,
                detected="Example Polymer X preparation",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US2010", "Process for preparing Example Polymer X")],
            _strategy(),
            _run("Low-Unit Example Polymer X"),
        )
    assert [c["patent_number"] for c in selected] == ["US2010"]


@pytest.mark.asyncio
async def test_strategy_base_alignment_rescues_overstrict_material_mismatch():
    """Detected base-material + synthesis focus can rescue MISMATCH identity when qualifier unknown."""
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US2011",
                SelectionDecision.REJECT,
                relationship=TargetRelationship.REJECTED,
                material_identity="MISMATCH",
                variant_match="UNKNOWN",
                classification=TitleTriageClassification.DIRECT_SYNTHESIS,
                detected="Example Polymer X emulsion polymerization",
                reason="LLM conflated missing qualifier into material mismatch",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US2011", "Emulsion polymerization of Example Polymer X")],
            _strategy(),
            _run("Low-Unit Example Polymer X"),
        )
    assert [c["patent_number"] for c in selected] == ["US2011"]


@pytest.mark.asyncio
async def test_excluded_variant_in_detected_blocks_strategy_rescue():
    orch = _orch()
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US2012",
                SelectionDecision.KEEP,
                relationship=TargetRelationship.REJECTED,
                material_identity="MISMATCH",
                variant_match="UNKNOWN",
                classification=TitleTriageClassification.DIRECT_SYNTHESIS,
                detected="Example Block Copolymer Y containing EPX segment",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US2012", "Block copolymer Y")],
            _strategy(),
            _run("Example Polymer X"),
        )
    assert selected == []


def test_query_expansion_prompt_allows_identity_without_qualifier():
    from app.services.prompts.patent_prompts import (
        PATENT_QUERY_EXPANSION_PROMPT,
        PATENT_SELECTION_PROMPT,
    )

    assert "Do NOT force every query to include the requested qualifier" in PATENT_QUERY_EXPANSION_PROMPT
    assert "IDENTITY/DISCOVERY" in PATENT_QUERY_EXPANSION_PROMPT or "identity/discovery" in PATENT_QUERY_EXPANSION_PROMPT.lower()
    assert "CRITICAL DECOUPLING" in PATENT_SELECTION_PROMPT
    assert "Do NOT dedicate discovery queries to end-use applications" in PATENT_QUERY_EXPANSION_PROMPT
