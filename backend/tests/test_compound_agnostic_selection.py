"""
tests/test_compound_agnostic_selection.py

Compound-agnostic, evidence-aware selection regression tests.
Uses synthetic materials only — no production hardcoding for any real polymer.
"""
import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.research_run import ResearchRun
from app.services.pipeline import orchestrator as orch_mod
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.pipeline.report_service import ReportService
from app.services.pipeline.schemas import (
    CompoundSearchProfile,
    LLMPatentAnalysis,
    LLMPatentResearchReport,
    PatentExtraction,
    PatentSelectionCandidate,
    PatentSelectionResult,
    ReportPatentEvidence,
    SelectionDecision,
    TechnicalCentrality,
    TitleTriageClassification,
)


def _orch() -> PipelineOrchestrator:
    return PipelineOrchestrator(run_id=uuid.uuid4())


def _strategy_polymer_x() -> CompoundSearchProfile:
    return CompoundSearchProfile(
        original_input="Example Polymer X",
        base_material=["Example Polymer X", "EPX", "poly-example-x"],
        target_modifications=[],
        target_attributes=["low branching"],
        synthesis_transformations=["polymerization", "preparation"],
        excluded_variants=["Hydrogenated Example Polymer X", "HEP-X"],
        downstream_terms=["seal", "coating", "article"],
        search_queries=[],
        synthesis_intent=True,
    )


def _strategy_polymer_z() -> CompoundSearchProfile:
    return CompoundSearchProfile(
        original_input="Zephyr Elastomer Z",
        base_material=["Zephyr Elastomer Z", "ZEZ"],
        target_modifications=["carboxylated"],
        target_attributes=["high modulus"],
        synthesis_transformations=["carboxylation", "emulsion polymerization"],
        excluded_variants=["Uncarboxylated Zephyr", "ZEZ-U"],
        downstream_terms=["hose", "belt"],
        search_queries=[],
        synthesis_intent=True,
    )


def _run(compound: str = "Example Polymer X", **kwargs) -> ResearchRun:
    defaults = {
        "compound_name": compound,
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


def _cand(number: str, title: str, **extra) -> dict:
    base = {
        "patent_number": number,
        "title": title,
        "snippet": extra.pop("snippet", ""),
        "url": f"https://patents.google.com/patent/{number}",
        "assignee": "",
        "publication_date": "2018-01-01",
        "selection_evidence_sources": ["title", "snippet"],
    }
    base.update(extra)
    return base


def _verdict(
    number: str,
    decision: SelectionDecision,
    classification: TitleTriageClassification = TitleTriageClassification.DIRECT_SYNTHESIS,
    **kwargs,
) -> PatentSelectionCandidate:
    if 'medium_mismatch' in kwargs:
        kwargs['polymerization_medium_mismatch'] = kwargs.pop('medium_mismatch')
    defaults = dict(
        patent_number=number,
        classification=classification,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=decision,
        confidence=0.9,
        reason="fixture",
        technical_centrality=TechnicalCentrality.CENTRAL,
        evidence_strength=0.85 if decision == SelectionDecision.KEEP else 0.0,
        downstream_only=False,
        evidence=["fixture evidence"],
    )
    defaults.update(kwargs)
    return PatentSelectionCandidate(**defaults)


def test_orchestrator_has_no_material_specific_branching():
    src = inspect.getsource(orch_mod)
    for needle in (
        'if compound == "HNBR"',
        'if "NBR" in compound',
        'if "styrene" in compound',
        "HNBR_SYNONYMS",
        "SBR_TERMS",
        "NBR_TERMS",
        "GENERIC_RELEVANCE_TERMS",
    ):
        assert needle not in src


@pytest.mark.asyncio
async def test_arbitrary_compound_strategy_flows_into_selection_prompt():
    orch = _orch()
    orch._reset_filter_stats()
    captured = {}

    async def fake_llm(*, prompt, **kwargs):
        captured["prompt"] = prompt
        return PatentSelectionResult(candidates=[]), "mock", {}

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(side_effect=fake_llm),
    ):
        await orch._select_patents_via_llm(
            [_cand("US1", "Preparation of Example Polymer X")],
            _strategy_polymer_x(),
            _run("Example Polymer X"),
        )

    assert "Example Polymer X" in captured["prompt"]
    assert "poly-example-x" in captured["prompt"]
    assert "HEP-X" in captured["prompt"]
    assert "Low Styrene SBR" not in captured["prompt"]


@pytest.mark.asyncio
async def test_different_compound_changes_strategy_in_prompt():
    orch = _orch()
    captured = {}

    async def fake_llm(*, prompt, **kwargs):
        captured["prompt"] = prompt
        return PatentSelectionResult(candidates=[]), "mock", {}

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(side_effect=fake_llm),
    ):
        await orch._select_patents_via_llm(
            [_cand("US2", "Carboxylation of Zephyr Elastomer Z")],
            _strategy_polymer_z(),
            _run("Zephyr Elastomer Z"),
        )

    assert "Zephyr Elastomer Z" in captured["prompt"]
    assert "carboxylation" in captured["prompt"].lower()
    assert "Example Polymer X" not in captured["prompt"]


@pytest.mark.asyncio
async def test_direct_synthesis_keep():
    orch = _orch()
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1001",
                SelectionDecision.KEEP,
                reason="Direct preparation of EPX",
                evidence=["Abstract: process for preparing Example Polymer X"],
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand(
                    "US1001",
                    "Process for preparing Example Polymer X",
                    abstract="A polymerization process for Example Polymer X with low branching.",
                )
            ],
            _strategy_polymer_x(),
            _run(),
        )
    assert [c["patent_number"] for c in selected] == ["US1001"]


@pytest.mark.asyncio
async def test_downstream_only_reject():
    orch = _orch()
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1002",
                SelectionDecision.REJECT,
                classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
                technical_centrality=TechnicalCentrality.NONE,
                downstream_only=True,
                reason="EPX is only a purchased ingredient in a seal",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand(
                    "US1002",
                    "Seal composition comprising Example Polymer X",
                    snippet="A finished seal using commercially available EPX.",
                )
            ],
            _strategy_polymer_x(),
            _run(),
        )
    assert selected == []
    assert orch._filter_stats["selection_reject_downstream"] == 1


@pytest.mark.asyncio
async def test_synthesis_plus_downstream_examples_can_keep():
    orch = _orch()
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1003",
                SelectionDecision.KEEP,
                technical_centrality=TechnicalCentrality.CENTRAL,
                downstream_only=False,
                reason="Central invention is EPX polymerization; coating is only an example use",
                evidence=["Claims: process for polymerizing Example Polymer X"],
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand(
                    "US1003",
                    "Coating composition and process for preparing Example Polymer X",
                    abstract="Discloses polymerization of EPX; coatings are optional application examples.",
                )
            ],
            _strategy_polymer_x(),
            _run(),
        )
    assert len(selected) == 1


@pytest.mark.asyncio
async def test_misleading_downstream_title_eligible_when_synthesis_central():
    orch = _orch()
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1004",
                SelectionDecision.KEEP,
                technical_centrality=TechnicalCentrality.CENTRAL,
                reason="Title mentions article but claims disclose EPX synthesis",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand(
                    "US1004",
                    "Industrial article containing rubber",
                    claims_excerpt="1. A process for preparing Example Polymer X by emulsion polymerization.",
                    abstract="The invention provides a synthesis route for EPX.",
                )
            ],
            _strategy_polymer_x(),
            _run(),
        )
    assert len(selected) == 1


@pytest.mark.asyncio
async def test_attribute_only_in_body_still_eligible():
    orch = _orch()
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1005",
                SelectionDecision.KEEP,
                target_match="MATCH",
                reason="Low branching disclosed in abstract, not title",
                evidence=["Abstract: branching index < 0.2"],
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand(
                    "US1005",
                    "Polymerization process for Example Polymer X",
                    abstract="Produces EPX with low branching suitable for the target grade.",
                )
            ],
            _strategy_polymer_x(),
            _run(attribute_constraint="low branching"),
        )
    assert len(selected) == 1


@pytest.mark.asyncio
async def test_target_as_ingredient_only_rejected():
    orch = _orch()
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US1006",
                SelectionDecision.REJECT,
                classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
                technical_centrality=TechnicalCentrality.PERIPHERAL,
                downstream_only=True,
                reason="EPX purchased and compounded; not synthesized",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US1006", "Adhesive blend including Example Polymer X")],
            _strategy_polymer_x(),
            _run(),
        )
    assert selected == []


@pytest.mark.asyncio
async def test_aqueous_polymerization_eligible():
    orch = _orch()
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US2001",
                SelectionDecision.KEEP,
                medium_match="MATCH",
                reason="Aqueous emulsion polymerization of EPX",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand(
                    "US2001",
                    "Aqueous emulsion polymerization of Example Polymer X",
                    abstract="Polymerization conducted in aqueous emulsion.",
                )
            ],
            _strategy_polymer_x(),
            _run(polymerization_medium="aqueous"),
        )
    assert len(selected) == 1


@pytest.mark.asyncio
async def test_water_for_workup_not_aqueous_polymerization_mismatch_path():
    orch = _orch()
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US2002",
                SelectionDecision.REJECT,
                polymerization_medium_mismatch=True,
                medium_match="MISMATCH",
                reason="Solution polymerization; water used only for washing",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [
                _cand(
                    "US2002",
                    "Solution polymerization of Example Polymer X",
                    abstract="Polymerized in hexane; product washed with water.",
                )
            ],
            _strategy_polymer_x(),
            _run(polymerization_medium="aqueous"),
        )
    assert selected == []
    assert orch._filter_stats["selection_reject_medium"] == 1


@pytest.mark.asyncio
async def test_solvent_request_rejects_clear_aqueous_route():
    orch = _orch()
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US2003",
                SelectionDecision.REJECT,
                polymerization_medium_mismatch=True,
                medium_match="MISMATCH",
                reason="Emulsion/aqueous primary medium vs solvent constraint",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US2003", "Emulsion polymerization of Example Polymer X")],
            _strategy_polymer_x(),
            _run(polymerization_medium="solvent"),
        )
    assert selected == []
    assert orch._filter_stats["selection_reject_medium"] == 1


@pytest.mark.asyncio
async def test_arbitrary_medium_terminology_is_strategy_prompted_not_hardcoded():
    orch = _orch()
    captured = {}

    async def fake_llm(*, prompt, **kwargs):
        captured["prompt"] = prompt
        return PatentSelectionResult(candidates=[]), "mock", {}

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(side_effect=fake_llm),
    ):
        await orch._select_patents_via_llm(
            [_cand("US2004", "Supercritical CO2 polymerization of Example Polymer X")],
            _strategy_polymer_x(),
            _run(polymerization_medium="solvent"),
        )

    assert "Polymerization Medium Constraint: solvent" in captured["prompt"]
    assert "role" in captured["prompt"].lower()
    assert "KNOWN_SOLVENTS" not in captured["prompt"]


@pytest.mark.asyncio
async def test_variant_mismatch_from_strategy_exclusions():
    orch = _orch()
    orch._reset_filter_stats()
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                "US3001",
                SelectionDecision.REJECT,
                variant_mismatch=True,
                variant_match="MISMATCH",
                reason="HEP-X is excluded for Example Polymer X target",
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US3001", "Process for producing Hydrogenated Example Polymer X (HEP-X)")],
            _strategy_polymer_x(),
            _run(),
        )
    assert selected == []
    assert orch._filter_stats["selection_reject_variant"] == 1


@pytest.mark.asyncio
async def test_no_quota_padding_returns_only_relevant():
    orch = _orch()
    orch._reset_filter_stats()
    cands = [
        _cand("US4001", "Preparation of Example Polymer X"),
        _cand("US4002", "Another preparation of Example Polymer X"),
        _cand("US4003", "Unrelated water filter"),
        _cand("US4004", "Seal using purchased EPX"),
    ]
    result = PatentSelectionResult(
        candidates=[
            _verdict("US4001", SelectionDecision.KEEP),
            _verdict("US4002", SelectionDecision.KEEP),
            _verdict(
                "US4003",
                SelectionDecision.REJECT,
                classification=TitleTriageClassification.UNRELATED,
                technical_centrality=TechnicalCentrality.NONE,
            ),
            _verdict(
                "US4004",
                SelectionDecision.REJECT,
                classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
                downstream_only=True,
            ),
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            cands, _strategy_polymer_x(), _run(), max_keep=10
        )
    assert len(selected) == 2


@pytest.mark.asyncio
async def test_max_keep_ranks_strongest_not_first_encountered():
    orch = _orch()
    orch._reset_filter_stats()
    cands = [_cand(f"US5{i:03d}", f"Prep {i}") for i in range(15)]
    result = PatentSelectionResult(
        candidates=[
            _verdict(
                f"US5{i:03d}",
                SelectionDecision.KEEP,
                confidence=0.5 + i * 0.02,
                evidence_strength=0.4 + i * 0.02,
                technical_centrality=(
                    TechnicalCentrality.CENTRAL if i >= 10 else TechnicalCentrality.PARTIAL
                ),
            )
            for i in range(15)
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(result, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            cands, _strategy_polymer_x(), _run(), max_keep=10
        )
    nums = {c["patent_number"] for c in selected}
    assert len(selected) == 10
    assert "US5014" in nums
    assert "US5000" not in nums


@pytest.mark.asyncio
async def test_rejected_candidates_never_reach_full_fetch():
    orch = _orch()
    orch._reset_filter_stats()
    selected = [_cand("US6001", "Preparation of Example Polymer X")]
    fetched = []

    async def fake_fetch(url: str):
        fetched.append(url)
        from app.services.pipeline.schemas import ParsedPatent

        return ParsedPatent(
            patent_number="US6001",
            title="Preparation of Example Polymer X",
            url=url,
            abstract="x",
            claims="1. A process.",
        )

    orch.fetcher_service.fetch_patent = AsyncMock(side_effect=fake_fetch)
    orch.extractor_service.extract_polymerization_data = AsyncMock(
        return_value=PatentExtraction()
    )
    orch.extractor_service.validate_extraction = MagicMock(return_value=True)
    original_sleep = orch_mod.asyncio.sleep
    orch_mod.asyncio.sleep = AsyncMock(return_value=None)
    try:
        await orch._fetch_and_extract_selected(selected, _strategy_polymer_x())
    finally:
        orch_mod.asyncio.sleep = original_sleep
    assert all("US6999" not in u for u in fetched)
    assert fetched == ["https://patents.google.com/patent/US6001"]


@pytest.mark.asyncio
async def test_report_patent_ids_subset_of_selected_and_no_phantoms():
    evidence = [
        ReportPatentEvidence(
            patent_number="US7001",
            title="Prep EPX",
            jurisdiction="US",
            assignee="A",
            publication_year="2019",
            url="https://patents.google.com/patent/US7001",
            source_text="synthesis of Example Polymer X",
        ),
        ReportPatentEvidence(
            patent_number="US7002",
            title="Prep EPX 2",
            jurisdiction="US",
            assignee="B",
            publication_year="2020",
            url="https://patents.google.com/patent/US7002",
            source_text="another EPX route",
        ),
    ]
    llm = LLMPatentResearchReport(
        title="Report",
        abstract="Abstract",
        per_patent_analysis=[
            LLMPatentAnalysis(
                patent_number="US7001",
                synthesis_method="polymerization",
                disclosed_parameters=["T: 50C"],
                example_highlights=["Ex1"],
                technical_relevance="central",
            ),
            LLMPatentAnalysis(
                patent_number="US7002",
                synthesis_method="polymerization",
                disclosed_parameters=["T: 60C"],
                example_highlights=["Ex1"],
                technical_relevance="central",
            ),
            LLMPatentAnalysis(
                patent_number="US9999PHANTOM",
                synthesis_method="invented",
                disclosed_parameters=[],
                example_highlights=[],
                technical_relevance="should be ignored",
            ),
        ],
        cross_patent_comparison=["both synthesize EPX"],
        conclusion="done",
        references=["US7001", "US7002", "US9999PHANTOM"],
    )
    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {"input_tokens": 10, "output_tokens": 5})),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Example Polymer X",
            extractions=evidence,
            patent_manifest=["US7001", "US7002"],
            original_input="Example Polymer X",
            research_profile='{"base_material":["Example Polymer X"]}',
        )

    report_pns = {p.patent_details.patent_number for p in report.methodology_patents}
    assert report_pns == {"US7001", "US7002"}
    assert "US9999PHANTOM" not in report_pns
    assert "US9999PHANTOM" not in report.references
    assert set(report.references).issubset({"US7001", "US7002"})


def test_patent_evidence_objects_remain_isolated():
    a = ReportPatentEvidence(
        patent_number="US8001",
        title="A",
        jurisdiction="US",
        assignee="A",
        publication_year="2018",
        url="u1",
        source_text="UNIQUE_EVIDENCE_ALPHA_ONLY",
        technical_findings=["alpha finding"],
    )
    b = ReportPatentEvidence(
        patent_number="US8002",
        title="B",
        jurisdiction="US",
        assignee="B",
        publication_year="2019",
        url="u2",
        source_text="UNIQUE_EVIDENCE_BETA_ONLY",
        technical_findings=["beta finding"],
    )
    assert "ALPHA" not in b.source_text
    assert "BETA" not in a.source_text
    assert a.technical_findings != b.technical_findings


@pytest.mark.asyncio
async def test_enrichment_uses_lightweight_metadata_not_full_fetch():
    orch = _orch()
    cands = [_cand("US9001", "Prep EPX")]
    orch.fetcher_service.fetch_selection_evidence = AsyncMock(
        return_value={
            "url": cands[0]["url"],
            "patent_number": "US9001",
            "title": "Prep EPX",
            "abstract": "Abstract about preparing Example Polymer X.",
            "claims_excerpt": "1. A process for preparing Example Polymer X.",
            "assignee": "X Corp",
            "publication_date": "2018-01-01",
            "jurisdiction": "US",
            "legal_status": "Active",
            "cpc_ipc": [],
            "evidence_sources": ["title", "abstract", "claims"],
        }
    )
    orch.fetcher_service.fetch_patent = AsyncMock(
        side_effect=AssertionError("full fetch must not run during enrichment")
    )

    enriched = await orch._enrich_candidates_for_selection(
        cands, _strategy_polymer_x(), "Example Polymer X"
    )
    assert enriched[0]["abstract"].startswith("Abstract about preparing")
    assert "claims" in enriched[0]["selection_evidence_sources"]
    orch.fetcher_service.fetch_selection_evidence.assert_awaited()
    orch.fetcher_service.fetch_patent.assert_not_awaited()


@pytest.mark.asyncio
async def test_selection_prompt_includes_evidence_fields():
    orch = _orch()
    captured = {}

    async def fake_llm(*, prompt, **kwargs):
        captured["prompt"] = prompt
        return PatentSelectionResult(candidates=[]), "mock", {}

    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(side_effect=fake_llm),
    ):
        await orch._select_patents_via_llm(
            [
                _cand(
                    "US9002",
                    "Prep",
                    abstract="Abstract text here",
                    claims_excerpt="Claim 1 text here",
                    selection_evidence_sources=["title", "snippet", "abstract", "claims"],
                )
            ],
            _strategy_polymer_x(),
            _run(),
        )

    assert "Abstract text here" in captured["prompt"]
    assert "Claim 1 text here" in captured["prompt"]
    assert "technical_centrality" in captured["prompt"]
    assert "Do NOT assume the target is any particular polymer" in captured["prompt"]
