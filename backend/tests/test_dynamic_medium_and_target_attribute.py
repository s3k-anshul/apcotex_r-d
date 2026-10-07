"""
Regression: dynamic Medium & Water Role + strategy-derived target attribute
on the report-generation path (selected evidence → report input → structured output).

Uses generic synthetic compounds only (Example Polymer X / Zephyr Elastomer Z).
Does not loosen selection or run live patent APIs.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.pipeline.report_service import (
    ReportService,
    resolve_target_attribute_label,
    _NO_WATER_SUMMARY,
    _NOT_DISCLOSED_VALUE,
)
from app.services.pipeline.schemas import (
    DynamicTargetAttributeEvidence,
    LLMPatentAnalysis,
    LLMPatentResearchReport,
    MediumAndWaterRoleEvidence,
    ReportPatentEvidence,
)
from app.services.prompts.patent_prompts import (
    REPORT_GENERATION_SYSTEM_PROMPT,
    REPORT_GENERATION_USER_TEMPLATE,
)


def _evidence(pn: str, source_text: str, title: str = "Synthetic patent") -> ReportPatentEvidence:
    return ReportPatentEvidence(
        patent_number=pn,
        title=title,
        jurisdiction=pn[:2],
        assignee="Example Polymer GmbH",
        publication_year="2020",
        url=f"https://patents.google.com/patent/{pn}",
        source_text=source_text,
        relevance_tier="PRIMARY",
        relevance_score=100.0,
    )


def _analysis(
    pn: str,
    *,
    medium: MediumAndWaterRoleEvidence,
    target: DynamicTargetAttributeEvidence,
) -> LLMPatentAnalysis:
    return LLMPatentAnalysis(
        patent_number=pn,
        synthesis_method="Synthetic polymerization process",
        disclosed_parameters=[],
        example_highlights=["Example 1: synthetic demonstration"],
        technical_relevance="Relevant to Example Polymer X",
        medium_and_water_role=medium,
        target_attribute=target,
    )


def test_resolve_target_attribute_label_priority():
    assert (
        resolve_target_attribute_label(
            attribute_constraint="Example Unit Content",
            research_profile={"target_attributes": ["Other Label"]},
        )
        == "Example Unit Content"
    )
    assert (
        resolve_target_attribute_label(
            attribute_constraint=None,
            research_profile={"target_attributes": ["Zephyr Unit Incorporation"]},
        )
        == "Zephyr Unit Incorporation"
    )
    assert (
        resolve_target_attribute_label(
            attribute_constraint="None",
            research_profile='{"target_attributes":["Example Unit Content"]}',
        )
        == "Example Unit Content"
    )
    assert resolve_target_attribute_label(None, {}) == "Target Attribute"


def test_report_prompts_require_medium_and_dynamic_attribute():
    sys_prompt = REPORT_GENERATION_SYSTEM_PROMPT.format(compound_name="Example Polymer X")
    assert "medium_and_water_role" in sys_prompt
    assert "TARGET ATTRIBUTE LABEL" in REPORT_GENERATION_USER_TEMPLATE or "{target_attribute_label}" in REPORT_GENERATION_USER_TEMPLATE
    assert "Not disclosed in extracted evidence" in sys_prompt
    assert _NO_WATER_SUMMARY in sys_prompt
    user = REPORT_GENERATION_USER_TEMPLATE.format(
        compound_name="Example Polymer X",
        original_input="Example Polymer X",
        research_profile='{"target_attributes":["Example Unit Content"]}',
        extractions_data="PATENT: US8001",
        patent_manifest="1. US8001",
        primary_count=1,
        patent_count=1,
        target_attribute_label="Example Unit Content",
        attribute_constraint="None",
    )
    assert "Example Unit Content" in user
    assert "TARGET ATTRIBUTE LABEL" in user


@pytest.mark.asyncio
async def test_solvent_patent_water_role_and_dynamic_attribute():
    """Tests 1–3: solvent core medium + downstream water; dynamic attribute value."""
    evidence = [
        _evidence(
            "US8001",
            source_text=(
                "Polymerization of Example Polymer X is performed in organic solvent X. "
                "After polymerization the polymer is contacted with water for washing "
                "and steam stripping. Example Unit Content = 14–18 wt%."
            ),
            title="Solution polymerization of Example Polymer X",
        )
    ]
    llm = LLMPatentResearchReport(
        title="EPX Report",
        abstract="Abstract",
        per_patent_analysis=[
            _analysis(
                "US8001",
                medium=MediumAndWaterRoleEvidence(
                    core_reaction_medium="organic solvent X; solution polymerization",
                    water_present=True,
                    water_roles=["washing", "steam_stripping", "post-treatment"],
                    summary=(
                        "Solution polymerization in organic solvent X; water is used later "
                        "for washing/steam stripping and is not the polymerization medium."
                    ),
                    evidence=["polymerization ... in organic solvent X", "contacted with water for washing"],
                ),
                target=DynamicTargetAttributeEvidence(
                    label="Example Unit Content",
                    value="14–18 wt%",
                    status="direct",
                    material_context="Example Polymer X",
                    belongs_to_target=True,
                    evidence=["Example Unit Content = 14–18 wt%"],
                ),
            )
        ],
        cross_patent_comparison=[],
        conclusion="done",
        references=["US8001"],
    )
    captured = {}

    async def _capture(*args, **kwargs):
        captured["prompt"] = kwargs.get("prompt") or (args[0] if args else "")
        captured["system_prompt"] = kwargs.get("system_prompt", "")
        return llm, "mock", {"input_tokens": 10, "output_tokens": 5}

    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_capture),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Example Polymer X",
            extractions=evidence,
            patent_manifest=["US8001"],
            original_input="Example Polymer X",
            research_profile='{"target_attributes":["Example Unit Content"],"base_material":["Example Polymer X"]}',
        )

    assert "TARGET ATTRIBUTE LABEL" in captured["prompt"]
    assert "Example Unit Content" in captured["prompt"]
    assert "medium_and_water_role" in captured["system_prompt"]

    patent = report.methodology_patents[0]
    assert patent.medium_and_water_role is not None
    summary = patent.medium_and_water_role.summary.lower()
    assert "solvent" in summary or "solution" in summary
    assert "aqueous" not in summary.split("not")[0] or "not the polymerization medium" in summary
    assert "not the polymerization medium" in summary or "steam" in summary or "washing" in summary

    assert patent.target_attribute.label == "Example Unit Content"
    assert patent.target_attribute.value == "14–18 wt%"
    assert patent.target_attribute.status == "direct"

    params = patent.polymerization_method.dynamic_parameters
    assert not any(p.startswith("Medium & Water Role:") for p in params)
    assert not any(p.startswith("Example Unit Content:") for p in params)

    assert report.dynamic_target_attribute_label == "Example Unit Content"
    dim_names = [d.parameter_name for d in report.comparison_dimensions]
    assert "Medium & Water Role" in dim_names
    assert "Example Unit Content" in dim_names

    md = ReportService().report_to_markdown(report)
    assert "Medium & Water Role" in md
    assert "Example Unit Content" in md
    assert "14–18 wt%" in md


@pytest.mark.asyncio
async def test_no_water_and_missing_target_attribute():
    """Tests 4–5: explicit no-water summary + not disclosed attribute."""
    evidence = [
        _evidence(
            "US8002",
            source_text=(
                "Bulk polymerization of Zephyr Elastomer Z under inert atmosphere. "
                "No aqueous or solvent workup steps are described in this excerpt."
            ),
            title="Bulk polymerization of Zephyr Elastomer Z",
        )
    ]
    llm = LLMPatentResearchReport(
        title="ZEZ Report",
        abstract="Abstract",
        per_patent_analysis=[
            _analysis(
                "US8002",
                medium=MediumAndWaterRoleEvidence(
                    core_reaction_medium="bulk polymerization",
                    water_present=False,
                    water_roles=[],
                    summary=_NO_WATER_SUMMARY,
                    evidence=[],
                ),
                target=DynamicTargetAttributeEvidence(
                    label="Zephyr Unit Incorporation",
                    value=_NOT_DISCLOSED_VALUE,
                    status="not_found",
                    evidence=[],
                ),
            )
        ],
        cross_patent_comparison=[],
        conclusion="done",
        references=["US8002"],
    )
    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Zephyr Elastomer Z",
            extractions=evidence,
            patent_manifest=["US8002"],
            research_profile='{"target_attributes":["Zephyr Unit Incorporation"]}',
            attribute_constraint=None,
        )

    patent = report.methodology_patents[0]
    assert patent.medium_and_water_role.summary == _NO_WATER_SUMMARY
    assert patent.medium_and_water_role.water_present is False
    assert patent.target_attribute.label == "Zephyr Unit Incorporation"
    assert patent.target_attribute.value == _NOT_DISCLOSED_VALUE
    assert patent.target_attribute.status == "not_found"
    assert patent.target_attribute.value.lower() not in ("", "unknown", "null")


@pytest.mark.asyncio
async def test_per_patent_isolation_no_cross_bleed():
    """Test 6: Patent B must not inherit Patent A's water role or attribute value."""
    evidence = [
        _evidence(
            "US9001",
            source_text=(
                "Polymerization in organic solvent X. Later washed with water. "
                "Example Unit Content = 14–18 wt%."
            ),
        ),
        _evidence(
            "US9002",
            source_text=(
                "Emulsion polymerization in aqueous medium for Example Polymer X. "
                "No Example Unit Content value is stated."
            ),
        ),
    ]
    llm = LLMPatentResearchReport(
        title="Isolation Report",
        abstract="Abstract",
        per_patent_analysis=[
            _analysis(
                "US9001",
                medium=MediumAndWaterRoleEvidence(
                    core_reaction_medium="organic solvent X",
                    water_present=True,
                    water_roles=["washing"],
                    summary="Solvent polymerization; water used only for washing.",
                    evidence=["organic solvent X"],
                ),
                target=DynamicTargetAttributeEvidence(
                    label="Example Unit Content",
                    value="14–18 wt%",
                    status="direct",
                    material_context="Example Polymer X",
                    belongs_to_target=True,
                    evidence=["14–18 wt%"],
                ),
            ),
            _analysis(
                "US9002",
                medium=MediumAndWaterRoleEvidence(
                    core_reaction_medium="aqueous emulsion",
                    water_present=True,
                    water_roles=["polymerization_medium", "emulsion/latex"],
                    summary="Aqueous emulsion polymerization; water is part of the polymerization medium.",
                    evidence=["Emulsion polymerization in aqueous medium"],
                ),
                target=DynamicTargetAttributeEvidence(
                    label="Example Unit Content",
                    value=_NOT_DISCLOSED_VALUE,
                    status="not_found",
                    belongs_to_target=False,
                    evidence=[],
                ),
            ),
        ],
        cross_patent_comparison=["A is solvent; B is aqueous emulsion"],
        conclusion="done",
        references=["US9001", "US9002"],
    )
    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Example Polymer X",
            extractions=evidence,
            patent_manifest=["US9001", "US9002"],
            research_profile='{"target_attributes":["Example Unit Content"]}',
        )

    by_pn = {p.patent_details.patent_number: p for p in report.methodology_patents}
    assert by_pn["US9001"].target_attribute.value == "14–18 wt%"
    assert by_pn["US9002"].target_attribute.value == _NOT_DISCLOSED_VALUE
    assert "14–18" not in by_pn["US9002"].target_attribute.value
    assert "solvent" in by_pn["US9001"].medium_and_water_role.summary.lower()
    assert "aqueous emulsion" in by_pn["US9002"].medium_and_water_role.summary.lower()
    assert by_pn["US9001"].medium_and_water_role.summary != by_pn["US9002"].medium_and_water_role.summary

    # Comparison table cells remain isolated
    attr_dim = next(d for d in report.comparison_dimensions if d.parameter_name == "Example Unit Content")
    assert attr_dim.values["US9001"] == "14–18 wt%"
    assert attr_dim.values["US9002"] == _NOT_DISCLOSED_VALUE


@pytest.mark.asyncio
async def test_empty_llm_fields_get_explicit_defaults():
    """Empty/unknown LLM medium or attribute must not remain null/unknown."""
    evidence = [_evidence("US9101", source_text="Generic process description without water.")]
    llm = LLMPatentResearchReport(
        title="Defaults",
        abstract="Abstract",
        per_patent_analysis=[
            LLMPatentAnalysis(
                patent_number="US9101",
                synthesis_method="process",
                disclosed_parameters=[],
                example_highlights=[],
                technical_relevance="relevant",
                medium_and_water_role=MediumAndWaterRoleEvidence(summary="unknown"),
                target_attribute=DynamicTargetAttributeEvidence(label="", value="", status=""),
            )
        ],
        cross_patent_comparison=[],
        conclusion="done",
        references=["US9101"],
    )
    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Example Polymer X",
            extractions=evidence,
            patent_manifest=["US9101"],
            research_profile='{"target_attributes":["Example Unit Content"]}',
        )

    patent = report.methodology_patents[0]
    assert patent.medium_and_water_role.summary == _NO_WATER_SUMMARY
    assert patent.target_attribute.label == "Example Unit Content"
    assert patent.target_attribute.value == _NOT_DISCLOSED_VALUE


@pytest.mark.asyncio
async def test_attribute_constraint_overrides_strategy_list():
    evidence = [_evidence("US9201", source_text="Example Unit Content = 12 mol%.")]
    llm = LLMPatentResearchReport(
        title="Constraint",
        abstract="Abstract",
        per_patent_analysis=[
            _analysis(
                "US9201",
                medium=MediumAndWaterRoleEvidence(summary=_NO_WATER_SUMMARY),
                target=DynamicTargetAttributeEvidence(
                    label="Wrong",
                    value="12 mol%",
                    status="direct",
                    material_context="Zephyr Elastomer Z",
                    belongs_to_target=True,
                ),
            )
        ],
        cross_patent_comparison=[],
        conclusion="done",
        references=["US9201"],
    )
    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Zephyr Elastomer Z",
            extractions=evidence,
            patent_manifest=["US9201"],
            research_profile='{"target_attributes":["Ignored Attribute"]}',
            attribute_constraint="Zephyr Unit Incorporation",
        )

    assert report.dynamic_target_attribute_label == "Zephyr Unit Incorporation"
    assert report.methodology_patents[0].target_attribute.label == "Zephyr Unit Incorporation"
    assert report.methodology_patents[0].target_attribute.value == "12 mol%"
