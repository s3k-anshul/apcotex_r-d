"""
tests/test_patent_evidence_pipeline.py

Comprehensive tests for:
- Full patent evidence retention & table preservation
- Structured HTML table extraction & markdown generation
- Dynamic property extraction & safe normalization
- Dynamic cross-patent comparison dimensions
- PDF & DOCX rendering with structured tables
- Compound-agnostic validation (no NBR-specific logic)
"""
import os
import pytest
from pathlib import Path

from app.services.pipeline.schemas import (
    ExtractedTableSchema,
    PatentExtraction,
    PatentMetadata,
    PatentExample,
    SynthesisSection,
    ReportPatentEvidence,
    ReportPatent,
    ReportPatentDetails,
    ReportPatentMethodology,
    PatentResearchReport,
    ReportComparisonDimension,
    MediumAndWaterRoleEvidence,
    DynamicTargetAttributeEvidence,
)
from app.services.pipeline.extractor_service import (
    _extract_structured_table,
    _attach_tables_missing_from_examples,
)
from app.services.pipeline.report_evidence_service import ReportEvidenceService
from app.services.pipeline.report_service import (
    ReportService,
    _normalize_dynamic_parameter_name,
    _build_dynamic_comparison_dimensions,
    _comparison_widths,
    _comparison_table_html,
    pdf_html_from_markdown,
)


def test_extracted_table_schema_to_markdown():
    """Verify structured table transforms into valid Markdown table."""
    table = ExtractedTableSchema(
        title="Table 1: Polymerization Conditions",
        headers=["Monomer", "Feed (phr)", "Conversion (%)"],
        rows=[
            ["1,3-Butadiene", "70", "85"],
            ["Acrylonitrile", "30", "88"],
        ],
    )
    md = table.to_markdown()
    assert "**Table 1: Polymerization Conditions**" in md
    assert "| Monomer | Feed (phr) | Conversion (%) |" in md
    assert "| --- | --- | --- |" in md
    assert "| 1,3-Butadiene | 70 | 85 |" in md
    assert "| Acrylonitrile | 30 | 88 |" in md


def test_html_table_parsing_into_structured_schema():
    """Verify HTML table is correctly converted into ExtractedTableSchema."""
    html_content = """
    <table>
        <caption>Polymer Formulation 2</caption>
        <thead>
            <tr><th>Component</th><th>phr</th><th>Role</th></tr>
        </thead>
        <tbody>
            <tr><td>Monomer A</td><td>60</td><td>Main monomer</td></tr>
            <tr><td>Monomer B</td><td>40</td><td>Comonomer</td></tr>
            <tr><td>Potassium persulfate</td><td>0.3</td><td>Initiator</td></tr>
        </tbody>
    </table>
    """
    tbl = _extract_structured_table(html_content, default_title="Fallback Title")
    assert tbl is not None
    assert "Polymer Formulation 2" in tbl.title
    assert tbl.headers == ["Component", "phr", "Role"]
    assert len(tbl.rows) == 3
    assert tbl.rows[0] == ["Monomer A", "60", "Main monomer"]
    assert tbl.rows[2][0] == "Potassium persulfate"


def test_attach_tables_preserves_structure_in_extraction():
    """Verify _attach_tables_missing_from_examples attaches structured table and Markdown."""
    extraction = PatentExtraction(
        metadata=PatentMetadata(patent_number="US9999999A", patent_title="Sample Patent"),
        examples=[PatentExample(example_id="Example 1", raw_text="Short narrative text.")],
    )
    mock_patent = type(
        "ParsedPatent",
        (),
        {
            "tables": [
                {
                    "html": (
                        "<table><tr><th>Initiator</th><th>Temp</th></tr>"
                        "<tr><td>KPS</td><td>50 C</td></tr></table>"
                    )
                }
            ]
        },
    )()

    _attach_tables_missing_from_examples(extraction, mock_patent)
    assert len(extraction.tables) == 1
    assert extraction.tables[0].headers == ["Initiator", "Temp"]
    assert len(extraction.synthesis_sections) == 1
    assert "| Initiator | Temp |" in extraction.synthesis_sections[0].raw_text
    assert "| --- | --- |" in extraction.synthesis_sections[0].raw_text


def test_evidence_service_carries_structured_tables():
    """Verify ReportEvidenceService preserves tables in ReportPatentEvidence."""
    svc = ReportEvidenceService()
    extraction = PatentExtraction(
        metadata=PatentMetadata(patent_number="EP1234567B1", patent_title="Test Polymer"),
        tables=[
            ExtractedTableSchema(
                title="Table 3",
                headers=["Temperature", "Yield"],
                rows=[["80 °C", "92%"]],
            )
        ],
    )
    evidence = svc.build_compact_evidence(extraction)
    assert len(evidence.tables) == 1
    assert evidence.tables[0].title == "Table 3"

    serialized = svc.serialize_evidence([evidence])
    assert "Patent Tables:" in serialized
    assert "[Table 3]:" in serialized
    assert "| Temperature | Yield |" in serialized


def test_dynamic_parameter_normalization_generic():
    """Verify parameter normalization is generic and material-agnostic."""
    assert _normalize_dynamic_parameter_name("polymerization temperature") == "Polymerization Temperature"
    assert _normalize_dynamic_parameter_name("reaction temp") == "Polymerization Temperature"
    assert _normalize_dynamic_parameter_name("monomer conversion") == "Conversion"
    assert _normalize_dynamic_parameter_name("initiator system") == "Initiator / Catalyst"
    assert _normalize_dynamic_parameter_name("catalyst") == "Initiator / Catalyst"
    assert _normalize_dynamic_parameter_name("chain transfer agent") == "Chain Transfer Agent"
    assert _normalize_dynamic_parameter_name("cta") == "Chain Transfer Agent"
    assert _normalize_dynamic_parameter_name("solids content") == "Solids Content"
    assert _normalize_dynamic_parameter_name("hydrogen pressure") == "Pressure"
    # Generic novel property
    assert _normalize_dynamic_parameter_name("tensile elongation") == "Tensile Elongation"


def test_dynamic_comparison_dimensions_discovery():
    """Verify comparison dimensions are collected across diverse patents."""
    p1 = ReportPatent(
        patent_details=ReportPatentDetails(patent_number="PAT-1", patent_title="P1"),
        polymerization_method=ReportPatentMethodology(
            dynamic_parameters=[
                "Polymerization temperature: 10 °C",
                "Conversion: 80%",
                "Initiator: KPS 0.3 phr",
            ]
        ),
        experimental_evidence=["Example 1: Cold emulsion"],
        technical_relevance="Relevance 1",
    )
    p2 = ReportPatent(
        patent_details=ReportPatentDetails(patent_number="PAT-2", patent_title="P2"),
        polymerization_method=ReportPatentMethodology(
            dynamic_parameters=[
                "Reaction temperature: 15 °C",
                "Conversion: 85%",
                "Pressure: 5 bar",
            ]
        ),
        experimental_evidence=["Example 2: Pressurized run"],
        technical_relevance="Relevance 2",
    )

    dims = _build_dynamic_comparison_dimensions(
        methodology_patents=[p1, p2],
        resolved_label="Dynamic Attribute",
        medium_values={"PAT-1": "Aqueous", "PAT-2": "Solvent"},
        attribute_values={"PAT-1": "25%", "PAT-2": "Not disclosed in extracted evidence"},
    )

    dim_names = [d.parameter_name for d in dims]
    # Invariants: first two dimensions are Medium & Water Role and Target Attribute
    assert dim_names[0] == "Medium & Water Role"
    assert dim_names[1] == "Dynamic Attribute"

    # Discovered dynamic dimensions
    assert "Conversion" in dim_names
    assert "Polymerization Temperature" in dim_names

    conv_dim = next(d for d in dims if d.parameter_name == "Conversion")
    assert conv_dim.values["PAT-1"] == "80%"
    assert conv_dim.values["PAT-2"] == "85%"

    temp_dim = next(d for d in dims if d.parameter_name == "Polymerization Temperature")
    assert temp_dim.values["PAT-1"] == "10 °C"
    assert temp_dim.values["PAT-2"] == "15 °C"


def test_pdf_rendering_with_structured_tables():
    """Verify PDF HTML converts markdown tables with clean styling and without bullet corruption."""
    markdown_text = """# TEST REPORT

## 1. ABSTRACT
Abstract technical content.

## 2. METHODOLOGY
### PRIMARY PATENT EVIDENCE
#### Patent 1
- Patent Number: US1111111B2
- Patent Title: Sample Synthesis

**Patent Tables**

| Catalyst | Loading (mol%) | Selectivity (%) |
| --- | --- | --- |
| Ru-complex | 0.05 | 98.5 |

**Relevant Experimental Evidence**
- Example 1: High yield demonstration.
- Example 2: Comparative batch run.

### PATENT COMPARISON TABLE
| Patent | Applicant | Date | Medium & Water Role | Target Attribute | Key Findings |
| --- | --- | --- | --- | --- | --- |
| US1111111B2 | Sample Chem | 2020 | Emulsion | 20% | High conversion |

## 4. CONCLUSION
Report conclusion.
"""
    html = pdf_html_from_markdown(markdown_text)
    assert '<table class="compare' in html
    assert "Catalyst" in html and "Loading (mol%)" in html
    assert "Ru-complex" in html
    assert "<li>Example 1: High yield demonstration.</li>" in html
    assert "<li>Example 2: Comparative batch run.</li>" in html
    # Ensure tables are not mangled inside <li> tags
    assert "<li>| Catalyst" not in html
    assert "<li>| ---" not in html


@pytest.mark.asyncio
async def test_export_to_docx_with_structured_tables(tmp_path):
    """Verify DOCX exporter writes native Word tables for structured patent tables."""
    svc = ReportService()
    svc.export_dir = str(tmp_path)

    patent = ReportPatent(
        patent_details=ReportPatentDetails(
            patent_number="EP2222222A1",
            patent_title="Biodegradable Polyester Synthesis",
            assignee="Green Polymers Corp.",
            jurisdiction="EP",
            publication_year="2021",
        ),
        polymerization_method=ReportPatentMethodology(
            dynamic_parameters=["Reaction Temperature: 180 °C", "Catalyst: Tin octoate"]
        ),
        experimental_evidence=["Example 1: Ring opening polymerization."],
        technical_relevance="Relevant for bio-based polyester.",
        tables=[
            ExtractedTableSchema(
                title="Table 1: Monomer Charges",
                headers=["Monomer", "Amount (g)", "Purity (%)"],
                rows=[["L-Lactide", "500", "99.8"], ["Glycolide", "150", "99.5"]],
            )
        ],
    )

    report = PatentResearchReport(
        title="BIODEGRADABLE POLYESTER REPORT",
        abstract="Synthesis of high MW polyester.",
        methodology_patents=[patent],
        references=["EP2222222A1 | Biodegradable Polyester | Green Polymers Corp. | EP | 2021 | https://patents.google.com"],
    )

    docx_path = await svc.export_to_docx(report, "test_bio_polyester.docx")
    assert docx_path and os.path.isfile(docx_path)

    from docx import Document
    doc = Document(docx_path)
    # Check headings and tables exist in document
    table_texts = []
    for t in doc.tables:
        for r in t.rows:
            table_texts.append([c.text for c in r.cells])

    flat_cells = [cell for row in table_texts for cell in row]
    # In concise 5-section report, docx exports native Word tables for Methodology and Comparison
    assert "EP2222222A1" in flat_cells
    assert "Green Polymers Corp." in flat_cells

    # Raw extracted tables are preserved internally on patent.tables but NOT dumped into export
    assert len(patent.tables) == 1
    assert patent.tables[0].rows[0][0] == "L-Lactide"
    assert "L-Lactide" not in flat_cells

    heading_texts = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert any("ABSTRACT" in h for h in heading_texts)
    assert any("METHODOLOGY" in h for h in heading_texts)
    assert any("CROSS-PATENT COMPARISON" in h for h in heading_texts)
    assert any("CONCLUSION" in h for h in heading_texts)
    assert any("REFERENCES" in h for h in heading_texts)



def test_no_compound_hardcoding():
    """Verify that normalizer and dimension builder have zero NBR-specific hardcoded keywords."""
    import inspect
    norm_source = inspect.getsource(_normalize_dynamic_parameter_name)
    dims_source = inspect.getsource(_build_dynamic_comparison_dimensions)

    forbidden = ["nbr", "acrylonitrile", "butadiene", "carboxyl content"]
    for word in forbidden:
        assert word not in norm_source.lower(), f"Forbidden hardcoded word '{word}' found in normalizer!"
        assert word not in dims_source.lower(), f"Forbidden hardcoded word '{word}' found in dimensions builder!"
