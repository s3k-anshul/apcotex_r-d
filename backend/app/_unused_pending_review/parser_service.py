"""
app/services/pipeline/parser_service.py

Performs deterministic, rule-based extraction to pre-fill the PatentExtraction JSON.
Parses HTML tables into structured JSON.
"""
import logging
import re
from bs4 import BeautifulSoup
from typing import Dict, Any

from app.services.pipeline.schemas import ParsedPatent, PatentExtraction

logger = logging.getLogger(__name__)

class ParserService:
    def __init__(self):
        pass

    def parse_tables(self, html_tables: list[Dict[str, str]]) -> str:
        """
        Converts a list of HTML tables into a structured Markdown representation
        so the LLM can easily read it without noisy HTML tags.
        """
        parsed_tables = []
        for i, table_dict in enumerate(html_tables):
            html = table_dict.get("html", "")
            title = table_dict.get("title", f"Table {i+1}")
            if not html:
                continue
                
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.find_all("tr")
            
            table_data = []
            for r_idx, row in enumerate(rows):
                cells = [cell.get_text(strip=True).replace("\n", " ").replace("|", " ") for cell in row.find_all(["th", "td"])]
                if any(cells):  # Skip empty rows
                    table_data.append("| " + " | ".join(cells) + " |")
                    # Add markdown header separator after first row
                    if r_idx == 0:
                        table_data.append("|" + "|".join(["---" for _ in cells]) + "|")
            
            if table_data:
                parsed_tables.append(f"{title}:\n" + "\n".join(table_data))
                
        return "\n\n".join(parsed_tables)

    def detect_recipe_blocks(self, parsed: ParsedPatent) -> list['PatentExample']:
        """
        Identify distinct recipe blocks using flexible section detection.
        """
        text = ""
        if parsed.examples:
            text += parsed.examples + "\n"
        if parsed.tables:
            text += self.parse_tables(parsed.tables) + "\n"
            
        if not text:
            text = parsed.detailed_description

        # Flexible detection for sections as requested
        # Example, Example 1, Experimental Example, Preparation Example, Working Example,
        # Polymerization Example, Synthesis Example, Preparation of Polymer, Polymer Preparation,
        # Polymerization Procedure, Synthesis Procedure, Experimental Procedure, Production Process,
        # Manufacturing Process, Detailed Description
        
        headers = [
            r"Example\s*\d*",
            r"Experimental Example\s*\d*",
            r"Preparation Example\s*\d*",
            r"Working Example\s*\d*",
            r"Polymerization Example\s*\d*",
            r"Synthesis Example\s*\d*",
            r"Preparation of Polymer\s*\d*",
            r"Polymer Preparation\s*\d*",
            r"Polymerization Procedure\s*\d*",
            r"Synthesis Procedure\s*\d*",
            r"Experimental Procedure\s*\d*",
            r"Production Process\s*\d*",
            r"Manufacturing Process\s*\d*",
            r"Comparative Example\s*\d*",
            r"General Procedure",
            r"General Polymerization Procedure",
            r"Process for Producing",
            r"Reaction Procedure",
            r"Preparation\s*\d*",
            r"Polymerization\s*\d*",
            r"Experimental",
            r"Synthesis",
            r"Detailed Description"
        ]
        
        # Build one big regex: matches start-of-string or newline, followed by any header, optionally a colon or dash, then newline
        pattern_str = r'(?:^|\n)(' + '|'.join(headers) + r')[\s:\-]*\n'
        pattern = re.compile(pattern_str, re.IGNORECASE)
        
        parts = pattern.split(text)
        from app.services.pipeline.schemas import PatentExample
        blocks = []
        
        if len(parts) == 1:
            # No headers found, just return one big block if it's large enough
            if len(parts[0].strip()) > 50:
                blocks.append(PatentExample(
                    number="1",
                    type="GENERAL PROCEDURE",
                    title="General Procedure",
                    raw_text=parts[0].strip()
                ))
        else:
            for i in range(1, len(parts), 2):
                header = parts[i].strip()
                body = parts[i+1].strip() if i+1 < len(parts) else ""
                if len(body) > 50:
                    # Extract number if present
                    num_match = re.search(r'\d+', header)
                    number = num_match.group(0) if num_match else ""
                    
                    # Determine type
                    ex_type = "EXAMPLE"
                    if "comparative" in header.lower():
                        ex_type = "COMPARATIVE EXAMPLE"
                    elif "preparation" in header.lower() or "synthesis" in header.lower():
                        ex_type = "PREPARATION"
                        
                    blocks.append(PatentExample(
                        number=number,
                        type=ex_type,
                        title=header.upper(),
                        raw_text=body
                    ))
                
        return blocks

    def retrieve_targeted_evidence(self, parsed: ParsedPatent, missing_keywords: list[str], max_chars: int = 10000) -> str:
        """
        Targeted retrieval: ranks paragraphs by evidence value and returns the most relevant sections.
        """
        import json
        
        all_text_blocks = []
        
        # 1. Structure the blocks
        if parsed.abstract:
            all_text_blocks.append(("Abstract", parsed.abstract))
        if parsed.claims:
            all_text_blocks.append(("Claims", parsed.claims))
            
        # Incorporate detected examples if they exist
        blocks = self.detect_recipe_blocks(parsed)
        for b_idx, b in enumerate(blocks):
            all_text_blocks.append((b.title or f"Example {b_idx}", b.raw_text))
            
        for t_idx, t in enumerate(parsed.tables):
            parsed_t = self.parse_tables([t])
            all_text_blocks.append((f"Table {t_idx+1}", parsed_t))
            
        # Detailed description as fallback
        if parsed.detailed_description:
            all_text_blocks.append(("Detailed Description", parsed.detailed_description))
            
        for sec in getattr(parsed, 'structured_sections', []):
            all_text_blocks.append((sec.name, sec.text))
            
        # 2. Score paragraphs
        scored_paragraphs = []
        
        high_value_sections = ["example", "preparation", "synthesis", "table", "procedure", "process"]
        
        kw_lower_list = [kw.lower() for kw in missing_keywords]
        
        for section_name, text in all_text_blocks:
            paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 20]
            section_lower = section_name.lower()
            
            # Base section score
            section_score = 0
            if any(hv in section_lower for hv in high_value_sections):
                section_score += 50
                
            for i, p in enumerate(paragraphs):
                p_lower = p.lower()
                score = section_score
                
                # Boost for keywords
                kw_matches = sum(1 for kw in kw_lower_list if kw in p_lower)
                score += (kw_matches * 20)
                
                # Boost for chemical/process terms
                if "part" in p_lower or "wt%" in p_lower or "ratio" in p_lower:
                    score += 15
                if "temperature" in p_lower or "°c" in p_lower or "pressure" in p_lower:
                    score += 15
                if "initiator" in p_lower or "catalyst" in p_lower or "emulsifier" in p_lower:
                    score += 15
                    
                if score > 0:
                    scored_paragraphs.append({
                        "section": section_name,
                        "index": i,
                        "text": p,
                        "score": score,
                        "total_paragraphs": len(paragraphs),
                        "all_paragraphs": paragraphs
                    })
                    
        # 3. Sort by score
        scored_paragraphs.sort(key=lambda x: x["score"], reverse=True)
        
        # 4. Extract top paragraphs with surrounding context
        evidence_blocks = []
        total_chars = 0
        added_keys = set()
        
        for sp in scored_paragraphs:
            section_name = sp["section"]
            i = sp["index"]
            paragraphs = sp["all_paragraphs"]
            
            start_idx = max(0, i-1)
            end_idx = min(len(paragraphs), i+2)
            
            block_text = ""
            for j in range(start_idx, end_idx):
                pid = f"{section_name}_{j}"
                if pid not in added_keys:
                    added_keys.add(pid)
                    block_text += paragraphs[j] + "\n"
                    
            if block_text:
                block_len = len(block_text)
                if total_chars + block_len > max_chars:
                    # Allow one partial truncation if it's the very first block, otherwise break
                    if total_chars == 0:
                        block_text = block_text[:max_chars]
                    else:
                        break
                        
                evidence_blocks.append({
                    "section": section_name,
                    "text": block_text.strip()
                })
                total_chars += len(block_text)
                
            if total_chars >= max_chars:
                break
                
        return json.dumps(evidence_blocks, indent=2)
