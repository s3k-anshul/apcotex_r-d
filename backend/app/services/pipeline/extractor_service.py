"""
app/services/pipeline/extractor_service.py

Uses Gemini Structured Outputs to:
1. Batch rank discovered patents based on metadata (title/snippet).
2. Extract the detailed polymerization JSON parameters from the full document.
"""
import logging
from typing import List, Dict, Any

from app.core.config import settings
from app.services.pipeline.schemas import (
    PatentExtraction, PatentRankList, PatentRank, SynthesisSection, ExtractedTableSchema
)
from app.services.llm import llm_client

logger = logging.getLogger(__name__)


def _extract_structured_table(html: str, default_title: str = "") -> ExtractedTableSchema | None:
    """Parse HTML table into structured ExtractedTableSchema (title, headers, rows)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    table_node = soup.find("table") or soup

    title = default_title
    caption = ""
    caption_node = table_node.find("caption")
    if caption_node:
        caption_text = caption_node.get_text(" ", strip=True)
        if caption_text:
            title = caption_text
            caption = caption_text

    rows_data: list[list[str]] = []
    header_data: list[str] = []

    all_trs = table_node.find_all("tr")
    for tr_idx, tr in enumerate(all_trs):
        th_cells = tr.find_all("th")
        td_cells = tr.find_all("td")
        if th_cells and not header_data:
            header_data = [th.get_text(" ", strip=True) for th in th_cells]
        else:
            cells = [cell.get_text(" ", strip=True) for cell in (th_cells or td_cells if not th_cells else tr.find_all(["th", "td"]))]
            if any(cells):
                if not header_data and tr_idx == 0:
                    header_data = cells
                else:
                    rows_data.append(cells)

    if not header_data and not rows_data:
        return None

    return ExtractedTableSchema(
        title=title,
        headers=header_data,
        rows=rows_data,
        caption=caption,
    )


def _attach_tables_missing_from_examples(extraction, parsed_patent) -> None:
    """
    Keep experimental tables that the plain-text example split did not already contain.
    Preserves tables as both structured ExtractedTableSchema and formatted Markdown.
    """
    covered = "\n".join(
        (ex.raw_text or "") for ex in extraction.examples
    )
    covered_compact = "".join(covered.split())
    for index, table in enumerate(getattr(parsed_patent, "tables", None) or [], start=1):
        html = table.get("html", "") if isinstance(table, dict) else ""
        structured_tbl = _extract_structured_table(html, default_title=f"Table {index}")
        if not structured_tbl:
            continue
        text = structured_tbl.to_markdown()
        if len(text) < 20:
            continue
        probe = "".join(text[:180].split())
        if probe and probe in covered_compact:
            continue
        extraction.synthesis_sections.append(
            SynthesisSection(section_title=structured_tbl.title or f"Table {index}", raw_text=text)
        )
        if hasattr(extraction, "tables"):
            extraction.tables.append(structured_tbl)

# No LLM prompts needed as this is now 100% deterministic.



class ExtractorService:
    def __init__(self):
        pass



    def validate_extraction(self, ext: PatentExtraction) -> bool:
        """Validate that the extracted patent contains essential synthesis information."""
        if getattr(ext.metadata, "patent_number", "Not disclosed") == "Not disclosed" or getattr(ext.metadata, "patent_title", "Not disclosed") == "Not disclosed":
            logger.warning("Extraction validation failed: Missing Patent Number or Title")
            return False
        return True

    async def extract_polymerization_data(self, parsed_patent, url: str = "", profile=None) -> PatentExtraction | None:
        """Deterministically extract structured examples and filter out excluded variants."""
        import re
        logger.info("[EXTRACTION] Deterministically extracting data for %s", parsed_patent.patent_number)
        
        try:
            extraction = PatentExtraction()
            extraction.metadata.url = url
            extraction.metadata.patent_number = parsed_patent.patent_number or "Not disclosed"
            extraction.metadata.patent_title = parsed_patent.title or "Not disclosed"
            extraction.metadata.assignee = (parsed_patent.assignee or "").strip() or "Not disclosed"
            extraction.metadata.jurisdiction = parsed_patent.jurisdiction or "Not disclosed"
            extraction.metadata.publication_year = parsed_patent.publication_date[:4] if parsed_patent.publication_date else "Not disclosed"
            source_status = (
                (parsed_patent.metadata or {}).get("legal_status") or ""
            ).strip()
            if source_status and source_status.lower() not in {"unknown", "patent", "not disclosed"}:
                extraction.metadata.legal_status = source_status
            
            if parsed_patent.claims:
                extraction.claims = [c.strip() for c in parsed_patent.claims.split('\n') if c.strip()]
            
            excluded_variants = []
            if profile and hasattr(profile, 'excluded_variants'):
                excluded_variants = [v.lower() for v in profile.excluded_variants]
                
            from app.services.pipeline.schemas import PatentExample, SynthesisSection
            from app.services.pipeline.example_boundaries import split_example_sections
            
            # Structural Example Extraction
            examples_found = 0
            examples_source_text = parsed_patent.examples or ""
            sections = split_example_sections(examples_source_text)

            # If the dedicated examples field has no section headings, try the
            # full description (same patterns — formatting gap, not jurisdiction).
            if not sections and parsed_patent.detailed_description:
                sections = split_example_sections(parsed_patent.detailed_description)
                if sections:
                    examples_source_text = parsed_patent.detailed_description

            logger.info(
                "Example sections found (line-start split count): %d",
                len(sections),
            )

            if not sections:
                # No clear example boundaries. Preserve available text as synthesis context.
                if examples_source_text.strip():
                    ex_text = examples_source_text
                    extraction.synthesis_sections.append(
                        SynthesisSection(
                            section_title="Examples Block (unsegmented)",
                            raw_text=ex_text,
                        )
                    )
                    extraction.examples_detection_note = (
                        "No numbered/worked-example section headings were detected; "
                        "unsegmented process text retained for report evidence."
                    )
                else:
                    extraction.examples_detection_note = (
                        "No worked-example sections were present in the patent text; "
                        "report evidence falls back to claims/description."
                    )
            else:
                seen_counts: dict[str, int] = {}
                for header, body in sections:
                    if not (body or "").strip():
                        continue
                    norm_key = " ".join(header.lower().split())
                    seen_counts[norm_key] = seen_counts.get(norm_key, 0) + 1
                    example_id = header
                    if seen_counts[norm_key] > 1:
                        example_id = f"{header} (#{seen_counts[norm_key]})"
                    ex = PatentExample(
                        example_id=example_id,
                        example_type="Extracted Example",
                        title=header,
                        raw_text=header + "\n" + body,
                    )
                    extraction.examples.append(ex)
                    examples_found += 1
            _attach_tables_missing_from_examples(extraction, parsed_patent)
            
            # Description Fallback (if no examples or very few)
            if examples_found == 0 and parsed_patent.detailed_description:
                desc = parsed_patent.detailed_description
                extraction.synthesis_sections.append(SynthesisSection(section_title="Detailed Description", raw_text=desc))
                
            extraction.raw_text = (
                (parsed_patent.title or "") + "\n"
                + (parsed_patent.abstract or "") + "\n"
                + (parsed_patent.claims or "")
            )
                
            raw_chars = len(parsed_patent.detailed_description or "") + len(parsed_patent.examples or "")
            table_count = len(getattr(parsed_patent, "tables", []) or [])
            logger.info(
                "[FULL EVIDENCE] Patent: %s | Title: %s | Raw chars: %d | Examples: %d | Tables: %d",
                extraction.metadata.patent_number,
                extraction.metadata.patent_title,
                raw_chars,
                examples_found,
                table_count,
            )
            for ex in extraction.examples:
                logger.info("- %s", ex.example_id)
            if examples_found == 0:
                logger.info("No strict example sections found. Added synthesis_sections.")
                
            return extraction
        except Exception as e:
            logger.error("Deterministic Extraction failed: %s", e)
            return None
