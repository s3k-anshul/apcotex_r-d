"""PDF layout only. Markdown text and the DOCX exporter stay on their existing path."""
import os
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.services.pipeline.report_service import ReportService, pdf_html_from_markdown
from app.services.pipeline.schemas import (
    DynamicTargetAttributeEvidence,
    MediumAndWaterRoleEvidence,
    PatentResearchReport,
    ReportComparisonDimension,
    ReportPatent,
    ReportPatentDetails,
    ReportPatentMethodology,
)

REFERENCE_DOCX = Path(r"C:\Users\desha\Downloads\APCOTEX_Report_Low styrene SBR.docx")


def _patent(
    number: str,
    title: str,
    assignee: str,
    parameters: list[str],
    evidence: list[str],
    *,
    priority: str | None = None,
    medium: str | None = None,
    target_label: str | None = None,
    target_value: str | None = None,
) -> ReportPatent:
    return ReportPatent(
        patent_details=ReportPatentDetails(
            patent_number=number,
            patent_title=title,
            assignee=assignee,
            jurisdiction=number[:2],
            publication_year="2018",
            priority_date=priority,
            relevance_to_target="Selected primary evidence",
            relevance_tier="PRIMARY",
        ),
        polymerization_method=ReportPatentMethodology(dynamic_parameters=parameters),
        experimental_evidence=evidence,
        technical_relevance=f"Technical relevance for {number}.",
        medium_and_water_role=(
            MediumAndWaterRoleEvidence(summary=medium) if medium else None
        ),
        target_attribute=(
            DynamicTargetAttributeEvidence(label=target_label, value=target_value or "")
            if target_label
            else None
        ),
    )


def _report(patents: list[ReportPatent], dims: list[ReportComparisonDimension]) -> PatentResearchReport:
    return PatentResearchReport(
        title="Low styrene SBR patent research report",
        abstract="Abstract text with 10 wt% styrene and a glass-transition temperature near -50 °C.",
        methodology_patents=patents,
        cross_patent_comparison=["Continuous solution runs report lower combined styrene than batch runs."]
        if len(patents) >= 2
        else [],
        conclusion="Conclusion text is unchanged.",
        references=[f"{p.patent_details.patent_number} | {p.patent_details.patent_title}" for p in patents],
        comparison_dimensions=dims,
    )


def test_pdf_html_keeps_parameters_and_evidence_as_separate_bullets():
    patent = _patent(
        "EP3508508B1",
        "Modified conjugated diene-based polymer and rubber composition comprising same",
        "LG Chem, Ltd.",
        [
            "Synthesis method: Continuous solution polymerization",
            "Styrene feed rate: 1.80 kg/h — Example 1",
            "1,3-Butadiene feed rate: 14.2 kg/h — Example 1",
        ],
        [
            "Example 1: Continuous polymerization in three reactors.",
            "Comparative Example 5: Batch polymerization at 50 degrees C.",
        ],
        medium="No water-related process step disclosed in the extracted evidence.",
        target_label="styrene content",
        target_value="less than 15 wt%",
    )
    report = _report(
        [patent, _patent("US10174133B2", "Short title", "Lg Chem, Ltd.", ["Synthesis method: batch"], ["Example 2: 20 L autoclave."])],
        [ReportComparisonDimension(parameter_name="styrene content", values={"EP3508508B1": "less than 15 wt%", "US10174133B2": "Not disclosed in extracted evidence"})],
    )
    markdown = ReportService().report_to_markdown(report)
    html = pdf_html_from_markdown(markdown)

    assert "1. ABSTRACT" in html
    assert "2. METHODOLOGY" in html
    assert "3. CROSS-PATENT COMPARISON" in html
    assert "4. CONCLUSION" in html
    assert "5. REFERENCES" in html

    assert "EP3508508B1" in html
    assert "LG Chem, Ltd." in html
    assert "Continuous solution polymerization" in html
    assert "Continuous polymerization in three reactors" in html

    assert "Abstract text with 10 wt% styrene" in html
    assert "Conclusion text is unchanged." in html

    # Must NOT have verbose/dump sections
    assert "Patent Tables" not in html
    assert "Evidence Coverage" not in html
    assert "Raw Evidence" not in html


def test_pdf_html_omits_missing_optional_metadata_and_supports_extra_dimensions():
    patent = _patent(
        "WO2020999999A1",
        "A very long patent title about styrene-butadiene rubber prepared with 2,2-di(2-tetrahydrofuryl)propane modifier",
        "Korea Kumho Petrochemical Co., Ltd.",
        ["Initiator: n-butyllithium"],
        ["Example I: no comparative example in this record."],
    )
    dims = [
        ReportComparisonDimension(parameter_name="Medium & Water Role", values={"WO2020999999A1": "aqueous emulsion"}),
        ReportComparisonDimension(parameter_name="vinyl content", values={"WO2020999999A1": "50 wt%"}),
        ReportComparisonDimension(parameter_name="Mooney viscosity ML(1+4) at 100 °C", values={"WO2020999999A1": "45–55"}),
    ]
    html = pdf_html_from_markdown(ReportService().report_to_markdown(_report([patent], dims)))
    assert "Priority Date" not in html
    assert "Legal Status" not in html
    assert "Polymer Type" not in html
    assert ">Patent</th>" in html
    assert "WO2020999999A1" in html
    assert "Mooney viscosity ML(1+4) at 100 °C" in html


@pytest.mark.asyncio
async def test_export_to_pdf_renders_text_and_a_landscape_table_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    long_name = "poly(styrene-co-1,3-butadiene) with α-methylstyrene and 10 μm particles"
    patents = [
        _patent(
            f"US1000000{i}B2",
            f"Title {i} {long_name}",
            "The Goodyear Tire & Rubber Company",
            [f"Polymerization temperature: {40 + i} degrees C — Example {i}", "Styrene feed rate: 1.80 kg/h"],
            [f"Example {i}: separate experimental evidence item for patent {i}."],
            priority="2016-01-01" if i == 1 else None,
            medium="Water is the emulsion medium." if i % 2 == 0 else None,
            target_label="styrene content",
            target_value=f"{10 + i} wt%",
        )
        for i in range(1, 4)
    ]
    # Provide 4 dimensions so comparison table has 7 columns (> 6) and triggers landscape
    dims = [
        ReportComparisonDimension(
            parameter_name="styrene content",
            values={p.patent_details.patent_number: f"{10} wt%" for p in patents},
        ),
        ReportComparisonDimension(
            parameter_name="vinyl content",
            values={p.patent_details.patent_number: f"{50} wt%" for p in patents},
        ),
        ReportComparisonDimension(
            parameter_name="Mooney viscosity",
            values={p.patent_details.patent_number: "45-55" for p in patents},
        ),
        ReportComparisonDimension(
            parameter_name="Glass transition temp",
            values={p.patent_details.patent_number: "-50 °C" for p in patents},
        ),
    ]
    service = ReportService()
    report = _report(patents, dims)
    markdown = service.report_to_markdown(report)
    pdf_path = await service.export_to_pdf(markdown, "layout.pdf")
    assert pdf_path and os.path.isfile(pdf_path)

    reader = PdfReader(pdf_path)
    sizes = [(page.mediabox.width, page.mediabox.height) for page in reader.pages]
    assert sizes[0][0] < sizes[0][1]
    assert any(width > height for width, height in sizes)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    compact = "".join(text.split())
    for patent in patents:
        assert patent.patent_details.patent_number in compact
    assert "α-methylstyrene" in compact
    assert "10μm" in compact or "10µm" in compact
    assert "Conclusiontextisunchanged." in compact

    docx_path = await service.export_to_docx(report, "layout.docx")
    from docx import Document

    document = Document(docx_path)
    headings = [p.text for p in document.paragraphs if p.style and p.style.name.startswith("Heading")]
    assert any("ABSTRACT" in h for h in headings)
    assert any("METHODOLOGY" in h for h in headings)
    assert any("CROSS-PATENT COMPARISON" in h for h in headings)
    assert any("CONCLUSION" in h for h in headings)
    assert any("REFERENCES" in h for h in headings)
    assert len(document.tables) == 2



def _blocks(document):
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body:
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _report_from_reference_docx(path: Path) -> PatentResearchReport:
    from docx import Document

    document = Document(str(path))
    abstract = []
    conclusion = []
    references = []
    trends = []
    patents: list[ReportPatent] = []
    section = ""
    current = None
    subsection = ""
    comparison_headers: list[str] = []
    comparison_rows: list[list[str]] = []

    def finish_patent():
        nonlocal current
        if current:
            patents.append(current)
            current = None

    for block in _blocks(document):
        if hasattr(block, "text"):
            style = block.style.name if block.style is not None else ""
            text = block.text.strip()
            if not text:
                continue
            if style == "Heading 2":
                finish_patent()
                section = text
                subsection = ""
                continue
            if style == "Heading 3" and text.startswith("Patent ") and "Comparison" not in text:
                finish_patent()
                current = {
                    "details": {},
                    "parameters": [],
                    "evidence": [],
                    "relevance": "",
                    "medium": "",
                    "target_label": "",
                    "target_value": "",
                }
                subsection = ""
                continue
            if style == "Heading 3" and "Comparison" in text:
                finish_patent()
                section = "comparison"
                continue
            if style == "Heading 4" and current is not None:
                subsection = text
                continue
            if section.startswith("1.") and style == "Normal":
                abstract.append(text)
            elif section.startswith("3.") and style == "List Bullet":
                trends.append(text)
            elif section.startswith("4.") and style == "Normal":
                conclusion.append(text)
            elif section.startswith("5.") and style == "List Bullet":
                references.append(text)
            elif current is not None and style == "List Bullet" and subsection.startswith("Polymerization"):
                current["parameters"].append(text)
            elif current is not None and style == "Normal" and subsection == "Medium & Water Role":
                current["medium"] = text
            elif current is not None and style == "Normal" and subsection not in {
                "Polymerization / Synthesis Method",
                "Relevant Experimental Evidence",
                "Technical Relevance",
                "Medium & Water Role",
                "",
            }:
                current["target_label"] = subsection
                current["target_value"] = text
            elif current is not None and style == "List Bullet" and subsection.startswith("Relevant Experimental"):
                current["evidence"].append(text)
            elif current is not None and style == "Normal" and subsection == "Technical Relevance":
                current["relevance"] = text
            continue

        if section == "comparison":
            comparison_headers = [cell.text.strip() for cell in block.rows[0].cells]
            comparison_rows = [
                [cell.text.strip() for cell in row.cells] for row in block.rows[1:]
            ]
            section = ""
            continue
        if current is not None and not current["details"]:
            for row in block.rows:
                label = row.cells[0].text.strip()
                value = row.cells[1].text.strip()
                current["details"][label] = value

    finish_patent()
    built = []
    for item in patents:
        details = item["details"]
        number = details.get("Patent Number", "")
        priority = details.get("Priority Date")
        if priority == "Not available from source":
            priority = None
        built.append(
            ReportPatent(
                patent_details=ReportPatentDetails(
                    patent_number=number,
                    patent_title=details.get("Title", ""),
                    assignee=details.get("Assignee"),
                    jurisdiction=details.get("Jurisdiction"),
                    publication_year=details.get("Publication Year"),
                    priority_date=priority,
                    legal_status=None if details.get("Legal Status") in (None, "Not available from source") else details.get("Legal Status"),
                    polymer_type=None if details.get("Polymer Type") in (None, "Not available from source") else details.get("Polymer Type"),
                    relevance_to_target=details.get("Relevance to Target", ""),
                    relevance_tier="PRIMARY",
                ),
                polymerization_method=ReportPatentMethodology(dynamic_parameters=item["parameters"]),
                experimental_evidence=item["evidence"],
                technical_relevance=item["relevance"],
                medium_and_water_role=MediumAndWaterRoleEvidence(summary=item["medium"]) if item["medium"] else None,
                target_attribute=DynamicTargetAttributeEvidence(
                    label=item["target_label"],
                    value=item["target_value"],
                ) if item["target_label"] else None,
            )
        )
    dim_names = comparison_headers[2:]
    dims = []
    for offset, name in enumerate(dim_names):
        values = {}
        for row in comparison_rows:
            if len(row) > offset + 2:
                values[row[0]] = row[offset + 2]
        dims.append(ReportComparisonDimension(parameter_name=name, values=values))
    return PatentResearchReport(
        title="PATENT RESEARCH REPORT",
        abstract=" ".join(abstract),
        methodology_patents=built,
        cross_patent_comparison=trends,
        conclusion=" ".join(conclusion),
        references=references,
        comparison_dimensions=dims,
    )


@pytest.mark.skipif(not REFERENCE_DOCX.exists(), reason="Low styrene SBR reference document is not present")
@pytest.mark.asyncio
async def test_low_styrene_reference_pdf_preserves_word_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = _report_from_reference_docx(REFERENCE_DOCX)
    assert len(report.methodology_patents) == 10
    service = ReportService()
    markdown = service.report_to_markdown(report)
    pdf_path = await service.export_to_pdf(markdown, "low-styrene.pdf")
    reader = PdfReader(pdf_path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    compact = "".join(text.split())
    # Validation: The report must be approximately 5 pages (4 to 7 pages), NOT 154 pages!
    assert 4 <= len(reader.pages) <= 7
    # 5 Major sections present
    assert "1.ABSTRACT" in compact
    assert "2.METHODOLOGY" in compact
    assert "3.CROSS-PATENTCOMPARISON" in compact
    assert "4.CONCLUSION" in compact
    assert "5.REFERENCES" in compact
    # All 10 patents are referenced
    for patent in report.methodology_patents:
        assert patent.patent_details.patent_number in compact
    assert "".join(report.abstract[:80].split()) in compact
    assert "".join(report.conclusion[:80].split()) in compact
    for ref in report.references:
        head = ref.split("|")[0].strip()
        assert "".join(head.split()) in compact
    # Confirm no raw table dumps or obsolete section headers
    assert "PATENTTABLES" not in compact
    assert "EVIDENCECOVERAGE" not in compact
    assert "RAWEVIDENCE" not in compact

