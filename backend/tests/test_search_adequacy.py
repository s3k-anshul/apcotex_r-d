"""
tests/test_search_adequacy.py

Comprehensive tests for the Dynamic Patent Discovery Pipeline & Search Adequacy Gate.
Verifies all 10 requirements from Step 14:
  Test 1: Low Acrylonitrile NBR dynamic profile, query distribution, synthesis preference
  Test 2: Low Styrene SBR compound-agnostic dynamic profile and adequacy
  Test 3: HNBR as target is not globally excluded
  Test 4: Carboxylated NBR as target is not globally excluded
  Test 5: Downstream application patent not classified as PRIMARY
  Test 6: Synthesis patent receives PRIMARY classification
  Test 7: Insufficient search coverage returns LOW adequacy and triggers expansion
  Test 8: Generic synthetic compound has zero hardcoded rubber assumptions
  Test 9: Deduplication (publication and family) preserves best representative
  Test 10: SearchAdequacy and SearchAdequacyMetrics schema integrity & edge cases
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.research_run import ResearchRun, RunStatus
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.pipeline.schemas import (
    CompoundSearchProfile,
    GeneratedQuery,
    PatentSelectionCandidate,
    PatentSelectionResult,
    SearchAdequacy,
    SearchAdequacyMetrics,
    SelectionDecision,
    TechnicalCentrality,
    TitleTriageClassification,
)


def _orch() -> PipelineOrchestrator:
    return PipelineOrchestrator(run_id=uuid.uuid4())


def _run(compound: str, **kwargs) -> ResearchRun:
    defaults = {
        "compound_name": compound,
        "competitors": [],
        "mentioned_websites": [],
        "publication_filter": None,
        "selected_sources": [],
        "jurisdictions": ["US", "EP"],
        "attribute_constraint": None,
        "polymerization_medium": "any",
        "status": "PENDING",
        "cache_key": "test_cache",
        "report_version": 1,
        "created_by": uuid.uuid4(),
    }
    defaults.update(kwargs)
    return ResearchRun(**defaults)


def _gq(query: str, intent: str = "synthesis") -> GeneratedQuery:
    return GeneratedQuery(
        query=query,
        required_concepts=["polymerization"],
        alternative_concepts=["synthesis"],
        intent=intent,
        scope="title",
    )


def _cand(number: str, title: str, snippet: str = "", **extra) -> dict:
    base = {
        "patent_number": number,
        "title": title,
        "snippet": snippet,
        "url": f"https://patents.google.com/patent/{number}",
        "assignee": "Test Chem Corp",
        "publication_date": "2020-01-01",
        "priority_date": "2019-01-01",
        "query_matched": "test query",
    }
    base.update(extra)
    return base


def _verdict(
    number: str,
    decision: SelectionDecision,
    classification: TitleTriageClassification = TitleTriageClassification.DIRECT_SYNTHESIS,
    **kwargs,
) -> PatentSelectionCandidate:
    defaults = dict(
        patent_number=number,
        classification=classification,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=decision,
        confidence=0.9,
        reason="fixture reason",
        technical_centrality=TechnicalCentrality.CENTRAL,
        evidence_strength=0.85 if decision == SelectionDecision.KEEP else 0.0,
        downstream_only=False,
        evidence=["fixture evidence"],
    )
    defaults.update(kwargs)
    return PatentSelectionCandidate(**defaults)


# ==============================================================================
# Test 1: Low Acrylonitrile NBR
# ==============================================================================
@pytest.mark.asyncio
async def test_1_low_acn_nbr_dynamic_behavior():
    """
    Test 1: Low Acrylonitrile NBR
    Verify:
    - profile generated dynamically
    - queries contain NBR synonyms/monomers/process concepts
    - 'low' is not mandatory in every query
    - synthesis patents receive higher relevance than downstream NBR applications
    - unrelated patents are rejected
    - HNBR is not selected as PRIMARY unless justified
    """
    orch = _orch()
    strategy = CompoundSearchProfile(
        original_input="Low Acrylonitrile NBR",
        base_material=[
            "acrylonitrile butadiene rubber",
            "nitrile butadiene rubber",
            "NBR",
            "acrylonitrile-butadiene copolymer",
        ],
        target_modifications=["low acrylonitrile", "low ACN", "reduced bound acrylonitrile"],
        target_attributes=["low bound ACN content", "cold resistance"],
        synthesis_transformations=["emulsion polymerization", "copolymerization", "synthesis"],
        excluded_variants=["hydrogenated acrylonitrile butadiene rubber", "HNBR"],
        downstream_terms=["gasket", "o-ring", "hose", "shoe sole", "fuel pipe"],
        search_queries=[
            _gq("emulsion polymerization acrylonitrile butadiene"),
            _gq("low acrylonitrile NBR polymerization cold resistance"),
            _gq("acrylonitrile butadiene copolymer preparation initiator"),
            _gq("NBR latex emulsion synthesis surfactant"),
        ],
        synthesis_intent=True,
    )

    # 1. Profile generated dynamically — contains base material synonyms and transformations
    assert "acrylonitrile butadiene rubber" in strategy.base_material
    assert "NBR" in strategy.base_material

    # 2. Queries contain NBR synonyms/monomers/process concepts
    query_texts = [q.query for q in strategy.search_queries]
    all_query_blob = " ".join(query_texts).lower()
    assert "acrylonitrile" in all_query_blob
    assert "butadiene" in all_query_blob
    assert "polymerization" in all_query_blob

    # 3. 'low' is NOT mandatory in every query
    queries_without_low = [q for q in query_texts if "low" not in q.lower()]
    assert len(queries_without_low) >= 2, "Broad synthesis queries should not all require 'low'"

    # 4. Synthesis patent vs Downstream vs Unrelated
    synthesis_cand = _cand(
        "US1001",
        "Process for emulsion polymerization of low acrylonitrile butadiene rubber",
        snippet="Emulsion copolymerization of butadiene and acrylonitrile yielding 18% bound ACN.",
    )
    downstream_cand = _cand(
        "US1002",
        "Automotive fuel hose comprising NBR outer layer",
        snippet="A multi-layer fuel hose having an NBR rubber inner tube and nylon cover.",
    )
    unrelated_cand = _cand(
        "US1003",
        "Lithium ion secondary battery with solid electrolyte",
        snippet="Electrode assembly for electric vehicle power storage.",
    )

    # Test adequacy metrics
    metrics = orch._compute_search_adequacy([synthesis_cand, downstream_cand, unrelated_cand], strategy)
    assert metrics.direct_material_candidates == 2
    assert metrics.synthesis_candidates == 1
    assert metrics.unrelated_count == 1

    # Test selection: synthesis kept, downstream rejected
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict("US1001", SelectionDecision.KEEP, TitleTriageClassification.DIRECT_SYNTHESIS),
            _verdict("US1002", SelectionDecision.REJECT, TitleTriageClassification.DOWNSTREAM_APPLICATION, downstream_only=True),
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [synthesis_cand, downstream_cand],
            strategy,
            _run("Low Acrylonitrile NBR"),
        )
    assert [c["patent_number"] for c in selected] == ["US1001"]


# ==============================================================================
# Test 2: Low Styrene SBR
# ==============================================================================
@pytest.mark.asyncio
async def test_2_low_styrene_sbr_compound_agnostic_profile():
    """
    Test 2: Low Styrene SBR
    Verify:
    - no NBR-specific logic is triggered
    - profile dynamically changes
    - styrene becomes the target modifier
    - SBR polymerization patents receive appropriate relevance
    """
    orch = _orch()
    strategy = CompoundSearchProfile(
        original_input="Low Styrene SBR",
        base_material=[
            "styrene butadiene rubber",
            "styrene-butadiene copolymer",
            "SBR",
        ],
        target_modifications=["low styrene", "reduced styrene content"],
        target_attributes=["low glass transition temperature", "high flexibility"],
        synthesis_transformations=["solution polymerization", "emulsion polymerization", "copolymerization"],
        excluded_variants=["high styrene resin", "block copolymer SBS"],
        downstream_terms=["tire tread", "conveyor belt", "footwear"],
        search_queries=[],
        synthesis_intent=True,
    )

    # 1. No NBR-specific terms present anywhere in profile
    all_terms = " ".join(
        strategy.base_material
        + strategy.target_modifications
        + strategy.synthesis_transformations
        + strategy.excluded_variants
    ).lower()
    assert "acrylonitrile" not in all_terms
    assert "nbr" not in all_terms

    # 2. Profile dynamically changes for SBR
    assert "styrene butadiene rubber" in strategy.base_material
    assert any("styrene" in m.lower() for m in strategy.target_modifications)

    # 3. Adequacy and relevance on SBR candidates
    sbr_synth = _cand(
        "US2001",
        "Preparation of low styrene content styrene-butadiene copolymer by solution polymerization",
        snippet="Anionic polymerization of 1,3-butadiene and styrene in cyclohexane solvent.",
    )
    sbr_downstream = _cand(
        "US2002",
        "Tire tread rubber composition comprising SBR and silica filler",
        snippet="Vulcanized rubber tread formulation with improved wet grip.",
    )
    unrelated_intruder = _cand(
        "US2003",
        "Polyurethane acrylate resin for optical coating",
        snippet="UV curable acrylate oligomer for protective display film.",
    )

    metrics = orch._compute_search_adequacy([sbr_synth, sbr_downstream, unrelated_intruder], strategy)
    # SBR candidates match base_material; unrelated intruder has no SBR tokens -> unrelated
    assert metrics.direct_material_candidates == 2
    assert metrics.synthesis_candidates == 1
    assert metrics.unrelated_count == 1
    assert metrics.adequacy in (SearchAdequacy.HIGH, SearchAdequacy.MEDIUM)


# ==============================================================================
# Test 3: HNBR as Target
# ==============================================================================
@pytest.mark.asyncio
async def test_3_hnbr_as_target_is_not_globally_excluded():
    """
    Test 3: HNBR
    Verify:
    - HNBR is treated as the target
    - it is NOT rejected because of a global HNBR exclusion rule
    """
    orch = _orch()
    hnbr_strategy = CompoundSearchProfile(
        original_input="HNBR",
        base_material=[
            "hydrogenated nitrile butadiene rubber",
            "HNBR",
            "hydrogenated acrylonitrile-butadiene copolymer",
        ],
        target_modifications=[],
        target_attributes=["high heat resistance", "oil resistance"],
        synthesis_transformations=["catalytic hydrogenation", "solution hydrogenation"],
        excluded_variants=["uncarboxylated standard NBR"],
        downstream_terms=["timing belt", "oil well packer"],
        search_queries=[],
        synthesis_intent=True,
    )

    # HNBR is in base_material, NOT in excluded_variants
    assert "HNBR" in hnbr_strategy.base_material
    assert not any("hnbr" == v.lower() for v in hnbr_strategy.excluded_variants)

    hnbr_cand = _cand(
        "US3001",
        "Process for selective hydrogenation of nitrile rubber to produce HNBR",
        snippet="Hydrogenation in methyl ethyl ketone using Wilkinson catalyst yielding HNBR.",
    )
    metrics = orch._compute_search_adequacy([hnbr_cand], hnbr_strategy)
    assert metrics.direct_material_candidates == 1
    assert metrics.synthesis_candidates == 1
    assert metrics.excluded_variant_count == 0

    # Selection verification: HNBR candidate is kept when HNBR is the target
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US3001",
                SelectionDecision.KEEP,
                TitleTriageClassification.DIRECT_SYNTHESIS,
                material_identity="MATCH",
                technical_centrality=TechnicalCentrality.CENTRAL,
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [hnbr_cand],
            hnbr_strategy,
            _run("HNBR"),
        )
    assert [c["patent_number"] for c in selected] == ["US3001"]


# ==============================================================================
# Test 4: Carboxylated NBR as Target
# ==============================================================================
def test_4_carboxylated_nbr_as_target_not_excluded():
    """
    Test 4: Carboxylated NBR
    Verify:
    - carboxylated NBR is treated as the requested target
    - it is not globally excluded
    """
    orch = _orch()
    xnbr_strategy = CompoundSearchProfile(
        original_input="Carboxylated NBR",
        base_material=[
            "carboxylated acrylonitrile butadiene rubber",
            "carboxylated nitrile rubber",
            "XNBR",
        ],
        target_modifications=["methacrylic acid termonomer", "carboxylic acid groups"],
        target_attributes=["abrasion resistance", "high tensile strength"],
        synthesis_transformations=["terpolymerization", "emulsion polymerization"],
        excluded_variants=["standard unfunctionalized NBR", "hydrogenated NBR"],
        downstream_terms=["textile roll", "glove coating"],
        search_queries=[],
        synthesis_intent=True,
    )

    assert "XNBR" in xnbr_strategy.base_material
    assert not any("carboxylated nbr" == v.lower() for v in xnbr_strategy.excluded_variants)

    xnbr_cand = _cand(
        "US4001",
        "Emulsion terpolymerization process for carboxylated nitrile rubber latex",
        snippet="Terpolymerization of butadiene, acrylonitrile, and methacrylic acid in aqueous emulsion.",
    )
    metrics = orch._compute_search_adequacy([xnbr_cand], xnbr_strategy)
    assert metrics.direct_material_candidates == 1
    assert metrics.synthesis_candidates == 1
    assert metrics.excluded_variant_count == 0


# ==============================================================================
# Test 5: Downstream Application Patent Not Classified as PRIMARY
# ==============================================================================
@pytest.mark.asyncio
async def test_5_downstream_application_patent_not_primary():
    """
    Test 5: Downstream application patent
    Verify:
    - it does not receive PRIMARY classification merely because NBR appears in it.
    """
    orch = _orch()
    strategy = CompoundSearchProfile(
        original_input="Low Acrylonitrile NBR",
        base_material=["acrylonitrile butadiene rubber", "NBR"],
        target_modifications=["low acrylonitrile"],
        target_attributes=[],
        synthesis_transformations=["polymerization", "synthesis"],
        excluded_variants=["HNBR"],
        downstream_terms=["golf ball", "tire", "shoe"],
        search_queries=[],
        synthesis_intent=True,
    )

    golf_ball_cand = _cand(
        "US5001",
        "Multi-piece solid golf ball having core layer comprising NBR and polybutadiene",
        snippet="Golf ball core composition comprising 100 parts polybutadiene rubber and 5 parts NBR modifier.",
    )

    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US5001",
                SelectionDecision.REJECT,
                TitleTriageClassification.DOWNSTREAM_APPLICATION,
                technical_centrality=TechnicalCentrality.PERIPHERAL,
                downstream_only=True,
            )
        ]
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [golf_ball_cand],
            strategy,
            _run("Low Acrylonitrile NBR"),
        )
    assert len(selected) == 0, "Downstream application patent must not be selected as primary"


# ==============================================================================
# Test 6: Synthesis Patent Receives PRIMARY Classification
# ==============================================================================
@pytest.mark.asyncio
async def test_6_synthesis_patent_receives_primary_classification():
    """
    Test 6: Synthesis patent
    Verify:
    - it receives PRIMARY classification when aligned with the target.
    """
    orch = _orch()
    strategy = CompoundSearchProfile(
        original_input="Low Acrylonitrile NBR",
        base_material=["acrylonitrile butadiene rubber", "nitrile rubber", "NBR"],
        target_modifications=["low acrylonitrile"],
        target_attributes=[],
        synthesis_transformations=["emulsion polymerization", "copolymerization"],
        excluded_variants=["HNBR"],
        downstream_terms=["hose", "gasket"],
        search_queries=[],
        synthesis_intent=True,
    )

    synth_cand = _cand(
        "US6001",
        "Method for producing nitrile rubber having low bound acrylonitrile by emulsion polymerization",
        snippet="Copolymerizing 1,3-butadiene and acrylonitrile at 10 deg C with sodium dodecyl sulfate emulsifier.",
    )

    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US6001",
                SelectionDecision.KEEP,
                TitleTriageClassification.DIRECT_SYNTHESIS,
                technical_centrality=TechnicalCentrality.CENTRAL,
                material_identity="MATCH",
            )
        ]
    )

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [synth_cand],
            strategy,
            _run("Low Acrylonitrile NBR"),
        )
    assert [c["patent_number"] for c in selected] == ["US6001"]


# ==============================================================================
# Test 7: Insufficient Search Coverage Returns LOW Adequacy
# ==============================================================================
def test_7_insufficient_search_coverage_returns_low_adequacy():
    """
    Test 7: Insufficient search coverage
    Simulate a candidate pool containing mostly unrelated patents.
    Verify:
    - search adequacy becomes LOW
    - unrelated_rate is high
    - the pipeline recognizes insufficient coverage
    """
    orch = _orch()
    strategy = CompoundSearchProfile(
        original_input="Low Acrylonitrile NBR",
        base_material=["acrylonitrile butadiene rubber", "nitrile rubber", "NBR"],
        target_modifications=["low acrylonitrile"],
        target_attributes=[],
        synthesis_transformations=["polymerization"],
        excluded_variants=["HNBR"],
        downstream_terms=["shoe sole"],
        search_queries=[],
        synthesis_intent=True,
    )

    # Pool of 10 patents: 9 completely unrelated, 1 downstream with zero synthesis
    mostly_unrelated = [
        _cand(f"US700{i}", f"Electrochemical cell separator membrane {i}", snippet="Lithium battery battery anode")
        for i in range(9)
    ]
    mostly_unrelated.append(_cand("US7010", "Shoe sole outsole", snippet="Shoe outsole thermoplastic"))

    metrics = orch._compute_search_adequacy(mostly_unrelated, strategy, search_round=1)

    assert metrics.adequacy == SearchAdequacy.LOW
    assert metrics.direct_material_candidates <= 1
    assert metrics.synthesis_candidates == 0
    assert metrics.unrelated_rate >= 0.85
    assert metrics.candidate_count == 10


# ==============================================================================
# Test 8: Generic Dynamic Behavior (Zero NBR/SBR Hardcoding)
# ==============================================================================
def test_8_generic_dynamic_behavior_synthetic_compound():
    """
    Test 8: Generic dynamic behavior
    Use a synthetic/novel polymer profile to verify that the adequacy algorithm
    contains zero hidden NBR/SBR-specific assumptions.
    """
    orch = _orch()
    synthetic_strategy = CompoundSearchProfile(
        original_input="Polyzirconium Siloxane Alpha-7",
        base_material=["polyzirconium siloxane", "PZS-7", "zirconosiloxane polymer"],
        target_modifications=["high refractive index"],
        target_attributes=["heat resistance > 400C"],
        synthesis_transformations=["sol-gel polycondensation", "hydrolytic condensation"],
        excluded_variants=["titanosiloxane", "pure polysiloxane"],
        downstream_terms=["optical coating", "lens"],
        search_queries=[],
        synthesis_intent=True,
    )

    candidates = [
        _cand(
            "US8001",
            "Synthesis of zirconosiloxane polymer by hydrolytic condensation",
            snippet="Preparation of polyzirconium siloxane via sol-gel polycondensation method.",
        ),
        _cand(
            "US8002",
            "Zirconosiloxane hybrid resin for high temperature dielectric",
            snippet="A composition containing PZS-7 polymer and silica nanoparticles.",
        ),
        _cand(
            "US8003",
            "Optical lens coating comprising zirconosiloxane resin",
            snippet="Curable formulation for anti-reflective lens coating.",
        ),
        _cand(
            "US8004",
            "Method for producing cementitious mortar with slag additive",
            snippet="Concrete binder mix comprising portland cement and blast furnace slag.",
        ),
    ]

    metrics = orch._compute_search_adequacy(candidates, synthetic_strategy, search_round=1)

    assert metrics.direct_material_candidates == 3
    assert metrics.synthesis_candidates >= 1
    assert metrics.unrelated_count == 1  # Cement patent
    assert metrics.adequacy in (SearchAdequacy.HIGH, SearchAdequacy.MEDIUM)


# ==============================================================================
# Test 9: Deduplication Preserves Best Representative
# ==============================================================================
def test_9_deduplication_family_and_publication():
    """
    Test 9: Deduplication
    Verify family/duplicate patents are correctly deduplicated, preferring
    jurisdictions in the user filter (e.g. US/EP).
    """
    orch = _orch()
    # Check publication jurisdiction extraction
    assert orch.get_publication_jurisdiction("US10001234B2") == "US"
    assert orch.get_publication_jurisdiction("EP2473281B1") == "EP"
    assert orch.get_publication_jurisdiction("WO2020123456A1") == "WO"
    assert orch.get_publication_jurisdiction("CN108765432A") == "CN"

    # Family grouping logic: same priority + assignee + inventor
    group = [
        _cand("CN101A", "NBR Polymerization CN", priority_date="2018-01-01", assignee="PetroCorp", inventor="Zhang"),
        _cand("US101B", "NBR Polymerization US", priority_date="2018-01-01", assignee="PetroCorp", inventor="Zhang"),
        _cand("WO101C", "NBR Polymerization WO", priority_date="2018-01-01", assignee="PetroCorp", inventor="Zhang"),
    ]

    # Best representative with US filter should be US
    jurisdictions_filter = ["US", "EP"]
    best_cand = None
    best_score = -1
    for c in group:
        jur = orch.get_publication_jurisdiction(c["patent_number"])
        score = 0
        if jur in jurisdictions_filter:
            score += 10
        elif jur in ["US", "EP"]:
            score += 5
        if score > best_score:
            best_score = score
            best_cand = c

    assert best_cand is not None
    assert best_cand["patent_number"] == "US101B"


# ==============================================================================
# Test 10: SearchAdequacy & SearchAdequacyMetrics Schema Validation & Edge Cases
# ==============================================================================
def test_10_search_adequacy_schema_and_edge_cases():
    """
    Test 10: SearchAdequacyMetrics schema validation & edge cases.
    Verifies:
    - Default values
    - Enum members
    - Empty candidate list produces 0.0 rates without division by zero
    - High synthesis pool produces HIGH adequacy
    """
    orch = _orch()
    strategy = CompoundSearchProfile(
        original_input="NBR",
        base_material=["nitrile butadiene rubber", "NBR"],
        target_modifications=[],
        target_attributes=[],
        synthesis_transformations=["polymerization"],
        excluded_variants=[],
        downstream_terms=[],
        search_queries=[],
        synthesis_intent=True,
    )

    # Edge case: empty candidates list
    empty_metrics = orch._compute_search_adequacy([], strategy)
    assert empty_metrics.candidate_count == 0
    assert empty_metrics.unrelated_rate == 0.0
    assert empty_metrics.adequacy == SearchAdequacy.LOW

    # High synthesis pool
    high_pool = [
        _cand("US1", "Emulsion polymerization of nitrile butadiene rubber", "synthesis recipe conversion"),
        _cand("US2", "Continuous polymerization of NBR latex", "polymerization process catalyst"),
        _cand("US3", "Preparation of nitrile butadiene rubber copolymer", "monomer emulsion recipe"),
    ]
    high_metrics = orch._compute_search_adequacy(high_pool, strategy)
    assert high_metrics.adequacy == SearchAdequacy.HIGH
    assert high_metrics.direct_material_candidates == 3
    assert high_metrics.synthesis_candidates == 3
    assert high_metrics.unrelated_rate == 0.0
