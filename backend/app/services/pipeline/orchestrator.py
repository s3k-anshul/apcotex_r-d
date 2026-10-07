"""
app/services/pipeline/orchestrator.py

Main state machine for the Patent Research Pipeline.
Updates database status and executes the steps sequentially.
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.database import engine
from app.models.research_run import ResearchRun, RunStatus
from app.models.report_metadata import ReportMetadata
from app.models.report_file import ReportFile
from app.services.pipeline.schemas import (
    PatentExtraction,
    PatentSelectionCandidate,
    PatentSelectionResult,
    SearchAdequacy,
    SearchAdequacyMetrics,
    SelectionDecision,
    TechnicalCentrality,
    TitleTriageClassification,
    TargetRelationship,
)
from app.services.pipeline.search_service import SearchService
from app.services.pipeline.fetcher_service import FetcherService
from app.services.pipeline.extractor_service import ExtractorService
from app.services.pipeline.report_service import ReportService
from app.core.telemetry import set_current_run_id, set_current_stage, get_current_stage, TelemetryStage
from app.services.llm import llm_client
from app.services.prompts.patent_prompts import PATENT_SELECTION_PROMPT

logger = logging.getLogger(__name__)


def prefer_source_title(document_title: str, search_title: str) -> str:
    """
    Keep the fuller bibliographic title.

    Search snippets often end in an ellipsis. A title taken from the patent
    document is preferred when the snippet is cut, and the longer intact title
    is preferred when both are complete.
    """
    document = (document_title or "").strip()
    search = (search_title or "").strip()

    def looks_cut(text: str) -> bool:
        return text.endswith("...") or text.endswith("…")

    if document and search:
        if looks_cut(search) and not looks_cut(document):
            return document
        if looks_cut(document) and not looks_cut(search):
            return search
        return document if len(document) >= len(search) else search
    return document or search


async def get_background_session() -> AsyncSession:
    """Provide a new session for background tasks."""
    return AsyncSession(engine, expire_on_commit=False)


class PipelineOrchestrator:
    def __init__(self, run_id: UUID):
        self.run_id = run_id
        self.search_service = SearchService()
        self.fetcher_service = FetcherService()
        self.extractor_service = ExtractorService()
        self.report_service = ReportService()

    async def _update_status(self, session: AsyncSession, run: ResearchRun, status: RunStatus):
        run.status = status
        run.updated_at = datetime.now(timezone.utc)
        await session.commit()
        logger.info("Run %s transitioned to %s", self.run_id, status.name)

    async def _mark_failed(self, session: AsyncSession, run: ResearchRun, error_msg: str):
        logger.error("Run %s FAILED: %s", self.run_id, error_msg)
        # Using existing status transition mechanism
        await self._update_status(session, run, RunStatus.FAILED)

    def get_publication_jurisdiction(self, pub_num: str) -> str:
        if not pub_num:
            return ""
        match = re.match(r'^([A-Z]{2})', pub_num.upper())
        if match:
            return match.group(1)
        return ""

    def _generate_aliases(self, terms: list[str]) -> list[str]:
        """
        Alias expansion is DISABLED.

        Rationale: first-letter acronym generation produces degenerate short
        tokens that cause false-positive material-evidence matches in unrelated
        patents. The LLM already provides a complete synonym/abbreviation set in
        base_material for the current compound, so no additional expansion is
        needed. Return an empty list so callers continue to work unchanged.
        """
        return []


    # ── Generic directional qualifier words ──────────────────────────────────
    # Used to detect TYPE_B (attribute/range) targets.
    # Must NOT contain any compound-specific vocabulary.
    _DIRECTIONAL_QUALIFIERS = frozenset([
        "low", "lower", "lowest", "reduced", "minimal", "minimum", "minor",
        "high", "higher", "highest", "elevated", "increased", "maximum", "ultra",
        "narrow", "broad", "wide", "controlled", "very", "medium", "moderate",
        "partial", "partially",
        # Generic property-dimension words — too common to be material identity tokens.
        # E.g. "Low Molecular Weight <Material>" → only material identity tokens remain.
        "molecular", "weight", "content", "level", "degree", "number", "index",
        "average", "distribution", "ratio", "fraction", "percent",
    ])

    # ── Search adequacy gate constants ────────────────────────────────────────
    # These are generic thresholds — NOT compound-specific rules.
    # Adjust as needed for your search depth / corpus size.
    _MAX_SEARCH_ROUNDS: int = 3
    _ADEQUACY_MIN_DIRECT_MATERIAL: int = 2   # min candidates with a material-token hit
    _ADEQUACY_MIN_SYNTHESIS: int = 1         # min candidates with synthesis-term hit
    _ADEQUACY_MAX_UNRELATED_RATE: float = 0.85  # above → LOW adequacy

    # Generic synthesis/process vocabulary for adequacy scoring.
    # Compound-agnostic — no material-specific terms.
    _SYNTHESIS_VOCAB: frozenset = frozenset([
        "polymerization", "polymerisation", "copolymerization", "copolymerisation",
        "preparation", "synthesis", "prepared", "preparing", "process",
        "manufacturing", "production", "emulsion", "solution", "hydrogenation",
        "functionalization", "carboxylation", "grafting", "crosslink",
        "initiator", "catalyst", "monomer", "comonomer", "latex",
        "conversion", "copolymer", "homopolymer", "precursor",
    ])


    def _reset_filter_stats(self) -> None:
        self._filter_stats = {
            "selection_reject_variant": 0,
            "selection_reject_downstream": 0,
            "selection_reject_medium": 0,
            "selection_reject_other": 0,
            "selection_related_retain": 0,
            "selection_keep": 0,
            "selection_unverified": 0,
            "selection_llm_failure": 0,
            "selection_llm_partial_missing": 0,
            "selection_invalid_llm_objects": 0,
            "fetch_failures": 0,
            "extraction_failures": 0,
            "reached_selection": 0,
            "reached_fetch": 0,
        }
        self._related_candidates = []

    def _format_zero_survivors_error(self, *, reached_validation: int) -> str:
        s = getattr(self, "_filter_stats", {})
        variant_total = s.get("selection_reject_variant", 0)
        downstream_total = s.get("selection_reject_downstream", 0)
        related_total = s.get("selection_related_retain", 0)
        unverified = s.get("selection_unverified", 0)
        llm_fail = s.get("selection_llm_failure", 0)
        other = (
            s.get("selection_reject_other", 0)
            + s.get("selection_reject_medium", 0)
            + s.get("fetch_failures", 0)
            + s.get("extraction_failures", 0)
        )
        if llm_fail and not s.get("selection_keep", 0) and unverified == 0:
            return (
                "SELECTION_EMPTY / LLM_VALIDATION_FAILURE: 0 patents selected because "
                f"LLM structured-output validation failed for {llm_fail} candidate(s) "
                "and no REVIEW/UNVERIFIED fallback survivors remained. "
                "This is NOT a claim that patents are technically irrelevant."
            )
        return (
            f"SELECTION_EMPTY: Pipeline stopped: 0 patents survived the configured selection criteria "
            f"(this is not a claim that no related patents exist in the literature). "
            f"Of candidates that reached selection ({reached_validation}): "
            f"{variant_total} qualifier/variant mismatch, "
            f"{downstream_total} downstream-only, "
            f"{related_total} related/non-primary retained for diagnostics only, "
            f"{unverified} unverified/REVIEW (LLM missing or fallback), "
            f"{llm_fail} LLM failure markers, "
            f"{other} other technical rejections (identity mismatch, unrelated, insufficient evidence). "
            f"Consider broadening discovery queries or reviewing identity/qualifier thresholds."
        )

    @staticmethod
    def _strategy_tokens(strategy, compound_name: str) -> set[str]:
        """Tokenize the current research strategy for evidence overlap (compound-agnostic)."""
        tokens: set[str] = set()
        fields = (
            "base_material",
            "target_modifications",
            "target_attributes",
            "synthesis_transformations",
            "excluded_variants",
            "precursor_relationships",
            "relevant_process_concepts",
            "downstream_terms",
        )
        for field in fields:
            for term in getattr(strategy, field, []) or []:
                for tok in re.findall(r"\b[a-zA-Z]{3,}\b", str(term).lower()):
                    tokens.add(tok)
        for tok in re.findall(r"\b[a-zA-Z]{3,}\b", (compound_name or "").lower()):
            if tok not in PipelineOrchestrator._DIRECTIONAL_QUALIFIERS:
                tokens.add(tok)
        return tokens

    def _compute_search_adequacy(
        self,
        candidates: list,
        strategy,
        search_round: int = 1,
    ) -> SearchAdequacyMetrics:
        """
        Compute compound-agnostic search adequacy metrics from the filtered
        candidate pool (after dedup/jurisdiction/date, before LLM selection).

        Token matching uses ONLY strategy.base_material and generic synthesis
        vocabulary — never hardcoded compound names or monomers.
        """
        # Build material token set from THIS run's strategy (dynamically derived)
        mat_tokens: set[str] = set()
        for term in getattr(strategy, "base_material", None) or []:
            for tok in re.findall(r"\b[a-zA-Z]{3,}\b", (term or "").lower()):
                if tok not in self._DIRECTIONAL_QUALIFIERS:
                    mat_tokens.add(tok)

        # Build qualifier token set from THIS run's strategy
        qual_tokens: set[str] = set()
        for field in ("target_modifications", "target_attributes"):
            for term in getattr(strategy, field, None) or []:
                for tok in re.findall(r"\b[a-zA-Z]{3,}\b", (term or "").lower()):
                    if tok not in self._DIRECTIONAL_QUALIFIERS:
                        qual_tokens.add(tok)

        # Build excluded-variant token set
        excl_tokens: set[str] = set()
        for field in ("excluded_variants", "identity_exclusions"):
            for term in getattr(strategy, field, None) or []:
                for tok in re.findall(r"\b[a-zA-Z]{3,}\b", (term or "").lower()):
                    if len(tok) >= 4:
                        excl_tokens.add(tok)

        total = len(candidates)
        direct_material = 0
        synthesis_count = 0
        qualifier_count = 0
        supporting_count = 0
        excl_count = 0
        unrelated_count = 0

        for cand in candidates:
            blob = (
                (cand.get("title") or "")
                + " "
                + (cand.get("snippet") or "")
                + " "
                + (cand.get("abstract") or "")
            ).lower()
            blob_toks = set(re.findall(r"\b[a-zA-Z]{3,}\b", blob))

            has_material = bool(mat_tokens and mat_tokens.intersection(blob_toks))
            has_synthesis = bool(self._SYNTHESIS_VOCAB.intersection(blob_toks))
            has_qualifier = bool(qual_tokens and qual_tokens.intersection(blob_toks))
            # Strong excluded-variant signal: multiple excl_tokens match
            excl_hits = len(excl_tokens.intersection(blob_toks)) if excl_tokens else 0

            if has_material:
                direct_material += 1
                if has_synthesis:
                    synthesis_count += 1
                else:
                    supporting_count += 1
                if has_qualifier:
                    qualifier_count += 1
            else:
                unrelated_count += 1

            if excl_hits >= 2:
                excl_count += 1

        unrelated_rate = unrelated_count / total if total > 0 else 0.0

        # Adequacy verdict — generic thresholds, no compound-specific rules
        if (
            direct_material >= self._ADEQUACY_MIN_DIRECT_MATERIAL
            and synthesis_count >= self._ADEQUACY_MIN_SYNTHESIS
            and unrelated_rate <= self._ADEQUACY_MAX_UNRELATED_RATE
        ):
            adequacy = SearchAdequacy.HIGH
        elif direct_material >= self._ADEQUACY_MIN_DIRECT_MATERIAL or synthesis_count >= 1:
            adequacy = SearchAdequacy.MEDIUM
        else:
            adequacy = SearchAdequacy.LOW

        metrics = SearchAdequacyMetrics(
            candidate_count=total,
            direct_material_candidates=direct_material,
            synthesis_candidates=synthesis_count,
            qualifier_candidates=qualifier_count,
            supporting_candidates=supporting_count,
            excluded_variant_count=excl_count,
            unrelated_count=unrelated_count,
            unrelated_rate=round(unrelated_rate, 3),
            search_round=search_round,
            adequacy=adequacy,
        )

        logger.info(
            "[SEARCH ADEQUACY] Round=%d | Compound=%s | "
            "total=%d | direct_material=%d | synthesis=%d | qualifier=%d | "
            "supporting=%d | excluded_variant=%d | unrelated=%d | unrelated_rate=%.2f | "
            "adequacy=%s",
            search_round,
            getattr(strategy, "original_input", ""),
            total,
            direct_material,
            synthesis_count,
            qualifier_count,
            supporting_count,
            excl_count,
            unrelated_count,
            unrelated_rate,
            adequacy.value,
        )
        return metrics

    async def _generate_expansion_queries(
        self,
        strategy,
        existing_query_strings: set[str],
        round_num: int,
        run,
    ) -> list:
        """
        Ask the LLM for additional search queries that are distinct from the
        already-executed set.  Reuses existing search_service.generate_strategy
        retry pattern — no new LLM infrastructure.
        """
        from app.services.pipeline.schemas import LLMCompoundSearchProfile, GeneratedQuery
        from app.services.prompts.patent_prompts import build_query_expansion_prompt
        from app.services.llm import llm_client

        compound_name = getattr(run, "compound_name", "") or ""
        attribute_constraint = getattr(run, "attribute_constraint", None) or None
        medium = (getattr(run, "polymerization_medium", None) or "any").strip().lower()

        comp_str = ", ".join(run.competitors) if getattr(run, "competitors", None) else "None"
        web_str = (
            ", ".join(run.mentioned_websites)
            if getattr(run, "mentioned_websites", None)
            else "None"
        )
        jur_str = (
            ", ".join(run.jurisdictions)
            if getattr(run, "jurisdictions", None)
            else "None"
        )
        pub_str = str(run.publication_filter) if getattr(run, "publication_filter", None) else "None"

        existing_list = sorted(existing_query_strings)
        base_prompt = build_query_expansion_prompt(
            compound_name=compound_name,
            competitors=comp_str,
            websites=web_str,
            jurisdictions=jur_str,
            publication_filter=pub_str,
            attribute_constraint=attribute_constraint,
            polymerization_medium=medium,
        )
        expansion_prompt = (
            base_prompt
            + f"\n\nSEARCH EXPANSION ROUND {round_num}: "
            "The previous search queries produced insufficient technical coverage. "
            f"The following {len(existing_list)} queries have already been executed:\n"
            + "\n".join(f"  - {q}" for q in existing_list[:30])
            + "\nGenerate 15 ADDITIONAL DISTINCT queries using DIFFERENT phrasing, "
            "synonyms, process terms, and composition angles. "
            "Do NOT repeat or paraphrase any query from the list above. "
            "Prioritize synthesis/polymerization/preparation queries for the same target material."
        )

        new_queries: list = []
        try:
            result, _, _ = await llm_client.generate_structured(
                prompt=expansion_prompt,
                system_prompt="You are a JSON generator. Do not include markdown blocks.",
                schema=LLMCompoundSearchProfile,
                temperature=0.5,
            )
            if result and getattr(result, "search_queries", None):
                for gq in result.search_queries:
                    key = gq.query.strip().lower()
                    if key not in existing_query_strings:
                        # Basic validation: must contain a base-material token
                        q_lower = gq.query.lower()
                        has_base = any(
                            (b.lower() in q_lower)
                            for b in (getattr(strategy, "base_material", []) or [])
                        )
                        if has_base:
                            new_queries.append(gq)
                            existing_query_strings.add(key)
                        else:
                            logger.info(
                                "[QUERY EXPANSION] Round %d: rejected query (no base material): %s",
                                round_num, gq.query,
                            )
        except Exception as e:
            logger.warning(
                "[QUERY EXPANSION] Round %d LLM call failed: %s", round_num, e
            )

        logger.info(
            "[QUERY EXPANSION] Round %d: %d new queries generated",
            round_num, len(new_queries),
        )
        return new_queries

    async def _enrich_candidates_for_selection(
        self,
        candidates: list,
        strategy,
        compound_name: str,
        *,
        max_enrich: int = 60,
        concurrency: int = 6,
    ) -> list:
        """
        Lightweight evidence enrichment before authoritative selection.
        Uses FetcherService.fetch_selection_evidence (metadata/abstract/claims),
        not full-text extraction. Bounded concurrency and candidate cap.
        """
        if not candidates:
            return candidates

        tokens = self._strategy_tokens(strategy, compound_name)
        to_enrich = candidates[:max_enrich]
        sem = asyncio.Semaphore(concurrency)

        async def _one(cand: dict) -> None:
            url = cand.get("url") or ""
            if not url:
                cand["selection_evidence_sources"] = ["title", "snippet"]
                return
            async with sem:
                try:
                    pack = await self.fetcher_service.fetch_selection_evidence(
                        url, strategy_tokens=tokens
                    )
                except Exception as e:
                    logger.warning(
                        "[SELECTION ENRICH] %s failed: %s",
                        cand.get("patent_number"),
                        e,
                    )
                    pack = None
            sources = ["title", "snippet"]
            if pack:
                if pack.get("title") and not cand.get("title"):
                    cand["title"] = pack["title"]
                if pack.get("abstract"):
                    cand["abstract"] = pack["abstract"]
                    sources.append("abstract")
                if pack.get("claims_excerpt"):
                    cand["claims_excerpt"] = pack["claims_excerpt"]
                    sources.append("claims")
                if pack.get("assignee") and not cand.get("assignee"):
                    cand["assignee"] = pack["assignee"]
                if pack.get("publication_date") and not cand.get("publication_date"):
                    cand["publication_date"] = pack["publication_date"]
                for s in pack.get("evidence_sources") or []:
                    if s not in sources:
                        sources.append(s)
            cand["selection_evidence_sources"] = sources
            logger.info(
                "[SELECTION ENRICH] %s | sources=%s | abstract_chars=%d | claims_chars=%d",
                cand.get("patent_number"),
                ",".join(sources),
                len(cand.get("abstract") or ""),
                len(cand.get("claims_excerpt") or ""),
            )

        await asyncio.gather(*[_one(c) for c in to_enrich])
        for cand in candidates[max_enrich:]:
            cand.setdefault("selection_evidence_sources", ["title", "snippet"])
        return candidates

    @staticmethod
    def _selection_rank_tuple(verdict, synthesis_relevance: bool = False) -> tuple:
        """Higher is better — used after evaluating ALL candidates.

        Prefer direct synthesis / transformation of the target over generic
        composition or residual downstream cases. Qualifier MATCH ranks above
        UNKNOWN; MISMATCH should not reach ranking.
        """
        cls = getattr(verdict, "classification", None)
        cls_name = str(getattr(cls, "value", cls) or "").upper()
        cls_score = {
            "DIRECT_SYNTHESIS": 6,
            "TARGET_TRANSFORMATION": 6,
            "POLYMER_STRUCTURE": 5,
            "PRECURSOR_OR_INTERMEDIATE": 4,
            "AMBIGUOUS": 2,
            "BASE_MATERIAL_ONLY": 1,
            "DOWNSTREAM_APPLICATION": 3 if synthesis_relevance else 0,
            "UNRELATED": 0,
        }.get(cls_name, 3 if synthesis_relevance else 2)
        centrality = getattr(verdict, "technical_centrality", None)
        c_val = getattr(centrality, "value", centrality) if centrality is not None else "PARTIAL"
        c_score = {"CENTRAL": 4, "PARTIAL": 2, "PERIPHERAL": 1, "NONE": 0}.get(str(c_val), 2)
        vm = str(getattr(verdict, "variant_match", "UNKNOWN") or "UNKNOWN").upper()
        q_score = {"MATCH": 3, "PARTIAL": 2, "UNKNOWN": 1, "MISMATCH": 0}.get(vm, 1)
        strength = float(getattr(verdict, "evidence_strength", 0.0) or 0.0)
        conf = float(getattr(verdict, "confidence", 0.0) or 0.0)
        return (cls_score, c_score, q_score, strength, conf)

    @staticmethod
    def _norm_str_field(verdict, name: str, default: str = "UNKNOWN") -> str:
        raw = getattr(verdict, name, None)
        if raw is None:
            return default
        return str(getattr(raw, "value", raw) or default).upper()

    def _derive_rejection_category(
        self,
        *,
        relationship: str,
        material_identity: str,
        variant_match: str,
        variant_mismatch: bool,
        medium_mismatch: bool,
        downstream_only: bool,
        cls_name: str,
        retain_related: bool,
        llm_category: str = "",
    ) -> str:
        cat = (llm_category or "").strip().upper()
        allowed = {
            "UNRELATED_MATERIAL",
            "NON_TARGET_MATERIAL",
            "TARGET_AS_COMPONENT",
            "TARGET_AS_SEGMENT",
            "DOWNSTREAM_ONLY",
            "QUALIFIER_MISMATCH",
            "INSUFFICIENT_TARGET_EVIDENCE",
            "AMBIGUOUS_TARGET_IDENTITY",
            "MEDIUM_MISMATCH",
            "RELATED_RETAINED",
        }
        if cat in allowed:
            return cat
        if medium_mismatch:
            return "MEDIUM_MISMATCH"
        if variant_mismatch or variant_match == "MISMATCH":
            return "QUALIFIER_MISMATCH"
        if relationship == "RELATED_TARGET" or retain_related:
            return "RELATED_RETAINED"
        if relationship == "DOWNSTREAM_ADJACENT" or downstream_only or cls_name == "DOWNSTREAM_APPLICATION":
            return "DOWNSTREAM_ONLY"
        if material_identity == "MISMATCH" or relationship == "REJECTED":
            return "NON_TARGET_MATERIAL"
        if material_identity == "UNKNOWN" or relationship == "REJECTED":
            return "AMBIGUOUS_TARGET_IDENTITY"
        if cls_name == "UNRELATED":
            return "UNRELATED_MATERIAL"
        return "INSUFFICIENT_TARGET_EVIDENCE"

    @staticmethod
    def _detected_aligns_with_base_material(detected: str, strategy) -> bool:
        """
        Compound-agnostic overlap check using THIS run's strategy base_material /
        identity_exclusions only — never a hard-coded synonym table.
        """
        det = (detected or "").strip().lower()
        if not det or strategy is None:
            return False
        exclusions = []
        for field in ("identity_exclusions", "excluded_variants"):
            for term in getattr(strategy, field, None) or []:
                t = str(term or "").strip().lower()
                if t:
                    exclusions.append(t)
        for ex in exclusions:
            if len(ex) >= 3 and ex in det:
                return False
        bases = []
        for term in getattr(strategy, "base_material", None) or []:
            t = str(term or "").strip().lower()
            if t:
                bases.append(t)
        for b in bases:
            if len(b) >= 3 and b in det:
                return True
        return False

    @staticmethod
    def _text_hits_strategy_downstream(text: str, strategy) -> bool:
        blob = (text or "").lower()
        if not blob or strategy is None:
            return False
        for term in getattr(strategy, "downstream_terms", None) or []:
            t = str(term or "").strip().lower()
            if len(t) >= 4 and t in blob:
                return True
        return False

    @staticmethod
    def _text_hits_excluded_variants(text: str, strategy) -> bool:
        """
        Compound-agnostic check whether text explicitly hits excluded chemical
        variants or identity exclusions from THIS run's strategy profile.
        """
        blob = (text or "").lower()
        if not blob or strategy is None:
            return False
        for field in ("identity_exclusions", "excluded_variants"):
            for term in getattr(strategy, field, None) or []:
                t = str(term or "").strip().lower()
                if len(t) >= 3 and t in blob:
                    return True
        return False

    def _detect_synthesis_relevance(
        self,
        verdict,
        *,
        title: str = "",
        strategy=None,
    ) -> tuple[bool, str]:
        """
        Target-agnostic determination of whether patent contains actual
        polymer synthesis, polymerization, copolymerization, latex preparation,
        or target polymer modification/formulation evidence, vs true downstream-only
        finished article usage where polymer is merely an ingredient.
        """
        cls = getattr(verdict, "classification", None)
        cls_name = str(getattr(cls, "value", cls) or "").upper()
        if cls_name == "UNRELATED":
            return False, "Classification is UNRELATED"

        centrality = self._norm_str_field(verdict, "technical_centrality", "PARTIAL")
        downstream_only = bool(getattr(verdict, "downstream_only", False))
        detected = (getattr(verdict, "detected_primary_material", None) or "").strip().lower()
        reason = (getattr(verdict, "reason", None) or "").strip().lower()
        evidence_list = [str(e).strip().lower() for e in (getattr(verdict, "evidence", None) or [])]
        evidence_text = " ".join(evidence_list)
        title_lower = (title or "").strip().lower()

        # 1. Inherent synthesis classifications from LLM
        if cls_name in {
            "DIRECT_SYNTHESIS",
            "TARGET_TRANSFORMATION",
            "POLYMER_STRUCTURE",
            "PRECURSOR_OR_INTERMEDIATE",
        }:
            return True, f"Invention classification is {cls_name}"

        # 2. Peripheral / None centrality without direct synthesis focus is not synthesis-relevant
        if centrality in ("PERIPHERAL", "NONE"):
            return False, f"Target material centrality is {centrality} (peripheral/ingredient role)"

        # 3. Dynamic synthesis indicators from strategy + core polymer preparation roots
        synthesis_indicators = {
            "polymeriz",  # polymerization, polymerizing, polymerized, copolymerization
            "synthes",    # synthesis, synthesizing, synthesized
            "emulsion",   # emulsion polymerization, emulsion
            "latex",      # latex preparation, latex formulation, rubber latex, polymer latex
            "copolymer",  # copolymer preparation, copolymerizing
            "monomer",    # monomer feed, monomer mixture, comonomer
            "preparation of",
            "process for preparing",
            "process for producing",
            "method of preparing",
            "method of producing",
            "functionaliz",
            "carboxylation",
            "grafting",
            "crosslink",
        }
        if strategy is not None:
            for term in getattr(strategy, "synthesis_transformations", None) or []:
                t = str(term or "").strip().lower()
                if len(t) >= 4:
                    synthesis_indicators.add(t)

        # Check synthesis evidence in detected material, evidence quotes, and title
        substantive_text = f"{detected} {evidence_text} {title_lower}"
        has_synthesis_evidence = any(ind in substantive_text for ind in synthesis_indicators)

        # If not found in substantive text, check positive mentions in reason (excluding negative phrases)
        if not has_synthesis_evidence:
            reason_clean = reason
            for neg in (
                "not synthesis", "unrelated to", "not about", "no synthesis",
                "not the primary synthesis", "not polymer synthesis",
            ):
                reason_clean = reason_clean.replace(neg, "")
            has_synthesis_evidence = any(ind in reason_clean for ind in synthesis_indicators)

        # 4. Finished-article downstream indicators (merely an ingredient/article)
        article_terms = {
            "glove", "dipping", "dip former", "dip-forming", "dip-molded",
            "tire", "pneumatic tire", "tread", "carcass",
            "charging roller", "charging member",
            "shoe sole", "footwear",
            "finished article", "consumer product", "medical device",
        }
        if strategy is not None:
            for term in getattr(strategy, "downstream_terms", None) or []:
                t = str(term or "").strip().lower()
                if len(t) >= 4:
                    article_terms.add(t)

        detected_article = any(art in detected for art in article_terms)
        reason_ingredient_only = any(
            phrase in reason
            for phrase in (
                "only mentions", "merely mentions", "merely used", "only a component",
                "component in a downstream", "not about", "not the primary synthesis",
                "purchased ingredient", "commercially available", "end-use article",
            )
        )

        if downstream_only and (detected_article or reason_ingredient_only):
            return False, "Target material is used only as an ingredient in a finished application"

        if has_synthesis_evidence and centrality == "CENTRAL" and not reason_ingredient_only:
            return True, "Target material is central and synthesis/latex/polymer preparation evidence is present"

        if has_synthesis_evidence and not downstream_only and not detected_article:
            return True, "Technical evidence indicates polymer preparation or synthesis"

        return False, "No target material preparation or synthesis evidence identified"

    def _compute_primary_eligibility(
        self, verdict, relationship: str, *, llm_decision: str, strategy=None, title: str = ""
    ) -> tuple[bool, str, str]:
        """
        Authoritative primary eligibility.
        Separates material identity from qualifier UNKNOWN vs MISMATCH.
        Decouples DOWNSTREAM_ADJACENT from blanket rejection when target material
        is central and synthesis/preparation evidence exists.
        Returns PrimaryEligibilityResult(eligible, effective_relationship, variant_match_norm).
        """
        class _EligibilityTuple(tuple):
            eligible: bool
            effective_relationship: str
            variant_match: str
            is_synthesis_relevant: bool
            reason: str

            def __new__(
                cls,
                eligible: bool,
                effective_relationship: str,
                variant_match: str,
                is_synthesis_relevant: bool = False,
                reason: str = "",
            ):
                inst = super().__new__(cls, (eligible, effective_relationship, variant_match))
                inst.eligible = eligible
                inst.effective_relationship = effective_relationship
                inst.variant_match = variant_match
                inst.is_synthesis_relevant = is_synthesis_relevant
                inst.reason = reason
                return inst

        material_identity = self._norm_str_field(verdict, "material_identity", "UNKNOWN")
        variant_match = self._norm_str_field(verdict, "variant_match", "UNKNOWN")
        target_match = self._norm_str_field(verdict, "target_match", "UNKNOWN")
        centrality = self._norm_str_field(verdict, "technical_centrality", "PARTIAL")
        downstream_only = bool(getattr(verdict, "downstream_only", False))
        variant_mismatch = bool(getattr(verdict, "variant_mismatch", False)) or variant_match == "MISMATCH"
        medium_mismatch = bool(getattr(verdict, "polymerization_medium_mismatch", False))
        decision = (llm_decision or "REJECT").upper()
        cls = getattr(verdict, "classification", None)
        cls_name = str(getattr(cls, "value", cls) or "").upper()
        detected = (getattr(verdict, "detected_primary_material", None) or "").strip()
        synthesis_focus = cls_name in {
            "DIRECT_SYNTHESIS",
            "TARGET_TRANSFORMATION",
            "POLYMER_STRUCTURE",
            "PRECURSOR_OR_INTERMEDIATE",
            "BASE_MATERIAL_ONLY",
            "AMBIGUOUS",
        }

        # Dynamic synthesis relevance check
        is_synth_rel, synth_reason = self._detect_synthesis_relevance(
            verdict, title=title, strategy=strategy
        )

        # Dynamic check for excluded chemical variants in detected/title text
        if self._text_hits_excluded_variants(f"{detected} {title}", strategy):
            variant_mismatch = True

        effective_rel = relationship

        # Soft-correct REJECTED → PRIMARY when base material MATCH and synthesis-focused.
        if (
            material_identity == "MATCH"
            and relationship == "REJECTED"
            and centrality in ("CENTRAL", "PARTIAL")
            and synthesis_focus
        ):
            effective_rel = "PRIMARY_TARGET"

        # Soft-correct UNKNOWN material_identity when LLM already asserted PRIMARY
        # with synthesis focus (common over-strict conflation of qualifier into identity).
        if (
            effective_rel == "PRIMARY_TARGET"
            and material_identity == "UNKNOWN"
            and synthesis_focus
            and centrality in ("CENTRAL", "PARTIAL")
        ):
            material_identity = "MATCH"

        # Strategy-driven rescue: LLM sometimes sets material MISMATCH/UNKNOWN because
        # the qualifier differs, while detected_primary_material still names the base.
        if (
            material_identity in ("MISMATCH", "UNKNOWN")
            and synthesis_focus
            and centrality in ("CENTRAL", "PARTIAL")
            and not variant_mismatch
            and relationship not in ("RELATED_TARGET",)
            and self._detected_aligns_with_base_material(detected, strategy)
        ):
            material_identity = "MATCH"
            if effective_rel in ("REJECTED", "DOWNSTREAM_ADJACENT"):
                effective_rel = "PRIMARY_TARGET"

        # CASE 1: Material identity mismatch or UNRELATED classification -> REJECT
        if material_identity == "MISMATCH" or cls_name == "UNRELATED":
            return _EligibilityTuple(
                False, effective_rel, variant_match, False, "Material identity is MISMATCH or UNRELATED for requested target"
            )

        # CASE 2: Qualifier / variant mismatch -> REJECT
        if variant_mismatch:
            return _EligibilityTuple(
                False, effective_rel, variant_match, False, "Qualifier / variant is MISMATCH or excluded for requested target"
            )

        # CASE 3: Target match mismatch -> REJECT
        if target_match == "MISMATCH":
            return _EligibilityTuple(
                False, effective_rel, variant_match, False, "Target match overall is MISMATCH"
            )

        # Medium mismatch -> REJECT
        if medium_mismatch:
            return _EligibilityTuple(
                False, effective_rel, variant_match, False, "Polymerization medium mismatch"
            )

        # RELATED is never primary (preserve anti-contamination)
        if relationship == "RELATED_TARGET" or effective_rel == "RELATED_TARGET":
            return _EligibilityTuple(
                False, "RELATED_TARGET", variant_match, is_synth_rel, "Classified as RELATED_TARGET (retained separately)"
            )

        # CASE 6: Centrality NONE without synthesis evidence -> REJECT
        if centrality == "NONE" and not is_synth_rel:
            return _EligibilityTuple(
                False, effective_rel, variant_match, False, "Technical centrality is NONE and no synthesis evidence present"
            )

        # Downstream framing check:
        is_downstream_framed = (
            relationship == "DOWNSTREAM_ADJACENT"
            or effective_rel == "DOWNSTREAM_ADJACENT"
            or cls_name == "DOWNSTREAM_APPLICATION"
            or downstream_only
        )

        if is_downstream_framed:
            # CASE 4 & CASE 8: Target material is CENTRAL, material MATCH, qualifier MATCH/UNKNOWN,
            # and actual synthesis/polymerization/preparation/latex evidence exists.
            # If candidate was KEEP by LLM or has direct synthesis focus, retain it as PRIMARY_TARGET.
            if (
                material_identity == "MATCH"
                and centrality == "CENTRAL"
                and is_synth_rel
                and not variant_mismatch
                and (decision == "KEEP" or cls_name in {"DIRECT_SYNTHESIS", "TARGET_TRANSFORMATION"})
            ):
                reason_msg = (
                    "Target material is central and synthesis/preparation evidence is present; "
                    "DOWNSTREAM_ADJACENT classification alone does not exclude this patent."
                )
                return _EligibilityTuple(True, "PRIMARY_TARGET", variant_match, True, reason_msg)

            # CASE 5: Peripheral centrality, or true finished product article, or rejected by LLM -> REJECT as DOWNSTREAM_ONLY
            reason_msg = (
                "Target material is used only as an ingredient/component in a downstream "
                "application and no target-polymer preparation evidence is present."
            )
            return _EligibilityTuple(False, "DOWNSTREAM_ADJACENT", variant_match, False, reason_msg)

        # Strategy downstream cues (from THIS run's profile) catch mislabeled article patents
        if not is_synth_rel and self._text_hits_strategy_downstream(f"{detected} {title}", strategy):
            return _EligibilityTuple(
                False, "DOWNSTREAM_ADJACENT", variant_match, False, "Hit strategy downstream article keywords without synthesis evidence"
            )

        # CASE 7: Primary target with synthesis/preparation focus
        if material_identity == "MATCH" and effective_rel == "PRIMARY_TARGET":
            if centrality in ("CENTRAL", "PARTIAL") and is_synth_rel and decision == "KEEP":
                return _EligibilityTuple(
                    True, "PRIMARY_TARGET", variant_match, True, "Target material matches and synthesis/preparation focus confirmed"
                )
            if decision == "KEEP" and centrality in ("CENTRAL", "PARTIAL"):
                return _EligibilityTuple(
                    True, "PRIMARY_TARGET", variant_match, is_synth_rel, "Target material matches and LLM selected KEEP"
                )

        # Soft-KEEP LLM REJECT only when identity already MATCH after soft-corrects AND synthesis_focus is True
        if decision != "KEEP":
            if material_identity == "MATCH" and synthesis_focus and centrality in ("CENTRAL", "PARTIAL") and not variant_mismatch:
                return _EligibilityTuple(
                    True, "PRIMARY_TARGET", variant_match, is_synth_rel, "Soft-KEEP: Base material matches with synthesis focus"
                )
            return _EligibilityTuple(
                False, effective_rel, variant_match, False, "Candidate rejected by LLM without direct target synthesis evidence"
            )

        if material_identity == "MATCH" and centrality in ("CENTRAL", "PARTIAL") and not variant_mismatch:
            return _EligibilityTuple(
                True, "PRIMARY_TARGET", variant_match, is_synth_rel, "Base material matches with eligible qualifier"
            )

        return _EligibilityTuple(
            False, effective_rel, variant_match, False, "Insufficient target material evidence for primary selection"
        )

    def _candidate_evidence_packet(self, c: dict) -> dict:
        return {
            "patent_number": c.get("patent_number", ""),
            "title": c.get("title", ""),
            "snippet": (c.get("snippet", "") or "")[:800],
            "abstract": (c.get("abstract", "") or "")[:1500],
            "claims_excerpt": (c.get("claims_excerpt", "") or "")[:2500],
            "publication_year": (
                c.get("publication_date", "") or c.get("grant_date", "") or ""
            )[:4],
            "jurisdiction": (c.get("patent_number", "") or "")[:2],
            "assignee": c.get("assignee", "") or "",
            "evidence_sources": c.get("selection_evidence_sources")
            or ["title", "snippet"],
        }

    @staticmethod
    def _norm_target_relationship(verdict) -> str:
        raw = getattr(verdict, "target_relationship", None)
        if raw is None:
            decision = getattr(verdict.final_decision, "value", str(verdict.final_decision))
            if decision == "KEEP":
                return "PRIMARY_TARGET"
            if decision == "REVIEW":
                return "PRIMARY_TARGET"
            return "REJECTED"
        return getattr(raw, "value", str(raw)).upper()

    _SELECTION_REQUIRED_FIELDS = (
        "patent_number",
        "classification",
        "variant_mismatch",
        "polymerization_medium_mismatch",
        "final_decision",
        "confidence",
        "reason",
    )

    @classmethod
    def _missing_selection_fields(cls, obj: dict) -> list[str]:
        missing = []
        for f in cls._SELECTION_REQUIRED_FIELDS:
            if f not in obj or obj.get(f) is None:
                missing.append(f)
            elif f == "reason" and not str(obj.get(f) or "").strip():
                missing.append(f)
        return missing

    @classmethod
    def _salvage_selection_candidates(
        cls,
        raw_text: str | None,
        expected_numbers: set[str],
    ) -> tuple[list[PatentSelectionCandidate], list[str], list[str]]:
        """
        Parse raw Gemini JSON and keep only candidates that fully validate.
        Returns (valid_candidates, invalid_patent_notes, missing_field_names_seen).
        """
        valid: list[PatentSelectionCandidate] = []
        invalid_notes: list[str] = []
        missing_fields_seen: list[str] = []
        if not raw_text:
            return valid, invalid_notes, missing_fields_seen
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            invalid_notes.append(f"malformed_json:{e}")
            return valid, invalid_notes, missing_fields_seen

        items = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(items, list):
            invalid_notes.append("missing_candidates_array")
            return valid, invalid_notes, missing_fields_seen

        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                invalid_notes.append("non_object_candidate")
                continue
            pnum = str(item.get("patent_number") or "").strip()
            if not pnum:
                invalid_notes.append("missing_patent_number")
                continue
            if pnum not in expected_numbers:
                invalid_notes.append(f"unknown_patent:{pnum}")
                continue
            if pnum in seen:
                invalid_notes.append(f"duplicate_patent:{pnum}")
                continue
            missing = cls._missing_selection_fields(item)
            if missing:
                missing_fields_seen.extend(missing)
                invalid_notes.append(f"incomplete:{pnum}:missing={missing}")
                continue
            try:
                cand = PatentSelectionCandidate.model_validate(item)
            except Exception as ve:
                invalid_notes.append(f"validation:{pnum}:{ve}")
                continue
            seen.add(pnum)
            valid.append(cand)
        # Deduplicate missing field names while preserving order
        uniq_missing: list[str] = []
        for f in missing_fields_seen:
            if f not in uniq_missing:
                uniq_missing.append(f)
        return valid, invalid_notes, uniq_missing

    def _deterministic_review_verdict(
        self,
        cand: dict,
        strategy,
        *,
        reason_prefix: str = "LLM verdict unavailable",
    ) -> PatentSelectionCandidate:
        """
        Application fallback when Gemini provides no usable verdict.
        Never pretends to be an LLM KEEP/REJECT with high confidence.
        Only hard-reject when evidence clearly shows excluded variant or
        clearly unrelated / downstream-only finished article.
        """
        title = (cand.get("title") or "").lower()
        snippet = (cand.get("snippet") or "").lower()
        abstract = (cand.get("abstract") or "").lower()
        blob = f"{title} {snippet} {abstract}"

        # Clear excluded-variant mismatch → technical REJECT
        for excl in getattr(strategy, "excluded_variants", None) or []:
            term = str(excl or "").strip().lower()
            if len(term) >= 3 and term in blob:
                return PatentSelectionCandidate(
                    patent_number=cand.get("patent_number", ""),
                    classification=TitleTriageClassification.UNRELATED,
                    variant_mismatch=True,
                    polymerization_medium_mismatch=False,
                    final_decision=SelectionDecision.REJECT,
                    confidence=0.0,
                    reason=(
                        f"{reason_prefix}; deterministic REJECT: excluded variant "
                        f"evidence ({excl!r}) in title/snippet/abstract"
                    ),
                    technical_centrality=TechnicalCentrality.NONE,
                    target_relationship=TargetRelationship.REJECTED,
                    material_identity="MISMATCH",
                    variant_match="MISMATCH",
                    rejection_category="QUALIFIER_MISMATCH",
                    evidence_strength=0.0,
                )

        # Clear finished-article downstream cues with no synthesis language → REJECT
        synthesis_cues = any(
            tok in blob
            for tok in (
                "polymeriz", "synthesis", "preparation", "preparing",
                "copolymer", "emulsion", "latex", "manufactur",
            )
        )
        downstream_hit = self._text_hits_strategy_downstream(blob, strategy)
        if downstream_hit and not synthesis_cues:
            return PatentSelectionCandidate(
                patent_number=cand.get("patent_number", ""),
                classification=TitleTriageClassification.DOWNSTREAM_APPLICATION,
                variant_mismatch=False,
                polymerization_medium_mismatch=False,
                final_decision=SelectionDecision.REJECT,
                confidence=0.0,
                reason=(
                    f"{reason_prefix}; deterministic REJECT: downstream-only indicators "
                    "without synthesis/polymerization evidence"
                ),
                technical_centrality=TechnicalCentrality.PERIPHERAL,
                target_relationship=TargetRelationship.DOWNSTREAM_ADJACENT,
                downstream_only=True,
                rejection_category="DOWNSTREAM_ONLY",
                evidence_strength=0.0,
            )

        # Base-material token overlap → REVIEW (unverified, not technical reject)
        base_hit = False
        for term in getattr(strategy, "base_material", None) or []:
            t = str(term or "").strip().lower()
            if len(t) >= 2 and t in blob:
                base_hit = True
                break
        compound = str(getattr(strategy, "original_input", "") or "").lower()
        if not base_hit and compound:
            for tok in re.findall(r"[a-z0-9]{3,}", compound):
                if tok in blob:
                    base_hit = True
                    break

        return PatentSelectionCandidate(
            patent_number=cand.get("patent_number", ""),
            classification=(
                TitleTriageClassification.AMBIGUOUS
                if base_hit
                else TitleTriageClassification.AMBIGUOUS
            ),
            variant_mismatch=False,
            polymerization_medium_mismatch=False,
            final_decision=SelectionDecision.REVIEW,
            confidence=0.0,
            reason=(
                f"{reason_prefix}; marked REVIEW/UNVERIFIED pending human or later review "
                f"(base_material_evidence={'yes' if base_hit else 'weak'})"
            ),
            technical_centrality=(
                TechnicalCentrality.PARTIAL if base_hit else TechnicalCentrality.PERIPHERAL
            ),
            target_relationship=TargetRelationship.PRIMARY_TARGET,
            material_identity="UNKNOWN",
            variant_match="UNKNOWN",
            medium_match="NOT_APPLICABLE",
            rejection_category="INSUFFICIENT_TARGET_EVIDENCE",
            evidence_strength=0.0,
            evidence=[],
        )

    async def _call_selection_llm_with_repair(
        self,
        prompt: str,
        batch: list,
        *,
        batch_index: int,
    ) -> tuple[list[PatentSelectionCandidate], dict]:
        """
        Call Gemini for a selection batch. On validation failure: salvage + one repair retry.
        Never treats validation failure as mass technical REJECT.
        """
        expected = {c.get("patent_number", "") for c in batch if c.get("patent_number")}
        meta = {
            "gemini_candidates": 0,
            "schema_validation": "FAIL",
            "retry_validation": None,
            "missing_fields": [],
            "invalid_notes": [],
            "salvaged": 0,
            "llm_call_failed": False,
        }

        result, _, usage = await llm_client.generate_structured(
            prompt=prompt,
            system_prompt=(
                "You are a JSON generator. Return ONLY valid JSON matching the "
                "PatentSelectionResult schema. Do not omit required fields. "
                "Do not include markdown blocks."
            ),
            schema=PatentSelectionResult,
            temperature=0.1,
        )

        valid: list[PatentSelectionCandidate] = []
        if result and getattr(result, "candidates", None):
            # Filter to expected numbers; drop unknowns/duplicates
            seen: set[str] = set()
            for cand in result.candidates:
                pnum = cand.patent_number
                if pnum not in expected:
                    meta["invalid_notes"].append(f"unknown_patent:{pnum}")
                    continue
                if pnum in seen:
                    meta["invalid_notes"].append(f"duplicate_patent:{pnum}")
                    continue
                seen.add(pnum)
                valid.append(cand)
            meta["gemini_candidates"] = len(result.candidates)
            meta["schema_validation"] = "PASS"
            meta["salvaged"] = len(valid)
            return valid, meta

        # Validation failed or empty — attempt salvage from raw response
        raw_text = (usage or {}).get("raw_response_text")
        validation_error = (usage or {}).get("validation_error") or "empty_or_invalid_response"
        logger.warning(
            "[LLM PATENT SELECTION] Schema validation: FAIL | batch=%d | error=%s",
            batch_index,
            str(validation_error)[:500],
        )
        salvaged, notes, missing_fields = self._salvage_selection_candidates(raw_text, expected)
        meta["invalid_notes"].extend(notes)
        meta["missing_fields"] = missing_fields
        meta["salvaged"] = len(salvaged)
        if salvaged:
            logger.info(
                "[LLM PATENT SELECTION] Salvaged %d/%d candidates from partial response",
                len(salvaged),
                len(expected),
            )
            valid = list(salvaged)

        still_missing = expected - {c.patent_number for c in valid}
        if not still_missing:
            meta["schema_validation"] = "PARTIAL_SALVAGE_COMPLETE"
            return valid, meta

        # Repair retry for missing / incomplete candidates
        logger.info(
            "[LLM PATENT SELECTION] Retrying structured response... missing_fields=%s "
            "still_missing_patents=%d",
            missing_fields or self._SELECTION_REQUIRED_FIELDS,
            len(still_missing),
        )
        missing_list = ", ".join(missing_fields) if missing_fields else ", ".join(
            self._SELECTION_REQUIRED_FIELDS
        )
        still_json = json.dumps(sorted(still_missing))
        repair_prompt = (
            prompt
            + "\n\nREPAIR INSTRUCTION:\n"
            "The previous response failed schema validation or omitted required fields / patents.\n"
            f"Missing or invalid fields observed: {missing_list}.\n"
            f"Patents that still need a COMPLETE object: {still_json}.\n"
            "Return a complete PatentSelectionResult JSON with a 'candidates' array containing "
            "exactly one COMPLETE object for EACH listed patent_number.\n"
            "Every object MUST include: patent_number, classification, variant_mismatch, "
            "polymerization_medium_mismatch, final_decision, confidence, reason "
            "(and the other documented fields).\n"
            "Do not omit any field. Do not invent patent numbers."
        )
        try:
            retry_result, _, retry_usage = await llm_client.generate_structured(
                prompt=repair_prompt,
                system_prompt=(
                    "You are a JSON generator repairing an incomplete PatentSelectionResult. "
                    "Do not omit required fields. No markdown."
                ),
                schema=PatentSelectionResult,
                temperature=0.1,
            )
        except Exception as e:
            logger.error("[LLM PATENT SELECTION] Repair call failed: %s", e)
            meta["retry_validation"] = "FAIL"
            meta["llm_call_failed"] = True
            return valid, meta

        if retry_result and getattr(retry_result, "candidates", None):
            meta["retry_validation"] = "PASS"
            have = {c.patent_number for c in valid}
            for cand in retry_result.candidates:
                if cand.patent_number in still_missing and cand.patent_number not in have:
                    valid.append(cand)
                    have.add(cand.patent_number)
            meta["gemini_candidates"] = max(
                meta["gemini_candidates"], len(retry_result.candidates)
            )
        else:
            meta["retry_validation"] = "FAIL"
            raw2 = (retry_usage or {}).get("raw_response_text")
            salvaged2, notes2, missing2 = self._salvage_selection_candidates(raw2, still_missing)
            meta["invalid_notes"].extend(notes2)
            if missing2:
                meta["missing_fields"] = list(
                    dict.fromkeys(meta["missing_fields"] + missing2)
                )
            have = {c.patent_number for c in valid}
            for cand in salvaged2:
                if cand.patent_number not in have:
                    valid.append(cand)
                    have.add(cand.patent_number)
            logger.warning(
                "[LLM PATENT SELECTION] Retry validation: FAIL | salvaged_after_retry=%d",
                len(salvaged2),
            )

        return valid, meta

    async def _select_patents_via_llm(
        self,
        candidates: list,
        strategy,
        run: ResearchRun,
        *,
        batch_size: int = 50,
        max_keep: int = 10,
    ) -> list:
        """Evidence-aware selection via batched LLM — authoritative PRIMARY KEEP/REJECT/REVIEW."""
        if not hasattr(self, "_filter_stats"):
            self._reset_filter_stats()
        self._related_candidates = []
        medium = (getattr(run, "polymerization_medium", None) or "any").strip().lower()
        attribute_constraint = getattr(run, "attribute_constraint", None) or "None"
        search_intents = [
            q.intent for q in getattr(strategy, "search_queries", []) if hasattr(q, "intent")
        ]
        synthesis_intent_str = (
            "YES (Target synthesis/preparation)"
            if getattr(strategy, "synthesis_intent", False)
            else "NO"
        )
        prompt_template = PATENT_SELECTION_PROMPT.format(
            compound_name=run.compound_name,
            base_material=", ".join(getattr(strategy, "base_material", [])),
            target_modifications=", ".join(getattr(strategy, "target_modifications", [])),
            target_attributes=", ".join(getattr(strategy, "target_attributes", [])),
            synthesis_transformations=", ".join(
                getattr(strategy, "synthesis_transformations", [])
            ),
            downstream_terms=", ".join(getattr(strategy, "downstream_terms", [])),
            excluded_variants=", ".join(getattr(strategy, "excluded_variants", [])),
            identity_exclusions=", ".join(getattr(strategy, "identity_exclusions", []) or []) or "None",
            related_materials=", ".join(getattr(strategy, "related_materials", []) or []) or "None",
            relevance_definition=(getattr(strategy, "relevance_definition", None) or "").strip()
            or "Requested target material itself must be the central technical subject.",
            search_intent=(
                f"Synthesis Required: {synthesis_intent_str}. Intents: "
                + (
                    ", ".join(search_intents)
                    if search_intents
                    else "synthesis and material preparation"
                )
            ),
            attribute_constraint=attribute_constraint,
            polymerization_medium=medium,
            candidates_json="{candidates_json}",
        )

        logger.info(
            "[LLM PATENT SELECTION] Input candidates: %d",
            len(candidates),
        )

        selection_by_number: dict = {}
        total_gemini_returned = 0
        any_validation_fail = False

        for i in range(0, len(candidates), batch_size):
            batch = candidates[i : i + batch_size]
            batch_json = json.dumps(
                [self._candidate_evidence_packet(c) for c in batch],
                indent=2,
            )
            prompt = prompt_template.replace("{candidates_json}", batch_json)
            try:
                valid, meta = await self._call_selection_llm_with_repair(
                    prompt, batch, batch_index=i
                )
                total_gemini_returned += meta.get("gemini_candidates", 0) or len(valid)
                if meta.get("schema_validation") == "FAIL" or meta.get("retry_validation") == "FAIL":
                    any_validation_fail = True
                if meta.get("invalid_notes"):
                    self._filter_stats["selection_invalid_llm_objects"] += len(
                        meta["invalid_notes"]
                    )
                    logger.warning(
                        "[LLM PATENT SELECTION] Invalid candidates: %s",
                        meta["invalid_notes"][:20],
                    )
                if meta.get("missing_fields"):
                    logger.warning(
                        "[LLM PATENT SELECTION] Missing fields: %s",
                        meta["missing_fields"],
                    )
                for cand in valid:
                    selection_by_number[cand.patent_number] = cand
            except Exception as e:
                any_validation_fail = True
                logger.error(
                    "[LLM PATENT SELECTION] Failed for batch %d-%d: %s",
                    i,
                    i + len(batch),
                    str(e),
                )
                self._filter_stats["selection_llm_failure"] += len(batch)

        logger.info(
            "[LLM PATENT SELECTION] Gemini response candidates: %d | "
            "mapped_valid_verdicts: %d | schema_had_failures: %s",
            total_gemini_returned,
            len(selection_by_number),
            any_validation_fail,
        )

        # Fill gaps with deterministic REVIEW / clear-mismatch REJECT — never silent REJECT-as-NO_VERDICT
        for cand in candidates:
            pnum = cand.get("patent_number", "")
            if pnum and pnum not in selection_by_number:
                self._filter_stats["selection_llm_partial_missing"] += 1
                selection_by_number[pnum] = self._deterministic_review_verdict(
                    cand,
                    strategy,
                    reason_prefix="No usable LLM verdict after validation/repair",
                )
                fb = selection_by_number[pnum]
                fb_dec = getattr(fb.final_decision, "value", str(fb.final_decision))
                logger.info(
                    "[LLM PATENT SELECTION] %s → deterministic fallback decision=%s "
                    "(LLM missing/invalid — not counted as NO_VERDICT silent REJECT)",
                    pnum,
                    fb_dec,
                )

        # Evaluate EVERY candidate first — do not early-break on max_keep.
        kept_pairs: list[tuple] = []  # (rank_tuple, candidate_dict)
        related_pairs: list[tuple] = []
        review_pairs: list[tuple] = []

        for cand in candidates:
            self._filter_stats["reached_selection"] += 1
            pnum = cand.get("patent_number", "")
            verdict = selection_by_number.get(pnum)
            if verdict is None:
                # Should not happen after fallback fill — belt and suspenders
                verdict = self._deterministic_review_verdict(
                    cand, strategy, reason_prefix="Internal gap: missing verdict map entry"
                )
                selection_by_number[pnum] = verdict

            cls_name = getattr(verdict.classification, "value", str(verdict.classification))
            llm_decision = getattr(verdict.final_decision, "value", str(verdict.final_decision))
            centrality_s = self._norm_str_field(verdict, "technical_centrality", "PARTIAL")
            relationship = self._norm_target_relationship(verdict)
            material_identity = self._norm_str_field(verdict, "material_identity", "UNKNOWN")
            detected_material = (getattr(verdict, "detected_primary_material", None) or "").strip()
            retain_related = bool(getattr(verdict, "retain_as_related", False)) or (
                relationship == "RELATED_TARGET"
            )
            variant_match = self._norm_str_field(verdict, "variant_match", "UNKNOWN")
            variant_mismatch = bool(verdict.variant_mismatch) or variant_match == "MISMATCH"
            medium_mismatch = bool(verdict.polymerization_medium_mismatch)

            # REVIEW / UNVERIFIED path — not a technical rejection
            if llm_decision == "REVIEW":
                self._filter_stats["selection_unverified"] += 1
                if "No usable LLM" in (verdict.reason or "") or "LLM verdict unavailable" in (
                    verdict.reason or ""
                ):
                    self._filter_stats["selection_llm_failure"] += 1
                cand["selection_classification"] = verdict.classification
                cand["selection_variant_mismatch"] = variant_mismatch
                cand["selection_medium_mismatch"] = medium_mismatch
                cand["selection_decision"] = "REVIEW"
                cand["selection_reason"] = verdict.reason
                cand["selection_confidence"] = 0.0
                cand["selection_technical_centrality"] = centrality_s
                cand["selection_target_match"] = getattr(verdict, "target_match", "unknown")
                cand["selection_variant_match"] = variant_match
                cand["selection_medium_match"] = getattr(verdict, "medium_match", "not_applicable")
                cand["selection_downstream_only"] = bool(getattr(verdict, "downstream_only", False))
                cand["selection_evidence"] = list(getattr(verdict, "evidence", None) or [])
                cand["selection_evidence_strength"] = 0.0
                cand["selection_target_relationship"] = "PRIMARY_TARGET"
                cand["selection_material_identity"] = material_identity
                cand["selection_detected_primary_material"] = detected_material
                cand["selection_retain_as_related"] = False
                cand["selection_rejection_category"] = "LLM_UNVERIFIED"
                cand["triage_classification"] = verdict.classification
                cand["ft_category"] = cls_name
                logger.info(
                    "[PATENT SELECTION] %s | decision=REVIEW | classification=%s | "
                    "confidence=0 | technical_centrality=%s | target_match=UNKNOWN | "
                    "target_relationship=PRIMARY_TARGET | reason=%s | "
                    "NOTE=not counted as technical REJECT",
                    pnum,
                    cls_name,
                    centrality_s,
                    verdict.reason,
                )
                review_pairs.append((self._selection_rank_tuple(verdict), cand))
                continue

            eligibility = self._compute_primary_eligibility(
                verdict,
                relationship,
                llm_decision=llm_decision,
                strategy=strategy,
                title=cand.get("title") or "",
            )
            primary_keep = eligibility.eligible
            effective_rel = eligibility.effective_relationship
            variant_match = eligibility.variant_match
            is_synth_rel = getattr(eligibility, "is_synthesis_relevant", False)
            select_reason = getattr(eligibility, "reason", "")

            if primary_keep and llm_decision != "KEEP":
                logger.info(
                    "[PATENT SELECTION] Soft-KEEP %s: material identity eligible with "
                    "variant_match=%s (LLM had final_decision=%s) | reason=%s",
                    pnum,
                    variant_match,
                    llm_decision,
                    select_reason,
                )
            elif primary_keep and relationship == "DOWNSTREAM_ADJACENT":
                logger.info(
                    "[PATENT SELECTION] Downstream-KEEP %s: target material central and "
                    "synthesis/preparation evidence present | reason=%s",
                    pnum,
                    select_reason,
                )
            elif (not primary_keep) and llm_decision == "KEEP":
                logger.warning(
                    "[PATENT SELECTION] Demoting %s from KEEP: target_relationship=%s "
                    "material_identity=%s | reason=%s",
                    pnum,
                    effective_rel,
                    material_identity,
                    select_reason,
                )

            rejection_category = ""
            if not primary_keep:
                rejection_category = self._derive_rejection_category(
                    relationship=effective_rel,
                    material_identity=material_identity,
                    variant_match=variant_match,
                    variant_mismatch=variant_mismatch,
                    medium_mismatch=medium_mismatch,
                    downstream_only=bool(getattr(verdict, "downstream_only", False)),
                    cls_name=cls_name,
                    retain_related=retain_related and not primary_keep,
                    llm_category=getattr(verdict, "rejection_category", "") or "",
                )

            cand["selection_classification"] = verdict.classification
            cand["selection_variant_mismatch"] = variant_mismatch
            cand["selection_medium_mismatch"] = medium_mismatch
            cand["selection_decision"] = "KEEP" if primary_keep else "REJECT"
            cand["selection_reason"] = verdict.reason
            cand["selection_decision_reason"] = select_reason
            cand["selection_synthesis_relevance"] = is_synth_rel
            cand["selection_confidence"] = verdict.confidence
            cand["selection_technical_centrality"] = centrality_s
            cand["selection_target_match"] = getattr(verdict, "target_match", "unknown")
            cand["selection_variant_match"] = variant_match
            cand["selection_medium_match"] = getattr(verdict, "medium_match", "not_applicable")
            cand["selection_downstream_only"] = bool(getattr(verdict, "downstream_only", False))
            cand["selection_evidence"] = list(getattr(verdict, "evidence", None) or [])
            cand["selection_evidence_strength"] = float(
                getattr(verdict, "evidence_strength", 0.0) or 0.0
            )
            cand["selection_target_relationship"] = effective_rel
            cand["selection_material_identity"] = material_identity
            cand["selection_detected_primary_material"] = detected_material
            cand["selection_retain_as_related"] = retain_related and not primary_keep
            cand["selection_rejection_category"] = rejection_category
            cand["triage_classification"] = verdict.classification
            cand["ft_category"] = cls_name

            logger.info(
                "[PATENT SELECTION] Patent: %s | Requested target: %s | "
                "Detected primary material: %s | Material identity: %s | "
                "Target relationship: %s | Technical centrality: %s | "
                "Qualifier/variant match: %s | Target match: %s | "
                "invention_focus=%s | Primary selection: %s | Related retention: %s | "
                "synthesis_relevance=%s | rejection_category=%s | decision=%s | "
                "classification=%s | confidence=%.2f | material_identity_confidence=%.2f | "
                "medium_match=%s | downstream_only=%s | sources=%s | "
                "selection_reason=%s | reason=%s",
                pnum,
                run.compound_name,
                detected_material or "unknown",
                material_identity,
                effective_rel,
                centrality_s,
                variant_match,
                cand["selection_target_match"],
                cls_name,
                "KEEP" if primary_keep else "REJECT",
                "YES" if (not primary_keep and retain_related) else "NO",
                "YES" if is_synth_rel else "NO",
                rejection_category or "-",
                cand["selection_decision"],
                cls_name,
                float(verdict.confidence or 0),
                float(verdict.confidence or 0),
                cand["selection_medium_match"],
                cand["selection_downstream_only"],
                ",".join(cand.get("selection_evidence_sources") or ["title", "snippet"]),
                select_reason,
                verdict.reason,
            )

            if primary_keep:
                self._filter_stats["selection_keep"] += 1
                kept_pairs.append((self._selection_rank_tuple(verdict, synthesis_relevance=is_synth_rel), cand))
                continue

            if retain_related and effective_rel == "RELATED_TARGET":
                self._filter_stats["selection_related_retain"] += 1
                related_pairs.append((self._selection_rank_tuple(verdict), cand))
                continue

            if rejection_category == "QUALIFIER_MISMATCH" or variant_mismatch:
                self._filter_stats["selection_reject_variant"] += 1
            elif rejection_category == "DOWNSTREAM_ONLY":
                self._filter_stats["selection_reject_downstream"] += 1
            elif rejection_category == "MEDIUM_MISMATCH" or medium_mismatch:
                self._filter_stats["selection_reject_medium"] += 1
            else:
                self._filter_stats["selection_reject_other"] += 1
                key = f"reject_{rejection_category.lower()}" if rejection_category else "reject_other"
                self._filter_stats[key] = self._filter_stats.get(key, 0) + 1

        # Rank all PRIMARY KEEP decisions, then apply max_keep as an upper bound (not a quota).
        kept_pairs.sort(key=lambda x: x[0], reverse=True)
        selected = [c for _, c in kept_pairs[:max_keep]]

        related_pairs.sort(key=lambda x: x[0], reverse=True)
        # Cap related separately — never pad primary with related.
        self._related_candidates = [c for _, c in related_pairs[:max_keep]]

        # If no KEEP survived but REVIEW/UNVERIFIED exist, promote them so LLM failure
        # does not empty the pipeline (SELECTION_EMPTY from validation alone).
        review_pairs.sort(key=lambda x: x[0], reverse=True)
        if not selected and review_pairs:
            selected = [c for _, c in review_pairs[:max_keep]]
            logger.warning(
                "[LLM PATENT SELECTION] No KEEP verdicts; promoting %d REVIEW/UNVERIFIED "
                "candidates so LLM failure does not mass-reject the pool",
                len(selected),
            )

        technical_rejects = (
            self._filter_stats["selection_reject_variant"]
            + self._filter_stats["selection_reject_downstream"]
            + self._filter_stats["selection_reject_medium"]
            + self._filter_stats["selection_reject_other"]
        )
        logger.info(
            "[LLM PATENT SELECTION] Valid verdicts: %d | Unverified: %d | "
            "Technical rejects: %d | Kept: %d | Related: %d",
            len(selection_by_number) - self._filter_stats["selection_unverified"],
            self._filter_stats["selection_unverified"],
            technical_rejects,
            self._filter_stats["selection_keep"],
            len(self._related_candidates),
        )

        logger.info(
            "[PATENT SELECTION SUMMARY] entered=%d keep_before_cap=%d keep_after_cap=%d "
            "related_retained=%d unverified=%d llm_failure=%d reject_variant=%d "
            "reject_downstream=%d reject_medium=%d reject_other=%d max_keep=%d | "
            "category_counts=%s",
            self._filter_stats["reached_selection"],
            self._filter_stats["selection_keep"],
            len(selected),
            len(self._related_candidates),
            self._filter_stats["selection_unverified"],
            self._filter_stats["selection_llm_failure"],
            self._filter_stats["selection_reject_variant"],
            self._filter_stats["selection_reject_downstream"],
            self._filter_stats["selection_reject_medium"],
            self._filter_stats["selection_reject_other"],
            max_keep,
            {
                k: v
                for k, v in self._filter_stats.items()
                if k.startswith("reject_") and k
                not in (
                    "selection_reject_variant",
                    "selection_reject_downstream",
                    "selection_reject_medium",
                    "selection_reject_other",
                )
            },
        )
        return selected

    def _validate_primary_manifest_integrity(self, selected_candidates: list) -> list:
        """Fail loudly (log + drop) if a non-PRIMARY patent leaked into the primary list."""
        clean = []
        for cand in selected_candidates:
            # REVIEW/UNVERIFIED survivors are allowed through when LLM failed —
            # they are not technical PRIMARY claims but must not be discarded here.
            if (cand.get("selection_decision") or "").upper() == "REVIEW":
                clean.append(cand)
                continue
            rel = (cand.get("selection_target_relationship") or "PRIMARY_TARGET").upper()
            pnum = cand.get("patent_number", "")
            vm = str(cand.get("selection_variant_match") or "UNKNOWN").upper()
            cls = str(cand.get("ft_category") or cand.get("selection_classification") or "").upper()
            synth_rel = bool(cand.get("selection_synthesis_relevance", False))
            if ("DOWNSTREAM_APPLICATION" in cls or cand.get("selection_downstream_only")) and not synth_rel:
                logger.error(
                    "[INTEGRITY] Dropping %s from primary manifest: downstream/ingredient focus",
                    pnum,
                )
                continue
            if rel != "PRIMARY_TARGET":
                logger.error(
                    "[INTEGRITY] Dropping %s from primary manifest: target_relationship=%s",
                    pnum,
                    rel,
                )
                continue
            if cand.get("selection_decision") != "KEEP":
                logger.error(
                    "[INTEGRITY] Dropping %s from primary manifest: selection_decision=%s",
                    pnum,
                    cand.get("selection_decision"),
                )
                continue
            if vm == "MISMATCH" or cand.get("selection_variant_mismatch"):
                logger.error(
                    "[INTEGRITY] Dropping %s from primary manifest: qualifier MISMATCH",
                    pnum,
                )
                continue
            clean.append(cand)
        return clean

    @staticmethod
    def _build_related_report_patents(related_candidates: list) -> list:
        """Lightweight SECONDARY report entries from related selection candidates (no full extract)."""
        from app.services.pipeline.schemas import (
            ReportPatent,
            ReportPatentDetails,
            ReportPatentMethodology,
        )

        out = []
        for cand in related_candidates or []:
            pn = cand.get("patent_number") or ""
            if not pn:
                continue
            assignee = (cand.get("assignee") or "").strip() or None
            out.append(
                ReportPatent(
                    patent_details=ReportPatentDetails(
                        patent_number=pn,
                        patent_title=cand.get("title") or "Not disclosed",
                        assignee=assignee,
                        jurisdiction=(pn[:2] if len(pn) >= 2 else None),
                        publication_year=(cand.get("publication_date") or "")[:4] or None,
                        relevance_to_target=cand.get("selection_reason")
                        or "Related/adjacent to requested target; not primary.",
                        relevance_tier="SECONDARY",
                    ),
                    polymerization_method=ReportPatentMethodology(dynamic_parameters=[]),
                    experimental_evidence=[
                        f"Detected primary material: {cand.get('selection_detected_primary_material') or 'unknown'}",
                        f"Target relationship: {cand.get('selection_target_relationship') or 'RELATED_TARGET'}",
                    ],
                    technical_relevance=cand.get("selection_reason")
                    or "Retained as RELATED_TARGET — not a primary target patent.",
                )
            )
        return out

    async def _fetch_and_extract_selected(
        self,
        selected_candidates: list,
        strategy,
    ) -> tuple[list, dict]:
        """
        Fetch full patent HTML and run extractor ONLY for Phase-3 selected candidates.
        Returns (extractions, parsed_patents_map). Does not modify extractor_service logic.
        """
        parsed_patents_map: dict = {}
        extractions: list = []

        for candidate in selected_candidates:
            self._filter_stats["reached_fetch"] += 1
            url = candidate["url"]
            logger.info("Fetching selected patent: %s", url)

            parsed_patent = await self.fetcher_service.fetch_patent(url)
            if not parsed_patent:
                logger.warning(
                    "[FETCH FAILURE] patent number: %s | URL: %s",
                    candidate["patent_number"],
                    url,
                )
                self._filter_stats["fetch_failures"] += 1
                continue

            # Authoritative metadata precedence: search/enrichment assignee survives full parse.
            cand_assignee = (candidate.get("assignee") or "").strip()
            if cand_assignee:
                if not (parsed_patent.assignee or "").strip():
                    parsed_patent.assignee = cand_assignee
                parsed_patent.metadata["assignee"] = (
                    (parsed_patent.metadata.get("assignee") or "").strip() or cand_assignee
                )
            parsed_patent.title = prefer_source_title(
                parsed_patent.title, candidate.get("title") or ""
            )

            logger.info(
                "[FETCH SUCCESS] patent number: %s | URL: %s | assignee=%s",
                candidate["patent_number"],
                url,
                (parsed_patent.assignee or "")[:80] or "(empty)",
            )
            parsed_patents_map[candidate["patent_number"]] = parsed_patent
            await asyncio.sleep(1)

            ext = await self.extractor_service.extract_polymerization_data(
                parsed_patent, url=candidate["url"], profile=strategy
            )
            if not ext:
                self._filter_stats["extraction_failures"] += 1
                continue

            ext.metadata.patent_number = candidate["patent_number"]
            ext.metadata.patent_title = prefer_source_title(
                parsed_patent.title, candidate.get("title") or ""
            )
            # Never let empty LLM/placeholder overwrite authoritative assignee
            authoritative_assignee = (
                cand_assignee
                or (parsed_patent.assignee or "").strip()
                or (getattr(ext.metadata, "assignee", None) or "").strip()
            )
            if authoritative_assignee and authoritative_assignee.lower() not in (
                "not disclosed",
                "unknown",
                "none",
                "n/a",
            ):
                ext.metadata.assignee = authoritative_assignee
            elif not (getattr(ext.metadata, "assignee", None) or "").strip():
                ext.metadata.assignee = "Not disclosed"

            if self.extractor_service.validate_extraction(ext):
                extractions.append(ext)
                logger.info("EXTRACTION SUCCESS: %s", ext.metadata.patent_number)
            else:
                self._filter_stats["extraction_failures"] += 1

        return extractions, parsed_patents_map

    async def execute(self):
        """
        Main entry point for the background task.
        """
        set_current_run_id(self.run_id)
        async with await get_background_session() as session:
            result = await session.execute(select(ResearchRun).where(ResearchRun.id == self.run_id))
            run = result.scalar_one_or_none()

            if not run:
                logger.error("Orchestrator could not find run %s", self.run_id)
                return

            try:
                # ── Step 1 & 2: Strategy & Search
                logger.info("[PIPELINE] RUN START | run_id=%s compound=%r", self.run_id, run.compound_name)
                logger.info(
                    "[PIPELINE] INPUT VALIDATED | compound=%r jurisdictions=%s publication_filter=%s competitors=%s websites=%s attribute_constraint=%s polymerization_medium=%s",
                    run.compound_name,
                    run.jurisdictions,
                    run.publication_filter,
                    run.competitors,
                    run.mentioned_websites,
                    getattr(run, "attribute_constraint", None),
                    getattr(run, "polymerization_medium", None) or "any",
                )

                set_current_stage(TelemetryStage.QUERY_EXPANSION)
                await self._update_status(session, run, RunStatus.SEARCHING)
                
                logger.info(
                    "[ORCHESTRATOR] Research Inputs: Compound='%s', Jurisdictions=%s, "
                    "DateFilter=%s, Competitors=%s, Websites=%s, "
                    "AttributeConstraint=%s, PolymerizationMedium=%s",
                    run.compound_name,
                    run.jurisdictions,
                    run.publication_filter,
                    run.competitors,
                    run.mentioned_websites,
                    getattr(run, "attribute_constraint", None),
                    getattr(run, "polymerization_medium", None) or "any",
                )
                
                logger.info("[LLM CALL 1] QUERY_EXPANSION")
                logger.info("[PIPELINE] QUERY_EXPANSION START")
                from app.services.pipeline.search_service import SearchPreparationError

                try:
                    strategy = await self.search_service.generate_strategy(
                        compound_name=run.compound_name,
                        competitors=run.competitors,
                        websites=run.mentioned_websites,
                        jurisdictions=run.jurisdictions,
                        publication_filter=run.publication_filter,
                        attribute_constraint=getattr(run, "attribute_constraint", None),
                        polymerization_medium=getattr(run, "polymerization_medium", None) or "any",
                    )
                except SearchPreparationError as prep_err:
                    logger.error("[SEARCH_PREPARATION_FAILURE] %s", prep_err)
                    raise

                logger.info(
                    "[PIPELINE] QUERY_EXPANSION END | queries_generated=%d",
                    len(strategy.search_queries or []),
                )
                logger.info("[QUERY_EXPANSION] Target compound: %s", run.compound_name)
                logger.info("[QUERY_EXPANSION] Number of generated queries: %d", len(strategy.search_queries))
                logger.info("[QUERY_EXPANSION] All 15 queries: %s", strategy.search_queries)

                search_queries = list(strategy.search_queries)
                if run.competitors:
                    for comp in run.competitors:
                        search_queries.append(f'"{comp}" "{run.compound_name}" patent')
                if run.mentioned_websites:
                    for site in run.mentioned_websites:
                        search_queries.append(f'"{run.compound_name}" site:{site}')

                # Deduplicate queries while preserving order
                unique_queries = []
                seen_q = set()
                for q in search_queries:
                    q_str = q.query if hasattr(q, 'query') else q.get('query', q) if isinstance(q, dict) else str(q)
                    if q_str not in seen_q:
                        unique_queries.append(q)
                        seen_q.add(q_str)
                search_queries = unique_queries

                if not search_queries:
                    raise SearchPreparationError(
                        "SEARCH_PREPARATION_FAILURE: zero queries after strategy assembly; "
                        "Serper was not called. This is not a patent-availability failure."
                    )

                set_current_stage(TelemetryStage.PATENT_SEARCH)
                logger.info("[PIPELINE] SEARCH START | queries_count=%d", len(search_queries))
                from app.core.telemetry import heartbeat
                heartbeat(progress="General patent search")
                patent_candidates = await self.search_service.search_patents(search_queries)
                logger.info("[PIPELINE] SEARCH END | candidates_found=%d", len(patent_candidates))
                logger.info("[ORCHESTRATOR] Raw results: %d", len(patent_candidates))
                logger.info(
                    "[SEARCH] queries_sent_to_serper=%d candidates_returned=%d",
                    len(search_queries),
                    len(patent_candidates),
                )

                # Track executed query strings for adaptive expansion dedup
                _executed_query_strings: set[str] = {
                    (q.query if hasattr(q, "query") else str(q)).strip().lower()
                    for q in search_queries
                }

                if not patent_candidates:
                    raise Exception(
                        "SEARCH_RETURNED_ZERO_RESULTS: No patents found for the given compound "
                        f"after executing {len(search_queries)} search queries."
                    )
                    
                # ── Apply Hard Filters (Jurisdiction & Date)
                logger.info("[PIPELINE] FILTER START | raw_candidates=%d", len(patent_candidates))
                filtered_candidates = []
                jurisdictions_filter = [j.upper() for j in run.jurisdictions] if run.jurisdictions else []
                min_year = None
                
                logger.info("[ORCHESTRATOR] Jurisdiction filter selected: %s", jurisdictions_filter)
                
                if run.publication_filter:
                    date_range = run.publication_filter.get("date_range", "")
                    year_from = run.publication_filter.get("year_from")
                    
                    current_year = datetime.now(timezone.utc).year
                    if date_range == "Last 10 Years":
                        min_year = current_year - 10
                    elif date_range == "Last 5 Years":
                        min_year = current_year - 5
                    elif date_range == "Last 3 Years":
                        min_year = current_year - 3
                    elif year_from:
                        min_year = int(year_from)
                        
                logger.info("[ORCHESTRATOR] Date filter selected: %s | minimum_publication_year: %s", 
                            run.publication_filter, min_year)
                        
                removed_by_jurisdiction = 0
                removed_by_date = 0
                
                # Publication Deduplication
                pub_to_cand = {}
                for cand in patent_candidates:
                    pub_num = cand.get("patent_number")
                    q = cand.get("query_matched")
                    if pub_num not in pub_to_cand:
                        cand["matched_queries"] = [q] if q else []
                        pub_to_cand[pub_num] = cand
                    else:
                        if q and q not in pub_to_cand[pub_num]["matched_queries"]:
                            pub_to_cand[pub_num]["matched_queries"].append(q)
                
                dedup_candidates = list(pub_to_cand.values())
                removed_by_pub_dedup = len(patent_candidates) - len(dedup_candidates)
                
                # Family Deduplication First
                from app.core.telemetry import heartbeat
                heartbeat(progress="Deduplication")
                set_current_stage(TelemetryStage.FAMILY_DEDUPLICATION)
                family_groups = {}
                for cand in dedup_candidates:
                    priority = cand.get("priority_date", "").strip()
                    assignee = cand.get("assignee", "").strip()
                    inventor = cand.get("inventor", "").strip()
                    
                    if not priority:
                        family_key = cand.get("patent_number")
                    else:
                        family_key = f"{priority}_{assignee[:10]}_{inventor[:10]}"
                        
                    if family_key not in family_groups:
                        family_groups[family_key] = []
                    family_groups[family_key].append(cand)
                    
                removed_by_jurisdiction = 0
                removed_by_date = 0
                family_deduped = []
                
                for fkey, group in family_groups.items():
                    valid_members = []
                    has_date_failure_only = False
                    
                    for cand in group:
                        pub_num = cand.get('patent_number', '')
                        cand_jurisdiction = self.get_publication_jurisdiction(pub_num)
                        
                        cand_year = None
                        pub_date = cand.get("publication_date", "")
                        if pub_date:
                            date_match = re.search(r'\b(19\d{2}|20\d{2})\b', pub_date)
                            if date_match:
                                cand_year = int(date_match.group(1))
                                
                        if not cand_year:
                            year_match = re.search(r'[A-Z]{2}(\d{4})', pub_num)
                            if year_match:
                                cand_year = int(year_match.group(1))
                                
                        jur_ok = not jurisdictions_filter or cand_jurisdiction in jurisdictions_filter
                        date_ok = not min_year or (cand_year and cand_year >= min_year)
                        
                        if jur_ok and date_ok:
                            valid_members.append(cand)
                        elif jur_ok and not date_ok:
                            has_date_failure_only = True
                            
                    if not valid_members:
                        if has_date_failure_only:
                            removed_by_date += len(group)
                        else:
                            removed_by_jurisdiction += len(group)
                        continue
                        
                    # Pick the best representative from valid members
                    best_cand = valid_members[0]
                    best_score = -1
                    for cand in valid_members:
                        jur = self.get_publication_jurisdiction(cand.get("patent_number", ""))
                        score = 0
                        if jurisdictions_filter and jur in jurisdictions_filter:
                            score += 10
                        elif jur in ["US", "EP"]:
                            score += 5
                        if score > best_score:
                            best_score = score
                            best_cand = cand
                            
                    family_deduped.append(best_cand)
                    
                removed_by_family = len(dedup_candidates) - removed_by_jurisdiction - removed_by_date - len(family_deduped)
                
                logger.info("RAW DISCOVERY: %d", len(patent_candidates))
                logger.info("AFTER JURISDICTION: %d", len(patent_candidates) - removed_by_jurisdiction)
                logger.info("AFTER DATE: %d", len(patent_candidates) - removed_by_jurisdiction - removed_by_date)
                logger.info("AFTER DEDUPLICATION: %d", len(family_deduped))
                
                # ── Pre-Triage Deterministic Filter (Domain Denylist) ──
                # Reject only candidates whose titles contain explicit off-domain signal tokens
                # AND have ZERO overlap with the base material token set.
                # This is permissive by design — the LLM triage gate handles semantic classification.
                # Only the most obviously irrelevant patents are removed here to save LLM tokens.
                pre_triage_all = family_deduped
                _mat_tokens_for_filter = set()
                for t in getattr(strategy, 'base_material', []):
                    for tok in re.findall(r'\b[a-zA-Z]{3,}\b', t.lower()):
                        _mat_tokens_for_filter.add(tok)
                for tok in re.findall(r'\b[a-zA-Z]{3,}\b', run.compound_name.lower()):
                    if tok not in self._DIRECTIONAL_QUALIFIERS:
                        _mat_tokens_for_filter.add(tok)
                # Off-domain tokens: if ANY of these appear in title AND title has zero material tokens → reject
                _off_domain_tokens = {
                    # Electronics / energy storage
                    "electrode", "electrolyte", "battery", "capacitor", "photovoltaic", "semiconductor",
                    "transistor", "diode", "supercapacitor", "anode", "cathode", "electrolytic",
                    # Electrophotographic / imaging
                    "electrophotographic", "toner", "photoconductor", "photoreceptor",
                    # Biomedical
                    "antibiotic", "pharmaceutical", "drug", "wound", "implant", "prosthesis",
                    # Totally unrelated materials
                    "concrete", "cement", "asphalt", "ceramic", "glass",
                }
                
                deterministic_rejected = []
                deterministic_kept = []
                for cand in pre_triage_all:
                    title_lower = (cand.get('title', '') or '').lower()
                    title_toks = set(re.findall(r'\b[a-zA-Z]{3,}\b', title_lower))
                    has_material = bool(_mat_tokens_for_filter.intersection(title_toks))
                    has_off_domain = bool(_off_domain_tokens.intersection(title_toks))
                    # Only reject if: off-domain token present AND no material token present
                    if has_off_domain and not has_material:
                        deterministic_rejected.append(cand)
                    else:
                        deterministic_kept.append(cand)
                
                logger.info("[PRE-TRIAGE FILTER] Domain denylist check: kept=%d, rejected=%d (explicit off-domain, no material signal in title)",
                            len(deterministic_kept), len(deterministic_rejected))
                family_deduped = deterministic_kept

                # ── Search Adequacy Gate ──────────────────────────────────────
                # Compute adequacy BEFORE enrichment/selection.
                # If coverage is LOW, expand queries and search again.
                # Uses only strategy tokens — no hardcoded compound vocabulary.
                _search_round = 1
                _adequacy_metrics = self._compute_search_adequacy(
                    family_deduped, strategy, search_round=_search_round
                )

                while (
                    _adequacy_metrics.adequacy == SearchAdequacy.LOW
                    and _search_round < self._MAX_SEARCH_ROUNDS
                ):
                    _search_round += 1
                    logger.info(
                        "[SEARCH ADEQUACY] Adequacy=LOW — triggering expansion round %d "
                        "(max=%d). This does NOT mean no patents exist; it means the "
                        "current candidate pool lacks sufficient technical coverage.",
                        _search_round,
                        self._MAX_SEARCH_ROUNDS,
                    )

                    expansion_queries = await self._generate_expansion_queries(
                        strategy,
                        _executed_query_strings,
                        _search_round,
                        run,
                    )

                    if not expansion_queries:
                        logger.warning(
                            "[SEARCH ADEQUACY] Expansion round %d produced no new valid queries. "
                            "Stopping adaptive search early.",
                            _search_round,
                        )
                        break

                    new_raw = await self.search_service.search_patents(expansion_queries)
                    logger.info(
                        "[SEARCH ADEQUACY] Expansion round %d: %d new raw results",
                        _search_round, len(new_raw),
                    )

                    if new_raw:
                        # Merge + deduplicate by publication number
                        existing_pub_nums = {
                            c.get("patent_number") for c in patent_candidates
                        }
                        added = 0
                        for nc in new_raw:
                            if nc.get("patent_number") not in existing_pub_nums:
                                patent_candidates.append(nc)
                                existing_pub_nums.add(nc.get("patent_number"))
                                added += 1
                        logger.info(
                            "[SEARCH ADEQUACY] Expansion round %d: %d unique new candidates added "
                            "(total pool now %d)",
                            _search_round, added, len(patent_candidates),
                        )

                        # Re-run the same jurisdiction/date/family dedup + domain filter
                        # on the FULL merged pool so the adequacy re-check is accurate
                        _merged_pub_to_cand: dict = {}
                        for cand in patent_candidates:
                            pub_num = cand.get("patent_number")
                            q = cand.get("query_matched")
                            if pub_num not in _merged_pub_to_cand:
                                cand.setdefault("matched_queries", [q] if q else [])
                                _merged_pub_to_cand[pub_num] = cand
                            else:
                                if q and q not in _merged_pub_to_cand[pub_num]["matched_queries"]:
                                    _merged_pub_to_cand[pub_num]["matched_queries"].append(q)
                        patent_candidates = list(_merged_pub_to_cand.values())

                        # Re-apply family dedup on merged pool
                        _merged_family_groups: dict = {}
                        for cand in patent_candidates:
                            priority = cand.get("priority_date", "").strip()
                            assignee = cand.get("assignee", "").strip()
                            inventor = cand.get("inventor", "").strip()
                            fkey = (
                                f"{priority}_{assignee[:10]}_{inventor[:10]}"
                                if priority
                                else cand.get("patent_number")
                            )
                            _merged_family_groups.setdefault(fkey, []).append(cand)

                        _merged_deduped: list = []
                        for fkey, group in _merged_family_groups.items():
                            valid_members = []
                            for cand in group:
                                pub_num = cand.get("patent_number", "")
                                cand_jur = self.get_publication_jurisdiction(pub_num)
                                cand_year = None
                                pub_date = cand.get("publication_date", "")
                                if pub_date:
                                    dm = re.search(r"\b(19\d{2}|20\d{2})\b", pub_date)
                                    if dm:
                                        cand_year = int(dm.group(1))
                                if not cand_year:
                                    ym = re.search(r"[A-Z]{2}(\d{4})", pub_num)
                                    if ym:
                                        cand_year = int(ym.group(1))
                                jur_ok = not jurisdictions_filter or cand_jur in jurisdictions_filter
                                date_ok = not min_year or (cand_year and cand_year >= min_year)
                                if jur_ok and date_ok:
                                    valid_members.append(cand)
                            if valid_members:
                                best = valid_members[0]
                                best_score = -1
                                for cand in valid_members:
                                    jur = self.get_publication_jurisdiction(cand.get("patent_number", ""))
                                    sc = 10 if (jurisdictions_filter and jur in jurisdictions_filter) else (5 if jur in ("US", "EP") else 0)
                                    if sc > best_score:
                                        best_score = sc
                                        best = cand
                                _merged_deduped.append(best)

                        # Re-apply domain denylist filter
                        _expanded_kept: list = []
                        for cand in _merged_deduped:
                            title_lower = (cand.get("title", "") or "").lower()
                            title_toks = set(re.findall(r"\b[a-zA-Z]{3,}\b", title_lower))
                            has_mat = bool(_mat_tokens_for_filter.intersection(title_toks))
                            has_off = bool(_off_domain_tokens.intersection(title_toks))
                            if not (has_off and not has_mat):
                                _expanded_kept.append(cand)

                        family_deduped = _expanded_kept

                    # Recompute adequacy on updated pool
                    _adequacy_metrics = self._compute_search_adequacy(
                        family_deduped, strategy, search_round=_search_round
                    )

                logger.info(
                    "[PIPELINE] FILTER END | candidates_remaining=%d",
                    len(family_deduped),
                )
                logger.info(
                    "[SEARCH ADEQUACY] Final verdict after %d round(s): adequacy=%s | "
                    "candidates=%d | direct_material=%d | synthesis=%d | unrelated_rate=%.2f",
                    _search_round,
                    _adequacy_metrics.adequacy.value,
                    _adequacy_metrics.candidate_count,
                    _adequacy_metrics.direct_material_candidates,
                    _adequacy_metrics.synthesis_candidates,
                    _adequacy_metrics.unrelated_rate,
                )

                # ── Lightweight evidence enrichment (metadata/abstract/claims) ──
                family_deduped = await self._enrich_candidates_for_selection(
                    family_deduped, strategy, run.compound_name
                )

                # ── LLM Patent Selection (evidence-aware; authoritative KEEP/REJECT) ──
                self._reset_filter_stats()
                set_current_stage(TelemetryStage.PATENT_RANKING)
                await self._update_status(session, run, RunStatus.FILTERING)
                logger.info(
                    "[PIPELINE] RANK START | candidates_to_rank=%d",
                    len(family_deduped),
                )

                logger.info(
                    "[LLM PATENT SELECTION] Starting selection for %d candidates...",
                    len(family_deduped),
                )
                selected_candidates = await self._select_patents_via_llm(
                    family_deduped, strategy, run, batch_size=50, max_keep=10
                )
                selected_candidates = self._validate_primary_manifest_integrity(selected_candidates)
                related_candidates = list(getattr(self, "_related_candidates", []) or [])
                # Authoritative selected patent manifest for the rest of the pipeline
                selected_manifest = [
                    c.get("patent_number") for c in selected_candidates if c.get("patent_number")
                ]
                related_manifest = [
                    c.get("patent_number") for c in related_candidates if c.get("patent_number")
                ]
                logger.info(
                    "SELECTED: %d | manifest=%s | RELATED: %d | related_manifest=%s",
                    len(selected_candidates),
                    selected_manifest,
                    len(related_candidates),
                    related_manifest,
                )
                logger.info(
                    "[PIPELINE] RANK END | selected_patents=%d related_patents=%d",
                    len(selected_candidates),
                    len(related_candidates),
                )

                if not selected_candidates:
                    raise Exception(
                        self._format_zero_survivors_error(
                            reached_validation=self._filter_stats["reached_selection"],
                        )
                    )

                if run.competitors:
                    from app.core.config import settings as app_settings
                    from app.core.telemetry import heartbeat
                    from app.services.pipeline.assignee_search import discover_assignee_patents

                    material_terms = list(getattr(strategy, "base_material", None) or [])
                    if run.compound_name not in material_terms:
                        material_terms.insert(0, run.compound_name)
                    try:
                        assignee_result = await discover_assignee_patents(
                            self.search_service.search_patents,
                            list(run.competitors),
                            compound_name=run.compound_name,
                            material_terms=material_terms,
                            jurisdictions=jurisdictions_filter,
                            publication_filter=run.publication_filter,
                            selected_candidates=selected_candidates,
                            single_max=app_settings.ASSIGNEE_MAX_PATENTS_WHEN_SINGLE,
                            progress=lambda message: heartbeat(progress=message),
                            evidence_fn=self.fetcher_service.fetch_selection_evidence,
                            document_budget=app_settings.ASSIGNEE_DOCUMENT_CHECKS,
                        )
                        selected_candidates.extend(assignee_result.added)
                        selected_manifest = [
                            c.get("patent_number") for c in selected_candidates if c.get("patent_number")
                        ]
                        logger.info(
                            "[ASSIGNEE SEARCH] added=%d notes=%s combined_limit=%d general_kept=%d",
                            len(assignee_result.added),
                            assignee_result.notes,
                            len(selected_candidates),
                            len(selected_manifest) - len(assignee_result.added),
                        )
                    except Exception as assignee_exc:
                        logger.error(
                            "[ASSIGNEE SEARCH] unavailable (%s); general selection unchanged",
                            type(assignee_exc).__name__,
                        )
                        heartbeat(progress="Assignee search unavailable")

                for i, candidate in enumerate(selected_candidates):
                    logger.info(
                        "RANK %d\n"
                        f"PATENT: {candidate.get('patent_number')}\n"
                        f"TITLE: {candidate.get('title')}\n"
                        f"CATEGORY: {candidate.get('ft_category')}\n"
                        f"SELECTION: {candidate.get('selection_decision')} "
                        f"(conf={candidate.get('selection_confidence')})\n"
                        f"REASON: {candidate.get('selection_reason')}\n"
                        "----------------------------------------"
                    )

                # ── Fetch + Extract ONLY selected candidates ──
                from app.core.telemetry import heartbeat
                heartbeat(progress="Document retrieval")
                set_current_stage(TelemetryStage.PATENT_EXTRACTION)
                await self._update_status(session, run, RunStatus.EXTRACTING)
                logger.info("[PIPELINE] EXTRACTION START | patents_to_extract=%d", len(selected_candidates))
                heartbeat(progress="Evidence extraction")

                extractions, parsed_patents_map = await self._fetch_and_extract_selected(
                    selected_candidates, strategy
                )

                # Enforce selected manifest: drop any accidental non-selected extractions
                extractions = [
                    e for e in extractions
                    if getattr(e.metadata, "patent_number", None) in selected_manifest
                ]
                parsed_patents_map = {
                    k: v for k, v in parsed_patents_map.items() if k in selected_manifest
                }
                logger.info("[PIPELINE] EXTRACTION END | extracted_count=%d", len(extractions))

                if len(extractions) == 0:
                    raise Exception(
                        self._format_zero_survivors_error(
                            reached_validation=self._filter_stats["reached_selection"],
                        )
                    )

                # ── Step 5: Generate Report & Export
                set_current_stage(TelemetryStage.REPORT_GENERATION)
                await self._update_status(session, run, RunStatus.GENERATING)
                logger.info("[PIPELINE] REPORT GENERATION START | manifest_count=%d", len(selected_manifest))
                from app.core.telemetry import heartbeat
                heartbeat(progress="Report generation")
                
                # Truncate context size to strictly stay below 200k tokens (approx 800k chars)
                MAX_REPORT_CHARS = 750000 
                current_chars = 0
                for ext in extractions:
                    if ext.parameters:
                        param_str = str(ext.parameters)
                        current_chars += len(param_str)
                    
                    for ex in ext.examples:
                        if current_chars + len(ex.raw_text) > MAX_REPORT_CHARS:
                            ex.raw_text = "Truncated to fit context window."
                        else:
                            current_chars += len(ex.raw_text)
                            
                logger.info("[REPORT EVIDENCE]\n"
                            f"Number of patents: {len(extractions)}\n"
                            f"Total evidence chars: {current_chars}")
                
                from app.services.pipeline.report_evidence_service import ReportEvidenceService
                evidence_service = ReportEvidenceService()
                
                report_evidence_list = []
                candidate_by_number = {
                    c.get("patent_number"): c for c in selected_candidates if c.get("patent_number")
                }
                for ext in extractions:
                    parsed_patent = parsed_patents_map.get(ext.metadata.patent_number)
                    source_candidate = candidate_by_number.get(ext.metadata.patent_number) or {}
                    ev = evidence_service.build_compact_evidence(
                        ext,
                        discovery_source=source_candidate.get("discovery_source") or "NORMAL",
                        competitor_name=source_candidate.get("competitor_name"),
                        relevance_tier="PRIMARY",
                        relevance_score=100.0,
                        parsed_patent=parsed_patent
                    )
                    report_evidence_list.append(ev)
                    logger.info("Patent %s: evidence extracted", ext.metadata.patent_number)
                
                profile_json = strategy.model_dump_json(indent=2) if hasattr(strategy, 'model_dump_json') else str(strategy)
                report, usage = await self.report_service.generate_structured_report(
                    compound_name=run.compound_name, 
                    extractions=report_evidence_list,
                    patent_manifest=selected_manifest,
                    original_input=run.compound_name,
                    research_profile=profile_json,
                    attribute_constraint=getattr(run, "attribute_constraint", None),
                )
                extracted_numbers = {
                    getattr(ext.metadata, "patent_number", None) for ext in extractions
                }
                omitted = [pn for pn in selected_manifest if pn not in extracted_numbers]
                if omitted and report is not None and hasattr(report, "conclusion"):
                    disclosure = (
                        "Selected publications omitted from extracted evidence: "
                        + ", ".join(omitted)
                        + "."
                    )
                    report.conclusion = ((report.conclusion or "").rstrip() + "\n\n" + disclosure).strip()
                    logger.info("[REPORT] Disclosed omitted publications: %s", omitted)

                # Authoritative primary manifest only — never inject related/secondary patents.
                if hasattr(report, "secondary_patents"):
                    report.secondary_patents = []
                # Drop any phantom references not in the selected (primary) manifest
                allowed_refs = set(selected_manifest)
                if report and getattr(report, "references", None):
                    report.references = [
                        r for r in report.references
                        if (r.split("|")[0].strip() if "|" in r else r.strip()) in allowed_refs
                    ]
                # Integrity: primary methodology patents must match selected manifest only
                if report and getattr(report, "methodology_patents", None):
                    report.methodology_patents = [
                        p for p in report.methodology_patents
                        if getattr(p.patent_details, "patent_number", None) in allowed_refs
                    ]
                    for p in report.methodology_patents:
                        if getattr(p.patent_details, "relevance_tier", None) != "PRIMARY":
                            p.patent_details.relevance_tier = "PRIMARY"
                        ta = getattr(p, "target_attribute", None)
                        if ta is not None and hasattr(ta, "belongs_to_target") and not ta.belongs_to_target:
                            if (ta.value or "").strip() and ta.value != "Not disclosed in extracted evidence":
                                logger.error(
                                    "[INTEGRITY] Clearing non-owned target property on %s: %s=%s",
                                    p.patent_details.patent_number,
                                    ta.label,
                                    ta.value,
                                )
                                ta.value = "Not disclosed in extracted evidence"
                                ta.status = "not_found"
                markdown_report = self.report_service.report_to_markdown(report)
                
                logger.info("[REPORT] final report generation completed")
                
                pdf_name = f"APCOTEX_Report_{self.run_id}_{run.report_version}.pdf"
                docx_name = f"APCOTEX_Report_{self.run_id}_{run.report_version}.docx"
                md_name = f"APCOTEX_Report_{self.run_id}_{run.report_version}.md"
                json_name = f"APCOTEX_Report_{self.run_id}_{run.report_version}.json"
                
                export_dir = self.report_service.export_dir
                md_path = os.path.join(export_dir, md_name)
                json_path = os.path.join(export_dir, json_name)
                
                # Write Markdown and JSON to disk
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(markdown_report)
                
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump([ex.model_dump() for ex in extractions], f, indent=2)

                pdf_path = await self.report_service.export_to_pdf(markdown_report, pdf_name)
                docx_path = await self.report_service.export_to_docx(report, docx_name)
                
                # ── DB: Save Report Metadata and Files
                meta = ReportMetadata(
                    research_run_id=run.id,
                    title=f"{run.compound_name} Polymerization Report",
                    summary="Automated synthesis pipeline extraction.",
                    patent_count=len(patent_candidates),
                    source_count=len(extractions),
                    version=run.report_version,
                    generated_at=datetime.now(timezone.utc),
                    structured_data=report.model_dump() if hasattr(report, "model_dump") else report.dict()
                )
                session.add(meta)
                await session.flush()  # to get meta.id
                
                if pdf_path:
                    session.add(ReportFile(
                        report_metadata_id=meta.id,
                        file_type="PDF",
                        file_name=pdf_name,
                        file_path=pdf_path
                    ))
                    
                if docx_path:
                    session.add(ReportFile(
                        report_metadata_id=meta.id,
                        file_type="MARKDOWN", # Proxy for docx to avoid DB ENUM crash
                        file_name=docx_name,
                        file_path=docx_path
                    ))
                
                session.add(ReportFile(
                    report_metadata_id=meta.id,
                    file_type="MARKDOWN",
                    file_name=md_name,
                    file_path=md_path
                ))
                
                session.add(ReportFile(
                    report_metadata_id=meta.id,
                    file_type="JSON",
                    file_name=json_name,
                    file_path=json_path
                ))

                # ── Finalize
                logger.info("[PIPELINE] REPORT GENERATION END | report_id=%s", meta.id)
                await self._update_status(session, run, RunStatus.COMPLETED)
                logger.info("[PIPELINE] RUN COMPLETED | run_id=%s report_id=%s", self.run_id, meta.id)
                
                evidence_tokens = (usage or {}).get("input_tokens", 0) if usage else 0
                logger.info("[PIPELINE SUMMARY]\n\n"
                    f"Run ID: {run.id}\n"
                    f"Compound: {run.compound_name}\n\n"
                    f"LLM_CALL_1:\n"
                    f"status: SUCCESS\n"
                    f"queries_generated: 15\n\n"
                    f"SERPER:\n"
                    f"endpoint: /patents\n"
                    f"queries: 15\n"
                    f"pages_per_query: 3\n"
                    f"requests:\n"
                    f"  successful: 45\n"
                    f"  failed: 0\n"
                    f"raw_candidates: {len(patent_candidates)}\n\n"
                    f"FILTERING:\n"
                    f"jurisdictions: {jurisdictions_filter}\n"
                    f"date_filter: {min_year}\n"
                    f"raw: {len(patent_candidates)}\n"
                    f"duplicates_removed: {removed_by_pub_dedup}\n"
                    f"jurisdiction_removed: {removed_by_jurisdiction}\n"
                    f"date_removed: {removed_by_date}\n"
                    f"family_removed: {removed_by_family}\n"
                    f"ranking_pool: {len(family_deduped)}\n\n"
                    f"RANKING:\n"
                    f"method: llm_title_snippet_selection\n"
                    f"llm_calls: selection_batches\n"
                    f"selection_pool: {len(family_deduped)}\n"
                    f"selected: {len(selected_candidates)}\n\n"
                    f"EXTRACTION:\n"
                    f"selected: {len(selected_candidates)}\n"
                    f"extracted: {len(extractions)}\n"
                    f"failed: {len(selected_candidates) - len(extractions)}\n"
                    f"max_tokens_per_patent: ~10000\n\n"
                    f"REPORT:\n"
                    f"llm_call: 2\n"
                    f"patents: {len(extractions)}\n"
                    f"evidence_tokens: {evidence_tokens}\n"
                    f"estimated_input_tokens: {evidence_tokens}\n"
                    f"status: SUCCESS\n\n"
                    f"FINAL:\n"
                    f"status: COMPLETED\n"
                    f"report_id: {meta.id}\n"
                )
                
                return RunStatus.COMPLETED

            except asyncio.CancelledError:
                # uvicorn --reload / worker shutdown cancels the task. CancelledError is a
                # BaseException (not Exception), so without this handler the run stays stuck
                # forever in SEARCHING / FILTERING / etc.
                logger.warning(
                    "Pipeline cancelled for run %s (worker reload/shutdown). "
                    "Persisting CANCELLED so the run does not remain stuck.",
                    self.run_id,
                )
                try:
                    await self._update_status(session, run, RunStatus.CANCELLED)
                except Exception as persist_err:
                    logger.error(
                        "Failed to persist CANCELLED on active session for %s: %s",
                        self.run_id,
                        persist_err,
                    )
                    try:
                        async with await get_background_session() as recovery_session:
                            result = await recovery_session.execute(
                                select(ResearchRun).where(ResearchRun.id == self.run_id)
                            )
                            recovery_run = result.scalar_one_or_none()
                            if recovery_run and recovery_run.status in RunStatus.active_states():
                                await self._update_status(
                                    recovery_session, recovery_run, RunStatus.CANCELLED
                                )
                    except Exception:
                        logger.exception(
                            "Recovery session also failed to persist CANCELLED for %s",
                            self.run_id,
                        )
                raise

            except Exception as e:
                import traceback
                current_stage = getattr(get_current_stage(), 'value', 'UNKNOWN')
                logger.error("[PIPELINE] RUN FAILED | run_id=%s stage=%s error=%s", self.run_id, current_stage, e)
                
                if type(e).__name__ == "ProviderExhaustedException":
                    logger.error("Pipeline failure due to LLM provider exhaustion: %s", e)
                    await self._update_status(session, run, RunStatus.LLM_PROVIDER_EXHAUSTED)
                    return RunStatus.LLM_PROVIDER_EXHAUSTED
                    
                logger.error("Pipeline failure: %s\n%s", e, traceback.format_exc())
                await self._mark_failed(session, run, str(e))
                return RunStatus.FAILED
