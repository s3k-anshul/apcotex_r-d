"""
Report must contain ONLY selected primary patents and the canonical five sections.
"""
from app.services.pipeline.report_service import ReportService
from app.services.pipeline.schemas import (
    PatentResearchReport,
    ReportPatent,
    ReportPatentDetails,
    ReportPatentMethodology,
)


def _patent(number: str, title: str = "Title") -> ReportPatent:
    return ReportPatent(
        patent_details=ReportPatentDetails(
            patent_number=number,
            patent_title=title,
            assignee="Example Co",
            jurisdiction=number[:2],
            publication_year="2020",
            relevance_to_target="PRIMARY",
            relevance_tier="PRIMARY",
        ),
        polymerization_method=ReportPatentMethodology(
            dynamic_parameters=["Synthesis method: emulsion polymerization"]
        ),
        experimental_evidence=["Example 1: polymerized"],
        technical_relevance="Central synthesis patent.",
    )


def test_report_markdown_has_five_sections_and_no_secondary():
    primary = [_patent("US1111"), _patent("US2222")]
    leaked_secondary = [_patent("US9999", "Should not appear")]
    report = PatentResearchReport(
        title="Example Report",
        abstract="Abstract text.",
        methodology_patents=primary,
        secondary_patents=leaked_secondary,
        cross_patent_comparison=["Trend A"],
        conclusion="Conclusion text.",
        references=["US1111 | Title | Example Co", "US2222 | Title | Example Co"],
    )
    md = ReportService().report_to_markdown(report)
    assert "## 1. ABSTRACT" in md
    assert "## 2. METHODOLOGY" in md
    assert "## 3. CROSS-PATENT COMPARISON & SYNTHESIS TRENDS" in md
    assert "## 4. CONCLUSION" in md
    assert "## 5. REFERENCES" in md
    assert "SUPPORTING / RELATED PATENTS" not in md.upper()
    assert "SECONDARY PATENTS" not in md.upper()
    assert "US1111" in md and "US2222" in md
    assert "US9999" not in md


def test_validate_rejects_secondary_and_extra_patents():
    svc = ReportService()
    report = PatentResearchReport(
        title="t",
        abstract="a",
        methodology_patents=[_patent("US1111"), _patent("US3333")],
        secondary_patents=[_patent("US9999")],
        conclusion="c",
        references=["US1111 | t"],
    )
    ok, errors = svc.validate_report_consistency(report, primary_manifest=["US1111"])
    assert ok is False
    joined = " ".join(errors)
    assert "secondary" in joined.lower()
    assert "Extra patents" in joined or "Missing patents" in joined


def test_validate_passes_exact_primary_manifest():
    svc = ReportService()
    report = PatentResearchReport(
        title="t",
        abstract="a",
        methodology_patents=[_patent("US1111"), _patent("US2222")],
        secondary_patents=[],
        cross_patent_comparison=["trend"],
        conclusion="c",
        references=["US1111 | t", "US2222 | t"],
    )
    ok, errors = svc.validate_report_consistency(
        report, primary_manifest=["US1111", "US2222"]
    )
    assert ok is True, errors
