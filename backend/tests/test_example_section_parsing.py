"""
tests/test_example_section_parsing.py

Bug 2 regressions: EP-style / US-style example heading detection and
clear report notes when a patent genuinely has no worked examples.
"""
from pathlib import Path

import pytest

from app.services.pipeline.example_boundaries import (
    find_examples_block_start,
    split_example_sections,
)
from app.services.pipeline.extractor_service import ExtractorService
from app.services.pipeline.report_evidence_service import ReportEvidenceService
from app.services.pipeline.report_service import ReportService
from app.services.pipeline.schemas import (
    LLMPatentAnalysis,
    LLMPatentResearchReport,
    ParsedPatent,
    PatentExtraction,
    PatentMetadata,
    ReportPatentEvidence,
    SynthesisSection,
)
from unittest.mock import AsyncMock, patch

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_ep_style_inventive_examples_are_segmented():
    text = _load_text("ep_style_examples_text.txt")
    start = find_examples_block_start(text)
    assert start is not None
    # Must not start at mid-sentence "for example" / "Examples of"
    assert "For example" not in text[start : start + 40]
    assert "Examples of suitable" not in text[start : start + 40]
    block = text[start:]
    sections = split_example_sections(block)
    headers = [h.lower() for h, _ in sections]
    assert any("inventive examples" in h for h in headers)
    assert len(sections) >= 2
    # Bodies retain table/process content
    joined = "\n".join(b for _, b in sections)
    assert "Table 1" in joined or "Acrylonitrile" in joined


def test_us_style_numbered_examples_still_segmented():
    text = _load_text("us_style_examples_text.txt")
    start = find_examples_block_start(text)
    assert start is not None
    sections = split_example_sections(text[start:])
    headers = [h for h, _ in sections]
    assert "Example 1" in headers
    assert "Example 2" in headers
    assert any(h.startswith("Comparative Example") for h in headers)


def test_grouped_example_headings_stay_intact():
    text = (
        "Examples 1, 1a, 1b, 1c and 1d\n"
        "Styrene 100 g and butadiene 400 g were charged.\n"
        "Examples 2-25\n"
        "The same charge was repeated across the series.\n"
        "Examples 2a & 2b\n"
        "A second pair used a different modifier.\n"
    )
    sections = split_example_sections(text)
    headers = [header for header, _ in sections]
    assert any("1a" in header and "1d" in header for header in headers)
    assert any("2-25" in header for header in headers)
    assert any("2b" in header for header in headers)


@pytest.mark.asyncio
async def test_repeated_example_headings_are_not_merged():
    parsed = ParsedPatent(
        patent_number="US0000001B2",
        title="Repeated headings",
        detailed_description="",
        examples=(
            "Example 1\nFirst synthesis charge: styrene 10 wt%.\n"
            "Example 1\nLater series charge: styrene 40 wt%.\n"
        ),
    )
    ext = await ExtractorService().extract_polymerization_data(parsed, url="")
    assert ext is not None
    assert len(ext.examples) == 2
    assert "10 wt%" in ext.examples[0].raw_text
    assert "40 wt%" in ext.examples[1].raw_text
    assert "40 wt%" not in ext.examples[0].raw_text


def test_mid_sentence_example_does_not_start_block():
    prose = (
        "The initiator may be used, for example, in the form of mixtures of peroxides.\n"
        "Examples of suitable reducing agents are ascorbic acid.\n"
    )
    assert find_examples_block_start(prose) is None
    assert split_example_sections(prose) == []


@pytest.mark.asyncio
async def test_extractor_finds_ep_style_sections_from_description():
    text = _load_text("ep_style_examples_text.txt")
    parsed = ParsedPatent(
        patent_number="EP0000001B1",
        title="Synthetic EP-style examples patent",
        url="https://patents.google.com/patent/EP0000001B1",
        abstract="Emulsion polymerization process.",
        claims="1. A process for preparing a polymer.",
        detailed_description=text,
        examples="",  # force description fallback path
    )
    ext = await ExtractorService().extract_polymerization_data(parsed, url=parsed.url)
    assert ext is not None
    assert len(ext.examples) >= 2
    assert any("Inventive Examples" in (e.example_id or "") for e in ext.examples)


@pytest.mark.asyncio
async def test_genuinely_no_examples_produces_clear_report_note():
    text = _load_text("no_examples_patent_text.txt")
    parsed = ParsedPatent(
        patent_number="US0000001A",
        title="Process-focused patent without worked examples",
        url="https://patents.google.com/patent/US0000001A",
        abstract="A general process disclosure.",
        claims="1. A process for preparing a polymer.",
        detailed_description=text,
        examples="",
    )
    ext = await ExtractorService().extract_polymerization_data(parsed, url=parsed.url)
    assert ext is not None
    assert ext.examples == []
    assert ext.examples_detection_note
    assert "No worked-example" in ext.examples_detection_note or "fallback" in ext.examples_detection_note.lower()

    evidence = ReportEvidenceService().build_compact_evidence(ext, parsed_patent=parsed)
    assert evidence.examples == []
    assert evidence.limitations_or_missing_data
    assert any(
        "example" in n.lower() for n in evidence.limitations_or_missing_data
    )

    llm = LLMPatentResearchReport(
        title="Report",
        abstract="Abstract",
        per_patent_analysis=[
            LLMPatentAnalysis(
                patent_number="US0000001A",
                synthesis_method="General process",
                disclosed_parameters=["Temperature: controlled"],
                example_highlights=[
                    "Example 1: Not detected by parser.",
                    "Example 2: Not structurally extracted by parser.",
                ],
                technical_relevance="Process patent",
            )
        ],
        cross_patent_comparison=[],
        conclusion="done",
        references=["US0000001A"],
    )
    with patch(
        "app.services.pipeline.report_service.llm_client.generate_structured",
        new=AsyncMock(return_value=(llm, "mock", {})),
    ):
        report, _ = await ReportService().generate_structured_report(
            compound_name="Example Polymer X",
            extractions=[evidence],
            patent_manifest=["US0000001A"],
        )

    bullets = report.methodology_patents[0].experimental_evidence
    assert bullets
    joined = " | ".join(bullets).lower()
    assert "not detected by parser" not in joined
    assert "not structurally extracted" not in joined
