"""Report narrative checks and evidence reconciliation. Compound names here are fixtures only."""
from app.services.pipeline.orchestrator import prefer_source_title
from app.services.pipeline.report_service import (
    _date_cell,
    reconcile_target_attribute,
    salvage_narrative,
)
from app.services.pipeline.schemas import DynamicTargetAttributeEvidence, ReportPatentDetails

_NOT = "Not disclosed in extracted evidence"


def test_repeated_token_tail_is_removed_and_science_is_kept():
    phrase = "Kali kalyteres! Kali kalyterous! Kali kalytera! Kali kalytero! "
    science = (
        "Synthesis of the target polymer is achieved by emulsion and solution routes. "
        "The selected patents report monomer ratios, initiators, and workup conditions. "
    )
    cleaned, ok = salvage_narrative(science + (phrase * 30))
    assert ok
    assert "emulsion" in cleaned
    assert "kalyteres" not in cleaned.lower()


def test_entirely_repeated_narrative_is_rejected():
    phrase = "alpha beta gamma delta "
    cleaned, ok = salvage_narrative(phrase * 20)
    assert cleaned == ""
    assert ok is False


def test_measured_example_values_override_undisclosed_summary():
    attr = DynamicTargetAttributeEvidence(
        label="acrylonitrile content",
        value=_NOT,
        status="not_found",
        belongs_to_target=False,
    )
    evidence = [
        "Example 1: Describes preparation of Latex A (28.1% bound ACN).",
        "Example 2: Describes preparation of Latex B (33.9% bound ACN).",
    ]
    params = ["Initial acrylonitrile charge: 8.35 to 13.53 phr — Table 2"]
    context = "The report concerns acrylonitrile (ACN) content."
    updated = reconcile_target_attribute(attr, evidence, params, context)
    assert updated.value != _NOT
    assert "28.1%" in updated.value
    assert "33.9%" in updated.value
    assert "phr" not in updated.value
    assert updated.belongs_to_target is True


def test_truncated_search_title_does_not_replace_document_title():
    document = "Nitrile rubbers which optionally contain alkylthio terminal groups and which are optionally hydrogenated"
    search = "Nitrile rubbers which optionally contain alkylthio terminal groups and which ..."
    assert prefer_source_title(document, search) == document
    assert prefer_source_title("", search) == search
    assert prefer_source_title(document, document) == document


def test_date_cell_labels_priority_and_publication_separately():
    with_priority = ReportPatentDetails(
        patent_number="US1",
        patent_title="Title",
        publication_year="2018",
        priority_date="2014-03-01",
    )
    published_only = ReportPatentDetails(
        patent_number="US2",
        patent_title="Title",
        publication_year="2018",
    )
    assert _date_cell(with_priority) == "Priority 2014-03-01"
    assert _date_cell(published_only) == "Published 2018"


def test_claim_only_range_is_not_called_an_experimental_result():
    attr = DynamicTargetAttributeEvidence(
        label="styrene content",
        value=_NOT,
        status="not_found",
        belongs_to_target=False,
    )
    updated = reconcile_target_attribute(
        attr,
        [],
        ["Styrene content: 10 to 50 wt% — Claim 1"],
        "",
    )
    assert "claim" in updated.value.lower()
    assert updated.belongs_to_target is False


def test_third_property_vocabulary_keeps_measured_temperature():
    attr = DynamicTargetAttributeEvidence(
        label="glass transition temperature",
        value=_NOT,
        status="not_found",
        belongs_to_target=False,
    )
    updated = reconcile_target_attribute(
        attr,
        ["Example 4: glass transition temperature was -42 °C after drying."],
        ["Monomer feed: 20 phr — Table 1"],
        "",
    )
    assert "-42" in updated.value
    assert "phr" not in updated.value
    assert updated.belongs_to_target is True
