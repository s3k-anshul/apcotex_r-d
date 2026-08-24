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
            extraction.metadata.assignee = parsed_patent.assignee or "Not disclosed"
            extraction.metadata.jurisdiction = parsed_patent.jurisdiction or "Not disclosed"
            extraction.metadata.publication_year = parsed_patent.publication_date[:4] if parsed_patent.publication_date else "Not disclosed"
            
            if parsed_patent.claims:
                extraction.claims = [c.strip() for c in parsed_patent.claims.split('\n') if c.strip()][:10]
            
            excluded_variants = []
            if profile and hasattr(profile, 'excluded_variants'):
                excluded_variants = [v.lower() for v in profile.excluded_variants]
                
            from app.services.pipeline.schemas import PatentExample, SynthesisSection
            
            # Structural Example Extraction
            examples_found = 0
            if parsed_patent.examples:
                # Fix: only split on Example headers that appear at the START of a line or paragraph.
                # This prevents mid-sentence cross-references ("as described in Example 1",
                # "shown in Example 3") from being treated as new section boundaries.
                example_pattern = (
                    r"(?:(?<=\n)|(?<=\r\n)|^)"
                    r"(?:Example|Comparative Example|Preparation Example|Experimental Example|Synthesis Example)"
                    r"\s+(?:\d+[a-zA-Z]?|[a-zA-Z])\b[\.\:]?"
                )
                blocks = re.split(f"({example_pattern})", parsed_patent.examples, flags=re.IGNORECASE | re.MULTILINE)
                
                before_count = sum(1 for b in blocks[1::2] if b.strip())
                logger.info("Example sections found (line-start split count): %d", before_count)
                
                if len(blocks) <= 1:
                    # No clear example boundaries found. Preserve as synthesis_section.
                    ex_text = parsed_patent.examples
                    if len(ex_text) > 40000:
                        ex_text = ex_text[:40000] + "\n[... TRUNCATED ...]"
                    extraction.synthesis_sections.append(SynthesisSection(section_title="Examples Block", raw_text=ex_text))
                else:
                    # Dedup: normalize header for comparison (lowercase + collapse whitespace)
                    # but preserve original casing in the stored example_id.
                    seen_normalized: dict[str, int] = {}  # normalized_key -> index in extraction.examples
                    for i in range(1, len(blocks), 2):
                        header = blocks[i].strip()
                        body = blocks[i+1].strip() if i+1 < len(blocks) else ""
                        full_example_text = header + "\n" + body

                        if len(full_example_text) > 15000:
                            full_example_text = full_example_text[:15000] + "\n[... TRUNCATED DUE TO LENGTH ...]"

                        # Normalized key for dedup (case-insensitive, whitespace-collapsed)
                        norm_key = " ".join(header.lower().split())

                        if norm_key in seen_normalized:
                            # Merge body into the existing example (same section, different case)
                            existing_idx = seen_normalized[norm_key]
                            existing = extraction.examples[existing_idx]
                            merged = existing.raw_text.rstrip() + "\n" + body
                            if len(merged) > 15000:
                                merged = merged[:15000] + "\n[... TRUNCATED DUE TO LENGTH ...]"
                            extraction.examples[existing_idx] = PatentExample(
                                example_id=existing.example_id,
                                example_type=existing.example_type,
                                title=existing.title,
                                raw_text=merged
                            )
                        else:
                            ex = PatentExample(
                                example_id=header,
                                example_type="Extracted Example",
                                title=header,
                                raw_text=full_example_text
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
