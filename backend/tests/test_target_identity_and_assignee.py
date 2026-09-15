"""
Regression: dynamic target identity, property ownership, assignee metadata.

Uses strategy-driven selection (no production compound hardcoding).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.research_run import ResearchRun
from app.services.pipeline import orchestrator as orch_mod
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.pipeline.report_service import (
    ReportService,
    _normalize_target_attribute,
    _NOT_DISCLOSED_VALUE,
)
from app.services.pipeline.schemas import (
    DynamicTargetAttributeEvidence,
    LLMPatentAnalysis,
    LLMPatentResearchReport,
    MediumAndWaterRoleEvidence,
    PatentSelectionCandidate,
    PatentSelectionResult,
    ReportPatentEvidence,
    SelectionDecision,
    TargetRelationship,
    TechnicalCentrality,
    TitleTriageClassification,
)


def _orch() -> PipelineOrchestrator:
    o = PipelineOrchestrator.__new__(PipelineOrchestrator)
    o.run_id = "test-run"
    o.search_service = MagicMock()
    o.fetcher_service = MagicMock()
    o.extractor_service = MagicMock()
    o.report_service = MagicMock()
    o._reset_filter_stats()
    return o


def _run(compound: str = "Example Polymer X") -> ResearchRun:
    return ResearchRun(
        id="00000000-0000-0000-0000-000000000001",
        compound_name=compound,
        jurisdictions=["US", "EP"],
        status="FILTERING",
    )


def _cand(number: str, title: str, snippet: str = "", assignee: str = "") -> dict:
    return {
        "patent_number": number,
        "title": title,
        "snippet": snippet,
        "url": f"https://patents.google.com/patent/{number}",
        "assignee": assignee,
        "publication_date": "2020-01-01",
        "selection_evidence_sources": ["title", "snippet"],
    }


def _strategy_epx():
    from app.services.pipeline.schemas import LLMCompoundSearchProfile

    return LLMCompoundSearchProfile(
        original_input="Example Polymer X",
        base_material=["Example Polymer X", "EPX"],
        target_modifications=[],
        target_attributes=["Example Unit Content"],
        identity_exclusions=["Example Block Copolymer Y", "EBCY"],
        related_materials=["Example Block Copolymer Y"],
        relevance_definition=(
            "PRIMARY_TARGET only when the invention is about preparing or modifying "
            "Example Polymer X itself, not when EPX appears only as a segment/component."
        ),
        excluded_variants=[],
        search_queries=[],
    )


def _verdict(
    number: str,
    decision: SelectionDecision,
    *,
    relationship: TargetRelationship = TargetRelationship.PRIMARY_TARGET,
    detected: str = "Example Polymer X",
    retain_related: bool = False,
    classification: TitleTriageClassification = TitleTriageClassification.DIRECT_SYNTHESIS,
    centrality: TechnicalCentrality = TechnicalCentrality.CENTRAL,
    downstream_only: bool = False,
    reason: str = "fixture",
) -> PatentSelectionCandidate:
    return PatentSelectionCandidate(
        patent_number=number,
        classification=classification,
        variant_mismatch=False,
        polymerization_medium_mismatch=False,
        final_decision=decision,
        confidence=0.9,
        reason=reason,
        technical_centrality=centrality,
        target_relationship=relationship,
        detected_primary_material=detected,
        retain_as_related=retain_related,
        downstream_only=downstream_only,
        evidence_strength=0.9 if decision == SelectionDecision.KEEP else 0.2,
        evidence=["fixture"],
    )


@pytest.mark.asyncio
async def test_primary_vs_related_target_identity_not_keyword_match():
    """
    Patent A: true EPX synthesis → PRIMARY KEEP.
    Patent B: larger block system containing EPX segment → RELATED, not primary.
    """
    orch = _orch()
    candidates = [
        _cand("US8001", "Process for preparing Example Polymer X"),
        _cand(
            "US8002",
            "Example Block Copolymer Y containing an Example Polymer X segment",
            snippet="A triblock architecture where EPX is one segment of EBCY.",
        ),
    ]
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US8001",
                SelectionDecision.KEEP,
                relationship=TargetRelationship.PRIMARY_TARGET,
                detected="Example Polymer X",
            ),
            _verdict(
                "US8002",
                SelectionDecision.REJECT,
                relationship=TargetRelationship.RELATED_TARGET,
                detected="Example Block Copolymer Y",
                retain_related=True,
                classification=TitleTriageClassification.POLYMER_STRUCTURE,
                centrality=TechnicalCentrality.PARTIAL,
                reason="EPX appears only as a segment of a different polymer system",
            ),
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            candidates, _strategy_epx(), _run("Example Polymer X")
        )

    assert [c["patent_number"] for c in selected] == ["US8001"]
    related = getattr(orch, "_related_candidates", [])
    assert [c["patent_number"] for c in related] == ["US8002"]
    assert related[0]["selection_target_relationship"] == "RELATED_TARGET"


@pytest.mark.asyncio
async def test_keep_without_primary_relationship_is_demoted():
    """Soft demotion: LLM KEEP + RELATED_TARGET must not enter primary manifest."""
    orch = _orch()
    candidates = [
        _cand("US9624", "Graft copolymer system mentioning Example Polymer X"),
    ]
    llm = PatentSelectionResult(
        candidates=[
            _verdict(
                "US9624",
                SelectionDecision.KEEP,  # incorrect KEEP
                relationship=TargetRelationship.RELATED_TARGET,
                detected="Graft copolymer / adjacent system",
                retain_related=True,
            )
        ]
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        selected = await orch._select_patents_via_llm(
            candidates, _strategy_epx(), _run("Example Polymer X")
        )

    assert selected == []
    assert [c["patent_number"] for c in orch._related_candidates] == ["US9624"]


def test_property_ownership_blocks_non_target_values():
    """Styrene-like value on wrong material must not attach to requested target attribute."""
    owned = _normalize_target_attribute(
        DynamicTargetAttributeEvidence(
            label="Example Unit Content",
            value="14–18 wt%",
            status="direct",
            material_context="Example Polymer X",
            belongs_to_target=True,
            evidence=["Example Unit Content = 14–18 wt%"],
        ),
        "Example Unit Content",
    )
    assert owned.value == "14–18 wt%"
    assert owned.belongs_to_target is True

    leaked = _normalize_target_attribute(
        DynamicTargetAttributeEvidence(
            label="Example Unit Content",
            value="21 wt%",
            status="direct",
            material_context="Example Block Copolymer Y styrene phase",
            belongs_to_target=False,
            evidence=["styrene = 21 wt% in EBCY"],
        ),
        "Example Unit Content",
    )
    assert leaked.value == _NOT_DISCLOSED_VALUE
    assert leaked.belongs_to_target is False
    assert leaked.status == "not_found"


@pytest.mark.asyncio
async def test_sbr_like_dynamic_attribute_when_owned():
    """Low-Styrene SBR-style: strategy label + owned styrene value on primary patent."""
    evidence = [
        ReportPatentEvidence(
            patent_number="US8100",
            title="Low-styrene Example Polymer X",
            jurisdiction="US",
            assignee="Example Corporation",
            publication_year="2019",
            url="https://patents.google.com/patent/US8100",
            source_text="Example Polymer X with Example Unit Content = 15 wt%.",
        )
    ]
    llm = LLMPatentResearchReport(
        title="Report",
        abstract="Abstract",
        per_patent_analysis=[
            LLMPatentAnalysis(
                patent_number="US8100",
                synthesis_method="emulsion polymerization",
                disclosed_parameters=["Temperature: 5C"],
                example_highlights=["Ex1"],
                technical_relevance="primary",
                medium_and_water_role=MediumAndWaterRoleEvidence(
                    summary="Aqueous emulsion; water is polymerization medium.",
                    water_present=True,
                    water_roles=["polymerization_medium"],
                ),
                target_attribute=DynamicTargetAttributeEvidence(
                    label="Example Unit Content",
                    value="15 wt%",
                    status="direct",
                    material_context="Example Polymer X",
                    belongs_to_target=True,
                    evidence=["Example Unit Content = 15 wt%"],
                ),
            )
        ],
        cross_patent_comparison=[],
        conclusion="done",
        references=["US8100"],
    )
    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Low-Unit Example Polymer X",
            extractions=evidence,
            patent_manifest=["US8100"],
            research_profile='{"target_attributes":["Example Unit Content"],"base_material":["Example Polymer X"]}',
        )

    p = report.methodology_patents[0]
    assert p.target_attribute.label == "Example Unit Content"
    assert p.target_attribute.value == "15 wt%"
    assert p.target_attribute.belongs_to_target is True
    assert p.patent_details.assignee == "Example Corporation"


@pytest.mark.asyncio
async def test_xnbr_like_arbitrary_target_uses_strategy_not_hardcode():
    """Carboxylated Zephyr Elastomer Z — identity fields flow into selection prompt."""
    orch = _orch()
    captured = {}

    async def _capture(**kwargs):
        captured["prompt"] = kwargs.get("prompt", "")
        return (
            PatentSelectionResult(
                candidates=[
                    _verdict(
                        "US8200",
                        SelectionDecision.KEEP,
                        detected="Carboxylated Zephyr Elastomer Z",
                    )
                ]
            ),
            "mock",
            {},
        )

    from app.services.pipeline.schemas import LLMCompoundSearchProfile

    strategy = LLMCompoundSearchProfile(
        original_input="Carboxylated Zephyr Elastomer Z",
        base_material=["Zephyr Elastomer Z", "ZEZ"],
        target_modifications=["carboxylated", "carboxylation"],
        target_attributes=["Carboxyl Content"],
        identity_exclusions=["Uncarboxylated Zephyr"],
        related_materials=["Zephyr blend systems"],
        relevance_definition="PRIMARY when invention concerns carboxylated ZEZ itself.",
        search_queries=[],
    )
    with patch(
        "app.services.pipeline.orchestrator.llm_client.generate_structured",
        new=AsyncMock(side_effect=_capture),
    ):
        selected = await orch._select_patents_via_llm(
            [_cand("US8200", "Carboxylation of Zephyr Elastomer Z")],
            strategy,
            _run("Carboxylated Zephyr Elastomer Z"),
        )

    assert selected[0]["patent_number"] == "US8200"
    assert "Carboxylated Zephyr Elastomer Z" in captured["prompt"]
    assert "Uncarboxylated Zephyr" in captured["prompt"]
    assert "PRIMARY_TARGET" in captured["prompt"]
    assert "IDENTITY" in captured["prompt"].upper() or "Identity Exclusions" in captured["prompt"]


@pytest.mark.asyncio
async def test_assignee_preserved_from_candidate_through_fetch_extract():
    orch = _orch()
    parsed = MagicMock()
    parsed.assignee = ""
    parsed.title = ""
    parsed.metadata = {}
    parsed.patent_number = "US123"
    orch.fetcher_service.fetch_patent = AsyncMock(return_value=parsed)

    ext = MagicMock()
    ext.metadata = MagicMock()
    ext.metadata.patent_number = "US123"
    ext.metadata.patent_title = "Title"
    ext.metadata.assignee = "Not disclosed"
    orch.extractor_service.extract_polymerization_data = AsyncMock(return_value=ext)
    orch.extractor_service.validate_extraction = MagicMock(return_value=True)

    cand = _cand("US123", "Title", assignee="Example Corporation")
    with patch.object(orch_mod.asyncio, "sleep", new=AsyncMock(return_value=None)):
        extractions, _ = await orch._fetch_and_extract_selected([cand], _strategy_epx())

    assert len(extractions) == 1
    assert extractions[0].metadata.assignee == "Example Corporation"
    assert parsed.assignee == "Example Corporation"


@pytest.mark.asyncio
async def test_missing_assignee_allows_not_disclosed():
    orch = _orch()
    parsed = MagicMock()
    parsed.assignee = ""
    parsed.title = "T"
    parsed.metadata = {}
    parsed.patent_number = "US124"
    orch.fetcher_service.fetch_patent = AsyncMock(return_value=parsed)

    ext = MagicMock()
    ext.metadata = MagicMock()
    ext.metadata.patent_number = "US124"
    ext.metadata.patent_title = "T"
    ext.metadata.assignee = "Not disclosed"
    orch.extractor_service.extract_polymerization_data = AsyncMock(return_value=ext)
    orch.extractor_service.validate_extraction = MagicMock(return_value=True)

    with patch.object(orch_mod.asyncio, "sleep", new=AsyncMock(return_value=None)):
        extractions, _ = await orch._fetch_and_extract_selected(
            [_cand("US124", "T", assignee="")], _strategy_epx()
        )

    assert extractions[0].metadata.assignee == "Not disclosed"


@pytest.mark.asyncio
async def test_llm_cannot_overwrite_authoritative_assignee_in_report():
    """Source evidence assignee wins; report mapping ignores absent LLM metadata."""
    evidence = [
        ReportPatentEvidence(
            patent_number="US125",
            title="Prep EPX",
            jurisdiction="US",
            assignee="Example Corporation",
            publication_year="2018",
            url="https://patents.google.com/patent/US125",
            source_text="Example Polymer X preparation.",
        )
    ]
    llm = LLMPatentResearchReport(
        title="Report",
        abstract="Abstract",
        per_patent_analysis=[
            LLMPatentAnalysis(
                patent_number="US125",
                synthesis_method="process",
                technical_relevance="ok",
                medium_and_water_role=MediumAndWaterRoleEvidence(
                    summary="No water-related process step disclosed in the extracted evidence."
                ),
                target_attribute=DynamicTargetAttributeEvidence(
                    label="Example Unit Content",
                    value="Not disclosed in extracted evidence",
                    status="not_found",
                    belongs_to_target=False,
                ),
            )
        ],
        references=["US125"],
    )
    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Example Polymer X",
            extractions=evidence,
            patent_manifest=["US125"],
            research_profile='{"target_attributes":["Example Unit Content"]}',
        )

    assert report.methodology_patents[0].patent_details.assignee == "Example Corporation"
    md = ReportService().report_to_markdown(report)
    assert "Example Corporation" in md
    assert "Assignee: Not disclosed" not in md


def test_integrity_drops_non_primary_from_manifest():
    orch = _orch()
    cleaned = orch._validate_primary_manifest_integrity(
        [
            {
                "patent_number": "US1",
                "selection_decision": "KEEP",
                "selection_target_relationship": "PRIMARY_TARGET",
            },
            {
                "patent_number": "US2",
                "selection_decision": "KEEP",
                "selection_target_relationship": "RELATED_TARGET",
            },
        ]
    )
    assert [c["patent_number"] for c in cleaned] == ["US1"]


def test_related_report_patents_helper_still_builds_entries_but_report_must_not_use_them():
    """Related retention may still be logged internally; reports must not render them."""
    orch = _orch()
    related = [
        {
            "patent_number": "US9002",
            "title": "Adjacent system",
            "assignee": "Related Co",
            "selection_reason": "RELATED_TARGET",
            "selection_detected_primary_material": "Adjacent polymer",
            "selection_target_relationship": "RELATED_TARGET",
        }
    ]
    patents = orch._build_related_report_patents(related)
    assert len(patents) == 1
    assert patents[0].patent_details.assignee == "Related Co"

    from app.services.pipeline.schemas import PatentResearchReport

    report = PatentResearchReport(
        title="t",
        abstract="a",
        methodology_patents=[],
        secondary_patents=patents,
        conclusion="c",
        references=[],
    )
    md = ReportService().report_to_markdown(report)
    assert "SUPPORTING / RELATED PATENTS" not in md.upper()
    assert "RELATED PATENTS (SECONDARY)" not in md.upper()
    assert "US9002" not in md
    assert "## 1. ABSTRACT" in md
    assert "## 2. METHODOLOGY" in md
    assert "## 3. CROSS-PATENT COMPARISON" in md
    assert "## 4. CONCLUSION" in md
    assert "## 5. REFERENCES" in md
