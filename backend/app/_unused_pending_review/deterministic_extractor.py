import re
import logging
from typing import List, Dict, Optional
from app.services.pipeline.schemas import ParsedPatent, PatentExtraction, ExtractedParameterSchema

logger = logging.getLogger(__name__)

class DeterministicExtractor:
    def __init__(self):
        # Common chemistry units
        self.units = r'(?:°C|degrees C|parts by weight|parts|phr|wt%|wt %|mol%|mol %|hours?|hrs?|minutes?|mins?|MPa|bar|g|mg|kg|ml|L|%)'
        
        # Chemical prefixes/suffixes or ALL CAPS abbreviations
        self.chem_pattern = r'\b(?:[A-Z][a-z]+(?:ene|ide|ate|ol|amine|ane|acid|sulfate|chloride)|[A-Z0-9\-]{2,25})\b'
        
        # Categories mapping based on keywords
        self.category_map = {
            "temperature": "Reaction Conditions",
            "time": "Reaction Conditions",
            "hours": "Reaction Conditions",
            "minutes": "Reaction Conditions",
            "pressure": "Reaction Conditions",
            "yield": "Process Variables",
            "conversion": "Process Variables",
            "initiator": "Raw Materials",
            "catalyst": "Raw Materials",
            "emulsifier": "Raw Materials",
            "monomer": "Raw Materials",
            "water": "Raw Materials",
            "solid content": "Polymer Properties",
            "viscosity": "Polymer Properties"
        }

    def _determine_category(self, name: str) -> str:
        name_lower = name.lower()
        for kw, cat in self.category_map.items():
            if kw in name_lower:
                return cat
        
        # If it looks like a chemical, default to Raw Materials
        if re.search(self.chem_pattern, name):
            return "Raw Materials"
            
        return "Other"

    def _validate_and_merge(self, parameters: List[ExtractedParameterSchema]) -> tuple[List[ExtractedParameterSchema], int]:
        """
        Phase 5: Extraction Validation Layer.
        Rejects hallucinated values, duplicate parameters, and merges repeated values.
        """
        candidate_count = len(parameters)
        valid_params = []
        for p in parameters:
            # Reject if Name or Value is missing
            if not p.name or not p.value or p.value == "Not disclosed":
                continue
            
            # Reject if the source sentence doesn't actually contain the value (Hallucination check)
            if p.value not in p.source_sentence:
                continue
                
            valid_params.append(p)
            
        # Merge duplicates (Same Name and Same Value)
        merged_map: Dict[str, ExtractedParameterSchema] = {}
        for p in valid_params:
            key = f"{p.name.lower()}_{p.value}_{p.unit.lower()}"
            if key not in merged_map:
                merged_map[key] = p
                
        return list(merged_map.values()), candidate_count

    def _extract_entities(self, text: str, section: str = "EXPERIMENTAL PROCEDURES & EXAMPLES") -> tuple[List[ExtractedParameterSchema], int]:
        parameters = []
        # Keep track of sentence offsets
        current_offset = 0
        sentences = text.replace('\n', ' ').split('. ')
        
        current_example = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                current_offset += 2 # account for '. '
                continue
                
            # Track current example heading
            ex_match = re.search(r'(?i)(example\s+\d+|experimental example[\s\d]*)', sentence)
            if ex_match:
                current_example = ex_match.group(0).strip().title()
                
            # Pattern 1: [Value] + [Unit] + of + [Chemical]
            # e.g., "100 parts of MDI" or "MDI (100 parts)"
            stop_words = {"the", "by", "in", "of", "to", "and", "or", "for", "with", "from", "at", "as", "is", "a", "an", "des", "on", "was", "were", "are", "about", "approximately"}
            
            matches = re.finditer(rf'(\d+(?:\.\d+)?)\s*({self.units})\s+(?:of\s+)?([A-Za-z0-9\-]+(?:ene|ide|ate|ol|amine|ane|acid|sulfate|chloride)|[A-Z0-9\-]{{2,25}})', sentence, re.IGNORECASE)
            for m in matches:
                value = m.group(1)
                unit = m.group(2)
                chem_name = m.group(3)
                
                if chem_name.lower() in stop_words:
                    continue
                    
                chem_name = chem_name.capitalize()
                
                parameters.append(ExtractedParameterSchema(
                    name=chem_name,
                    category="Raw Materials",
                    value=value,
                    unit=unit,
                    context=f"{value} {unit} of {chem_name}",
                    section=section,
                    example_number=current_example,
                    source_sentence=sentence,
                    confidence=0.9,
                    source_offset=current_offset + m.start()
                ))
                
            # Pattern 2: [Keyword] ... [Value] + [Unit]
            keywords = ["temperature", "pressure", "yield", "conversion", "time", "solid content", "viscosity", "initiator", "emulsifier"]
            for kw in keywords:
                kw_match = re.search(rf'(?i){kw}.{{0,50}}?\b(\d+(?:\.\d+)?)\s*({self.units})(?!\w)', sentence)
                if kw_match:
                    value = kw_match.group(1)
                    unit = kw_match.group(2)
                    
                    parameters.append(ExtractedParameterSchema(
                        name=kw.title(),
                        category=self._determine_category(kw),
                        value=value,
                        unit=unit,
                        context=f"{kw} ... {value} {unit}",
                        section=section,
                        example_number=current_example,
                        source_sentence=sentence,
                        confidence=0.95,
                        source_offset=current_offset + kw_match.start()
                    ))
                    
            # Pattern 3 (Orphan Conditions) IS REMOVED to prevent counting isolated numbers as instructed.

            current_offset += len(sentence) + 2

        return self._validate_and_merge(parameters)

    # Structured mapping removed because the schema is now fully dynamic.
    # The parameters list contains all extracted data.

    def extract(self, parsed_patent: ParsedPatent, initial_json: PatentExtraction, profile = None) -> tuple[PatentExtraction, int]:
        """
        Stage 6: Deterministic Extraction.
        Dynamically generates meaningful entities (Field + Value + Context).
        """
        logger.debug(f"Running Deterministic Extraction on {initial_json.metadata.patent_number}...")
        
        from app.services.pipeline.parser_service import ParserService
        parser = ParserService()
        blocks = parser.detect_recipe_blocks(parsed_patent)
        
        total_candidates = 0
        
        # Check downstream terms
        downstream_terms = [t.lower() for t in profile.downstream_application_terms] if profile and hasattr(profile, 'downstream_application_terms') else []
        
        if not blocks:
            # Fallback to detailed description if no examples detected
            text = parsed_patent.detailed_description or ""
            final_params, candidate_count = self._extract_entities(text, section="DETAILED DESCRIPTION")
            initial_json.parameters = final_params
            total_candidates += candidate_count
            logger.debug(f"Deterministic extraction found {len(final_params)} parameters in Detailed Description.")
        else:
            total_params = 0
            all_params = []
            for block in blocks:
                # Dynamic Downstream check
                if downstream_terms:
                    text_lower = block.raw_text.lower()
                    downstream_hits = sum(1 for term in downstream_terms if term in text_lower)
                    if downstream_hits >= 3:
                        logger.debug(f"Skipping block '{block.title}' due to downstream application terms.")
                        continue

                # Extract specifically from this block
                params, c_count = self._extract_entities(block.raw_text, section=block.title)
                block.extracted_parameters = params
                
                total_candidates += c_count
                total_params += len(params)
                all_params.extend(params)

                
            initial_json.examples = blocks
            initial_json.parameters = all_params  # Aggregate all parameters from blocks
            logger.info(f"Deterministic extraction found {total_params} parameters across {len(blocks)} segmented examples.")
        
        # Mapping removed.
            
        return initial_json, total_candidates
