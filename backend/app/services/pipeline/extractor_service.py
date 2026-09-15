"""
app/services/pipeline/extractor_service.py

Uses Gemini Structured Outputs to:
1. Batch rank discovered patents based on metadata (title/snippet).
2. Extract the detailed polymerization JSON parameters from the full document.
"""
import logging
from typing import List, Dict, Any

from app.core.config import settings
from app.services.pipeline.schemas import PatentExtraction, PatentRankList, PatentRank
from app.services.llm import llm_client

logger = logging.getLogger(__name__)

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
            
            if parsed_patent.claims:
                extraction.claims = [c.strip() for c in parsed_patent.claims.split('\n') if c.strip()][:10]
            
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
                    if len(ex_text) > 40000:
                        ex_text = ex_text[:40000] + "\n[... TRUNCATED ...]"
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
                seen_normalized: dict[str, int] = {}
                for header, body in sections:
                    full_example_text = header + "\n" + body
                    if len(full_example_text) > 15000:
                        full_example_text = (
                            full_example_text[:15000]
                            + "\n[... TRUNCATED DUE TO LENGTH ...]"
                        )
                    norm_key = " ".join(header.lower().split())
                    if norm_key in seen_normalized:
                        existing_idx = seen_normalized[norm_key]
                        existing = extraction.examples[existing_idx]
                        merged = existing.raw_text.rstrip() + "\n" + body
                        if len(merged) > 15000:
                            merged = merged[:15000] + "\n[... TRUNCATED DUE TO LENGTH ...]"
                        extraction.examples[existing_idx] = PatentExample(
                            example_id=existing.example_id,
                            example_type=existing.example_type,
                            title=existing.title,
                            raw_text=merged,
                        )
                    else:
                        ex = PatentExample(
                            example_id=header,
                            example_type="Extracted Example",
                            title=header,
                            raw_text=full_example_text,
                        )
                        seen_normalized[norm_key] = len(extraction.examples)
                        extraction.examples.append(ex)
                        examples_found += 1
            
            # Description Fallback (if no examples or very few)
            if examples_found == 0 and parsed_patent.detailed_description:
                desc = parsed_patent.detailed_description
                if len(desc) > 30000:
                    desc = desc[:30000] + "\n[... TRUNCATED ...]"
                extraction.synthesis_sections.append(SynthesisSection(section_title="Detailed Description", raw_text=desc))
                
            extraction.raw_text = ((parsed_patent.title or "") + "\n" + (parsed_patent.abstract or "") + "\n" + (parsed_patent.claims or ""))[:10000]
                
            logger.info("[EXTRACTION]")
            logger.info("Patent: %s", extraction.metadata.patent_number)
            logger.info("Title: %s", extraction.metadata.patent_title)
            logger.info("Raw text characters: %d", len(parsed_patent.detailed_description or "") + len(parsed_patent.examples or ""))
            logger.info("Example sections found: %d", examples_found)
            for ex in extraction.examples:
                logger.info("- %s", ex.example_id)
            if examples_found == 0:
                logger.info("No strict example sections found. Added synthesis_sections.")
                
            return extraction
        except Exception as e:
            logger.error("Deterministic Extraction failed: %s", e)
            return None
