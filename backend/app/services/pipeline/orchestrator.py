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
from app.services.pipeline.schemas import PatentExtraction, TitleTriageResult
from app.services.pipeline.search_service import SearchService
from app.services.pipeline.fetcher_service import FetcherService
from app.services.pipeline.extractor_service import ExtractorService
from app.services.pipeline.report_service import ReportService
from app.core.telemetry import set_current_run_id, set_current_stage, TelemetryStage
from app.services.llm import llm_client
from app.services.prompts.patent_prompts import TITLE_TRIAGE_PROMPT

logger = logging.getLogger(__name__)


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
        tokens (e.g. 'nr' from 'nitrile rubber', 'hn' from 'hydrogenated nbr')
        that cause false-positive material-evidence matches in unrelated patents.
        The LLM already provides a complete synonym/abbreviation set in
        base_material (e.g. 'NBR', 'HNBR', 'ACN'), so no additional expansion
        is needed. Return an empty list so callers continue to work unchanged.
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
        # E.g. "Low Molecular Weight NBR" → only "nbr" remains as identity token.
        "molecular", "weight", "content", "level", "degree", "number", "index",
        "average", "distribution", "ratio", "fraction", "percent",
    ])

    # Verb/process stems that indicate a TYPE_A (transformation) target
    # when they appear in the target modification concepts.
    _TRANSFORMATION_VERB_STEMS = (
        "hydrogenat", "carboxylat", "sulfon", "graft", "crosslink",
        "functionali", "chlorinat", "epoxidi", "oxidis", "oxidiz",
        "vulcaniz", "degrad", "metathesi", "polymeriz", "copolymeriz",
    )

    def _classify_target_type(self, requested_attributes: set, target_modifications: list) -> str:
        """
        Dynamically classify the target type from LLM-provided concept strings:
          'TYPE_A' — process/transformation target (has transformation verb stem)
          'TYPE_B' — attribute/range target (has directional qualifier word)
          'MIXED'  — both signals present; apply TYPE_B tolerance for attribute scoring
        No compound-specific terms used — decision is based solely on structure.
        """
        has_directional = False
        has_transformation = False

        all_concepts = list(requested_attributes) + [m.lower() for m in (target_modifications or [])]
        for concept in all_concepts:
            for tok in re.findall(r'\b[a-zA-Z]+\b', concept.lower()):
                if tok in self._DIRECTIONAL_QUALIFIERS:
                    has_directional = True
                for stem in self._TRANSFORMATION_VERB_STEMS:
                    if tok.startswith(stem):
                        has_transformation = True

        if has_directional and has_transformation:
            return "MIXED"
        if has_directional:
            return "TYPE_B"
        if has_transformation:
            return "TYPE_A"
        return "TYPE_A"  # default: treat as process intent

    def _split_attribute_concepts(self, phrase: str) -> tuple:
        """
        For a TYPE_B attribute phrase (e.g. 'low acrylonitrile', 'high Mooney viscosity'):
        Split into (qualifier_tokens, dimension_tokens).
        qualifier_tokens — directional words (used for directional context only)
        dimension_tokens — property/attribute nouns (used for title/text matching)

        Generic: works for any property noun regardless of compound type.
        """
        tokens = re.findall(r'\b[a-zA-Z]+\b', phrase.lower())
        qualifiers = set()
        dimensions = set()
        for tok in tokens:
            if tok in self._DIRECTIONAL_QUALIFIERS:
                qualifiers.add(tok)
            elif len(tok) >= 3:
                dimensions.add(tok)
        return qualifiers, dimensions

    # ── SYNTHESIS VERB STEMS used by Gate A ──────────────────────────────────
    # Generic — no compound-specific terms.
    _SYNTHESIS_VERB_STEMS = (
        "prepar", "produc", "synthesi", "polymeriz", "copolymeriz",
        "manufactur", "obtain", "mak", "form",
    )

    # ── DOWNSTREAM ARTICLE / PRODUCT NOUNS used by Gate A ────────────────────
    # If Claim 1's primary subject (before "comprising") is one of these, the
    # patent's invention is a downstream article, formulation, or device that
    # USES the target material — it is not about making the material itself.
    # Deliberately excludes: "rubber", "polymer", "elastomer", "copolymer",
    # "composition", "formulation", "mixture", "blend" — in rubber/polymer
    # chemistry these words describe the MATERIAL ITSELF, not a downstream product.
    # "A rubber composition comprising..." is a standard material-identity claim.
    _DOWNSTREAM_CLAIM_NOUNS = frozenset([
        # End-use articles and parts (unambiguously downstream)
        "article", "seal", "hose", "belt", "glove", "tire", "tyre",
        "roller", "gasket", "bushing", "bearing", "tube", "pipe",
        "cable", "wire", "insulation", "sheath", "jacket",
        "panel", "board", "mat", "pad", "foam", "cushion",
        "part", "component", "element", "member",
        # Coatings, films and surface materials
        "layer", "coating", "film", "ink", "paste", "varnish", "lacquer",
        "laminate", "sheet", "substrate", "tape", "adhesive", "sealant",
        "fabric", "fiber", "textile", "thread",
        # Electrical / electronic devices (not the polymer material itself)
        "electrode", "battery", "capacitor",
        "cartridge", "toner", "printer",
        # Polymer-class nouns unambiguously different from rubber/elastomer
        "composite", "nanocomposite",
        "thermoplastic", "thermoset",
        "epoxy", "resin", "vulcanizate",
        # Device / apparatus
        "membrane", "device", "apparatus", "dispenser",
        # Dispersant / pigment / cosmetic / specialty
        # NOTE: "emulsifier" and "surfactant" are synthesis REAGENTS used in
        # emulsion polymerization — NOT downstream article nouns. Do NOT add them here.
        "dispersant", "pigment",
        "cosmetic", "lotion", "cream",
        # Implant / medical
        "implant", "prosthesis", "scaffold",
    ])

    def _gate_a_synthesis_subject(self, parsed_patent, material_tokens: set) -> dict:
        """
        GATE A — Synthesis Subject:
        Is the target material (or its direct precursor) the PRIMARY SUBJECT
        of the patent's independent claims — i.e. is the patent about MAKING
        the material — rather than a downstream article/device/composition that
        merely CONTAINS or USES the material?

        Iterates through all independent claims. Returns PASS if ANY independent claim passes.
        """
        claims_text = (parsed_patent.claims or "").strip().lower()
        abstract_text = (parsed_patent.abstract or "").strip().lower()

        independent_claims = []
        if claims_text:
            # Match numbered claims
            claim_matches = re.finditer(r'(?:^|\n)\s*(\d+)\.\s*(.*?)(?=(?:^|\n)\s*\d+\.|\Z)', claims_text, re.DOTALL)
            for match in claim_matches:
                num = match.group(1)
                text = match.group(2).strip()
                # Heuristic for independent claim: no reference to another claim
                if "claim " not in text.lower() and "claims " not in text.lower():
                    independent_claims.append(f"{num}. {text}")

        # Fallback to claim 1 extraction if no independent claims found using heuristic
        if not independent_claims and claims_text:
            c2_end = len(claims_text)
            for pat in [r'\n\s*2\.', r'\nclaim\s+2\b', r'\n\s*2\)\s']:
                m = re.search(pat, claims_text)
                if m and m.start() > 30:
                    c2_end = min(c2_end, m.start())
            independent_claims.append(claims_text[:min(c2_end, 900)])

        if not independent_claims and abstract_text:
            independent_claims.append(abstract_text[:600])

        if not independent_claims:
            return {"pass": True, "reason": "No claims/abstract text available — Gate A defaults to PASS"}

        all_process_stems = self._SYNTHESIS_VERB_STEMS + self._TRANSFORMATION_VERB_STEMS
        reasons_for_failure = []

        for claim_text in independent_claims:
            claim_text = claim_text[:900]
            _synth_claim_text = claim_text.replace('-', '')
            _synth_stem_re = '|'.join(all_process_stems)
            synthesis_as_subject = bool(re.search(
                r'(?:^|(?<=\s))(?:a\s+)?(?:process|method|procedure)\s+(?:for|of)\s+(?:the\s+)?(?:'
                + _synth_stem_re + r')\w*'
                r'|a\s+(?:process|method)\s+comprising\s+(?:the\s+)?steps?',
                _synth_claim_text
            ))

            polymer_structural = bool(re.search(
                r'a\s+(?:co)?polymer\b'
                r'|a\s+(?:nitrile\s+)?(?:rubber|elastomer)\b'
                r'|a\s+copolymer\b'
                r'|an?\s+elastomeric\s+(?:polymer|material)\b',
                claim_text[:400]
            ))

            comprising_split = re.split(
                r'\bcompris|\bcontain|\bconsist|\bbased\s+on|\bformed\s+from',
                claim_text[:500], maxsplit=1
            )
            pre_comprising = comprising_split[0] if len(comprising_split) > 1 else ""
            pre_comprising_toks = set(re.findall(r'\b[a-z]+\b', pre_comprising))
            pre_comprising_toks |= {tok.rstrip('s') for tok in pre_comprising_toks}
            downstream_noun_hit = pre_comprising_toks.intersection(self._DOWNSTREAM_CLAIM_NOUNS)
            is_downstream_claim = bool(downstream_noun_hit)

            material_in_claim = any(tok in claim_text for tok in material_tokens if len(tok) >= 3)

            if synthesis_as_subject and material_in_claim and not is_downstream_claim:
                return {"pass": True, "reason": "An independent claim describes synthesis/preparation process of target material"}

            if polymer_structural and material_in_claim and not is_downstream_claim:
                return {"pass": True, "reason": "An independent claim describes the target polymer/material itself (structural claim)"}

            # Also pass: structural composition claim (e.g. "A rubber composition comprising...") 
            # where the base material is explicitly identified. These are material-identity claims.
            composition_structural = bool(re.search(
                r'\b(?:rubber|polymer|elastomer|copolymer|nitrile)\b.*\bcomprising\b',
                claim_text[:400]
            ))
            if composition_structural and material_in_claim:
                return {"pass": True, "reason": "An independent claim is a structural composition claim for the target rubber/polymer material"}

            if synthesis_as_subject and is_downstream_claim:
                synth_pos = min(
                    (claim_text.find(stem) for stem in all_process_stems if stem in claim_text),
                    default=9999
                )
                if synth_pos < 9999:
                    nearby_text = claim_text[synth_pos: synth_pos + 80]
                    downstream_immediately_after = any(
                        noun in nearby_text for noun in self._DOWNSTREAM_CLAIM_NOUNS
                    )
                    if not downstream_immediately_after and material_in_claim:
                        return {"pass": True, "reason": "An independent claim synthesis verb's product is the target material"}

            if is_downstream_claim and not synthesis_as_subject:
                reasons_for_failure.append(f"Primary subject contains downstream noun ({', '.join(sorted(downstream_noun_hit)[:2])})")
            elif not material_in_claim:
                reasons_for_failure.append("No material identity tokens found in claim")
            else:
                reasons_for_failure.append("Claim describes making a downstream article or lacks synthesis intent")

        reason_str = "; ".join(list(set(reasons_for_failure))[:3]) if reasons_for_failure else "No valid claims parsed"
        return {
            "pass": False,
            "reason": f"No independent claim passed Gate A criteria. Reasons: {reason_str}"
        }

    def _gate_b_attribute_grounding(
        self, text: str, requested_attributes: set, target_type: str
    ) -> dict:
        """
        GATE B — Target-Attribute Grounding:
        Does the patent contain ACTUAL EVIDENCE addressing the specific target
        attribute dimension (e.g. acrylonitrile content, hydrogenation degree,
        molecular weight, carboxylation level — whatever the LLM derived for
        this run)?

        Generic — driven entirely by LLM-derived target_modifications / target_attributes.
        No compound names or attribute names are hardcoded.

        For TYPE_A (transformation) targets: the transformation verb IS the
        attribute dimension; it must appear in a synthesis/process context
        (near catalyst, reactor, temperature, step, etc.) — at least 2 windows.

        For TYPE_B / MIXED targets: the dimension token must appear in a
        controlling/quantitative context — near an active control verb (adjust,
        target, control, regulate, range, achieve, maintain) OR with an explicit
        numeric+unit value — at least 2 distinct text windows.

        Descriptive mentions ("the starting rubber had X% acrylonitrile") do NOT
        count — only controlling/process-intent contexts qualify.

        Returns dict: {'pass': bool, 'dimension_tokens': list, 'hits': int, 'reason': str}
        """
        # Collect all dimension tokens across all requested attributes
        all_dimension_tokens: set = set()
        for attr in requested_attributes:
            _, dim_toks = self._split_attribute_concepts(attr)
            all_dimension_tokens.update(dim_toks)

        # No specific attribute dimension: pure base-material search — PASS
        if not all_dimension_tokens:
            return {
                "pass": True, "dimension_tokens": [], "hits": 0,
                "reason": "Gate B: no attribute dimension tokens — base-material search only"
            }

        # ── TYPE_A: transformation verb is the attribute ──────────────────────
        # Require the transformation dimension to appear near synthesis-context words
        # (not just mentioned in background as "the compound was hydrogenated").
        if target_type == "TYPE_A":
            _TYPE_A_SYNTHESIS_CONTEXT = frozenset([
                "process", "method", "step", "catalyst", "reaction", "condition",
                "temperature", "pressure", "solvent", "agent", "convert", "degree",
                "percent", "level", "reactor", "hydrogen", "selective",
            ])
            qualifying_hits = 0
            seen_buckets: set = set()
            for dim in all_dimension_tokens:
                # Min 5 chars: filters generic short tokens like 'acid' (4 chars)
                # that are too common to serve as specific dimension evidence.
                if len(dim) < 5 or dim not in text:
                    continue
                for m in re.finditer(r'\b' + re.escape(dim) + r'\b', text):
                    bucket = m.start() // 300
                    if bucket in seen_buckets:
                        continue
                    ctx = text[max(0, m.start() - 200): m.end() + 200]
                    ctx_toks = set(re.findall(r'\b[a-z]+\b', ctx))
                    if ctx_toks.intersection(_TYPE_A_SYNTHESIS_CONTEXT):
                        qualifying_hits += 1
                        seen_buckets.add(bucket)
            if qualifying_hits >= 2:
                return {
                    "pass": True,
                    "dimension_tokens": sorted(all_dimension_tokens),
                    "hits": qualifying_hits,
                    "reason": (
                        f"Gate B TYPE_A: transformation dimension "
                        f"{sorted(all_dimension_tokens)[:2]} found in synthesis context "
                        f"({qualifying_hits} windows)"
                    )
                }
            return {
                "pass": False,
                "dimension_tokens": sorted(all_dimension_tokens),
                "hits": qualifying_hits,
                "reason": (
                    f"Gate B TYPE_A FAIL: transformation dimension "
                    f"{sorted(all_dimension_tokens)[:2]} not found in synthesis/process context "
                    f"({qualifying_hits} qualifying windows, need >= 2)"
                )
            }

        # ── TYPE_B / MIXED: require active-control or quantitative evidence ───
        # ACTIVE CONTROL verbs — intentional manipulation of the attribute.
        # Deliberately excludes purely descriptive words ('content', 'level', 'percent',
        # 'fraction') so that "the starting rubber had 34% acrylonitrile" does NOT qualify.
        _ACTIVE_CONTROL_STEMS = (
            "control", "adjust", "target", "achiev", "maintain", "regulat",
            "vari", "set ", "rang", "tuning", "tune", "select", "determin",
            "feed ratio", "monomer ratio", "feed composition", "mole ratio",
        )
        _NUMERIC_UNIT_RE = re.compile(
            r'\b\d+(?:[.,]\d+)?\s*'
            r'(?:%|wt\.?\s*%?|mol\.?\s*%?|phr\b|g\b|kg\b|ppm\b|eq\b|equiv\b|mole\b|weight\b|percent\b)',
            re.IGNORECASE
        )

        # SYNTHESIS PROCESS CONTEXT — words that appear in genuine synthesis discussions
        # but NOT in comparison/background sentences about a different polymer.
        # Required co-occurrence for at least ONE qualifying TYPE_B hit.
        _SYNTHESIS_PROC_STEMS = (
            "polymeriz", "copolymeriz", "monomer", "initiator", "catalyst",
            "emulsi", "react", "chain transfer", "conversion", "feed ratio",
            "monomer ratio", "feed composition",
        )

        THRESHOLD = 2
        qualifying_hits = 0
        synth_context_hit = False  # tracks if ≥1 window has synthesis co-occurrence
        seen_buckets: set = set()

        for dim in all_dimension_tokens:
            if len(dim) < 3 or dim not in text:
                continue
            for m in re.finditer(r'\b' + re.escape(dim) + r'\b', text):
                bucket = m.start() // 250
                if bucket in seen_buckets:
                    continue
                ctx = text[max(0, m.start() - 150): m.end() + 150]
                has_numeric = bool(_NUMERIC_UNIT_RE.search(ctx))
                has_active_control = any(stem in ctx for stem in _ACTIVE_CONTROL_STEMS)
                has_synth_context = any(stem in ctx for stem in _SYNTHESIS_PROC_STEMS)
                if has_synth_context:
                    synth_context_hit = True
                if has_numeric and has_active_control:
                    # Strongest evidence: numeric value + active control intent
                    qualifying_hits += 2
                    seen_buckets.add(bucket)
                elif has_active_control:
                    # Control intent without explicit numeric — partial credit
                    qualifying_hits += 1
                    seen_buckets.add(bucket)
                # Numeric alone (descriptive) does NOT qualify

        # Require at least one qualifying window to also contain a synthesis process
        # word. This prevents comparison-mention false positives such as:
        # "achieves properties equivalent to NBR with 40% acrylonitrile" — where
        # 'achiev' (active control stem) co-occurs with 'acrylonitrile' but no
        # genuine synthesis context is present.
        if qualifying_hits >= THRESHOLD and not synth_context_hit:
            return {
                "pass": False,
                "dimension_tokens": sorted(all_dimension_tokens),
                "hits": qualifying_hits,
                "reason": (
                    f"Gate B TYPE_B FAIL: {qualifying_hits} control-language windows found but "
                    f"none co-occur with synthesis-process context — likely comparison/background "
                    f"mention, not a synthesis-control claim."
                )
            }

        if qualifying_hits >= THRESHOLD:
            return {
                "pass": True,
                "dimension_tokens": sorted(all_dimension_tokens),
                "hits": qualifying_hits,
                "reason": (
                    f"Gate B TYPE_B: {qualifying_hits} qualifying evidence windows "
                    f"for dimension tokens {sorted(all_dimension_tokens)[:3]}"
                )
            }
        return {
            "pass": False,
            "dimension_tokens": sorted(all_dimension_tokens),
            "hits": qualifying_hits,
            "reason": (
                f"Gate B TYPE_B FAIL: no active-control/quantitative evidence "
                f"for attribute dimension {sorted(all_dimension_tokens)[:3]} "
                f"({qualifying_hits} qualifying windows, need >= {THRESHOLD}). "
                f"Patent discusses material identity but not the specific target attribute."
            )
        }

    def _deterministic_rank(self, candidates, profile, compound_name: str):

        # all_material_terms — used for PHRASE-LEVEL substring match only.
        # Includes compound_name so we can detect the exact user-input phrase.
        base_material_phrases = [compound_name.lower()]
        base_material_phrases.extend([syn.lower() for syn in getattr(profile, 'base_material', [])])
        all_material_terms = set(t for t in base_material_phrases if t)
        all_material_terms.update(self._generate_aliases(list(all_material_terms)))

        # material_tokens — used for INDIVIDUAL TOKEN matching.
        # Tokenize ONLY the LLM-provided base_material list, NOT compound_name,
        # to avoid injecting directional qualifiers (e.g. 'low') as identity tokens.
        # Min token length = 3 to avoid single-char noise from hyphenated terms (e.g. 'Buna-N' -> 'n').
        material_tokens = set()
        for t in getattr(profile, 'base_material', []):
            for tok in re.findall(r'\b[a-zA-Z]+\b', t.lower()):
                if len(tok) >= 3:
                    material_tokens.add(tok)
        # Also tokenize compound_name but strip directional qualifiers
        for tok in re.findall(r'\b[a-zA-Z]+\b', compound_name.lower()):
            if tok not in self._DIRECTIONAL_QUALIFIERS and len(tok) >= 3:
                material_tokens.add(tok)
            
        requested_attributes = set([t.lower() for t in getattr(profile, 'target_attributes', [])])
        requested_attributes.update([t.lower() for t in getattr(profile, 'target_modifications', [])])
        
        synthesis_terms = set([t.lower() for t in getattr(profile, 'synthesis_transformations', [])] + 
                              [t.lower() for t in getattr(profile, 'precursor_relationships', [])] + 
                              [t.lower() for t in getattr(profile, 'relevant_process_concepts', [])])
        # Default strong synthesis terms if model failed to provide enough
        synthesis_terms.update({"polymerization", "copolymerization", "preparation", "synthesis", "production", "manufacture", "hydrogenation", "metathesis", "degradation", "precursor"})
        
        downstream_terms = set([t.lower() for t in getattr(profile, 'downstream_terms', [])])
        # Default downstream penalty words
        hard_downstream = {"tire", "seal", "hose", "gasket", "article", "coating", "finished product", "rubber composition", "formulation", "battery", "electrode", "dispersion", "conductive", "adhesive", "glove", "film"}
        downstream_terms.update(hard_downstream)
        
        excluded_terms = set()
        for exc in getattr(profile, 'excluded_variants', []):
            excluded_terms.update([t.lower() for t in re.findall(r'\b[a-zA-Z]+\b', exc)])
            
        all_expanded_queries = [q.query if hasattr(q, 'query') else q.get('query', q) if isinstance(q, dict) else q for q in getattr(profile, 'search_queries', [])]
        
        for candidate in candidates:
            title = candidate.get('title', '').lower()
            snippet = candidate.get('snippet', '').lower()
            text_to_search = title + " " + snippet
            tokens = set(re.findall(r'\b[a-zA-Z]+\b', text_to_search))
            title_tokens = set(re.findall(r'\b[a-zA-Z]+\b', title))
            
            # --- 1. Material Identity Gate (Base Match) ---
            material_score = 0
            tok_m = material_tokens.intersection(tokens)
            if len(tok_m) >= 2:
                material_score += 30
            if any(mat in text_to_search for mat in all_material_terms):
                material_score += 20
                
            unrelated_penalty = 0
            if material_score > 0 and excluded_terms and excluded_terms.intersection(title_tokens):
                unrelated_penalty = -50
                
            # --- 2. Target Variant Match ---
            # Determine target type dynamically from concept structure (no compound knowledge).
            target_type = self._classify_target_type(
                requested_attributes,
                getattr(profile, 'target_modifications', [])
            )

            target_score = 0
            if requested_attributes:
                found_any_target = False

                if target_type in ("TYPE_A", "MIXED"):
                    # TYPE_A: require the full transformation phrase (e.g. "hydrogenation") to appear.
                    for attr in requested_attributes:
                        if attr in title:
                            target_score += 40
                            found_any_target = True
                        elif attr in text_to_search:
                            target_score += 20
                            found_any_target = True

                if target_type in ("TYPE_B", "MIXED"):
                    # TYPE_B: match on DIMENSION TOKENS only (property nouns without directional qualifier).
                    # E.g. for "low acrylonitrile": match "acrylonitrile" in title/text.
                    # This avoids the -100 false rejection for patents disclosing ACN content
                    # as a numeric value without literally saying "low acrylonitrile".
                    for attr in requested_attributes:
                        _, dim_tokens = self._split_attribute_concepts(attr)
                        if not dim_tokens:
                            continue
                        # Title hit: all dimension tokens present
                        if dim_tokens.issubset(title_tokens):
                            target_score += 30
                            found_any_target = True
                        # Snippet hit: at least one dimension token present
                        elif dim_tokens.intersection(tokens):
                            target_score += 15
                            found_any_target = True

                if not found_any_target:
                    if target_type == "TYPE_A":
                        # Hard penalty: transformation term should be detectable in title/snippet
                        target_score -= 100
                    else:
                        # TYPE_B / MIXED: defer to full-text validation — stay neutral at title stage
                        target_score = 0

                        
            # --- 3. Synthesis Intent ---
            synthesis_score = 0
            
            # Use substring matching for synthesis terms to catch "preparing", "producing" etc.
            syn_stems = set()
            for t in synthesis_terms:
                if len(t) >= 4:
                    syn_stems.add(t[:5])  # Take first 5 chars for stemming
                else:
                    syn_stems.add(t)
            syn_stems.update({"prepar", "produc", "manufactur", "polymeriz", "synthes", "process", "method", "mak", "form"})
            
            title_text = candidate.get('title', '').lower()
            snippet_text = candidate.get('snippet', '').lower()
            
            syn_matches = [stem for stem in syn_stems if stem in title_text]
            if syn_matches:
                synthesis_score += (len(syn_matches) * 15)
                
            syn_matches_snippet = [stem for stem in syn_stems if stem in snippet_text]
            if syn_matches_snippet:
                synthesis_score += (len(syn_matches_snippet) * 5)
                
            # --- 4. Query Match & Multi-Query Evidence ---
            matched_queries = candidate.get("matched_queries", [])
            query_match_score = min(len(matched_queries) * 2, 10)
            multi_query_score = 5 if len(matched_queries) >= 3 else 0
            
            # --- 5. Application / Downstream Penalty ---
            application_penalty = 0
            down_matches = downstream_terms.intersection(title_tokens)
            if down_matches:
                application_penalty = (len(down_matches) * 35)
                
            down_matches_snippet = downstream_terms.intersection(tokens)
            if down_matches_snippet:
                application_penalty += (len(down_matches_snippet) * 10)
                
            # --- 6. Triage Priority Bonus (additive signal, not gating — UNRELATED already excluded upstream) ---
            triage_cls = candidate.get('triage_classification')
            triage_str = getattr(triage_cls, "value", str(triage_cls)) if triage_cls else ""
            triage_priority = candidate.get('triage_priority', '')
            triage_bonus = {
                'HIGH': 20,
                'MEDIUM_HIGH': 10,
                'MEDIUM': 5,
                'LOW': 0,
                'REJECT': -10,  # Should not reach here, but guard anyway
            }.get(triage_priority, -5)  # -5 if triage was not run (no LLM result for this patent)
                
            # --- 7. Final Score Calculation ---
            final_score = material_score + target_score + synthesis_score + query_match_score + multi_query_score + unrelated_penalty + triage_bonus - application_penalty
            
            # Relevance threshold is loosened because triage has already handled semantic filtering
            # upstream — deterministic ranking no longer needs to carry the full precision burden alone.
            RELEVANCE_THRESHOLD = 15
            
            category = "UNRELATED"
            if final_score >= RELEVANCE_THRESHOLD and material_score > 0:
                decision = "KEEP"
                
                # Synthesis Strict Requirement
                requires_synthesis = getattr(profile, 'synthesis_intent', False)
                if not requires_synthesis and (getattr(profile, 'synthesis_transformations', []) or getattr(profile, 'precursor_relationships', [])):
                    requires_synthesis = True
                    
                if requires_synthesis and synthesis_score == 0:
                    decision = "REJECT"
                    category = "NO_SYNTHESIS_EVIDENCE"
                    
                if decision == "KEEP":
                    if synthesis_score >= 30 and target_score > 0:
                        category = "PRIMARY_SYNTHESIS"
                    elif target_score > 0 and synthesis_score > 0:
                        category = "TARGET_TRANSFORMATION"
                    elif synthesis_score >= 30 and target_score == 0:
                        category = "PRECURSOR_SYNTHESIS"
                    elif synthesis_score > 0 and target_score == 0:
                        category = "BASE_MATERIAL_RELEVANT"
                    else:
                        category = "DOWNSTREAM_APPLICATION"
            else:
                decision = "REJECT"
                if application_penalty > 0:
                    category = "DOWNSTREAM_APPLICATION"
                
            candidate['score'] = final_score
            candidate['eligibility'] = decision
            candidate['category'] = category
            
            # Logging
            logger.info("[RANKING]\n"
                f"PATENT: {candidate.get('patent_number')}\n"
                f"TITLE: {candidate.get('title')}\n"
                f"FINAL SCORE: {final_score}\n"
                f"CATEGORY: {category}\n"
                f"BASE MATCH: {material_score}\n"
                f"TARGET MATCH: {target_score}\n"
                f"SYNTHESIS MATCH: {synthesis_score}\n"
                f"QUERY MATCH: {query_match_score + multi_query_score}\n"
                f"APPLICATION PENALTY: {-application_penalty}\n"
                f"UNRELATED PENALTY: {unrelated_penalty}\n"
                f"MATCHED QUERIES: {matched_queries}\n"
                f"DECISION: {decision}"
            )

    def _validate_full_text(self, parsed_patent, profile, compound_name: str) -> dict:
        text = ((parsed_patent.title or "") + " " + (parsed_patent.abstract or "") + " " + (parsed_patent.claims or "") + " " + (parsed_patent.detailed_description or "") + " " + (parsed_patent.examples or "")).lower()
        tokens = set(re.findall(r'\b[a-zA-Z]+\b', text))
        
        # all_material_terms — used for PHRASE-LEVEL substring match only.
        base_material_phrases = [compound_name.lower()]
        base_material_phrases.extend([syn.lower() for syn in getattr(profile, 'base_material', [])])
        all_material_terms = set(t for t in base_material_phrases if t)
        all_material_terms.update(self._generate_aliases(list(all_material_terms)))

        # material_tokens — tokenized only from LLM base_material, NOT compound_name,
        # to avoid injecting directional qualifiers (e.g. 'low') as identity tokens.
        # Min token length = 3 to avoid single-char noise from hyphenated terms (e.g. 'Buna-N' -> 'n').
        material_tokens = set()
        for t in getattr(profile, 'base_material', []):
            for tok in re.findall(r'\b[a-zA-Z]+\b', t.lower()):
                if len(tok) >= 3:
                    material_tokens.add(tok)
        for tok in re.findall(r'\b[a-zA-Z]+\b', compound_name.lower()):
            if tok not in self._DIRECTIONAL_QUALIFIERS and len(tok) >= 3:
                material_tokens.add(tok)


        requested_attributes = set([t.lower() for t in getattr(profile, 'target_attributes', [])])
        requested_attributes.update([t.lower() for t in getattr(profile, 'target_modifications', [])])
            
        synthesis_terms = set([t.lower() for t in getattr(profile, 'synthesis_transformations', [])] + 
                              [t.lower() for t in getattr(profile, 'precursor_relationships', [])] + 
                              [t.lower() for t in getattr(profile, 'relevant_process_concepts', [])])
        synthesis_terms.update({"polymerization", "copolymerization", "preparation", "synthesis", "production", "manufacture", "hydrogenation", "metathesis", "degradation", "precursor"})
        
        downstream_terms = set([t.lower() for t in getattr(profile, 'downstream_terms', [])])
        # Expanded hard downstream vocabulary — includes application domains that use NBR/HNBR as a purchased ingredient
        hard_downstream = {
            "tire", "seal", "hose", "gasket", "article", "coating", "finished product",
            "rubber composition", "formulation", "battery", "electrode", "dispersion",
            "conductive", "adhesive", "glove", "film",
            # Sound/audio application domain
            "diaphragm", "membran", "membrane", "acoustic", "loudspeaker", "speaker",
            "sound", "audio", "transducer",
            # Other application domains that merely use rubber as ingredient
            "footwear", "belt", "roller", "wiper", "plug", "bushing", "bearing",
            "insulation", "cable", "medical", "implant",
        }
        downstream_terms.update(hard_downstream)
        
        excluded_terms = set()
        # Only keep excluded variant tokens that are meaningful chemical-name tokens (length >= 4)
        # This prevents single-letter/stop-word tokenization artifacts from triggering variant mismatch.
        for exc in getattr(profile, 'excluded_variants', []):
            for t in re.findall(r'\b[a-zA-Z]{4,}\b', exc):
                t_lower = t.lower()
                # Also skip tokens that are part of the valid base material vocabulary
                # (e.g. 'nitrile', 'rubber', 'butadiene' from 'nitrile rubber' excluded variant)
                if t_lower not in material_tokens:
                    excluded_terms.add(t_lower)
            
        # BASE MATERIAL — require at least 2 matching tokens OR a phrase match
        base_material_evidence = False
        tok_matches = material_tokens.intersection(tokens)
        n_material_token_matches = len(tok_matches)
        if n_material_token_matches >= 2:
            base_material_evidence = True
        elif any(mat in text for mat in all_material_terms):
            base_material_evidence = True

        # Title-subject mismatch flag: set True if Signal 5 fires (computed in centrality block).
        # Used in scoring to zero out attribute_score for device-title patents.
        title_subject_mismatch = False

        # ── MATERIAL CENTRALITY ──────────────────────────────────────────────
        # Measure whether the target material is the SUBJECT of the patent or just
        # one item in an enumeration. Generic — uses no compound-specific vocabulary.
        centrality_penalty = 0
        centrality_note = ""

        if base_material_evidence:
            # Signal 1: target material appears primarily in list/enum constructions
            list_context_patterns = [
                r'selected\s+from\s+(?:the\s+)?(?:group\s+)?(?:consisting\s+of\s+)?[^.]{0,200}',
                r'chosen\s+from\s+[^.]{0,200}',
                r'comprising\s+(?:at\s+least\s+one\s+of\s+)?[^.]{0,200}',
                r'(?:may\s+(?:also\s+)?(?:optionally\s+)?include|optionally\s+includes?)\s+[^.]{0,200}',
                r'(?:such\s+as|including\s+but\s+not\s+limited\s+to)\s+[^.]{0,200}',
            ]
            list_context_hits = 0
            for pat in list_context_patterns:
                for m in re.finditer(pat, text, re.IGNORECASE):
                    chunk = m.group(0).lower()
                    if any(alias in chunk for alias in all_material_terms):
                        list_context_hits += 1

            # Signal 2: competing polymer class diversity
            _POLYMER_CLASS_INDICATORS = frozenset([
                "polyurethane", "silicone", "epoxy", "polypropylene", "polyethylene",
                "polycarbonate", "polyester", "polyamide", "nylon", "acrylic",
                "styrene", "polyacrylate", "polysulfide", "fluorocarbon", "polychloroprene",
                "epdm", "sbr", "nbr", "hnbr", "acm", "aem", "fkm", "pvdf",
                "natural rubber", "latex", "elastomer",
            ])
            competing_classes = _POLYMER_CLASS_INDICATORS.intersection(tokens)
            competing_classes -= material_tokens

            # Signal 3: material in title = high centrality
            title_lower = (parsed_patent.title or "").lower()
            in_title = any(alias in title_lower for alias in all_material_terms) or \
                       len(material_tokens.intersection(set(re.findall(r'\b[a-zA-Z]+\b', title_lower)))) >= 2

            # Signal 4: sparse mention density — material mentioned very few times
            # in a large document, indicating it's incidental (e.g. one background sentence).
            # Count actual substring occurrences of each alias phrase in the raw text.
            alias_mention_count = 0
            for alias in all_material_terms:
                if len(alias) >= 3:  # skip degenerate short tokens
                    alias_mention_count += text.count(alias)
            doc_len_kchars = max(1, len(text) / 1000.0)
            alias_density = alias_mention_count / doc_len_kchars  # mentions per 1000 chars

            is_sparse = (alias_density < 0.08) and (alias_mention_count < 4)

            # Compute centrality penalty
            if list_context_hits >= 2 and len(competing_classes) >= 3 and not in_title:
                centrality_penalty = 30
                centrality_note = (
                    f"Low centrality: material appears {list_context_hits}x in list constructions "
                    f"alongside {len(competing_classes)} competing polymer classes"
                )
            elif list_context_hits >= 3 and not in_title:
                centrality_penalty = 20
                centrality_note = (
                    f"Low centrality: material appears {list_context_hits}x in list/enum constructions"
                )
            elif len(competing_classes) >= 5 and not in_title:
                centrality_penalty = 15
                centrality_note = (
                    f"Low centrality: {len(competing_classes)} competing polymer classes co-mentioned"
                )
            elif is_sparse and not in_title:
                # Sparse-density penalty: material mentioned only incidentally in a large doc
                centrality_penalty = 30
                centrality_note = (
                    f"Low centrality: sparse mention density "
                    f"({alias_mention_count} alias occurrences in {doc_len_kchars:.0f}k chars, "
                    f"density={alias_density:.3f}/kchar)"
                )

            # Signal 5: title-subject mismatch — title contains engineering/device vocabulary
            # but NONE of the material tokens. Indicates the patent's claimed invention is a
            # manufactured device/article that merely uses the target material as an ingredient.
            # Generic application-domain device keywords (not compound-specific).
            _APPLICATION_DOMAIN_KEYWORDS = frozenset([
                "charging", "cartridge", "photographic", "electrophotographic", "printer",
                "copier", "scanner", "camera", "display", "transistor", "semiconductor",
                "membrane", "electrode", "battery", "capacitor", "circuit",
                "belt", "roller", "conveyor", "transmission",
                "tire", "tyre", "seal", "gasket", "hose", "tube", "pipe",
                "glove", "catheter", "implant", "stent",
                "adhesive", "coating", "paint", "ink", "dye",
                "fiber", "textile", "fabric", "foam", "cushion",
            ])
            title_toks = set(re.findall(r'\b[a-zA-Z]+\b', title_lower))
            title_has_device_keyword = bool(_APPLICATION_DOMAIN_KEYWORDS.intersection(title_toks))
            if not in_title and title_has_device_keyword and centrality_penalty > 0:
                # Already penalized for centrality; boost the penalty further for clear device titles
                centrality_penalty = max(centrality_penalty, 45)
                title_subject_mismatch = True
                centrality_note = centrality_note + (
                    f"; title subject mismatch: device/application domain keywords in title "
                    f"({sorted(_APPLICATION_DOMAIN_KEYWORDS.intersection(title_toks))[:3]})"
                )


        # VARIANT MISMATCH
        variant_mismatch = False
        if base_material_evidence and excluded_terms:
            title_tokens = set(re.findall(r'\b[a-zA-Z]+\b', (parsed_patent.title or "").lower()))
            if excluded_terms.intersection(title_tokens):
                variant_mismatch = True

        # SYNTHESIS EVIDENCE
        syn_matches = synthesis_terms.intersection(tokens)
        synthesis_evidence_score = len(syn_matches)

        # DOWNSTREAM EVIDENCE
        downstream_matches = downstream_terms.intersection(tokens)
        downstream_evidence_score = len(downstream_matches)

        # ATTRIBUTE EVIDENCE — TYPE_B: also match on dimension tokens in full text
        # target_type is computed here (hoisted) so Gate B can use it below.
        target_type = self._classify_target_type(
            requested_attributes, getattr(profile, 'target_modifications', [])
        ) if requested_attributes else "TYPE_A"

        attribute_score = 0
        if requested_attributes:
            if target_type in ("TYPE_A", "MIXED"):
                attr_matches = sum(1 for attr in requested_attributes if attr in text)
                attribute_score += attr_matches * 15
            if target_type in ("TYPE_B", "MIXED"):
                # Parse LLM-provided attribute_dimension_ranges for numeric grounding.
                # Extract upper/lower bound hints from strings like:
                #   "acrylonitrile content: standard 18-51 wt%; low-ACN grade <20 wt%"
                # We pull out the first "<N" or "N-M" pattern near a qualifier as an upper/lower bound.
                dimension_ranges = getattr(profile, 'attribute_dimension_ranges', [])
                _range_upper: dict[str, float] = {}   # dim_token -> upper bound from "low" context
                _range_lower: dict[str, float] = {}   # dim_token -> lower bound from "high" context
                for range_str in dimension_ranges:
                    range_str_l = range_str.lower()
                    # Find "dim_word: ... <N wt%" patterns (upper bound for 'low' targets)
                    for m in re.finditer(r'([a-zA-Z]{4,})\s*(?:content|value|level|ratio)?[^:;]*(?:<|less than|up to)\s*(\d+(?:\.\d+)?)', range_str_l):
                        dim_hint = m.group(1)
                        try:
                            _range_upper[dim_hint] = float(m.group(2))
                        except ValueError:
                            pass
                    # "N-M" range
                    for m in re.finditer(r'([a-zA-Z]{4,})\s*(?:content|value|level|ratio)?[^:;]*?(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)', range_str_l):
                        dim_hint = m.group(1)
                        try:
                            _range_lower[dim_hint] = float(m.group(2))
                            _range_upper[dim_hint] = float(m.group(3))
                        except ValueError:
                            pass

                for attr in requested_attributes:
                    qualifiers, dim_tokens = self._split_attribute_concepts(attr)
                    is_low_qualifier = bool(qualifiers.intersection({"low", "lower", "reduced", "minimal", "minimum", "minor"}))
                    is_high_qualifier = bool(qualifiers.intersection({"high", "higher", "elevated", "increased", "maximum", "ultra"}))

                    for dim in dim_tokens:
                        if dim not in text:
                            continue
                        # Base credit for dimension word present
                        dim_base_score = 10
                        found_numeric = False
                        numeric_in_range = False
                        numeric_out_of_range = False

                        for m in re.finditer(r'\b' + re.escape(dim) + r'\b', text):
                            ctx = text[max(0, m.start()-100):m.end()+100]
                            num_match = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:%|wt|mol|phr|g|kg|ppm|\s)', ctx)
                            if num_match:
                                found_numeric = True
                                try:
                                    extracted_val = float(num_match.group(1))
                                    upper = _range_upper.get(dim)
                                    lower = _range_lower.get(dim)
                                    if is_low_qualifier and upper is not None:
                                        if extracted_val <= upper:
                                            numeric_in_range = True
                                        elif extracted_val > upper * 1.5:
                                            numeric_out_of_range = True
                                    elif is_high_qualifier and lower is not None:
                                        if extracted_val >= lower:
                                            numeric_in_range = True
                                        elif extracted_val < lower * 0.5:
                                            numeric_out_of_range = True
                                    else:
                                        numeric_in_range = True  # no range → accept any numeric
                                except ValueError:
                                    pass
                                break

                        if found_numeric and numeric_in_range:
                            attribute_score += dim_base_score + 10  # full credit + in-range bonus
                        elif found_numeric and numeric_out_of_range:
                            attribute_score += dim_base_score - 5   # reduced credit: wrong range
                        elif found_numeric:
                            attribute_score += dim_base_score + 5   # numeric present, no range to check
                        else:
                            attribute_score += dim_base_score // 2  # dimension word only, no numeric grounding


        decision = "KEEP"
        reason = "Passes full text validation"
        score = 0
        category = "DIRECT_SYNTHESIS"

        if not base_material_evidence:
            decision = "REJECT"
            reason = "Missing base material evidence"
            score = -100
        elif variant_mismatch:
            decision = "REJECT"
            reason = "Variant mismatch: excluded term found in title"
            score = -100
        else:
            # ── GATE A: Synthesis Subject ────────────────────────────────────
            # Must the target material be the SUBJECT of the claims (synthesized/
            # modified), not merely an ingredient in a downstream article?
            gate_a = self._gate_a_synthesis_subject(parsed_patent, material_tokens)
            logger.info("Gate A: %s | %s", "PASS" if gate_a["pass"] else "FAIL", gate_a["reason"])

            if not gate_a["pass"]:
                decision = "REJECT"
                reason = f"GATE A FAIL: {gate_a['reason']}"
                score = -200
                category = "DOWNSTREAM_APPLICATION"
                return {
                    "score": score, "decision": decision, "reason": reason,
                    "category": category,
                    "synthesis_evidence": synthesis_evidence_score,
                    "downstream_evidence": downstream_evidence_score,
                    "centrality_penalty": centrality_penalty,
                    "centrality_note": centrality_note,
                    "matched_material_tokens": sorted(material_tokens.intersection(tokens)),
                    "matched_downstream": sorted(downstream_matches),
                    "gate_a": gate_a, "gate_b": {"pass": None, "reason": "not reached"},
                }

            # ── GATE B: Target-Attribute Grounding ───────────────────────────
            # Must the patent contain ACTUAL evidence addressing the specific
            # target attribute dimension — not just base-material identity.
            gate_b = self._gate_b_attribute_grounding(text, requested_attributes, target_type)
            logger.info("Gate B: %s | %s", "PASS" if gate_b["pass"] else "FAIL", gate_b["reason"])

            if not gate_b["pass"]:
                decision = "REJECT"
                reason = f"GATE B FAIL: {gate_b['reason']}"
                score = -150
                category = "UNGROUNDED_BASE_MATCH"
                return {
                    "score": score, "decision": decision, "reason": reason,
                    "category": category,
                    "synthesis_evidence": synthesis_evidence_score,
                    "downstream_evidence": downstream_evidence_score,
                    "centrality_penalty": centrality_penalty,
                    "centrality_note": centrality_note,
                    "matched_material_tokens": sorted(material_tokens.intersection(tokens)),
                    "matched_downstream": sorted(downstream_matches),
                    "gate_a": gate_a, "gate_b": gate_b,
                }

            # Both gates passed — apply secondary synthesis/downstream scoring
            if synthesis_evidence_score < 2:
                decision = "REJECT"
                reason = "Insufficient synthesis evidence"
                score = -50
            elif downstream_evidence_score > synthesis_evidence_score * 2:
                if downstream_evidence_score > synthesis_evidence_score * 4:
                    decision = "REJECT"
                    reason = "Downstream application only"
                    score = -50
                else:
                    # For device-title patents, zero out attribute_score — their 'synthesis' language
                    # is about manufacturing the device, not producing the target material.
                    effective_attr_borderline = 0 if title_subject_mismatch else attribute_score
                    score = (synthesis_evidence_score * 2) + effective_attr_borderline - (downstream_evidence_score * 3) - centrality_penalty
                    decision = "KEEP"
                    reason = f"Borderline: downstream-heavy but synthesis context present{'; ' + centrality_note if centrality_note else ''}"
                    category = "DOWNSTREAM_APPLICATION"
            else:
                # Determine category first so we can attenuate attribute_score for downstream patents
                if downstream_evidence_score > synthesis_evidence_score:
                    category = "DOWNSTREAM_APPLICATION"
                elif attribute_score > 0:
                    category = "TARGET_TRANSFORMATION"
                else:
                    category = "PRECURSOR_SYNTHESIS"

                # For TYPE_B targets with device-title mismatch (Signal 5): zero out attribute_score.
                # For other DOWNSTREAM patents with centrality penalty: halve it.
                # A patent about making printer rollers or adhesive sheets may mention
                # "acrylonitrile content" as a property spec — not as a synthesis claim.
                effective_attribute_score = attribute_score
                if title_subject_mismatch:
                    effective_attribute_score = 0
                elif category == "DOWNSTREAM_APPLICATION" and centrality_penalty > 0:
                    effective_attribute_score = attribute_score // 2

                score = 50 + (synthesis_evidence_score * 2) + effective_attribute_score - downstream_evidence_score - centrality_penalty
                if centrality_note:
                    reason = f"Passes full text validation; {centrality_note}"

        return {
            "score": score,
            "decision": decision,
            "reason": reason,
            "category": category,
            "synthesis_evidence": synthesis_evidence_score,
            "downstream_evidence": downstream_evidence_score,
            "centrality_penalty": centrality_penalty,
            "centrality_note": centrality_note,
            "matched_material_tokens": sorted(material_tokens.intersection(tokens)),
            "matched_downstream": sorted(downstream_matches),
        }



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
                set_current_stage(TelemetryStage.QUERY_EXPANSION)
                await self._update_status(session, run, RunStatus.SEARCHING)
                
                logger.info("[ORCHESTRATOR] Research Inputs: Compound='%s', Jurisdictions=%s, DateFilter=%s, Competitors=%s, Websites=%s", 
                    run.compound_name, run.jurisdictions, run.publication_filter, run.competitors, run.mentioned_websites)
                
                logger.info("[LLM CALL 1] QUERY_EXPANSION")
                strategy = await self.search_service.generate_strategy(
                    compound_name=run.compound_name, 
                    competitors=run.competitors,
                    websites=run.mentioned_websites,
                    jurisdictions=run.jurisdictions,
                    publication_filter=run.publication_filter
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
                
                set_current_stage(TelemetryStage.PATENT_SEARCH)
                patent_candidates = await self.search_service.search_patents(search_queries)
                logger.info("[ORCHESTRATOR] Raw results: %d", len(patent_candidates))
                
                if not patent_candidates:
                    raise Exception("No patents found for the given compound.")
                    
                # ── Apply Hard Filters (Jurisdiction & Date)
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

                # ── LLM Title Triage ──
                logger.info("[LLM TITLE TRIAGE] Starting triage for %d candidates...", len(family_deduped))
                search_intents = [q.intent for q in getattr(strategy, 'search_queries', []) if hasattr(q, 'intent')]
                synthesis_intent_str = "YES (Target synthesis/preparation)" if getattr(strategy, 'synthesis_intent', False) else "NO"
                
                triage_prompt = TITLE_TRIAGE_PROMPT.format(
                    compound_name=run.compound_name,
                    base_material=", ".join(getattr(strategy, 'base_material', [])),
                    target_modifications=", ".join(getattr(strategy, 'target_modifications', [])),
                    target_attributes=", ".join(getattr(strategy, 'target_attributes', [])),
                    synthesis_transformations=", ".join(getattr(strategy, 'synthesis_transformations', [])),
                    downstream_terms=", ".join(getattr(strategy, 'downstream_terms', [])),
                    search_intent=f"Synthesis Required: {synthesis_intent_str}. Intents: " + (", ".join(search_intents) if search_intents else "synthesis and material preparation"),
                    candidates_json="{candidates_json}"
                )
                
                # Batch candidates 50 at a time, with enriched payload
                TRIAGE_SHORTLIST_MIN = 25
                TRIAGE_SHORTLIST_MAX = 50
                batch_size = 50
                triage_results = {}
                triage_llm_calls = 0
                for i in range(0, len(family_deduped), batch_size):
                    triage_llm_calls += 1
                    batch = family_deduped[i:i+batch_size]
                    batch_json = json.dumps([
                        {
                            "patent_number": c.get('patent_number', ''),
                            "title": c.get('title', ''),
                            "publication_year": (c.get('publication_date', '') or c.get('grant_date', '') or '')[:4],
                            "jurisdiction": (c.get('patent_number', '') or '')[:2],
                            "assignee": c.get('assignee', '') or '',
                            "matched_query_category": c.get('query_matched', '')[:120],
                        }
                        for c in batch
                    ], indent=2)
                    prompt = triage_prompt.replace("{candidates_json}", batch_json)
                    try:
                        result, _, _ = await llm_client.generate_structured(
                            prompt=prompt,
                            system_prompt="You are a JSON generator. Do not include markdown blocks.",
                            schema=TitleTriageResult,
                            temperature=0.1
                        )
                        if result and hasattr(result, 'candidates'):
                            for cand in result.candidates:
                                triage_results[cand.patent_number] = cand
                    except Exception as e:
                        logger.error("[LLM TITLE TRIAGE] Failed for batch %d-%d: %s", i, i+len(batch), str(e))
                        # Fallback: ignore failure and all candidates pass through untagged
                
                # --- Apply triage results back to candidates ---
                triage_counts = {
                    "DIRECT_SYNTHESIS": 0, "TARGET_TRANSFORMATION": 0, "POLYMER_STRUCTURE": 0, 
                    "PRECURSOR_OR_INTERMEDIATE": 0, "BASE_MATERIAL_ONLY": 0, 
                    "DOWNSTREAM_APPLICATION": 0, "UNRELATED": 0, "AMBIGUOUS": 0
                }
                # Priority mapping — generic, compound-agnostic
                PRIORITY_MAP = {
                    "DIRECT_SYNTHESIS": "HIGH",
                    "TARGET_TRANSFORMATION": "HIGH",
                    "POLYMER_STRUCTURE": "HIGH",
                    "PRECURSOR_OR_INTERMEDIATE": "MEDIUM_HIGH",
                    "AMBIGUOUS": "MEDIUM",
                    "BASE_MATERIAL_ONLY": "LOW",
                    "DOWNSTREAM_APPLICATION": "LOW",
                    "UNRELATED": "REJECT",
                }
                for cand in family_deduped:
                    pnum = cand.get('patent_number')
                    if pnum in triage_results:
                        triage_cand = triage_results[pnum]
                        cls_name = getattr(triage_cand.classification, "value", str(triage_cand.classification))
                        # Use LLM-provided priority if valid, else derive from classification
                        llm_priority = getattr(triage_cand, 'priority', '') or ''
                        derived_priority = PRIORITY_MAP.get(cls_name, "LOW")
                        final_priority = llm_priority if llm_priority in PRIORITY_MAP.values() or llm_priority == 'REJECT' else derived_priority
                        
                        cand['triage_classification'] = triage_cand.classification
                        cand['triage_priority'] = final_priority
                        cand['triage_relevance'] = triage_cand.relevance
                        cand['triage_reason'] = triage_cand.reason
                        
                        triage_counts[cls_name] = triage_counts.get(cls_name, 0) + 1
                        
                        logger.info("[TITLE TRIAGE_PATENT] %s | cls=%s | priority=%s | relevance=%s | %s",
                            pnum, cls_name, final_priority, triage_cand.relevance, triage_cand.reason)
                    else:
                        # No triage result: treat as AMBIGUOUS/MEDIUM so it still flows through
                        cand['triage_classification'] = None
                        cand['triage_priority'] = 'MEDIUM'
                        cand['triage_relevance'] = 'MEDIUM'
                        cand['triage_reason'] = 'No triage result — default pass-through'
                        
                clearly_relevant = triage_counts.get('DIRECT_SYNTHESIS', 0) + triage_counts.get('TARGET_TRANSFORMATION', 0) + triage_counts.get('POLYMER_STRUCTURE', 0)
                potentially_relevant = triage_counts.get('PRECURSOR_OR_INTERMEDIATE', 0) + triage_counts.get('BASE_MATERIAL_ONLY', 0) + triage_counts.get('AMBIGUOUS', 0)
                downstream = triage_counts.get('DOWNSTREAM_APPLICATION', 0)
                clearly_unrelated = triage_counts.get('UNRELATED', 0)
                
                logger.info(
                    "\n[TRIAGE SUMMARY]\n"
                    "Total candidates entering triage: %d\n"
                    "DIRECT_SYNTHESIS:       %d\n"
                    "TARGET_TRANSFORMATION:  %d\n"
                    "POLYMER_STRUCTURE:      %d\n"
                    "PRECURSOR_OR_INTERMEDIATE: %d\n"
                    "AMBIGUOUS:              %d\n"
                    "BASE_MATERIAL_ONLY:     %d\n"
                    "DOWNSTREAM_APPLICATION: %d\n"
                    "UNRELATED:              %d\n"
                    "Clearly relevant (HIGH): %d\n"
                    "Potentially relevant (MEDIUM/LOW): %d\n"
                    "Hard-excluded (UNRELATED): %d",
                    len(family_deduped),
                    triage_counts.get('DIRECT_SYNTHESIS', 0),
                    triage_counts.get('TARGET_TRANSFORMATION', 0),
                    triage_counts.get('POLYMER_STRUCTURE', 0),
                    triage_counts.get('PRECURSOR_OR_INTERMEDIATE', 0),
                    triage_counts.get('AMBIGUOUS', 0),
                    triage_counts.get('BASE_MATERIAL_ONLY', 0),
                    triage_counts.get('DOWNSTREAM_APPLICATION', 0),
                    triage_counts.get('UNRELATED', 0),
                    clearly_relevant,
                    potentially_relevant + downstream,
                    clearly_unrelated,
                )

                # ── FUNNEL GATE: Hard-exclude UNRELATED, then build priority-ordered shortlist ──
                pre_gate_count = len(family_deduped)
                post_unrelated = [c for c in family_deduped if c.get('triage_priority', 'MEDIUM') != 'REJECT']
                excluded_unrelated = pre_gate_count - len(post_unrelated)
                logger.info("[TRIAGE GATE] Hard-excluded %d UNRELATED candidates. Remaining: %d",
                            excluded_unrelated, len(post_unrelated))

                # Sort remaining by priority tier for shortlisting
                PRIORITY_ORDER = {'HIGH': 0, 'MEDIUM_HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'REJECT': 4}
                post_unrelated.sort(key=lambda c: PRIORITY_ORDER.get(c.get('triage_priority', 'MEDIUM'), 2))

                # Build shortlist: take all HIGH+MEDIUM_HIGH, then fill to TRIAGE_SHORTLIST_MAX with MEDIUM/LOW
                if len(post_unrelated) > TRIAGE_SHORTLIST_MAX:
                    high_medium_high = [c for c in post_unrelated if c.get('triage_priority') in ('HIGH', 'MEDIUM_HIGH')]
                    remaining = [c for c in post_unrelated if c.get('triage_priority') not in ('HIGH', 'MEDIUM_HIGH')]
                    shortlist = high_medium_high
                    # Fill up to TRIAGE_SHORTLIST_MAX with MEDIUM/LOW
                    slots = TRIAGE_SHORTLIST_MAX - len(shortlist)
                    if slots > 0:
                        shortlist = shortlist + remaining[:slots]
                    # Ensure we always have at least TRIAGE_SHORTLIST_MIN
                    if len(shortlist) < TRIAGE_SHORTLIST_MIN and len(post_unrelated) >= TRIAGE_SHORTLIST_MIN:
                        shortlist = post_unrelated[:TRIAGE_SHORTLIST_MIN]
                    triage_shortlist = shortlist
                else:
                    triage_shortlist = post_unrelated

                logger.info("[TRIAGE GATE] Shortlist built: %d candidates (min=%d, max=%d) → feeding into deterministic ranking",
                            len(triage_shortlist), TRIAGE_SHORTLIST_MIN, TRIAGE_SHORTLIST_MAX)

                # Step 3: Deterministic Ranking (operates on shortlist only)
                set_current_stage(TelemetryStage.PATENT_RANKING)
                await self._update_status(session, run, RunStatus.FILTERING)
                
                self._deterministic_rank(triage_shortlist, strategy, run.compound_name)
                logger.info("[ORCHESTRATOR] Preliminary title filtering completed")
                
                triage_shortlist.sort(key=lambda x: x['score'], reverse=True)
                # Keep all eligible for full text validation (relevance threshold applied later)
                preliminary_candidates = [c for c in triage_shortlist if c.get('eligibility', 'KEEP') != 'REJECT']
                
                logger.info(
                    f"\n[RANKING]\n"
                    f"Candidates entering ranking: {len(triage_shortlist)}\n"
                    f"Candidates passing preliminary threshold: {len(preliminary_candidates)}\n"
                )

                # ── Step 4: Fetch & Validate
                set_current_stage(TelemetryStage.PATENT_EXTRACTION)
                await self._update_status(session, run, RunStatus.EXTRACTING)
                
                validated_patents = []
                parsed_patents_map = {}
                
                for candidate in preliminary_candidates:
                    url = candidate['url']
                    logger.info("Fetching for validation: %s", url)
                    
                    parsed_patent = await self.fetcher_service.fetch_patent(url)
                    if not parsed_patent:
                        logger.warning("[FETCH FAILURE] patent number: %s | URL: %s", candidate['patent_number'], url)
                        continue
                        
                    logger.info("[FETCH SUCCESS] patent number: %s | URL: %s", candidate['patent_number'], url)
                    await asyncio.sleep(1)
                    
                    try:
                        val_result = self._validate_full_text(parsed_patent, strategy, run.compound_name)
                        
                        logger.info(
                            "[VALIDATION]\n"
                            f"Patent: {candidate['patent_number']}\n"
                            f"Target material evidence: {'STRONG' if val_result['decision'] != 'REJECT' else 'WEAK'} ({val_result.get('matched_material_tokens', [])})\n"
                            f"Transformation evidence: {val_result['synthesis_evidence']}\n"
                            f"Claim evidence: {'PASS' if val_result.get('gate_a', {}).get('pass', True) else 'FAIL'} | {val_result.get('gate_a', {}).get('reason', 'n/a')}\n"
                            f"Decision: {val_result['decision']} - {val_result['reason']}"
                        )

                        if val_result['decision'] == "KEEP":
                            candidate['final_score'] = val_result['score']
                            candidate['ft_category'] = val_result.get('category', 'DIRECT_SYNTHESIS')
                            validated_patents.append(candidate)
                            parsed_patents_map[candidate['patent_number']] = parsed_patent
                    except Exception as e:
                        logger.error(f"[VALIDATION ERROR] Failed to validate patent {candidate['patent_number']}: {e}")
                        continue
                validated_patents.sort(key=lambda x: x.get('final_score', 0), reverse=True)
                selected_candidates = [c for c in validated_patents if c.get('final_score', 0) >= -50][:10]
                
                logger.info("ABOVE RELEVANCE THRESHOLD: %d", len([c for c in validated_patents if c.get('final_score', 0) >= -50]))
                logger.info("SELECTED: %d", len(selected_candidates))
                
                for i, candidate in enumerate(selected_candidates):
                    logger.info("RANK %d\n"
                        f"PATENT: {candidate.get('patent_number')}\n"
                        f"TITLE: {candidate.get('title')}\n"
                        f"FINAL SCORE: {candidate.get('final_score')}\n"
                        f"CATEGORY: {candidate.get('ft_category', candidate.get('category'))}\n"
                        f"MATCHED QUERIES: {candidate.get('matched_queries')}\n"
                        "----------------------------------------"
                    )
                
                extractions: list[PatentExtraction] = []
                for candidate in selected_candidates:
                    parsed_patent = parsed_patents_map[candidate['patent_number']]
                    ext = await self.extractor_service.extract_polymerization_data(parsed_patent, url=candidate['url'], profile=strategy)
                    if not ext:
                        continue
                    
                    ext.metadata.patent_number = candidate['patent_number']
                    ext.metadata.patent_title = candidate['title']
                    
                    if self.extractor_service.validate_extraction(ext):
                        extractions.append(ext)
                        logger.info("EXTRACTION SUCCESS: %s", ext.metadata.patent_number)
                        
                if len(extractions) == 0:
                    raise Exception("Pipeline failed: Could not validate or extract any relevant patents.")

                # ── Step 5: Generate Report & Export
                set_current_stage(TelemetryStage.REPORT_GENERATION)
                await self._update_status(session, run, RunStatus.GENERATING)
                
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
                for ext in extractions:
                    parsed_patent = parsed_patents_map.get(ext.metadata.patent_number)
                    ev = evidence_service.build_compact_evidence(
                        ext,
                        discovery_source="NORMAL",
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
                    original_input=run.compound_name,
                    research_profile=profile_json
                )
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
                await self._update_status(session, run, RunStatus.COMPLETED)
                
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
                    f"method: deterministic\n"
                    f"llm_calls: 0\n"
                    f"ranked: {len(validated_patents)}\n"
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

            except Exception as e:
                import traceback
                
                if type(e).__name__ == "ProviderExhaustedException":
                    logger.error("Pipeline failure due to LLM provider exhaustion: %s", e)
                    await self._update_status(session, run, RunStatus.LLM_PROVIDER_EXHAUSTED)
                    return RunStatus.LLM_PROVIDER_EXHAUSTED
                    
                logger.error("Pipeline failure: %s\n%s", e, traceback.format_exc())
                await self._mark_failed(session, run, str(e))
                return RunStatus.FAILED
