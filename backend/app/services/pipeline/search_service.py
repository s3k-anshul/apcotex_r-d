"""
app/services/pipeline/search_service.py

Uses Gemini to generate a search strategy, then uses Serper API to find patent links.
LLM interprets free-form compound input; application code validates, recovers, and
never sends zero queries to Serper.
"""
import logging
import re
import time
from typing import List, Dict, Any, Tuple

import httpx

from app.core.config import settings
from app.services.pipeline.schemas import (
    LLMCompoundSearchProfile,
    GeneratedQuery,
    TargetNumericConstraint,
)
from app.services.llm import llm_client
from app.services.prompts.patent_prompts import build_query_expansion_prompt

logger = logging.getLogger(__name__)

TARGET_QUERY_COUNT = 15


class SerperCreditsExhaustedError(Exception):
    """Raised when Serper API returns 'Not enough credits' error."""
    pass


class SearchPreparationError(Exception):
    """
    Raised when search queries cannot be prepared.
    Distinguishes SEARCH_PREPARATION_FAILURE from SEARCH_RETURNED_ZERO_RESULTS.
    Serper must never be called when this is raised for empty query sets.
    """
    pass


# ---------------------------------------------------------------------------
# Deterministic free-form input recovery (compound-agnostic)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "for", "from", "with", "containing",
    "in", "on", "at", "to", "by", "via", "into", "as", "is", "are", "be",
    "based", "using", "through", "than", "least", "less", "greater", "more",
    "approximately", "about", "around", "between", "above", "below", "over",
    "under", "upto", "up", "down", "content", "degree", "level", "amount",
    "wt", "mol", "phr", "percent", "percentage", "mass", "volume", "vol",
})

_QUALITATIVE = frozenset({
    "low", "high", "ultra", "medium", "soft", "hard", "very", "slightly",
    "partially", "fully", "highly", "lightly",
})

_UNIT_RE = (
    r"(?:wt\s*%|wt%|mol\s*%|mol%|mass\s*%|vol\s*%|phr|%|percent)"
)

_MODIFIER_SUFFIX_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9-]{2,}(?:ated|ized|ysed|ylated|inated|enated|lated))\b",
    re.IGNORECASE,
)


def _normalize_dash(text: str) -> str:
    return (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("∼", "~")
    )


def _parse_float(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except (TypeError, ValueError):
        return None


def extract_numeric_constraints(text: str) -> list[TargetNumericConstraint]:
    """
    Dynamically extract numeric / range / comparison constraints from free-form text.
    Attribute names come from adjacent non-unit tokens — no compound catalog.
    """
    raw = _normalize_dash(text or "")
    if not raw.strip():
        return []

    constraints: list[TargetNumericConstraint] = []
    occupied: list[Tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= a or start >= b) for a, b in occupied)

    def _attribute_near(span_start: int, span_end: int) -> str:
        before = raw[:span_start]
        after = raw[span_end:]
        before_tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", before)
        after_tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", after)

        def _usable(tok: str) -> bool:
            low = tok.lower()
            if low in _STOPWORDS or re.fullmatch(r"wt|mol|phr|vol|mass", low):
                return False
            return True

        # Prefer post-number nouns ("18-22 wt% acrylonitrile", "7% carboxylated")
        after_candidates: list[str] = []
        for tok in after_tokens[:4]:
            if not _usable(tok):
                continue
            # Stop before a trailing acronym-like identity token (e.g. "... acrylonitrile NBR")
            if (
                after_candidates
                and 2 <= len(tok) <= 6
                and tok.isalpha()
                and tok.isupper()
            ):
                break
            after_candidates.append(tok)
            if len(after_candidates) >= 2:
                break
        if after_candidates:
            if (
                after_candidates[0].lower() in _QUALITATIVE
                and len(after_candidates) > 1
            ):
                return after_candidates[1].lower().strip()
            # Prefer the first scientific noun; keep two tokens only for multi-word attrs
            if len(after_candidates) == 1:
                return after_candidates[0].lower().strip()
            # "carboxyl content"-style: keep both if second is generic noun
            if after_candidates[1].lower() in {"content", "degree", "level", "ratio"}:
                return " ".join(t.lower() for t in after_candidates[:2]).strip()
            return after_candidates[0].lower().strip()

        # Fall back to pre-number nouns ("acrylonitrile content 18-22 wt%")
        before_candidates: list[str] = []
        for tok in reversed(before_tokens[-4:]):
            if not _usable(tok) or tok.lower() in _QUALITATIVE:
                continue
            before_candidates.insert(0, tok)
            if len(before_candidates) >= 2:
                break
        return " ".join(t.lower() for t in before_candidates).strip()

    def _unit_from(match_text: str) -> str:
        m = re.search(_UNIT_RE, match_text, re.IGNORECASE)
        if not m:
            return ""
        u = re.sub(r"\s+", "", m.group(0).lower())
        if u == "percent":
            return "%"
        return u

    # Comparisons: less than / greater than / at least / below / above / approximately
    comparison_specs = [
        (r"(?:less\s+than|below|under|<)\s*(\d+(?:\.\d+)?)\s*(" + _UNIT_RE + r")?", "<"),
        (r"(?:greater\s+than|above|over|>)\s*(\d+(?:\.\d+)?)\s*(" + _UNIT_RE + r")?", ">"),
        (r"(?:at\s+least|no\s+less\s+than|≥|>=)\s*(\d+(?:\.\d+)?)\s*(" + _UNIT_RE + r")?", ">="),
        (r"(?:at\s+most|no\s+more\s+than|≤|<=)\s*(\d+(?:\.\d+)?)\s*(" + _UNIT_RE + r")?", "<="),
        (r"(?:approximately|about|around|~|≈)\s*(\d+(?:\.\d+)?)\s*(" + _UNIT_RE + r")?", "~"),
    ]
    for pattern, op in comparison_specs:
        for m in re.finditer(pattern, raw, re.IGNORECASE):
            if _overlaps(m.start(), m.end()):
                continue
            value = _parse_float(m.group(1))
            if value is None:
                continue
            unit_grp = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            unit = _unit_from(unit_grp or m.group(0))
            attr = _attribute_near(m.start(), m.end())
            constraints.append(
                TargetNumericConstraint(
                    attribute=attr,
                    value=value,
                    unit=unit,
                    operator=op,
                    raw_span=m.group(0).strip(),
                )
            )
            occupied.append((m.start(), m.end()))

    # Ranges: 18-22 wt%, 18 to 22 %, 10–15 mol%
    range_pat = re.compile(
        r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(" + _UNIT_RE + r")?",
        re.IGNORECASE,
    )
    for m in range_pat.finditer(raw):
        if _overlaps(m.start(), m.end()):
            continue
        lo = _parse_float(m.group(1))
        hi = _parse_float(m.group(2))
        if lo is None or hi is None:
            continue
        unit = _unit_from(m.group(3) or m.group(0))
        attr = _attribute_near(m.start(), m.end())
        constraints.append(
            TargetNumericConstraint(
                attribute=attr,
                lower_bound=min(lo, hi),
                upper_bound=max(lo, hi),
                unit=unit,
                operator="range",
                raw_span=m.group(0).strip(),
            )
        )
        occupied.append((m.start(), m.end()))

    # Single values with unit: 7%, 2 wt%, 0.5 phr
    single_pat = re.compile(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(" + _UNIT_RE + r")",
        re.IGNORECASE,
    )
    for m in single_pat.finditer(raw):
        if _overlaps(m.start(), m.end()):
            continue
        value = _parse_float(m.group(1))
        if value is None:
            continue
        unit = _unit_from(m.group(2))
        attr = _attribute_near(m.start(), m.end())
        constraints.append(
            TargetNumericConstraint(
                attribute=attr,
                value=value,
                unit=unit,
                operator="=",
                raw_span=m.group(0).strip(),
            )
        )
        occupied.append((m.start(), m.end()))

    return constraints


def _strip_numeric_spans(text: str) -> str:
    """Remove numeric/comparison spans so remaining tokens are identity/modifier candidates."""
    raw = _normalize_dash(text or "")
    patterns = [
        r"(?:less\s+than|greater\s+than|at\s+least|at\s+most|below|above|under|over|"
        r"approximately|about|around|no\s+less\s+than|no\s+more\s+than)"
        r"\s*\d+(?:\.\d+)?\s*(?:" + _UNIT_RE + r")?",
        r"\d+(?:\.\d+)?\s*(?:-|to)\s*\d+(?:\.\d+)?\s*(?:" + _UNIT_RE + r")?",
        r"\d+(?:\.\d+)?\s*(?:" + _UNIT_RE + r")",
        r"[<>≤≥~≈]=?\s*\d+(?:\.\d+)?\s*(?:" + _UNIT_RE + r")?",
    ]
    cleaned = raw
    for pat in patterns:
        cleaned = re.sub(pat, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^\w\s-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_modifications_and_attributes(text: str) -> Tuple[list[str], list[str], list[str]]:
    """
    Return (modifications, qualitative_attributes, transformation-like terms)
    using generic morphology / qualifier detection — not a compound catalog.
    """
    cleaned = _strip_numeric_spans(text)
    mods: list[str] = []
    attrs: list[str] = []
    transforms: list[str] = []

    for m in _MODIFIER_SUFFIX_RE.finditer(cleaned):
        term = m.group(1)
        low = term.lower()
        if low not in {x.lower() for x in mods}:
            mods.append(low)
        # e.g. carboxylated → carboxyl; hydrogenated → hydrogenation
        stem = re.sub(r"(ated|ized|ysed)$", "", low, flags=re.IGNORECASE)
        if stem and len(stem) >= 4:
            if "hydrogen" in stem:
                transforms.append("hydrogenation")
            elif stem.endswith("yl"):
                transforms.append(f"{stem}ation")
            else:
                transforms.append(f"{stem}ation" if not stem.endswith("ation") else stem)

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", cleaned)
    for i, tok in enumerate(tokens):
        low = tok.lower()
        if low in _QUALITATIVE and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            if nxt.lower() not in _STOPWORDS:
                phrase = f"{low} {nxt.lower()}"
                if phrase not in attrs:
                    attrs.append(phrase)
        elif low in _QUALITATIVE:
            if low not in attrs:
                attrs.append(low)

    # Deduplicate transforms
    seen_t: set[str] = set()
    uniq_t: list[str] = []
    for t in transforms:
        if t.lower() not in seen_t:
            seen_t.add(t.lower())
            uniq_t.append(t)

    return mods, attrs, uniq_t


def extract_base_material_candidates(text: str) -> list[str]:
    """
    Extract base identity tokens/phrases from free-form input after removing
    numeric constraints and known qualitative/modifier tokens.
    """
    cleaned = _strip_numeric_spans(text)
    # Drop morphological modifiers from the identity string
    without_mods = _MODIFIER_SUFFIX_RE.sub(" ", cleaned)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", without_mods)

    # Tokens that follow a qualitative adjective are attribute nouns, not identity
    attribute_nouns: set[str] = set()
    for i, tok in enumerate(tokens):
        if tok.lower() in _QUALITATIVE and i + 1 < len(tokens):
            attribute_nouns.add(tokens[i + 1].lower())

    identity_tokens: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in _STOPWORDS or low in _QUALITATIVE or low in attribute_nouns:
            continue
        if re.fullmatch(r"wt|mol|phr|vol|mass|percent|percentage", low):
            continue
        identity_tokens.append(tok)

    bases: list[str] = []
    # Prefer acronym-like tokens (2–6 letters)
    for tok in identity_tokens:
        if 2 <= len(tok) <= 6 and tok.isalpha() and (tok.isupper() or tok[0].isupper()):
            if tok not in bases:
                bases.append(tok)

    # Remaining non-acronym content words (material name phrases)
    long_words = [
        t
        for t in identity_tokens
        if t.lower() not in {b.lower() for b in bases}
    ]
    if long_words and not bases:
        # No acronym found — use remaining phrase as identity
        phrase = " ".join(long_words).strip()
        if phrase:
            bases.append(phrase)
            for w in long_words:
                if w not in bases and len(w) >= 3:
                    bases.append(w)
    elif long_words and bases:
        # Acronym present: keep multi-word leftovers only if they look like material names
        # (avoid promoting attribute nouns). Prefer short leftover tokens as secondary aliases.
        for w in long_words:
            if len(w) <= 6 and w.isalpha() and w.lower() not in attribute_nouns:
                if w not in bases:
                    bases.append(w)

    # If nothing left, fall back to any non-stop token from original cleaned text
    if not bases:
        for tok in tokens:
            low = tok.lower()
            if low not in _STOPWORDS and low not in _QUALITATIVE and len(tok) >= 2:
                bases.append(tok)
                break

    # Last resort: trimmed original without numerics/modifiers (short phrases only)
    if not bases:
        fallback = without_mods.strip()
        if fallback and 1 <= len(fallback.split()) <= 6:
            bases.append(fallback)

    # Deduplicate case-insensitively, preserve order
    out: list[str] = []
    seen: set[str] = set()
    for b in bases:
        key = b.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(b.strip())
    return out


def input_has_numeric_signal(text: str) -> bool:
    """True if free-form input appears to contain a numeric/range/comparison constraint."""
    return bool(extract_numeric_constraints(text))


def assess_profile_completeness(
    profile: LLMCompoundSearchProfile,
    original_input: str,
) -> Tuple[bool, list[str]]:
    """Return (is_complete, list of missing reasons)."""
    reasons: list[str] = []
    if not (profile.base_material or []):
        reasons.append("base_material empty")
    if not (profile.search_queries or []):
        reasons.append("search_queries empty")
    if input_has_numeric_signal(original_input):
        has_structured = bool(profile.numeric_constraints or [])
        has_range_text = bool(profile.attribute_dimension_ranges or [])
        # Also accept target_attributes that mention a digit
        attrs_have_num = any(
            re.search(r"\d", a or "") for a in (profile.target_attributes or [])
        )
        if not (has_structured or has_range_text or attrs_have_num):
            reasons.append("numeric constraint present in input but missing from profile")
    return (len(reasons) == 0, reasons)


def _merge_unique(existing: list[str], extras: list[str]) -> list[str]:
    out = list(existing or [])
    seen = {x.strip().lower() for x in out if x and x.strip()}
    for item in extras or []:
        if not item or not str(item).strip():
            continue
        key = str(item).strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(str(item).strip())
    return out


def merge_recovered_into_profile(
    profile: LLMCompoundSearchProfile,
    original_input: str,
) -> LLMCompoundSearchProfile:
    """
    Deterministically recover missing identity / modifiers / numerics from the
    original user input and merge with any LLM-provided fields.
    """
    recovered_bases = extract_base_material_candidates(original_input)
    mods, attrs, transforms = extract_modifications_and_attributes(original_input)
    numerics = extract_numeric_constraints(original_input)

    profile.original_input = profile.original_input or original_input
    profile.base_material = _merge_unique(profile.base_material, recovered_bases)
    profile.target_modifications = _merge_unique(profile.target_modifications, mods)
    profile.target_attributes = _merge_unique(profile.target_attributes, attrs)
    profile.synthesis_transformations = _merge_unique(
        profile.synthesis_transformations, transforms
    )

    if numerics:
        if not profile.numeric_constraints:
            profile.numeric_constraints = numerics
        else:
            # Merge by raw_span / signature
            existing_keys = {
                (
                    c.attribute,
                    c.value,
                    c.lower_bound,
                    c.upper_bound,
                    c.unit,
                    c.operator,
                )
                for c in profile.numeric_constraints
            }
            for c in numerics:
                key = (c.attribute, c.value, c.lower_bound, c.upper_bound, c.unit, c.operator)
                if key not in existing_keys:
                    profile.numeric_constraints.append(c)
                    existing_keys.add(key)

        # Mirror into attribute_dimension_ranges as human-readable strings
        for c in profile.numeric_constraints:
            label = _format_constraint_label(c)
            if label and label not in (profile.attribute_dimension_ranges or []):
                profile.attribute_dimension_ranges = _merge_unique(
                    profile.attribute_dimension_ranges, [label]
                )
            if c.attribute:
                profile.target_attributes = _merge_unique(
                    profile.target_attributes, [c.attribute]
                )

    if not profile.relevance_definition and profile.base_material:
        primary = profile.base_material[0]
        profile.relevance_definition = (
            f"PRIMARY_TARGET inventions are about preparation/synthesis/polymerization "
            f"of {primary} (and synonyms). Qualifier disclosure is not required for identity."
        )

    profile.synthesis_intent = True if profile.synthesis_intent is None else profile.synthesis_intent
    if not profile.synthesis_intent:
        # Free-form product research is synthesis-oriented by default for this pipeline
        profile.synthesis_intent = True

    return profile


def _format_constraint_label(c: TargetNumericConstraint) -> str:
    attr = (c.attribute or "attribute").strip()
    unit = (c.unit or "").strip()
    if c.operator == "range" and c.lower_bound is not None and c.upper_bound is not None:
        return f"{attr}: {c.lower_bound}-{c.upper_bound} {unit}".strip()
    if c.operator in ("<", "<=", ">", ">=", "~", "=") and c.value is not None:
        return f"{attr}: {c.operator} {c.value} {unit}".strip()
    if c.value is not None:
        return f"{attr}: {c.value} {unit}".strip()
    return c.raw_span or ""


def _or_group(terms: list[str]) -> str:
    cleaned = []
    seen = set()
    for t in terms:
        if not t or not str(t).strip():
            continue
        s = str(t).strip()
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        if " " in s or "-" in s:
            cleaned.append(f'"{s}"')
        else:
            cleaned.append(s)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return "(" + " OR ".join(cleaned) + ")"


def _numeric_query_phrases(c: TargetNumericConstraint) -> list[str]:
    """Build diverse numeric phrasings without hardcoding compound chemistry."""
    phrases: list[str] = []
    attr = (c.attribute or "").strip()
    unit = (c.unit or "").strip()
    unit_alts = [unit] if unit else []
    if unit in ("wt%", "wt%"):
        unit_alts = ["wt%", "%"]
    elif unit == "%":
        unit_alts = ["%", "wt%"]
    elif unit == "mol%":
        unit_alts = ["mol%", "%"]

    def _with_units(num_str: str) -> list[str]:
        out = []
        for u in unit_alts or [""]:
            out.append(f"{num_str} {u}".strip() if u else num_str)
        return out

    if c.operator == "range" and c.lower_bound is not None and c.upper_bound is not None:
        lo, hi = c.lower_bound, c.upper_bound
        mid = (lo + hi) / 2
        mid_s = str(int(mid)) if mid == int(mid) else str(mid)
        lo_s = str(int(lo)) if lo == int(lo) else str(lo)
        hi_s = str(int(hi)) if hi == int(hi) else str(hi)
        for ns in (f"{lo_s}-{hi_s}", lo_s, mid_s, hi_s):
            phrases.extend(_with_units(ns))
        if attr:
            phrases.append(attr)
            phrases.append(f"{attr} content")
            phrases.append(f"{attr} percentage")
    elif c.value is not None:
        vs = str(int(c.value)) if c.value == int(c.value) else str(c.value)
        phrases.extend(_with_units(vs))
        if attr:
            phrases.append(attr)
            phrases.append(f"{attr} content")
        if c.operator in ("<", "<="):
            phrases.append(f"less than {vs} {unit}".strip())
        elif c.operator in (">", ">="):
            phrases.append(f"at least {vs} {unit}".strip())
    elif attr:
        phrases.append(attr)

    # Dedup
    out: list[str] = []
    seen: set[str] = set()
    for p in phrases:
        key = p.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(p.strip())
    return out


def build_deterministic_queries(
    profile: LLMCompoundSearchProfile,
    polymerization_medium: str = "any",
) -> list[GeneratedQuery]:
    """
    Construct a diverse query set from the normalized profile.
    Does not require exact user wording; does not force qualifiers into every query.
    """
    bases = list(profile.base_material or [])
    if not bases and profile.original_input:
        bases = extract_base_material_candidates(profile.original_input)
    if not bases:
        return []

    base_group = _or_group(bases[:6])
    mods = list(profile.target_modifications or [])
    attrs = list(profile.target_attributes or [])
    transforms = list(profile.synthesis_transformations or [])
    precursors = list(profile.precursor_relationships or [])
    process = list(profile.relevant_process_concepts or [])
    numerics = list(profile.numeric_constraints or [])

    medium = (polymerization_medium or "any").strip().lower()
    medium_terms: list[str] = []
    if medium in ("aqueous", "emulsion"):
        medium_terms = ["emulsion polymerization", "aqueous emulsion", "latex"]
    elif medium == "solvent":
        medium_terms = ["solution polymerization", "anionic polymerization"]

    specs: list[Tuple[str, list[str], list[str], str, str]] = []

    def add(expr: str, required: list[str], alts: list[str], intent: str, scope: str):
        if expr and expr.strip():
            specs.append((expr, required, alts, intent, scope))

    # Identity / discovery (majority)
    add(
        f"{base_group} AND (polymerization OR polymerisation)",
        [bases[0], "polymerization"],
        bases[1:4] + ["polymerisation"],
        "base polymerization discovery",
        "full_text",
    )
    add(
        f"{base_group} AND (synthesis OR preparation OR preparing)",
        [bases[0], "synthesis"],
        ["preparation", "preparing"],
        "base synthesis discovery",
        "full_text",
    )
    add(
        f"{base_group} AND (production OR manufacturing OR producing)",
        [bases[0], "production"],
        ["manufacturing", "producing"],
        "base manufacturing discovery",
        "full_text",
    )
    add(
        f"TI=({base_group} AND (polymerization OR synthesis OR preparation))",
        [bases[0], "polymerization"],
        ["synthesis", "preparation"],
        "title identity discovery",
        "title",
    )
    add(
        f"{base_group} AND (composition OR copolymer OR copolymerization)",
        [bases[0], "composition"],
        ["copolymer", "copolymerization"],
        "composition discovery",
        "full_text",
    )
    add(
        f"TI=({base_group})",
        [bases[0]],
        bases[1:3],
        "exact title identity",
        "title",
    )

    if medium_terms:
        mg = _or_group(medium_terms)
        add(
            f"{base_group} AND {mg}",
            [bases[0], medium_terms[0]],
            medium_terms[1:],
            "medium-biased polymerization",
            "full_text",
        )
    else:
        add(
            f"{base_group} AND (emulsion OR solution OR bulk) AND (polymerization OR polymerisation)",
            [bases[0], "polymerization"],
            ["emulsion", "solution"],
            "process-class discovery",
            "full_text",
        )

    if precursors:
        pg = _or_group(precursors[:4])
        add(
            f"{base_group} AND {pg} AND (polymerization OR copolymerization)",
            [bases[0], precursors[0]],
            precursors[1:3] + ["polymerization"],
            "precursor / monomer discovery",
            "full_text",
        )

    if process:
        pg = _or_group(process[:3])
        add(
            f"{base_group} AND {pg}",
            [bases[0], process[0]],
            process[1:3],
            "process concept discovery",
            "full_text",
        )

    # Modification / attribute / numeric (minority)
    if mods:
        mg = _or_group(mods[:4])
        add(
            f"{base_group} AND {mg}",
            [bases[0], mods[0]],
            mods[1:3],
            "target modification",
            "full_text",
        )
        add(
            f"TI=({base_group} AND {mg})",
            [bases[0], mods[0]],
            mods[1:2],
            "title modification",
            "title",
        )

    if attrs:
        ag = _or_group(attrs[:4])
        add(
            f"{base_group} AND {ag}",
            [bases[0], attrs[0]],
            attrs[1:3],
            "target attribute qualifier",
            "full_text",
        )

    if transforms:
        tg = _or_group(transforms[:3])
        add(
            f"{base_group} AND {tg}",
            [bases[0], transforms[0]],
            transforms[1:2],
            "transformation",
            "full_text",
        )

    for c in numerics[:2]:
        phrases = _numeric_query_phrases(c)[:5]
        if not phrases:
            continue
        ng = _or_group(phrases)
        add(
            f"{base_group} AND {ng}",
            [bases[0]] + phrases[:2],
            phrases[2:4],
            "numeric / range constraint",
            "full_text",
        )
        # Mid-range / content terminology without forcing exact number
        if c.attribute:
            add(
                f"{base_group} AND (\"{c.attribute}\" OR \"{c.attribute} content\")",
                [bases[0], c.attribute],
                [f"{c.attribute} content"],
                "attribute terminology",
                "full_text",
            )

    # Pad to target with synonym / intent variants
    pad_templates = [
        ("{base} AND (polymerization OR copolymerization OR polymerisation)", "polymerization pad", "full_text"),
        ("{base} AND (synthesis OR preparation OR manufacture)", "synthesis pad", "full_text"),
        ("TI=({base} AND (polymerization OR preparation))", "title pad", "title"),
        ("{base} AND (latex OR rubber OR elastomer)", "material class pad", "full_text"),
        ("{base} AND (process OR processing OR compounding)", "process pad", "full_text"),
        ("{base} AND (monomer OR comonomer OR feedstock)", "monomer pad", "full_text"),
        ("{base} AND (aqueous OR emulsion OR solution)", "medium pad", "full_text"),
        ("TI=({base})", "title identity pad", "title"),
    ]
    pad_i = 0
    while len(specs) < TARGET_QUERY_COUNT:
        base_term = bases[pad_i % len(bases)]
        quoted = f'"{base_term}"' if " " in base_term else base_term
        tmpl, intent, scope = pad_templates[pad_i % len(pad_templates)]
        expr = tmpl.format(base=quoted)
        add(expr, [base_term], bases[:3], intent, scope)
        pad_i += 1
        if pad_i > TARGET_QUERY_COUNT * 3:
            break

    queries: list[GeneratedQuery] = []
    seen: set[str] = set()
    for expr, required, alts, intent, scope in specs:
        key = expr.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(
            GeneratedQuery(
                query=expr,
                required_concepts=required,
                alternative_concepts=alts,
                intent=intent,
                scope=scope,
            )
        )
        if len(queries) >= TARGET_QUERY_COUNT:
            break

    return queries


def _identity_tokens_for_validation(profile: LLMCompoundSearchProfile) -> list[str]:
    tokens: list[str] = []
    for b in profile.base_material or []:
        if b and b.strip():
            tokens.append(b.strip())
            for part in re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", b):
                if len(part) >= 2:
                    tokens.append(part)
    # Original input identity leftovers
    for b in extract_base_material_candidates(profile.original_input or ""):
        tokens.append(b)
        for part in re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", b):
            if len(part) >= 2:
                tokens.append(part)
    # Dedup
    out: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        key = t.lower()
        if key not in seen and key not in _STOPWORDS:
            seen.add(key)
            out.append(t)
    return out


def validate_generated_query(
    generated_query: GeneratedQuery,
    profile: LLMCompoundSearchProfile,
) -> Tuple[bool, str]:
    """
    Profile-aware validation.
    A valid query must carry target identity (base or synonym token).
    Qualifiers/numeric constraints are optional — discovery queries without them PASS.
    """
    q = generated_query.query or ""
    q_lower = q.lower()

    identity_tokens = _identity_tokens_for_validation(profile)
    has_identity = False
    for tok in identity_tokens:
        t = tok.lower()
        if len(t) <= 2:
            if re.search(r"\b" + re.escape(t) + r"\b", q_lower):
                has_identity = True
                break
        elif t in q_lower:
            has_identity = True
            break

    if not has_identity:
        return False, "No base material / identity concept"

    flat_or_bad = " or " in q_lower and "(" not in q_lower and ")" not in q_lower
    if flat_or_bad:
        return False, "Top-level OR used inappropriately / flat keyword bag"

    # Reject queries that are only generic process words with no real identity
    # (identity already required above — this is a soft extra guard)
    generic_only = {
        "temperature", "emulsifier", "conversion", "initiator", "surfactant",
    }
    q_words = set(re.findall(r"[a-z]{4,}", q_lower))
    if q_words and q_words.issubset(generic_only):
        return False, "Generic terminology only"

    return True, "PASS"


def log_profile_summary(profile: LLMCompoundSearchProfile, *, recovery_used: bool, incomplete_reasons: list[str]):
    logger.info("[PROFILE] original_input=%r", profile.original_input)
    logger.info("[PROFILE] base_material=%s", profile.base_material)
    logger.info("[PROFILE] target_modifications=%s", profile.target_modifications)
    logger.info("[PROFILE] target_attributes=%s", profile.target_attributes)
    logger.info(
        "[PROFILE] numeric_constraints=%s",
        [
            {
                "attribute": c.attribute,
                "value": c.value,
                "lower_bound": c.lower_bound,
                "upper_bound": c.upper_bound,
                "unit": c.unit,
                "operator": c.operator,
                "raw_span": c.raw_span,
            }
            for c in (profile.numeric_constraints or [])
        ],
    )
    logger.info("[PROFILE] attribute_dimension_ranges=%s", profile.attribute_dimension_ranges)
    logger.info("[PROFILE] synthesis_transformations=%s", profile.synthesis_transformations)
    logger.info(
        "[RECOVERY] llm_profile_incomplete=%s reasons=%s deterministic_recovery_used=%s",
        bool(incomplete_reasons),
        incomplete_reasons,
        recovery_used,
    )


class SearchService:
    def __init__(self):
        self.serper_api_key = settings.SERPER_API_KEY

    def _filter_valid_queries(
        self,
        queries: list[GeneratedQuery],
        profile: LLMCompoundSearchProfile,
    ) -> Tuple[list[GeneratedQuery], int, list[str]]:
        validated: list[GeneratedQuery] = []
        rejected = 0
        reasons: list[str] = []
        for i, gq in enumerate(queries or []):
            ok, reason = validate_generated_query(gq, profile)
            logger.info("[QUERY_EXPANSION] Query %02d:", i + 1)
            logger.info("  Expression: %s", gq.query)
            logger.info("  Scope: %s", gq.scope)
            logger.info("  Required: %s", gq.required_concepts)
            logger.info("  Alternatives: %s", gq.alternative_concepts)
            if ok:
                logger.info("  Boolean validation: PASS")
                validated.append(gq)
            else:
                logger.info("  Boolean validation: FAIL (%s)", reason)
                rejected += 1
                reasons.append(reason)
        return validated, rejected, reasons

    async def generate_strategy(
        self,
        compound_name: str,
        competitors: List[str] = None,
        websites: List[str] = None,
        jurisdictions: List[str] = None,
        publication_filter: dict = None,
        attribute_constraint: str | None = None,
        polymerization_medium: str = "any",
    ) -> LLMCompoundSearchProfile:
        """Use LLM + deterministic recovery to create a complete search strategy."""
        logger.info("Generating search strategy for %s...", compound_name)
        logger.info("[INPUT] original_user_input=%r", compound_name)
        medium = (polymerization_medium or "any").strip().lower()
        logger.info(
            "[QUERY_EXPANSION] Optional constraints: "
            "attribute_constraint=%r polymerization_medium=%r publication_filter=%r",
            attribute_constraint,
            medium,
            publication_filter,
        )
        comp_str = ", ".join(competitors) if competitors else "None"
        web_str = ", ".join(websites) if websites else "None"
        jur_str = ", ".join(jurisdictions) if jurisdictions else "None"
        pub_str = str(publication_filter) if publication_filter else "None"

        prompt = build_query_expansion_prompt(
            compound_name=compound_name,
            competitors=comp_str,
            websites=web_str,
            jurisdictions=jur_str,
            publication_filter=pub_str,
            attribute_constraint=attribute_constraint,
            polymerization_medium=medium,
        )

        recovery_used = False
        incomplete_reasons: list[str] = []

        logger.info("[QUERY_EXPANSION] START | compound=%r", compound_name)
        logger.info("[QUERY_EXPANSION] Request prepared (prompt_len=%d, schema=%s)", len(prompt), LLMCompoundSearchProfile.__name__)
        logger.info("[QUERY_EXPANSION] Calling provider via llm_client...")
        t0 = time.time()

        try:
            result, provider, usage = await llm_client.generate_structured(
                prompt=prompt,
                system_prompt="You are a JSON generator. Do not include markdown blocks.",
                schema=LLMCompoundSearchProfile,
                temperature=0.3,
                metadata={"stage": "QUERY_EXPANSION"},
            )
            duration = time.time() - t0
            finish_reason = (usage or {}).get("finish_reason")
            resp_len = (usage or {}).get("response_length", 0)
            logger.info(
                "[QUERY_EXPANSION] Provider returned | provider=%s latency=%.2fs finish_reason=%s response_length=%s",
                provider, duration, finish_reason, resp_len
            )
            if not result:
                logger.warning("[QUERY_EXPANSION] Provider returned None for structured extraction; will use deterministic fallback")
                raise Exception("LLM Client returned None for structured extraction.")

            logger.info(
                "[QUERY_EXPANSION] Parsing response: SUCCESS | base_material=%s queries_count=%d",
                result.base_material,
                len(result.search_queries or []),
            )

            if not result.original_input:
                result.original_input = compound_name

            is_complete, incomplete_reasons = assess_profile_completeness(result, compound_name)
            if not is_complete:
                logger.warning(
                    "[PROFILE] Incomplete LLM profile: %s — running deterministic recovery",
                    incomplete_reasons,
                )
                result = merge_recovered_into_profile(result, compound_name)
                recovery_used = True
            else:
                # Still merge numerics / identity gaps without discarding LLM content
                before_bases = list(result.base_material or [])
                result = merge_recovered_into_profile(result, compound_name)
                if result.base_material != before_bases or result.numeric_constraints:
                    # Soft recovery enrichment only counts if we filled empty critical fields
                    if not before_bases:
                        recovery_used = True

            log_profile_summary(
                result,
                recovery_used=recovery_used,
                incomplete_reasons=incomplete_reasons,
            )

            validated_queries, rejected_queries, _ = self._filter_valid_queries(
                result.search_queries, result
            )
            logger.info(
                "[QUERY] generated=%d valid=%d rejected=%d",
                len(result.search_queries or []),
                len(validated_queries),
                rejected_queries,
            )

            # LLM repair attempt (once) if under target
            if len(validated_queries) < TARGET_QUERY_COUNT:
                missing_count = TARGET_QUERY_COUNT - len(validated_queries)
                logger.info(
                    "[QUERY_VALIDATION] Only %d valid queries from first LLM call (%d rejected). "
                    "Retrying LLM for %d additional distinct queries.",
                    len(validated_queries),
                    rejected_queries,
                    missing_count,
                )
                existing_exprs = [q.query for q in validated_queries]
                retry_prompt = (
                    build_query_expansion_prompt(
                        compound_name=compound_name,
                        competitors=comp_str,
                        websites=web_str,
                        jurisdictions=jur_str,
                        publication_filter=pub_str,
                        attribute_constraint=attribute_constraint,
                        polymerization_medium=medium,
                    )
                    + f"\n\nNOTE: A previous call already produced {len(validated_queries)} valid queries. "
                    f"You MUST produce a COMPLETE profile including non-empty base_material and "
                    f"{missing_count} ADDITIONAL distinct valid Boolean queries that "
                    f"are NOT equivalent to any of these already-generated queries:\n"
                    + "\n".join(f"  - {e}" for e in existing_exprs)
                    + "\nDo NOT leave base_material or search_queries empty."
                    + "\nDo NOT repeat or paraphrase any query from the list above."
                )
                try:
                    retry_result, _, _ = await llm_client.generate_structured(
                        prompt=retry_prompt,
                        system_prompt="You are a JSON generator. Do not include markdown blocks.",
                        schema=LLMCompoundSearchProfile,
                        temperature=0.5,
                    )
                    if retry_result:
                        # Merge any recovered identity from retry into working profile
                        if retry_result.base_material:
                            result.base_material = _merge_unique(
                                result.base_material, retry_result.base_material
                            )
                        for field in (
                            "target_modifications",
                            "target_attributes",
                            "synthesis_transformations",
                            "precursor_relationships",
                            "relevant_process_concepts",
                            "attribute_dimension_ranges",
                        ):
                            extra = getattr(retry_result, field, None) or []
                            setattr(
                                result,
                                field,
                                _merge_unique(getattr(result, field) or [], extra),
                            )
                        if retry_result.numeric_constraints:
                            result.numeric_constraints = _merge_unique_constraints(
                                result.numeric_constraints,
                                retry_result.numeric_constraints,
                            )

                        existing_query_strings = {
                            q.query.strip().lower() for q in validated_queries
                        }
                        for gq in retry_result.search_queries or []:
                            if gq.query.strip().lower() in existing_query_strings:
                                logger.info("[QUERY_RETRY] Duplicate skipped: %s", gq.query)
                                continue
                            ok, reason = validate_generated_query(gq, result)
                            if ok:
                                validated_queries.append(gq)
                                existing_query_strings.add(gq.query.strip().lower())
                                logger.info("[QUERY_RETRY] Accepted: %s", gq.query)
                            else:
                                logger.info("[QUERY_RETRY] Rejected (%s): %s", reason, gq.query)
                            if len(validated_queries) >= TARGET_QUERY_COUNT:
                                break
                except Exception as retry_err:
                    logger.warning("[QUERY_RETRY] Retry LLM call failed: %s", retry_err)

            # Deterministic query construction if still inadequate
            if len(validated_queries) < TARGET_QUERY_COUNT:
                logger.info(
                    "[RECOVERY] Deterministic query construction from normalized profile "
                    "(have %d, target %d)",
                    len(validated_queries),
                    TARGET_QUERY_COUNT,
                )
                recovery_used = True
                det_queries = build_deterministic_queries(result, polymerization_medium=medium)
                existing_query_strings = {q.query.strip().lower() for q in validated_queries}
                for gq in det_queries:
                    if gq.query.strip().lower() in existing_query_strings:
                        continue
                    ok, reason = validate_generated_query(gq, result)
                    if ok:
                        validated_queries.append(gq)
                        existing_query_strings.add(gq.query.strip().lower())
                        logger.info("[QUERY_DET] Accepted: %s", gq.query)
                    else:
                        logger.info("[QUERY_DET] Rejected (%s): %s", reason, gq.query)
                    if len(validated_queries) >= TARGET_QUERY_COUNT:
                        break

            # Final deduplication
            seen_q_strings: set[str] = set()
            deduped_queries: list[GeneratedQuery] = []
            for gq in validated_queries:
                key = gq.query.strip().lower()
                if key not in seen_q_strings:
                    seen_q_strings.add(key)
                    deduped_queries.append(gq)
                else:
                    logger.info("[QUERY_DEDUP] Removed duplicate: %s", gq.query)

            if not deduped_queries:
                log_profile_summary(
                    result,
                    recovery_used=recovery_used,
                    incomplete_reasons=incomplete_reasons or ["zero valid queries after recovery"],
                )
                raise SearchPreparationError(
                    "SEARCH_PREPARATION_FAILURE: Unable to prepare any valid search queries "
                    f"for input {compound_name!r}. Serper was not called. "
                    f"base_material={result.base_material!r} recovery_used={recovery_used}."
                )

            if len(deduped_queries) < TARGET_QUERY_COUNT:
                logger.warning(
                    "[QUERY_VALIDATION] Proceeding with %d distinct queries "
                    "(target=%d after LLM + deterministic recovery).",
                    len(deduped_queries),
                    TARGET_QUERY_COUNT,
                )
            else:
                logger.info(
                    "[QUERY_VALIDATION] Final distinct query count: %d",
                    len(deduped_queries),
                )

            result.search_queries = deduped_queries
            logger.info(
                "[SEARCH_PREP] queries_ready=%d recovery_used=%s — safe to call Serper",
                len(result.search_queries),
                recovery_used,
            )
            logger.info(
                "[QUERY_EXPANSION] Search profile generated successfully | total_queries=%d recovery_used=%s",
                len(result.search_queries),
                recovery_used,
            )
            return result

        except SearchPreparationError:
            raise
        except Exception as e:
            if type(e).__name__ == "ProviderExhaustedException":
                raise e
            logger.error("Failed to generate search strategy: %s", e, exc_info=True)
            logger.warning("[QUERY_EXPANSION] Entering deterministic fallback search strategy generation")

            # Deterministic last-resort profile — never return zero queries silently
            fallback = LLMCompoundSearchProfile(
                original_input=compound_name,
                synthesis_intent=True,
            )
            fallback = merge_recovered_into_profile(fallback, compound_name)
            fallback.search_queries = build_deterministic_queries(
                fallback, polymerization_medium=medium
            )
            if not fallback.search_queries:
                # Absolute minimum: quoted original + polymerization
                fallback.base_material = fallback.base_material or [compound_name]
                fallback.search_queries = [
                    GeneratedQuery(
                        query=f'("{compound_name}") AND polymerization',
                        required_concepts=[compound_name],
                        alternative_concepts=[],
                        intent="fallback",
                        scope="full_text",
                    )
                ]
            validated, _, _ = self._filter_valid_queries(fallback.search_queries, fallback)
            fallback.search_queries = validated or fallback.search_queries
            if not fallback.search_queries:
                raise SearchPreparationError(
                    "SEARCH_PREPARATION_FAILURE: Exception fallback also produced zero queries "
                    f"for input {compound_name!r}."
                ) from e
            logger.info(
                "[RECOVERY] Exception-path deterministic profile with %d queries",
                len(fallback.search_queries),
            )
            log_profile_summary(fallback, recovery_used=True, incomplete_reasons=[str(e)])
            return fallback

    async def search_patents(self, queries: List[Any]) -> List[Dict[str, Any]]:
        """Hit the Serper API to get patent links and metadata."""
        # HARD GUARD: never call Serper with zero queries
        if not queries:
            logger.error(
                "[SEARCH_PREPARATION_FAILURE] Refusing Serper call with 0 queries. "
                "This is not SEARCH_RETURNED_ZERO_RESULTS."
            )
            raise SearchPreparationError(
                "SEARCH_PREPARATION_FAILURE: zero queries supplied to search_patents; "
                "Serper was not called."
            )

        logger.info("Executing Serper API normal search for %d queries...", len(queries))
        logger.info("[SEARCH] queries_sent_to_serper=%d", len(queries))

        all_results = []

        if not self.serper_api_key:
            logger.warning("SERPER_API_KEY is not set. Returning empty list.")
            return []

        # Safe key fingerprint logging
        key_fingerprint = (
            self.serper_api_key[:6] + "..." + self.serper_api_key[-4:]
            if len(self.serper_api_key) > 10
            else "***"
        )
        logger.info(
            "[SERPER CONFIG] Endpoint: https://google.serper.dev/patents | "
            "API key configured: true | API key fingerprint: %s",
            key_fingerprint,
        )

        planned_requests = 0
        high_value = 0
        medium_value = 0
        supporting = 0

        query_configs = []
        for q in queries:
            q_str = (
                q.query
                if hasattr(q, "query")
                else q.get("query", q)
                if isinstance(q, dict)
                else str(q)
            )
            intent = (
                (q.intent if hasattr(q, "intent") else q.get("intent", ""))
                if hasattr(q, "intent") or isinstance(q, dict)
                else ""
            )

            intent_lower = intent.lower()
            if any(
                k in intent_lower
                for k in (
                    "synthesis",
                    "modification",
                    "base",
                    "preparation",
                    "polymerization",
                    "discovery",
                    "identity",
                )
            ):
                max_pages = 3
                high_value += 1
            elif any(
                k in intent_lower
                for k in (
                    "process",
                    "monomer",
                    "composition",
                    "feed",
                    "transformation",
                    "numeric",
                    "attribute",
                )
            ):
                max_pages = 2
                medium_value += 1
            else:
                max_pages = 1
                supporting += 1

            planned_requests += max_pages
            query_configs.append({"query_str": q_str, "max_pages": max_pages})

        logger.info(
            "[SERPER SEARCH PLAN] Total queries: %d | Maximum requests: %d | "
            "High-value queries: %d | Medium-value queries: %d | Supporting queries: %d",
            len(queries),
            planned_requests,
            high_value,
            medium_value,
            supporting,
        )

        async def execute_serper_search(
            q_configs: List[Dict], endpoint: str, extra_query_modifier: str = ""
        ) -> List[Dict[str, Any]]:
            results = []
            seen_pub_nums = set()
            requests_completed = 0
            requests_failed = 0
            requests_avoided = 0

            async with httpx.AsyncClient() as client:
                credits_exhausted = False
                for query_idx, qc in enumerate(q_configs, 1):
                    if credits_exhausted:
                        break

                    search_query = f"{extra_query_modifier} {qc['query_str']}".strip()
                    max_p = qc["max_pages"]

                    for page in range(1, max_p + 1):
                        payload = {"q": search_query, "page": page}
                        headers = {
                            "X-API-KEY": self.serper_api_key,
                            "Content-Type": "application/json",
                        }

                        try:
                            logger.info(
                                "[SERPER %s REQUEST] Query %d/%d Page %d/%d: '%s'",
                                endpoint.upper(),
                                query_idx,
                                len(q_configs),
                                page,
                                max_p,
                                search_query,
                            )
                            response = await client.post(
                                f"https://google.serper.dev/{endpoint}",
                                headers=headers,
                                json=payload,
                                timeout=15.0,
                            )

                            logger.info(
                                f"[SERPER {endpoint.upper()} RESPONSE] HTTP Status: {response.status_code}"
                            )

                            if response.status_code == 400:
                                if "Not enough credits" in response.text:
                                    logger.error(
                                        "[SERPER QUOTA ERROR] Endpoint: %s | Configured key: %s | "
                                        "Queries planned: %d | Maximum possible requests: %d | "
                                        "Requests completed: %d | Requests failed: %d | "
                                        "Reason: Not enough Serper credits.",
                                        endpoint,
                                        key_fingerprint,
                                        len(q_configs),
                                        planned_requests,
                                        requests_completed,
                                        requests_failed + 1,
                                    )
                                    raise SerperCreditsExhaustedError(
                                        "Serper API credits exhausted"
                                    )
                                else:
                                    logger.error(
                                        "Serper API 400 Bad Request (Syntax Error). Response: %s",
                                        response.text,
                                    )
                                    requests_failed += 1
                                    break

                            elif response.status_code in [401, 403]:
                                logger.error(
                                    "Serper API Auth Error (%d). Response: %s",
                                    response.status_code,
                                    response.text,
                                )
                                raise httpx.HTTPStatusError(
                                    f"Serper Auth Error: {response.text}",
                                    request=response.request,
                                    response=response,
                                )
                            elif response.status_code == 429:
                                logger.error(
                                    "Serper API Rate Limit Error (429). Response: %s",
                                    response.text,
                                )
                                raise httpx.HTTPStatusError(
                                    f"Serper Rate Limit Error: {response.text}",
                                    request=response.request,
                                    response=response,
                                )
                            elif response.status_code >= 500:
                                logger.error(
                                    "Serper API Upstream Error (%d). Response: %s",
                                    response.status_code,
                                    response.text,
                                )
                                requests_failed += 1
                                break
                            elif response.status_code != 200:
                                logger.error(
                                    "Serper API non-200. Status: %s, Text: %s",
                                    response.status_code,
                                    response.text,
                                )
                                response.raise_for_status()

                            requests_completed += 1
                            data = response.json()

                            patent_results = data.get("patents", [])
                            if not patent_results and "organic" in data:
                                patent_results = data.get("organic", [])

                            logger.info(
                                "[SERPER %s RESPONSE] Extracted %d results for query '%s' on page %d",
                                endpoint.upper(),
                                len(patent_results),
                                search_query,
                                page,
                            )

                            if not patent_results:
                                logger.info(
                                    "No more results for query '%s' on page %d. Stopping pagination.",
                                    search_query,
                                    page,
                                )
                                break

                            new_candidates_on_page = 0
                            for result in patent_results:
                                link = result.get("link", "")
                                pub_num = result.get("publicationNumber")

                                if not pub_num and link:
                                    match = re.search(
                                        r"patents\.google\.com/patent/([A-Z0-9]+)", link
                                    )
                                    if match:
                                        pub_num = match.group(1)

                                if not pub_num:
                                    continue

                                if pub_num in seen_pub_nums:
                                    continue

                                seen_pub_nums.add(pub_num)
                                new_candidates_on_page += 1

                                results.append(
                                    {
                                        "patent_number": pub_num,
                                        "title": result.get("title", ""),
                                        "snippet": result.get("snippet", "")
                                        or result.get("abstract", ""),
                                        "url": link,
                                        "query_matched": search_query,
                                        "family_id": pub_num,
                                        "publication_date": result.get("publicationDate", ""),
                                        "priority_date": result.get("priorityDate", ""),
                                        "filing_date": result.get("filingDate", ""),
                                        "grant_date": result.get("grantDate", ""),
                                        "inventor": result.get("inventor", ""),
                                        "assignee": result.get("assignee", ""),
                                        "pdf_url": result.get("pdfUrl", ""),
                                        "source": f"serper_{endpoint}",
                                    }
                                )

                            if new_candidates_on_page == 0:
                                logger.info(
                                    "Page %d yielded 0 new unique candidates for query '%s'. "
                                    "Early stopping pagination.",
                                    page,
                                    search_query,
                                )
                                requests_avoided += max_p - page
                                break

                        except SerperCreditsExhaustedError as e:
                            if len(results) > 0:
                                logger.warning(
                                    "[SERPER PARTIAL DISCOVERY] Credits exhausted midway, "
                                    "but safely preserving %d candidates found so far.",
                                    len(results),
                                )
                                credits_exhausted = True
                                break
                            else:
                                raise e
                        except Exception as e:
                            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in [
                                401,
                                403,
                                429,
                            ]:
                                raise e
                            logger.error(
                                "Serper API request failed for query '%s' page %d: %s",
                                search_query,
                                page,
                                e,
                            )
                            break

            logger.info(
                "[SERPER SEARCH SUMMARY] Queries attempted: %d | Requests completed: %d | "
                "Requests failed: %d | Unique patents: %d | "
                "Requests avoided by early stopping: %d",
                len(q_configs),
                requests_completed,
                requests_failed,
                len(results),
                requests_avoided,
            )
            return results

        all_results = await execute_serper_search(query_configs, "patents")

        if not all_results:
            logger.warning(
                "[SEARCH] Serper /patents returned ZERO results across all queries. "
                "Engaging /search fallback."
            )
            all_results = await execute_serper_search(
                query_configs, "search", "site:patents.google.com/patent/"
            )

        logger.info(
            "[SEARCH] candidates_returned=%d (queries_sent=%d)",
            len(all_results),
            len(queries),
        )
        logger.info("Total discovered Google Patent candidates: %d", len(all_results))
        return all_results


def _merge_unique_constraints(
    existing: list[TargetNumericConstraint],
    extras: list[TargetNumericConstraint],
) -> list[TargetNumericConstraint]:
    out = list(existing or [])
    keys = {
        (c.attribute, c.value, c.lower_bound, c.upper_bound, c.unit, c.operator)
        for c in out
    }
    for c in extras or []:
        key = (c.attribute, c.value, c.lower_bound, c.upper_bound, c.unit, c.operator)
        if key not in keys:
            out.append(c)
            keys.add(key)
    return out
