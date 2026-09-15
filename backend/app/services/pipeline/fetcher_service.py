"""
app/services/pipeline/fetcher_service.py

Downloads and parses patents from Google Patents or standard PDFs.
"""
import io
import logging
import re
import time
from typing import Optional

import httpx
from bs4 import BeautifulSoup
import pdfplumber

from app.services.pipeline.schemas import ParsedPatent, StructuralEvidence

logger = logging.getLogger(__name__)


class FetcherService:
    async def fetch_patent(self, url: str) -> Optional[ParsedPatent]:
        """Fetch full HTML and extract structured patent data."""
        logger.info("Fetching full patent content from %s...", url)
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(follow_redirects=True, limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)) as client:
                response = await client.get(url, timeout=30.0)
                response.raise_for_status()
                
                content_type = response.headers.get("Content-Type", "")
                if "application/pdf" in content_type.lower() or url.lower().endswith(".pdf"):
                    pdf_bytes = await response.aread()
                    parsed = self._parse_pdf(pdf_bytes)
                else:
                    html = response.text
                    # Explicit validation: ensure HTML is not empty
                    if not html or len(html.strip()) == 0:
                        raise ValueError("Parser Error: Received empty HTML content from Google Patents.")
                        
                    parsed = self._parse_google_patents_html(html)
                    
                    if not parsed:
                        raise ValueError("Parser Error: _parse_google_patents_html returned None for valid HTML.")
                        
                parsed.url = url
                parsed.patent_number = parsed.metadata.get("patent_number") or url.split("/")[-2]
                parsed.title = parsed.metadata.get("google_patents_title") or parsed.metadata.get("DC.title") or ""
                parsed.jurisdiction = parsed.metadata.get("jurisdiction") or parsed.patent_number[:2].upper() if parsed.patent_number else ""
                parsed.publication_date = parsed.metadata.get("publication_date") or parsed.metadata.get("DC.date") or ""
                parsed.assignee = parsed.metadata.get("assignee") or ""
                
                # Check for completely empty parsing
                if not parsed.abstract and not parsed.detailed_description and not parsed.claims:
                    raise ValueError(f"Parser Error: Failed to extract any meaningful content (abstract, description, claims) for {parsed.patent_number}.")
                
                duration_ms = int((time.time() - start_time) * 1000)
                logger.debug("PATENT FETCH")
                logger.debug("-" * 12)
                logger.debug(f"Patent: {parsed.metadata.get('patent_number', 'UNKNOWN')}")
                logger.debug(f"URL: {url}")
                logger.debug(f"HTTP Status: {response.status_code}")
                logger.debug(f"HTML Bytes: {len(response.content)}")
                logger.debug(f"Description Chars: {len(parsed.detailed_description or '')}")
                logger.debug(f"Claims Chars: {len(parsed.claims or '')}")
                logger.debug(f"Examples: {len(parsed.examples)}")
                logger.debug(f"Latency: {duration_ms}ms")
                logger.debug(f"Status: SUCCESS")
                logger.debug("=" * 60)
                
                return parsed
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching patent from %s: %s", url, e)
            raise e
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.debug("PATENT FETCH")
            logger.debug("-" * 12)
            logger.debug(f"Patent: UNKNOWN")
            logger.debug(f"URL: {url}")
            logger.debug(f"HTTP Status: N/A")
            logger.debug(f"HTML Bytes: 0")
            logger.debug(f"Description Chars: 0")
            logger.debug(f"Claims Chars: 0")
            logger.debug(f"Examples: 0")
            logger.debug(f"Latency: {duration_ms}ms")
            logger.debug(f"Status: FAILED ({type(e).__name__})")
            logger.debug("=" * 60)
            
            logger.error("Failed to fetch patent from %s: %s", url, e)
            return None

    async def fetch_patent_metadata(self, url: str) -> Optional[dict]:
        """
        Lightweight fetch to extract authoritative title and basic metadata from Google Patents HTML.
        Does not parse full text/examples.
        """
        logger.info("Fetching lightweight metadata from %s...", url)
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, timeout=15.0)
                response.raise_for_status()
                
                content_type = response.headers.get("Content-Type", "")
                if "application/pdf" in content_type.lower() or url.lower().endswith(".pdf"):
                    return {"url": url, "google_patents_title": "", "publication_date": "", "canonical_url": url}
                    
                soup = BeautifulSoup(response.text, "html.parser")
                meta_data = {"url": url, "google_patents_title": "", "publication_date": "", "canonical_url": url, "jurisdiction": "", "abstract": "", "claims": "", "cpc_ipc": [], "assignee": ""}
                
                dc_title = soup.find("meta", {"name": "DC.title"})
                citation_title = soup.find("meta", {"name": "citation_title"})
                
                if dc_title and dc_title.get("content"):
                    meta_data["google_patents_title"] = dc_title.get("content").strip()
                elif citation_title and citation_title.get("content"):
                    meta_data["google_patents_title"] = citation_title.get("content").strip()
                else:
                    title_tag = soup.find("title")
                    if title_tag:
                        raw_title = title_tag.get_text(strip=True)
                        raw_title = re.sub(r' - Google Patents$', '', raw_title, flags=re.IGNORECASE).strip()
                        meta_data["google_patents_title"] = raw_title
                        
                canonical = soup.find("link", {"rel": "canonical"})
                if canonical and canonical.get("href"):
                    meta_data["canonical_url"] = canonical.get("href")
                    match = re.search(r'patents\.google\.com/patent/([A-Z]{2}\d+[A-Z\d]*)', meta_data["canonical_url"])
                    if match:
                        pn = match.group(1)
                        meta_data["patent_number"] = pn
                        meta_data["jurisdiction"] = pn[:2].upper()
                        
                dc_date = soup.find("meta", {"name": "DC.date"})
                if dc_date and dc_date.get("content"):
                    meta_data["publication_date"] = dc_date.get("content")
                    
                abstract_node = soup.find("section", {"itemprop": "abstract"})
                if abstract_node:
                    meta_data["abstract"] = abstract_node.get_text(separator="\n", strip=True)
                    
                claims_node = soup.find("section", {"itemprop": "claims"})
                if claims_node:
                    meta_data["claims"] = claims_node.get_text(separator="\n", strip=True)
                    
                assignee_node = soup.find("meta", {"scheme": "assignee"}) or soup.find("meta", {"name": "DC.contributor"})
                if assignee_node and assignee_node.get("content"):
                    meta_data["assignee"] = assignee_node.get("content")
                    
                cpc_nodes = soup.find_all("span", {"itemprop": "Code"})
                for node in cpc_nodes:
                    meta_data["cpc_ipc"].append(node.get_text(strip=True))
                meta_data["cpc_ipc"] = list(set(meta_data["cpc_ipc"]))
                
                # Extract Legal Status
                meta_data["legal_status"] = "Unknown"
                status_node = soup.find("span", {"itemprop": "status"})
                if status_node:
                    meta_data["legal_status"] = status_node.get_text(strip=True)
                else:
                    dc_type = soup.find("meta", {"name": "DC.type"})
                    if dc_type and dc_type.get("content"):
                        meta_data["legal_status"] = dc_type.get("content").strip()
                    
                return meta_data
        except Exception as e:
            logger.error("Failed to fetch lightweight metadata from %s: %s", url, e)
            return None

    async def fetch_selection_evidence(
        self,
        url: str,
        *,
        strategy_tokens: set[str] | None = None,
        abstract_limit: int = 1500,
        claims_limit: int = 2500,
    ) -> dict | None:
        """
        Lightweight evidence pack for authoritative selection (not full-text extraction).

        Reuses fetch_patent_metadata — abstract + truncated claims/metadata only.
        Optionally prefers claim paragraphs overlapping strategy_tokens (from the
        current research strategy), without any material-specific hardcoding.
        """
        meta = await self.fetch_patent_metadata(url)
        if not meta:
            return None

        abstract = (meta.get("abstract") or "")[:abstract_limit]
        claims_raw = meta.get("claims") or ""
        claims_excerpt = self._claims_excerpt_for_selection(
            claims_raw,
            strategy_tokens=strategy_tokens or set(),
            limit=claims_limit,
        )

        sources: list[str] = []
        if meta.get("google_patents_title"):
            sources.append("title")
        if abstract:
            sources.append("abstract")
        if claims_excerpt:
            sources.append("claims")
        if meta.get("assignee"):
            sources.append("metadata")

        return {
            "url": meta.get("url") or url,
            "patent_number": meta.get("patent_number") or "",
            "title": meta.get("google_patents_title") or "",
            "abstract": abstract,
            "claims_excerpt": claims_excerpt,
            "assignee": meta.get("assignee") or "",
            "publication_date": meta.get("publication_date") or "",
            "jurisdiction": meta.get("jurisdiction") or "",
            "legal_status": meta.get("legal_status") or "",
            "cpc_ipc": meta.get("cpc_ipc") or [],
            "evidence_sources": sources,
        }

    @staticmethod
    def _claims_excerpt_for_selection(
        claims_text: str,
        *,
        strategy_tokens: set[str],
        limit: int,
    ) -> str:
        """Bounded claims excerpt; prefer paragraphs overlapping strategy tokens."""
        if not claims_text:
            return ""
        if not strategy_tokens:
            return claims_text[:limit]

        paragraphs = [p.strip() for p in re.split(r"\n+", claims_text) if p.strip()]
        preferred: list[str] = []
        fallback: list[str] = []
        for para in paragraphs:
            toks = set(re.findall(r"\b[a-zA-Z]{3,}\b", para.lower()))
            if strategy_tokens.intersection(toks):
                preferred.append(para)
            else:
                fallback.append(para)

        ordered = preferred + fallback
        out: list[str] = []
        size = 0
        for para in ordered:
            if size >= limit:
                break
            chunk = para if size + len(para) <= limit else para[: max(0, limit - size)]
            if chunk:
                out.append(chunk)
                size += len(chunk) + 1
        return "\n".join(out)

    def _parse_pdf(self, pdf_bytes: bytes) -> ParsedPatent:
        """Extract text from a PDF file using pdfplumber."""
        logger.info("Parsing PDF content...")
        text_pages = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_pages.append(text)
            
            # For PDF, we just dump everything into detailed_description since we lack HTML tags
            # Rule-based extraction will still run on it, but it's less structured.
            return ParsedPatent(detailed_description="\n".join(text_pages))
        except Exception as e:
            logger.error("PDF parsing failed: %s", e)
            return ""

    def _parse_google_patents_html(self, html: str) -> ParsedPatent:
        """
        Extract meaningful sections from Google Patents HTML.
        """
        logger.info("Parsing Google Patents HTML...")
        soup = BeautifulSoup(html, "html.parser")
        
        parsed = ParsedPatent()
        
        # 1. Extract metadata from meta tags
        meta_tags = soup.find_all("meta")
        for meta in meta_tags:
            name = meta.get("name") or meta.get("property")
            content = meta.get("content")
            if name and content and (name.startswith("DC.") or name.startswith("citation_")):
                parsed.metadata[name] = content

        # Authoritative assignee (same sources as lightweight fetch_patent_metadata)
        assignee_node = (
            soup.find("meta", {"scheme": "assignee"})
            or soup.find("meta", {"name": "DC.contributor"})
            or soup.find("meta", {"name": "citation_author"})
        )
        if assignee_node and assignee_node.get("content"):
            parsed.metadata["assignee"] = assignee_node.get("content").strip()
        elif parsed.metadata.get("DC.contributor"):
            parsed.metadata["assignee"] = str(parsed.metadata["DC.contributor"]).strip()

        # Remove noisy elements
        for tag in soup(["script", "style", "nav", "footer", "meta", "link", "noscript"]):
            tag.decompose()
            
        # Google Patents specific: remove citation lists, patent classifications
        for tag in soup.find_all(class_=re.compile("classification|citation|legal|history", re.IGNORECASE)):
            tag.decompose()

        # Extract abstract
        abstract_node = soup.find("section", {"itemprop": "abstract"})
        if abstract_node:
            parsed.abstract = abstract_node.get_text(separator="\n", strip=True)
            
        # Extract claims
        claims_node = soup.find("section", {"itemprop": "claims"})
        if claims_node:
            parsed.claims = claims_node.get_text(separator="\n", strip=True)
            
        # Extract tables from description BEFORE pulling text
        description_node = soup.find("section", {"itemprop": "description"})
        
        if description_node:
            # We want to segment description into Summary, Examples, Detailed Desc.
            # Google Patents doesn't strictly tag these, but often uses headers or bold text.
            # We'll just grab the full description and let the ParserService split it if needed,
            # or we can do a naive split here.
            # A common approach is to look for "Example", "Summary", etc in headings.
            
            # Pull tables first so they don't just become garbled text
            tables = description_node.find_all("table")
            for t in tables:
                # We'll pass the raw HTML of the table to the rule-based extractor
                parsed.tables.append({"html": str(t)})
                # We optionally remove them from text to reduce token count, but sometimes text refers to them.
                # Let's keep them in the text as plain text just in case, but they will be processed natively.
                
            desc_text = description_node.get_text(separator="\n", strip=True)
            parsed.detailed_description = desc_text
            
            # Phase 6: Structural Evidence
            from app.services.pipeline.schemas import StructuralEvidence
            from app.services.pipeline.example_boundaries import (
                EXAMPLE_BLOCK_START_RE,
                find_examples_block_start,
            )
            evidence = StructuralEvidence()
            
            # 1. Section Headings (Flexible detection — not mid-sentence "example")
            evidence.has_preparation_example = bool(re.search(r'preparation example', desc_text, re.IGNORECASE))
            evidence.has_experimental_example = bool(re.search(r'experimental example|experimental procedure', desc_text, re.IGNORECASE))
            evidence.has_working_example = bool(re.search(r'working example', desc_text, re.IGNORECASE))
            evidence.has_embodiment = bool(re.search(r'embodiment', desc_text, re.IGNORECASE))
            evidence.has_detailed_description = bool(re.search(r'detailed description', desc_text, re.IGNORECASE))
            evidence.has_claims = bool(parsed.claims)
            
            # 2. Extract Scientific Blocks (Examples & Procedures)
            ex_matches = list(EXAMPLE_BLOCK_START_RE.finditer(desc_text))
            evidence.example_count = len(ex_matches)
            
            start_idx = find_examples_block_start(desc_text)
            if start_idx is not None:
                parsed.examples = desc_text[start_idx:].strip()
            else:
                parsed.examples = ""
                
            # Populate structured sections using regex splitting
            # (PatentSection parsing has been removed as the deterministic pipeline directly uses ParsedPatent fields)
                
            evidence.table_count = len(parsed.tables)
            
            # 3. Counters (Reaction Conditions & Generic Entities)
            lower_text = desc_text.lower()
            evidence.temperature_count = lower_text.count("°c") + lower_text.count("degrees c") + lower_text.count("temperature")
            evidence.pressure_count = lower_text.count("mpa") + lower_text.count("bar") + lower_text.count("pressure")
            evidence.initiator_count = lower_text.count("initiator") + lower_text.count("catalyst")
            evidence.emulsifier_count = lower_text.count("emulsifier") + lower_text.count("surfactant") + lower_text.count("soap")
            evidence.chain_transfer_count = lower_text.count("chain transfer")
            evidence.conversion_count = lower_text.count("conversion") + lower_text.count("yield")
            evidence.coagulation_count = lower_text.count("coagulation") + lower_text.count("flocculation")
            evidence.wt_percent_count = lower_text.count("wt%") + lower_text.count("wt %") + lower_text.count("weight percent") + lower_text.count("mol%") + lower_text.count("mol %")
            evidence.phr_count = lower_text.count("phr") + lower_text.count("parts by weight")
            
            # Dynamic Chemical/Monomer Detection
            # CAS-like patterns (e.g. 100-42-5)
            cas_matches = len(re.findall(r'\b\d{2,7}-\d{2}-\d\b', desc_text))
            
                # Capitalized potential chemicals (generic heuristic — not material-specific)
            # Simple heuristic: capitalized word followed by chemical suffixes
            chem_matches = len(re.findall(r'\b[A-Z][a-z]+(?:ene|ide|ate|ol|amine|ane|acid)\b', desc_text))
            
            # 4. Densities
            total_len = len(desc_text) + 1
            num_count = len(re.findall(r'\d+\.?\d*', desc_text))
            evidence.numeric_density = num_count / total_len * 1000  # Numbers per 1000 chars
            evidence.example_density = evidence.example_count / total_len * 1000
            
            # Add dynamic chemical entities into the general density score or initiator score for Recipe Confidence
            evidence.initiator_count += cas_matches + (chem_matches // 10)
            
            parsed.structural_evidence = evidence
                
        else:
            # Fallback
            body = soup.find("body")
            if body:
                parsed.detailed_description = body.get_text(separator="\n", strip=True)
            else:
                parsed.detailed_description = soup.get_text(separator="\n", strip=True)
                
        # [DIAGNOSTIC LOGGING]
        html_bytes = len(html.encode("utf-8"))
        abs_len = len(parsed.abstract) if parsed.abstract else 0
        desc_len = len(parsed.detailed_description) if parsed.detailed_description else 0
        claims_len = len(parsed.claims) if parsed.claims else 0
        ex_count = parsed.structural_evidence.example_count if parsed.structural_evidence else 0
        
        logger.debug(f"[DIAGNOSTIC] FETCH: HTTP 200 | HTML bytes: {html_bytes}")
        logger.debug(f"[DIAGNOSTIC] PARSE: abstract length: {abs_len} | description length: {desc_len} | claims length: {claims_len} | examples found: {ex_count}")
        
        # Validation checks
        total_text_len = abs_len + desc_len + claims_len
        if total_text_len < 1000:
            logger.error("Parsed text is suspiciously short (length: %d), possible parsing failure.", total_text_len)
            
        return parsed

