"""
app/services/pipeline/report_evidence_service.py

Transforms raw PatentExtraction objects into compact ReportPatentEvidence.
Uses a single token budget derived from REPORT_SAFE_EVIDENCE_BUDGET (default 88K).

Architecture: 2 LLM calls per pipeline run (query expansion + report generation).
This service is deterministic only — zero LLM calls.

Key design decisions:
- EVERY selected patent appears in the evidence, even with 0 extracted parameters.
  0 params means "deterministic extractor found nothing", not "patent is useless".
  source_text (abstract + keyword-matched passages) provides the fallback.
- Parameters are priority-sorted by chemical significance, not just confidence.
- Examples are always included (even 0-param examples) — they carry source text context.
- The evidence budget (150K) is large enough to pass rich data for all 15 patents.
"""
import logging
import re
from typing import List, Dict, Optional

import tiktoken

from app.services.pipeline.schemas import (
    PatentExtraction, ReportPatentEvidence, ReportExampleEvidence,
    SynthesisSectionEvidence,
    ExtractedParameterSchema, BatchAnalysisResult, PatentBatchFindings
)
# Note: llm_client is NOT imported here — this service is deterministic only.
from app.services.prompts.patent_prompts import (
    CROSS_PATENT_ANALYSIS_SYSTEM_PROMPT,
    CROSS_PATENT_ANALYSIS_USER_TEMPLATE
)

logger = logging.getLogger(__name__)

# Max source_sentence length per parameter
MAX_SOURCE_SENTENCE_CHARS = 200   # increased to preserve provenance

# Max source_text per patent (chars) — abstract + claims + relevant passages
_MAX_SOURCE_TEXT_CHARS = 60000

# Compaction settings (initial — only tightened if total exceeds 150K budget)
_MAX_EXAMPLES_PER_PATENT = 20      # was 10
_MAX_PARAMS_PER_PATENT = 100        # was 60
_MAX_PARAMS_PER_PATENT_TIGHT = 50  # compaction pass 2
_MAX_EXAMPLES_TIGHT = 10            # compaction pass 1
_SOURCE_SENTENCE_TIGHT_CHARS = 120  # compaction pass 4

# Deterministic parameter priority keywords (ordered highest to lowest priority).
# Generic chemistry terms — NOT hardcoded to any specific compound.
_PARAM_PRIORITY_KEYWORDS = [
    # Tier 1: Core composition
    ("monomer", 90),
    ("comonomer", 87),
    ("ratio", 85),
    ("composition", 83),
    ("content", 80),
    # Tier 2: Polymerization method
    ("polymerization", 75),
    ("copolymerization", 75),
    ("emulsion", 72),
    ("initiat", 70),
    ("catalyst", 70),
    # Tier 3: Reaction conditions
    ("temperature", 65),
    ("pressure", 62),
    ("conversion", 60),
    ("time", 55),
    ("reaction", 52),
    # Tier 4: Process components
    ("emulsifi", 50),
    ("surfactant", 50),
    ("chain transfer", 48),
    ("modifier", 46),
    ("water", 44),
    ("ph", 42),
    ("buffer", 40),
    ("salt", 38),
    # Tier 5: Product properties
    ("solid", 35),
    ("molecular weight", 33),
    ("viscosity", 30),
    ("particle", 28),
    ("gel", 26),
    ("mooney", 25),
    # Tier 6: Other
    ("yield", 20),
]


class ReportEvidenceService:
    def __init__(self):
        try:
            self.encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.encoder = None

    def _get_evidence_budget(self) -> int:
        from app.core.config import settings
        safe_budget = getattr(settings, 'REPORT_SAFE_EVIDENCE_BUDGET', 150000)
        provider_limit = getattr(settings, 'REPORT_PROVIDER_SAFE_LIMIT', 100000)
        overhead = getattr(settings, 'REPORT_EVIDENCE_OVERHEAD_TOKENS', 4000)
        derived_budget = max(1000, provider_limit - overhead)
        return min(safe_budget, derived_budget)

    def estimate_tokens(self, text: str) -> int:
        if self.encoder:
            return len(self.encoder.encode(text))
        return len(text) // 4

    def generate_google_patents_url(self, patent_number: str, jurisdiction: str) -> str:
        clean_number = patent_number.replace(" ", "").replace("-", "").upper()
        return f"https://patents.google.com/patent/{clean_number}/en"

    def _param_priority_score(self, param: ExtractedParameterSchema) -> int:
        """
        Deterministic priority score for a parameter.
        Higher = higher priority = keep this parameter.
        Based on chemical significance of the parameter name, not just confidence.
        No LLM call.
        """
        name_lower = (param.name or "").lower()
        for keyword, score in _PARAM_PRIORITY_KEYWORDS:
            if keyword in name_lower:
                return score
        return int((param.confidence or 0) * 19)

    def score_example_relevance(self, example, profile=None) -> int:
        score = 0
        title_lower = (
            example.example_id if hasattr(example, 'example_id')
            else getattr(example, 'title', '')
        ).lower()

        if any(kw in title_lower for kw in ["example", "preparation", "synthesis", "procedure", "polymerization"]):
            score += 30
        if "comparative" in title_lower:
            score += 10

        params = getattr(example, 'extracted_parameters', [])
        score += min(len(params) * 5, 40)

        if profile:
            example_text = " ".join(
                p.source_sentence for p in params if p.source_sentence
            ).lower()
            for attr in getattr(profile, 'target_attributes', []):
                for term in getattr(attr, 'terms', []):
                    if term.lower() in example_text:
                        score += 20
                        break
            for st in getattr(profile, 'synthesis_terms', [])[:5]:
                if st.lower() in example_text:
                    score += 10
                    break

        return score

    def is_compounding_parameter(self, param: ExtractedParameterSchema) -> bool:
        return False

    # ── Source text extraction (deterministic, no LLM) ───────────────────────

    _SYNTHESIS_SECTION_KEYWORDS = [
        "polymeriz", "copolymeriz", "emulsion", "preparation", "synthesis",
        "manufacture", "process", "monomer", "initiator", "emulsifier",
        "chain transfer", "temperature", "pressure", "time", "conversion", "reaction",
        "catalyst", "solvent", "hydrogenation", "composition", "properties", "analytical",
        "procedure", "condition"
    ]

    def _extract_source_text(
        self,
        parsed_patent,
        max_chars: int = _MAX_SOURCE_TEXT_CHARS,
        include_example_head: bool = True,
    ) -> str:
        """
        Deterministically extract relevant source passages from a fetched patent.
        Priority: 1. Abstract 2. Claims 3. Keyword-matched synthesis sections 4. Examples
        No LLM call.
        """
        parts = []
        remaining = max_chars

        abstract = getattr(parsed_patent, 'abstract', '') or ''
        if abstract:
            snippet = abstract[:3000]
            parts.append(f"[ABSTRACT]\n{snippet}")
            remaining -= len(snippet)

        if remaining <= 0:
            return "\n\n".join(parts)
            
        claims = getattr(parsed_patent, 'claims', '') or ''
        if claims and remaining > 500:
            snippet = claims[:4000]
            parts.append(f"[CLAIMS]\n{snippet}")
            remaining -= len(snippet)

        desc = getattr(parsed_patent, 'detailed_description', '') or ''
        if desc and remaining > 500:
            windows = self._keyword_context_windows(
                desc,
                keywords=self._SYNTHESIS_SECTION_KEYWORDS,
                window_chars=800,
                max_total_chars=min(remaining, 35000)
            )
            if windows:
                parts.append(f"[SYNTHESIS PASSAGES]\n{windows}")
                remaining -= len(windows)

        examples_text = getattr(parsed_patent, 'examples', '') or ''
        # When worked examples are already stored as separate records, do not
        # also keep only the opening of that block here. That opening copy
        # crowded out later examples.
        if include_example_head and examples_text and remaining > 500:
            snippet = examples_text[:min(remaining, 35000)]
            parts.append(f"[EXAMPLES SECTION]\n{snippet}")

        return "\n\n".join(parts)

    def _keyword_context_windows(
        self,
        text: str,
        keywords: list,
        window_chars: int = 600,
        max_total_chars: int = 35000
    ) -> str:
        if not text or not keywords:
            return ""

        text_lower = text.lower()
        collected_ranges = []

        for kw in keywords:
            pos = 0
            while True:
                idx = text_lower.find(kw, pos)
                if idx == -1:
                    break
                start = max(0, idx - 80)
                end = min(len(text), idx + window_chars)
                overlaps = any(s <= start <= e or s <= end <= e for s, e in collected_ranges)
                if not overlaps:
                    collected_ranges.append((start, end))
                pos = idx + 1

        collected_ranges.sort(key=lambda r: r[0])

        total = 0
        parts = []
        for start, end in collected_ranges:
            chunk = text[start:end].strip()
            if not chunk:
                continue
            if total + len(chunk) > max_total_chars:
                chunk = chunk[:max_total_chars - total]
                parts.append(chunk)
                break
            parts.append(chunk)
            total += len(chunk)
            if total >= max_total_chars:
                break

        return "\n...\n".join(parts)

    # ── Core evidence building ────────────────────────────────────────────────

    def build_compact_evidence(
        self,
        extraction: PatentExtraction,
        discovery_source: str = "NORMAL",
        competitor_name: str | None = None,
        profile=None,
        parsed_patent=None,
        relevance_tier: str = "",
        relevance_score: float = 0.0,
    ) -> ReportPatentEvidence:
        """
        Transforms a heavy PatentExtraction into a compact ReportPatentEvidence.

        CRITICAL BEHAVIOUR:
        - Every patent ALWAYS produces an evidence object — even with 0 params.
        - Examples with 0 extracted parameters are ALWAYS included (data loss fix).
        - source_text provides a fallback for patents where structured extraction found nothing.
        """
        meta = extraction.metadata

        if not meta.url or "patents.google.com" not in meta.url:
            google_patents_url = self.generate_google_patents_url(meta.patent_number, meta.jurisdiction)
        else:
            google_patents_url = meta.url

        evidence = ReportPatentEvidence(
            patent_number=meta.patent_number,
            title=meta.patent_title,
            jurisdiction=meta.jurisdiction,
            assignee=meta.assignee,
            publication_year=meta.publication_year,
            url=google_patents_url,
            discovery_source=discovery_source,
            competitor_name=competitor_name,
            overall_patent_parameters=[],
            examples=[],
            synthesis_sections=[],
            technical_findings=[],
            limitations_or_missing_data=[],
            relevance_tier=relevance_tier,
            relevance_score=relevance_score,
            priority_date=((getattr(parsed_patent, "metadata", None) or {}).get("priority_date") or None),
            legal_status=(
                meta.legal_status
                if (meta.legal_status or "").strip().lower() not in {"", "unknown", "patent", "not disclosed"}
                else ((getattr(parsed_patent, "metadata", None) or {}).get("legal_status") or None)
            ),
        )

        # Parameters: priority-sort by chemical significance, take top N
        sorted_params = sorted(
            extraction.parameters,
            key=self._param_priority_score,
            reverse=True
        )
        for param in sorted_params[:_MAX_PARAMS_PER_PATENT]:
            if not self.is_compounding_parameter(param):
                p_copy = param.model_copy()
                if p_copy.source_sentence and len(p_copy.source_sentence) > MAX_SOURCE_SENTENCE_CHARS:
                    p_copy.source_sentence = p_copy.source_sentence[:MAX_SOURCE_SENTENCE_CHARS] + "..."
                evidence.overall_patent_parameters.append(p_copy)

        # Examples: score and sort, but ALWAYS include — even 0-param examples.
        # BUG FIX: previously gate `if ex_ev.extracted_parameters:` silently dropped
        # examples with 0 params, causing entire patents to disappear from evidence.
        scored_examples = []
        for ex in extraction.examples:
            ex_evidence = ReportExampleEvidence(
                # Use example_id directly — it already contains the full, correctly-cased label
                # from the source patent (e.g. "Comparative Example 1", "EXAMPLE 8",
                # "Synthesis Example 2"). Do not prepend example_type or any other prefix.
                example_id=(getattr(ex, 'example_id', '') or getattr(ex, 'example_type', 'Example')).strip(),
                raw_text=getattr(ex, 'raw_text', ''),
                extracted_parameters=[]
            )
            for param in ex.extracted_parameters:
                if not self.is_compounding_parameter(param):
                    p_copy = param.model_copy()
                    if p_copy.source_sentence and len(p_copy.source_sentence) > MAX_SOURCE_SENTENCE_CHARS:
                        p_copy.source_sentence = p_copy.source_sentence[:MAX_SOURCE_SENTENCE_CHARS] + "..."
                    ex_evidence.extracted_parameters.append(p_copy)

            rel_score = self.score_example_relevance(ex_evidence, profile=profile)
            scored_examples.append((rel_score, ex_evidence))

        scored_examples.sort(key=lambda x: x[0], reverse=True)
        for _, ex_ev in scored_examples[:_MAX_EXAMPLES_PER_PATENT]:
            # ALWAYS append — no gate on ex_ev.extracted_parameters
            evidence.examples.append(ex_ev)
        if len(scored_examples) > _MAX_EXAMPLES_PER_PATENT:
            omitted = [ex.example_id for _, ex in scored_examples[_MAX_EXAMPLES_PER_PATENT:]]
            evidence.limitations_or_missing_data.append(
                "Examples identified but not sent in this evidence batch: " + ", ".join(omitted)
            )
            
        for sec in getattr(extraction, 'synthesis_sections', []):
            evidence.synthesis_sections.append(SynthesisSectionEvidence(
                section_title=sec.section_title,
                raw_text=sec.raw_text
            ))

        for tbl in getattr(extraction, 'tables', []):
            evidence.tables.append(tbl)

        # Distinguish "no examples in patent" vs "examples not segmented"
        detection_note = getattr(extraction, "examples_detection_note", "") or ""
        if not evidence.examples:
            if detection_note:
                evidence.limitations_or_missing_data.append(detection_note)
                evidence.technical_findings.append(detection_note)
            elif evidence.synthesis_sections:
                evidence.limitations_or_missing_data.append(
                    "Worked-example headings were not segmented; process/description "
                    "sections are available as synthesis evidence."
                )
            else:
                evidence.limitations_or_missing_data.append(
                    "This patent did not yield segmented worked-example sections; "
                    "use claims/description/source_text for process evidence."
                )

        # Source text: deterministic passage extraction
        if parsed_patent is not None:
            evidence.source_text = self._extract_source_text(
                parsed_patent,
                include_example_head=not evidence.examples,
            )
        if meta.quality == "NO_DETERMINISTIC_EVIDENCE":
            evidence.limitations_or_missing_data.append(
                "Deterministic extraction found 0 structured parameters. "
                "Use abstract and title for report synthesis."
            )

        logger.info(
            "[STRUCTURED EXTRACTION] Patent: %s | Parameters: %d | Tables: %d | Examples: %d",
            evidence.patent_number,
            len(evidence.overall_patent_parameters),
            len(evidence.tables),
            len(evidence.examples),
        )

        return evidence

    def serialize_evidence(self, evidence_list: List[ReportPatentEvidence]) -> str:
        """
        Serializes evidence list into structured text for the report LLM.
        Every patent block is ALWAYS emitted — even with 0 params.
        """
        parts = []
        for ev in evidence_list:
            parts.append("=" * 60)
            parts.append(f"PATENT: {ev.patent_number}")
            parts.append(f"Title: {ev.title}")
            parts.append(f"Jurisdiction: {ev.jurisdiction}")
            parts.append(f"Assignee: {ev.assignee or 'Not disclosed'}")
            parts.append(f"Publication Year: {ev.publication_year or 'Not disclosed'}")
            parts.append(f"Source Type: {ev.discovery_source}")
            if ev.relevance_tier:
                parts.append(f"Relevance Tier: {ev.relevance_tier} (score: {ev.relevance_score:.1f})")
            if ev.competitor_name:
                parts.append(f"Competitor: {ev.competitor_name}")
            parts.append(f"URL: {ev.url}")
            parts.append(
                "NOTE: Extract medium_and_water_role and target_attribute from THIS patent's "
                "evidence only. Do not use other patents' text."
            )

            if ev.overall_patent_parameters:
                parts.append("\nGeneral Parameters:")
                for param in ev.overall_patent_parameters:
                    unit_str = f" {param.unit}" if param.unit else ""
                    src = f" | Source: {param.source_sentence}" if param.source_sentence else ""
                    parts.append(f"- {param.name}: {param.value}{unit_str}{src}")
            else:
                parts.append("\nGeneral Parameters: None extracted by deterministic parser.")

            if ev.examples:
                parts.append("\nExamples:")
                for ex in ev.examples:
                    parts.append(f"  [{ex.example_id}]:")
                    if ex.raw_text:
                        parts.append(f"    Raw Text: {ex.raw_text}")
                    if ex.extracted_parameters:
                        for param in ex.extracted_parameters:
                            unit_str = f" {param.unit}" if param.unit else ""
                            src = f" | Source: {param.source_sentence}" if param.source_sentence else ""
                            parts.append(f"    - {param.name}: {param.value}{unit_str}{src}")
                    else:
                        parts.append("    (No structured parameters extracted from this example)")
            else:
                parts.append("\nExamples: None detected by parser.")
                
            if getattr(ev, 'tables', None):
                parts.append("\nPatent Tables:")
                for tbl in ev.tables:
                    tbl_md = tbl.to_markdown() if hasattr(tbl, 'to_markdown') else str(tbl)
                    if tbl_md:
                        parts.append(f"  [{getattr(tbl, 'title', 'Table')}]:")
                        for line in tbl_md.splitlines():
                            parts.append(f"    {line}")

            if getattr(ev, 'synthesis_sections', None):
                parts.append("\nSynthesis Sections:")
                for sec in ev.synthesis_sections:
                    parts.append(f"  [{sec.section_title}]:")
                    for line in sec.raw_text.splitlines():
                        parts.append(f"    {line}")

            if ev.source_text:
                parts.append("\nSource Text (Relevant Passages):")
                parts.append(ev.source_text)

            if ev.technical_findings:
                parts.append("\nTechnical Findings:")
                for f in ev.technical_findings:
                    parts.append(f"- {f}")

            if ev.limitations_or_missing_data:
                parts.append("\nLimitations/Missing Data:")
                for lim in ev.limitations_or_missing_data:
                    parts.append(f"- {lim}")

            parts.append("")

        return "\n".join(parts)

    def create_semantic_batches(self, evidence_list: List[ReportPatentEvidence], budget: int) -> List[List[ReportPatentEvidence]]:
        batches = []
        current_batch = []
        current_tokens = 0

        for ev in evidence_list:
            ev_str = self.serialize_evidence([ev])
            tokens = self.estimate_tokens(ev_str)

            if current_tokens + tokens > budget and current_batch:
                batches.append(current_batch)
                current_batch = [ev]
                current_tokens = tokens
            else:
                current_batch.append(ev)
                current_tokens += tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    async def analyze_batch_with_llm(self, batch: List[ReportPatentEvidence], token_manager) -> BatchAnalysisResult:
        """STUBBED — LLM batch analysis removed. Architecture: only 2 LLM calls per pipeline run."""
        return None

    def merge_batch_findings(self, original_evidence: List[ReportPatentEvidence], batch_results: List[BatchAnalysisResult]):
        ev_index = {ev.patent_number: ev for ev in original_evidence}
        for res in batch_results:
            if not res:
                continue
            for finding in (res.patent_findings or []):
                ev = ev_index.get(finding.patent_number)
                if ev and finding.findings:
                    ev.technical_findings.append(finding.findings)

    def _shrink_longest_evidence_text(self, evidence_list: List[ReportPatentEvidence]) -> bool:
        """Shorten the single longest example or table. Returns False when nothing remains above the floor."""
        floor = 2500
        target = None
        target_attr = ""
        longest = floor
        for ev in evidence_list:
            for ex in ev.examples:
                size = len(ex.raw_text or "")
                if size > longest:
                    longest = size
                    target = ex
                    target_attr = "raw_text"
            for sec in ev.synthesis_sections:
                size = len(sec.raw_text or "")
                if size > longest:
                    longest = size
                    target = sec
                    target_attr = "raw_text"
        if target is None:
            return False
        new_len = max(floor, int(longest * 0.75))
        if new_len >= longest:
            new_len = floor
        note = "\n[... remainder omitted for the evidence budget; this section was retained ...]"
        current = getattr(target, target_attr) or ""
        setattr(target, target_attr, current[:new_len].rstrip() + note)
        return True

    def _deterministic_compact(
        self,
        compact_evidence: List[ReportPatentEvidence],
        budget: int,
        profile=None,
    ) -> List[ReportPatentEvidence]:
        """
        Deterministic multi-pass compaction, applied ONLY when total exceeds budget.
        With the 88K budget, this should rarely trigger.
        """
        text = self.serialize_evidence(compact_evidence)
        tokens = self.estimate_tokens(text)

        # Shrink the longest retained text before dropping any example.
        guard = 0
        while tokens > budget and guard < 40:
            guard += 1
            if not self._shrink_longest_evidence_text(compact_evidence):
                break
            tokens = self.estimate_tokens(self.serialize_evidence(compact_evidence))
        logger.info("COMPACTION length pass: %d tokens (budget=%d)", tokens, budget)
        if tokens <= budget:
            return compact_evidence

        # Pass 1: Trim examples only after length reduction still exceeds the budget.
        omitted_ids: list[str] = []
        for ev in compact_evidence:
            if len(ev.examples) > _MAX_EXAMPLES_TIGHT:
                scored = sorted(ev.examples, key=lambda e: self.score_example_relevance(e, profile=profile), reverse=True)
                omitted_ids.extend(ex.example_id for ex in scored[_MAX_EXAMPLES_TIGHT:])
                ev.examples = scored[:_MAX_EXAMPLES_TIGHT]
        if omitted_ids and compact_evidence:
            compact_evidence[0].limitations_or_missing_data.append(
                "Examples omitted after the evidence budget was exhausted: "
                + ", ".join(omitted_ids)
            )

        text = self.serialize_evidence(compact_evidence)
        tokens = self.estimate_tokens(text)
        logger.info("COMPACTION Pass 1 (examples to %d): %d tokens (budget=%d)", _MAX_EXAMPLES_TIGHT, tokens, budget)
        if tokens <= budget:
            return compact_evidence

        # Pass 2: Trim params by priority
        for ev in compact_evidence:
            if len(ev.overall_patent_parameters) > _MAX_PARAMS_PER_PATENT_TIGHT:
                ev.overall_patent_parameters = sorted(
                    ev.overall_patent_parameters, key=self._param_priority_score, reverse=True
                )[:_MAX_PARAMS_PER_PATENT_TIGHT]
            for ex in ev.examples:
                if len(ex.extracted_parameters) > _MAX_PARAMS_PER_PATENT_TIGHT:
                    ex.extracted_parameters = sorted(
                        ex.extracted_parameters, key=self._param_priority_score, reverse=True
                    )[:_MAX_PARAMS_PER_PATENT_TIGHT]

        text = self.serialize_evidence(compact_evidence)
        tokens = self.estimate_tokens(text)
        logger.info("COMPACTION Pass 2 (params to %d): %d tokens (budget=%d)", _MAX_PARAMS_PER_PATENT_TIGHT, tokens, budget)
        if tokens <= budget:
            return compact_evidence

        # Pass 3: Trim source_text
        for ev in compact_evidence:
            if ev.source_text and len(ev.source_text) > 500:
                ev.source_text = ev.source_text[:len(ev.source_text) // 2] + "..."

        text = self.serialize_evidence(compact_evidence)
        tokens = self.estimate_tokens(text)
        logger.info("COMPACTION Pass 3 (source_text halved): %d tokens (budget=%d)", tokens, budget)
        if tokens <= budget:
            return compact_evidence

        # Pass 4: Trim source_sentence chars
        for ev in compact_evidence:
            for param in ev.overall_patent_parameters:
                if param.source_sentence and len(param.source_sentence) > _SOURCE_SENTENCE_TIGHT_CHARS:
                    param.source_sentence = param.source_sentence[:_SOURCE_SENTENCE_TIGHT_CHARS] + "..."
            for ex in ev.examples:
                for param in ex.extracted_parameters:
                    if param.source_sentence and len(param.source_sentence) > _SOURCE_SENTENCE_TIGHT_CHARS:
                        param.source_sentence = param.source_sentence[:_SOURCE_SENTENCE_TIGHT_CHARS] + "..."

        text = self.serialize_evidence(compact_evidence)
        tokens = self.estimate_tokens(text)
        logger.info("COMPACTION Pass 4 (source_sentence trimmed): %d tokens (budget=%d)", tokens, budget)
        if tokens > budget:
            logger.warning(
                "Evidence still %d tokens after 4 compaction passes (budget=%d). "
                "Proceeding — should still be within provider 100K limit.",
                tokens, budget
            )
        return compact_evidence

    async def prepare_final_evidence(
        self,
        extractions_by_patent: Dict[str, PatentExtraction],
        token_manager,
        competitor_extractions_by_patent: Dict[str, PatentExtraction] = None,
        profile=None,
        selected_candidates=None,
        parsed_patents_by_number: Dict[str, object] = None,
    ) -> List[ReportPatentEvidence]:
        """
        Orchestrates building compact evidence for the final report.
        Every selected patent appears in the output — no patent is ever dropped.
        """
        evidence_budget = self._get_evidence_budget()
        logger.info(
            "EVIDENCE PREPARATION | Primary patents: %d | Budget: %d tokens",
            len(extractions_by_patent), evidence_budget
        )

        relevance_by_pn = {}
        if selected_candidates:
            for cand in selected_candidates:
                pn = getattr(cand, 'publication_number', None)
                if pn:
                    relevance_by_pn[pn] = {
                        'tier': getattr(cand.title_screening_status, 'name', ''),
                        'score': getattr(cand, 'title_score', 0.0) or 0.0,
                    }

        parsed_patents_by_number = parsed_patents_by_number or {}
        compact_evidence = []

        for pn, ext in extractions_by_patent.items():
            rel = relevance_by_pn.get(pn, {})
            parsed = parsed_patents_by_number.get(pn)
            ev = self.build_compact_evidence(
                ext,
                discovery_source="NORMAL",
                competitor_name=None,
                profile=profile,
                parsed_patent=parsed,
                relevance_tier=rel.get('tier', ''),
                relevance_score=rel.get('score', 0.0),
            )
            compact_evidence.append(ev)
            logger.info(
                "  %s (PRIMARY): %d params, %d examples, source_text=%d chars, tier=%s",
                pn, len(ev.overall_patent_parameters), len(ev.examples),
                len(ev.source_text), ev.relevance_tier
            )

        if competitor_extractions_by_patent:
            for pn, ext in competitor_extractions_by_patent.items():
                parsed = parsed_patents_by_number.get(pn)
                competitor_name = ext.metadata.assignee if hasattr(ext.metadata, "competitor_name") else None
                ev = self.build_compact_evidence(
                    ext,
                    discovery_source="COMPETITOR",
                    competitor_name=competitor_name,
                    profile=profile,
                    parsed_patent=parsed,
                )
                compact_evidence.append(ev)
                logger.info(
                    "  %s (COMPETITOR): %d params, %d examples",
                    pn, len(ev.overall_patent_parameters), len(ev.examples)
                )

        full_text = self.serialize_evidence(compact_evidence)
        estimated_tokens = self.estimate_tokens(full_text)

        total_params = sum(len(ev.overall_patent_parameters) for ev in compact_evidence)
        total_examples = sum(len(ev.examples) for ev in compact_evidence)
        logger.info(
            "EVIDENCE PREPARATION COMPLETE | Patents: %d | Params: %d | Examples: %d | "
            "Tokens: %d | Budget: %d | Fit: %s",
            len(compact_evidence), total_params, total_examples,
            estimated_tokens, evidence_budget,
            "YES" if estimated_tokens <= evidence_budget else "NO (applying deterministic compaction)"
        )

        if estimated_tokens <= evidence_budget:
            return compact_evidence

        logger.info(
            "Evidence %d tokens > budget %d. Applying deterministic compaction (no LLM call).",
            estimated_tokens, evidence_budget
        )
        return self._deterministic_compact(compact_evidence, evidence_budget, profile=profile)
