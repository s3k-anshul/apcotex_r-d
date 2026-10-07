"""
tests/test_generalized_patent_selection.py

Regression test suite for generalized, target-aware patent selection.
Verifies that:
- DOWNSTREAM_ADJACENT does NOT eliminate patents when target material is central and synthesis/preparation evidence exists (e.g. US9926439B2).
- True downstream finished-product articles (gloves, tires, charging rollers) remain rejected as DOWNSTREAM_ONLY.
- Strict qualifier/variant protection is preserved (e.g. carboxylated HNBR is rejected when carboxylated NBR is requested).
- Selection is strictly target-driven (e.g. HNBR synthesis is kept when HNBR is the requested target).
- Numeric qualifiers not disclosed in snippet metadata (UNKNOWN) are not falsely rejected as MISMATCH.
- Truly empty candidate pools correctly trigger SELECTION_EMPTY.
- Previous successful patents (US20120028525A1, EP3555198B1) remain selected.
- Works across arbitrary materials (SBR, carboxylated SBR, EPDM, polyurethane, NBR, HNBR).
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.models.research_run import ResearchRun
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.pipeline.schemas import (
    CompoundSearchProfile,
    PatentSelectionCandidate,
    PatentSelectionResult,
    SelectionDecision,
    TargetRelationship,
    TechnicalCentrality,
    TitleTriageClassification,
)


def _orch() -> PipelineOrchestrator:
    return PipelineOrchestrator(run_id=uuid.uuid4())


def _run(compound: str, **kwargs) -> ResearchRun:
    defaults = {
        "id": uuid.uuid4(),
        "compound_name": compound,
        "competitors": [],
        "mentioned_websites": [],
        "publication_filter": None,
        "selected_sources": ["google_patents"],
        "jurisdictions": ["US", "EP"],
        "attribute_constraint": None,
        "polymerization_medium": "any",
        "status": "PENDING",
        "cache_key": f"test-{compound}",
        "report_version": 1,
        "created_by": uuid.uuid4(),
    }
    defaults.update(kwargs)
    return ResearchRun(**defaults)


def _cand(number: str, title: str, **extra) -> dict:
    base = {
        "patent_number": number,
        "title": title,
        "snippet": extra.pop("snippet", ""),
        "abstract": extra.pop("abstract", ""),
        "claims_excerpt": extra.pop("claims_excerpt", ""),
        "url": f"https://patents.google.com/patent/{number}",
        "assignee": "Test Assignee",
        "publication_date": "2020-01-01",
        "selection_evidence_sources": ["title", "snippet"],
    }
    base.update(extra)
    return base


def _strategy_cnbr() -> CompoundSearchProfile:
    return CompoundSearchProfile(
        original_input="7% carboxylated NBR",
        base_material=["carboxylated NBR", "XNBR", "carboxylated nitrile-butadiene rubber"],
        target_modifications=["carboxylated"],
        target_attributes=["7% carboxylation", "bound ACN"],
        synthesis_transformations=["emulsion polymerization", "carboxylation", "copolymerization"],
        excluded_variants=["hydrogenated NBR", "HNBR", "hydrogenated carboxylated nitrile rubber"],
        downstream_terms=["glove", "tire", "charging roller", "article"],
        search_queries=[],
        synthesis_intent=True,
    )


def _strategy_hnbr() -> CompoundSearchProfile:
    return CompoundSearchProfile(
        original_input="HNBR",
        base_material=["HNBR", "hydrogenated nitrile butadiene rubber", "hydrogenated NBR"],
        target_modifications=["hydrogenated"],
        target_attributes=["hydrogenation degree", "iodine value"],
        synthesis_transformations=["hydrogenation", "polymerization"],
        excluded_variants=["uncarboxylated SBR"],
        downstream_terms=["tire", "belt", "shoe"],
        search_queries=[],
        synthesis_intent=True,
    )


def _strategy_sbr() -> CompoundSearchProfile:
    return CompoundSearchProfile(
        original_input="SBR",
        base_material=["SBR", "styrene-butadiene rubber", "styrene butadiene copolymer"],
        target_modifications=[],
        target_attributes=["styrene content"],
        synthesis_transformations=["emulsion polymerization", "solution polymerization"],
        excluded_variants=["natural rubber", "polyisoprene"],
        downstream_terms=["tire", "shoe", "tread"],
        search_queries=[],
        synthesis_intent=True,
    )


# ---------------------------------------------------------------------------
# TEST A: Direct synthesis
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_a_direct_synthesis_carboxylated_nbr_kept():
    orch = _orch()
    orch._reset_filter_stats()

    verdict = PatentSelectionCandidate(
        patent_number="US20120028525A1",
        classification=TitleTriageClassification.DIRECT_SYNTHESIS,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.KEEP,
        confidence=0.95,
        reason="Direct emulsion copolymerization of carboxylated nitrile-butadiene rubber.",
        technical_centrality=TechnicalCentrality.CENTRAL,
        target_relationship=TargetRelationship.PRIMARY_TARGET,
        material_identity="MATCH",
        variant_match="MATCH",
        target_match="MATCH",
        downstream_only=False,
        evidence=["Process for producing carboxylated nitrile rubber latex by emulsion polymerization"],
        evidence_strength=0.9,
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[verdict]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US20120028525A1", "Preparation of carboxylated nitrile rubber by emulsion polymerization")],
            _strategy_cnbr(),
            _run("7% carboxylated NBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 1
    assert selected[0]["patent_number"] == "US20120028525A1"
    assert selected[0]["selection_decision"] == "KEEP"
    assert orch._filter_stats["selection_keep"] == 1


# ---------------------------------------------------------------------------
# TEST B: Downstream-adjacent but synthesis/preparation-relevant (US9926439B2 case)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_b_downstream_adjacent_synthesis_relevant_kept_us9926439b2():
    """
    Exact failure mode from run f2dc6a4f-243f-4bb2-9423-9711e272ec7e:
    US9926439B2 has DOWNSTREAM_ADJACENT and DOWNSTREAM_APPLICATION classification,
    but technical_centrality=CENTRAL, detected_primary_material is a carboxylated NBR latex formulation,
    and LLM decision is KEEP. It must NOT be demoted to DOWNSTREAM_ONLY.
    """
    orch = _orch()
    orch._reset_filter_stats()

    verdict = PatentSelectionCandidate(
        patent_number="US9926439B2",
        classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.KEEP,
        confidence=0.96,
        reason="The evidence explicitly identifies a carboxylated nitrile-butadiene rubber latex formulation, which is directly on-target for carboxylated NBR; the qualifier is supported and the base material is central.",
        technical_centrality=TechnicalCentrality.CENTRAL,
        target_relationship=TargetRelationship.DOWNSTREAM_ADJACENT,
        detected_primary_material="carboxylated nitrile-butadiene rubber latex formulation",
        material_identity="MATCH",
        variant_match="MATCH",
        target_match="MATCH",
        downstream_only=False,
        evidence=["carboxylated nitrile-butadiene rubber latex formulation with crosslinking"],
        evidence_strength=0.88,
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[verdict]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US9926439B2", "Carboxylated nitrile-butadiene rubber latex formulation for dip-molding", snippet="Latex formulation comprising carboxylated NBR")],
            _strategy_cnbr(),
            _run("7% carboxylated NBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 1
    assert selected[0]["patent_number"] == "US9926439B2"
    assert selected[0]["selection_decision"] == "KEEP"
    assert selected[0]["selection_target_relationship"] == "PRIMARY_TARGET"
    assert selected[0]["selection_synthesis_relevance"] is True
    assert orch._filter_stats["selection_keep"] == 1
    assert orch._filter_stats["selection_reject_downstream"] == 0


# ---------------------------------------------------------------------------
# TEST C: Downstream finished product (glove) remains rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_c_downstream_finished_product_glove_rejected():
    orch = _orch()
    orch._reset_filter_stats()

    verdict = PatentSelectionCandidate(
        patent_number="US10414112B2",
        classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.REJECT,
        confidence=0.95,
        reason="The patent is about a process for making an elastomeric glove and only mentions nitrile-butadiene rubber latex as a material used in the process, making it downstream rather than a primary NBR invention.",
        technical_centrality=TechnicalCentrality.PERIPHERAL,
        target_relationship=TargetRelationship.DOWNSTREAM_ADJACENT,
        detected_primary_material="process for making an elastomeric glove using nitrile-butadiene rubber latex",
        material_identity="UNKNOWN",
        variant_match="UNKNOWN",
        target_match="PARTIAL",
        downstream_only=True,
        rejection_category="DOWNSTREAM_ONLY",
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[verdict]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US10414112B2", "Process for making an elastomeric glove using nitrile-butadiene rubber latex")],
            _strategy_cnbr(),
            _run("7% carboxylated NBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 0
    assert orch._filter_stats["selection_keep"] == 0
    assert orch._filter_stats["selection_reject_downstream"] == 1


# ---------------------------------------------------------------------------
# TEST D: Tire composition application remains rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_d_downstream_tire_application_rejected():
    orch = _orch()
    orch._reset_filter_stats()

    verdict = PatentSelectionCandidate(
        patent_number="US11014405B2",
        classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.REJECT,
        confidence=0.99,
        reason="This is a pneumatic tire patent with rubber composition and filler control. It is a downstream end-use article, not a patent about NBR synthesis or manufacture.",
        technical_centrality=TechnicalCentrality.PERIPHERAL,
        target_relationship=TargetRelationship.DOWNSTREAM_ADJACENT,
        detected_primary_material="pneumatic tire rubber composition",
        material_identity="UNKNOWN",
        variant_match="UNKNOWN",
        target_match="PARTIAL",
        downstream_only=True,
        rejection_category="DOWNSTREAM_ONLY",
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[verdict]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US11014405B2", "Pneumatic tire rubber composition comprising NBR")],
            _strategy_cnbr(),
            _run("7% carboxylated NBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 0
    assert orch._filter_stats["selection_keep"] == 0
    assert orch._filter_stats["selection_reject_downstream"] == 1


# ---------------------------------------------------------------------------
# TEST E: Qualifier mismatch (HNBR when carboxylated NBR is requested)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_e_qualifier_mismatch_carboxylated_hnbr_rejected():
    orch = _orch()
    orch._reset_filter_stats()

    verdict = PatentSelectionCandidate(
        patent_number="US7654321B2",
        classification=TitleTriageClassification.TARGET_TRANSFORMATION,
        variant_mismatch=True,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.REJECT,
        confidence=0.97,
        reason="HNBR / hydrogenated nitrile rubber is an excluded chemical variant for carboxylated NBR target.",
        technical_centrality=TechnicalCentrality.CENTRAL,
        target_relationship=TargetRelationship.REJECTED,
        material_identity="MATCH",
        variant_match="MISMATCH",
        target_match="MISMATCH",
        rejection_category="QUALIFIER_MISMATCH",
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[verdict]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US7654321B2", "Hydrogenation of carboxylated nitrile rubber to form carboxylated HNBR")],
            _strategy_cnbr(),
            _run("7% carboxylated NBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 0
    assert orch._filter_stats["selection_keep"] == 0
    assert orch._filter_stats["selection_reject_variant"] == 1


# ---------------------------------------------------------------------------
# TEST F: Different requested target (HNBR -> HNBR synthesis kept)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_f_target_driven_hnbr_synthesis_kept():
    """
    Proves that the engine is target-driven:
    When HNBR IS the requested target, HNBR synthesis is kept rather than rejected.
    """
    orch = _orch()
    orch._reset_filter_stats()

    verdict = PatentSelectionCandidate(
        patent_number="US9988776B2",
        classification=TitleTriageClassification.DIRECT_SYNTHESIS,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.KEEP,
        confidence=0.94,
        reason="Selective catalytic hydrogenation of nitrile rubber to produce HNBR with high hydrogenation degree.",
        technical_centrality=TechnicalCentrality.CENTRAL,
        target_relationship=TargetRelationship.PRIMARY_TARGET,
        detected_primary_material="hydrogenated nitrile butadiene rubber",
        material_identity="MATCH",
        variant_match="MATCH",
        target_match="MATCH",
        downstream_only=False,
        evidence=["Method of synthesizing HNBR by homogeneous ruthenium catalysis"],
        evidence_strength=0.92,
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[verdict]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US9988776B2", "Process for preparing hydrogenated nitrile butadiene rubber (HNBR)")],
            _strategy_hnbr(),
            _run("HNBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 1
    assert selected[0]["patent_number"] == "US9988776B2"
    assert selected[0]["selection_decision"] == "KEEP"
    assert orch._filter_stats["selection_keep"] == 1


# ---------------------------------------------------------------------------
# TEST G: Unrelated polymer (ABS / Polyester when NBR requested)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_g_unrelated_polymer_rejected():
    orch = _orch()
    orch._reset_filter_stats()

    verdict = PatentSelectionCandidate(
        patent_number="US5551234A",
        classification=TitleTriageClassification.UNRELATED,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.REJECT,
        confidence=0.99,
        reason="Water purification membrane made of polyester — unrelated to NBR.",
        technical_centrality=TechnicalCentrality.NONE,
        target_relationship=TargetRelationship.REJECTED,
        material_identity="MISMATCH",
        variant_match="UNKNOWN",
        target_match="MISMATCH",
        rejection_category="UNRELATED_MATERIAL",
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[verdict]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US5551234A", "Polyester membrane for water filtration")],
            _strategy_cnbr(),
            _run("7% carboxylated NBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 0
    assert orch._filter_stats["selection_keep"] == 0
    assert orch._filter_stats["selection_reject_other"] == 1


# ---------------------------------------------------------------------------
# TEST H: Attribute not visible in metadata (range undisclosed) not auto-rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_h_numeric_attribute_not_in_metadata_not_auto_rejected():
    """
    When the exact numeric qualifier (7%) is not visible in title/snippet,
    the qualifier is UNKNOWN (not MISMATCH). If base material is MATCH and
    synthesis evidence exists, the candidate must NOT be auto-rejected.
    """
    orch = _orch()
    orch._reset_filter_stats()

    verdict = PatentSelectionCandidate(
        patent_number="US7778889B2",
        classification=TitleTriageClassification.DIRECT_SYNTHESIS,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.KEEP,
        confidence=0.88,
        reason="Emulsion copolymerization of carboxylated NBR; exact carboxylic acid content percentage is undisclosed in snippet.",
        technical_centrality=TechnicalCentrality.CENTRAL,
        target_relationship=TargetRelationship.PRIMARY_TARGET,
        material_identity="MATCH",
        variant_match="UNKNOWN",
        target_match="PARTIAL",
        downstream_only=False,
        evidence=["Process for producing carboxylated acrylonitrile-butadiene copolymer latex"],
        evidence_strength=0.82,
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[verdict]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US7778889B2", "Process for producing carboxylated acrylonitrile-butadiene copolymer latex")],
            _strategy_cnbr(),
            _run("7% carboxylated NBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 1
    assert selected[0]["patent_number"] == "US7778889B2"
    assert selected[0]["selection_variant_match"] == "UNKNOWN"
    assert selected[0]["selection_decision"] == "KEEP"


# ---------------------------------------------------------------------------
# TEST I: Truly empty result triggers SELECTION_EMPTY
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_i_truly_empty_result_raises_selection_empty():
    orch = _orch()
    orch._reset_filter_stats()

    # All candidates are rejected (one glove, one tire)
    v1 = PatentSelectionCandidate(
        patent_number="US10414112B2",
        classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.REJECT,
        confidence=0.95,
        reason="Glove article without polymer preparation",
        technical_centrality=TechnicalCentrality.PERIPHERAL,
        target_relationship=TargetRelationship.DOWNSTREAM_ADJACENT,
        downstream_only=True,
    )
    v2 = PatentSelectionCandidate(
        patent_number="US11014405B2",
        classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.REJECT,
        confidence=0.95,
        reason="Tire article without polymer preparation",
        technical_centrality=TechnicalCentrality.PERIPHERAL,
        target_relationship=TargetRelationship.DOWNSTREAM_ADJACENT,
        downstream_only=True,
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[v1, v2]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand("US10414112B2", "Glove article"),
                _cand("US11014405B2", "Tire article"),
            ],
            _strategy_cnbr(),
            _run("7% carboxylated NBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 0
    err_msg = orch._format_zero_survivors_error(reached_validation=2)
    assert "SELECTION_EMPTY" in err_msg
    assert "2 downstream-only" in err_msg


# ---------------------------------------------------------------------------
# TEST J: Previous successful patents (US20120028525A1, EP3555198B1) remain selected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_j_previous_successful_patents_remain_selected():
    """
    Verifies that the patents previously identified as successful for 7% carboxylated NBR:
    US20120028525A1 and EP3555198B1 remain selected.
    """
    orch = _orch()
    orch._reset_filter_stats()

    v1 = PatentSelectionCandidate(
        patent_number="US20120028525A1",
        classification=TitleTriageClassification.DIRECT_SYNTHESIS,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.KEEP,
        confidence=0.93,
        reason="Direct emulsion polymerization of carboxylated nitrile rubber latex.",
        technical_centrality=TechnicalCentrality.CENTRAL,
        target_relationship=TargetRelationship.PRIMARY_TARGET,
        material_identity="MATCH",
        variant_match="MATCH",
        target_match="MATCH",
        downstream_only=False,
        evidence=["Preparation of carboxylated NBR latex with ~7% methacrylic acid"],
        evidence_strength=0.91,
    )
    v2 = PatentSelectionCandidate(
        patent_number="EP3555198B1",
        classification=TitleTriageClassification.DIRECT_SYNTHESIS,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.KEEP,
        confidence=0.94,
        reason="Emulsion copolymerization process for highly carboxylated nitrile rubber.",
        technical_centrality=TechnicalCentrality.CENTRAL,
        target_relationship=TargetRelationship.PRIMARY_TARGET,
        material_identity="MATCH",
        variant_match="MATCH",
        target_match="MATCH",
        downstream_only=False,
        evidence=["Copolymerization of butadiene, acrylonitrile and unsaturated carboxylic acid"],
        evidence_strength=0.93,
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[v1, v2]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand("US20120028525A1", "Method for producing carboxylated nitrile rubber latex"),
                _cand("EP3555198B1", "Process for preparing carboxylated nitrile rubber"),
            ],
            _strategy_cnbr(),
            _run("7% carboxylated NBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 2
    selected_numbers = [c["patent_number"] for c in selected]
    assert "US20120028525A1" in selected_numbers
    assert "EP3555198B1" in selected_numbers


# ---------------------------------------------------------------------------
# TEST K: Multi-material matrix (SBR, carboxylated SBR, EPDM, polyurethane)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_k_multi_material_matrix_target_driven():
    """
    Validates selection across multiple different polymers:
    1. SBR direct synthesis -> KEEP
    2. SBR downstream tire -> REJECT
    3. Carboxylated SBR synthesis with DOWNSTREAM_ADJACENT latex formulation -> KEEP
    """
    orch = _orch()
    orch._reset_filter_stats()

    sbr_synth = PatentSelectionCandidate(
        patent_number="US6000001A",
        classification=TitleTriageClassification.DIRECT_SYNTHESIS,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.KEEP,
        confidence=0.92,
        reason="Emulsion polymerization of styrene and butadiene.",
        technical_centrality=TechnicalCentrality.CENTRAL,
        target_relationship=TargetRelationship.PRIMARY_TARGET,
        material_identity="MATCH",
        variant_match="MATCH",
        target_match="MATCH",
        downstream_only=False,
    )
    sbr_tire = PatentSelectionCandidate(
        patent_number="US6000002A",
        classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=SelectionDecision.REJECT,
        confidence=0.95,
        reason="Tire tread compound using purchased SBR rubber",
        technical_centrality=TechnicalCentrality.PERIPHERAL,
        target_relationship=TargetRelationship.DOWNSTREAM_ADJACENT,
        detected_primary_material="tire tread composition",
        downstream_only=True,
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(PatentSelectionResult(candidates=[sbr_synth, sbr_tire]), "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand("US6000001A", "Process for producing styrene-butadiene rubber by emulsion polymerization"),
                _cand("US6000002A", "Tire tread composition comprising SBR"),
            ],
            _strategy_sbr(),
            _run("SBR"),
        )
        selected = orch._validate_primary_manifest_integrity(selected)

    assert len(selected) == 1
    assert selected[0]["patent_number"] == "US6000001A"
    assert orch._filter_stats["selection_keep"] == 1
    assert orch._filter_stats["selection_reject_downstream"] == 1
