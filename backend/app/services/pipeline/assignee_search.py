"""
Assignee-specific patent discovery.

Workflow B runs after the existing general search. It does not replace
query expansion, gates, ranking, or extraction. Each assignee is searched
and validated on its own, then qualifying patents are added to the same
selected set for the existing full-document extraction path.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

_LEGAL_SUFFIXES = frozenset({
    "incorporated", "inc", "ltd", "limited", "llc", "llp", "plc", "corp",
    "corporation", "company", "co", "gmbh", "ag", "sa", "nv", "bv", "kk",
    "pte", "pty", "srl", "spa", "ab", "oy", "as", "kg",
})

_SYNTHESIS_MARKERS = (
    "polymeriz", "polymeris", "copolymer", "emulsion", "monomer",
    "initiator", "emulsif", "synthesis", "prepared", "chain transfer",
    "coagulation",
)


def normalize_legal_name(name: str) -> str:
    """Compare legal names without punctuation or trailing entity suffixes."""
    text = (name or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [token for token in text.split() if token]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def names_are_same_entity(selected: str, observed: str, aliases: list[str] | None = None) -> bool:
    """True only when the bibliographic assignee is the same legal name.

    Suffix-only differences match. Subsidiaries, parents, and similarly
    named organizations do not.
    """
    observed_norm = normalize_legal_name(observed)
    if not observed_norm:
        return False
    targets = [selected, *(aliases or [])]
    return any(normalize_legal_name(target) == observed_norm for target in targets if target and target.strip())


def publication_jurisdiction(publication_number: str) -> str:
    match = re.match(r"^([A-Z]{2})", (publication_number or "").upper())
    return match.group(1) if match else ""


def jurisdiction_allowed(publication_number: str, selected: list[str] | None) -> bool:
    """Accept only the publication's own office. Family members do not qualify."""
    if not selected:
        return True
    allowed = set()
    for code in selected:
        office = (code or "").upper()
        if office == "EU":
            office = "EP"
        if office and office != "OTHER":
            allowed.add(office)
    if not allowed:
        return True
    return publication_jurisdiction(publication_number) in allowed


def publication_year(publication_number: str, publication_date: str = "") -> int | None:
    if publication_date:
        match = re.search(r"\b(19\d{2}|20\d{2})\b", publication_date)
        if match:
            return int(match.group(1))
    match = re.search(r"[A-Z]{2}(\d{4})", (publication_number or "").upper())
    if match:
        return int(match.group(1))
    return None


def min_publication_year(publication_filter: dict | None, current_year: int) -> int | None:
    if not publication_filter:
        return None
    date_range = publication_filter.get("date_range") or ""
    mode = publication_filter.get("mode") or ""
    year_from = publication_filter.get("year_from")
    if date_range == "Last 10 Years" or mode == "last10years":
        return current_year - 10
    if date_range == "Last 5 Years" or mode == "last5years":
        return current_year - 5
    if date_range == "Last 3 Years" or mode == "last3years":
        return current_year - 3
    if year_from:
        return int(year_from)
    custom_from = publication_filter.get("customFrom") or ""
    if mode == "custom" and custom_from[:4].isdigit():
        return int(custom_from[:4])
    return None


def date_allowed(publication_number: str, publication_date: str, min_year: int | None) -> bool:
    if not min_year:
        return True
    year = publication_year(publication_number, publication_date)
    return bool(year and year >= min_year)


def family_key(candidate: dict) -> str:
    """Family identity for assignee allocation. Publication number is the fallback."""
    priority = (candidate.get("priority_date") or "").strip()
    publication = candidate.get("patent_number") or ""
    if not priority:
        return publication
    return f"{priority}_{normalize_legal_name(candidate.get('assignee') or '')}"


def is_compound_relevant(title: str, snippet: str, material_terms: list[str]) -> bool:
    """Require the requested compound and synthesis language, not a passing mention."""
    blob = f"{title or ''} {snippet or ''}".lower()
    materials = []
    for term in material_terms:
        cleaned = (term or "").strip().lower()
        if len(cleaned) >= 3 and cleaned not in materials:
            materials.append(cleaned)
    if not materials or not any(term in blob for term in materials):
        return False
    return any(marker in blob for marker in _SYNTHESIS_MARKERS)


def patents_allowed(assignee_count: int, single_max: int = 1) -> int:
    if assignee_count <= 0:
        return 0
    if assignee_count == 1:
        return 2 if int(single_max) >= 2 else 1
    return 1


def build_assignee_queries(
    compound_name: str,
    assignee: str,
    material_terms: list[str] | None = None,
    jurisdictions: list[str] | None = None,
) -> list[str]:
    """One or two compound-and-assignee queries. Never a company-only search."""
    terms: list[str] = []
    for term in [compound_name, *(material_terms or [])]:
        cleaned = (term or "").strip()
        if cleaned and cleaned.lower() not in {item.lower() for item in terms}:
            terms.append(cleaned)
    terms = terms[:4]
    material = " OR ".join(f'"{term}"' for term in terms)
    offices = []
    for code in jurisdictions or []:
        office = "EP" if (code or "").upper() == "EU" else (code or "").upper()
        if office and office != "OTHER" and office not in offices:
            offices.append(office)
    jurisdiction_hint = f" ({' OR '.join(offices)})" if offices else ""
    quoted_assignee = f'"{assignee.strip()}"'
    first = (
        f"{quoted_assignee} ({material}) "
        f"(polymerization OR copolymerization OR emulsion){jurisdiction_hint}"
    )
    second = (
        f"{quoted_assignee} ({material}) "
        f"(monomer OR initiator OR emulsifier){jurisdiction_hint}"
    )
    return [first, second]


def allocate_assignee_patents(
    candidates: list[dict],
    assignee: str,
    *,
    aliases: list[str] | None = None,
    jurisdictions: list[str] | None = None,
    min_year: int | None = None,
    material_terms: list[str] | None = None,
    already_selected: set[str] | None = None,
    already_families: set[str] | None = None,
    quota: int = 1,
    defer_insufficient: bool = False,
) -> dict:
    """Validate candidates for one assignee. Does not invent a patent when none qualify."""
    selected_ids = set(already_selected or [])
    families = set(already_families or [])
    accepted: list[dict] = []
    satisfied_by_existing: list[str] = []
    rejected: list[dict] = []
    needs_document: list[dict] = []

    for candidate in candidates:
        publication = (candidate.get("patent_number") or "").strip()
        if not publication:
            continue
        if not jurisdiction_allowed(publication, jurisdictions):
            rejected.append({"patent_number": publication, "reason": "jurisdiction"})
            continue
        if not date_allowed(publication, candidate.get("publication_date") or "", min_year):
            rejected.append({"patent_number": publication, "reason": "date"})
            continue
        if not names_are_same_entity(assignee, candidate.get("assignee") or "", aliases):
            rejected.append({"patent_number": publication, "reason": "assignee"})
            continue
        if not is_compound_relevant(
            candidate.get("title") or "",
            candidate.get("snippet") or "",
            material_terms or [],
        ):
            if defer_insufficient:
                needs_document.append(candidate)
            else:
                rejected.append({"patent_number": publication, "reason": "relevance"})
            continue

        key = family_key(candidate)
        if publication in selected_ids or (key and key in families):
            satisfied_by_existing.append(publication)
            if len(accepted) + len(satisfied_by_existing) >= quota:
                break
            continue

        accepted.append(candidate)
        selected_ids.add(publication)
        if key:
            families.add(key)
        if len(accepted) + len(satisfied_by_existing) >= quota:
            break

    return {
        "accepted": accepted,
        "satisfied_by_existing": satisfied_by_existing,
        "rejected": rejected,
        "needs_document": needs_document,
    }


async def _confirm_with_documents(
    candidates: list[dict],
    assignee: str,
    *,
    material_terms: list[str],
    jurisdictions: list[str] | None,
    evidence_fn: Callable[[str], Awaitable[dict | None]] | None,
    budget: int,
    remaining: int,
) -> tuple[list[dict], list[dict]]:
    """Final relevance uses abstract and claims when the snippet is not enough."""
    if not evidence_fn or remaining <= 0 or budget <= 0:
        return [], []
    accepted: list[dict] = []
    rejected: list[dict] = []
    checks = 0
    for candidate in candidates:
        if len(accepted) >= remaining or checks >= budget:
            break
        publication = candidate.get("patent_number") or ""
        url = candidate.get("url") or ""
        checks += 1
        try:
            evidence = await evidence_fn(url) if url else None
        except Exception as exc:
            logger.warning("[ASSIGNEE SEARCH] document check failed: %s", type(exc).__name__)
            evidence = None
        if not evidence:
            rejected.append({"patent_number": publication, "reason": "document_unavailable"})
            continue
        observed = (evidence.get("assignee") or candidate.get("assignee") or "").strip()
        if not names_are_same_entity(assignee, observed):
            rejected.append({"patent_number": publication, "reason": "assignee"})
            continue
        meta_jurisdiction = (evidence.get("jurisdiction") or "").upper()
        publication_office = publication_jurisdiction(publication)
        if meta_jurisdiction and publication_office and meta_jurisdiction != publication_office:
            rejected.append({"patent_number": publication, "reason": "jurisdiction"})
            continue
        if not jurisdiction_allowed(publication, jurisdictions):
            rejected.append({"patent_number": publication, "reason": "jurisdiction"})
            continue
        body = " ".join([
            evidence.get("abstract") or "",
            evidence.get("claims_excerpt") or "",
            candidate.get("snippet") or "",
        ])
        if not is_compound_relevant(evidence.get("title") or candidate.get("title") or "", body, material_terms):
            rejected.append({"patent_number": publication, "reason": "relevance_fulltext"})
            continue
        candidate["assignee"] = observed or candidate.get("assignee")
        if evidence.get("abstract"):
            candidate["snippet"] = evidence["abstract"][:800]
        accepted.append(candidate)
    return accepted, rejected


@dataclass
class AssigneeDiscoveryResult:
    added: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)


async def discover_assignee_patents(
    search_fn: Callable[[list[Any]], Awaitable[list[dict]]],
    assignees: list[str],
    *,
    compound_name: str,
    material_terms: list[str],
    jurisdictions: list[str],
    publication_filter: dict | None,
    selected_candidates: list[dict],
    single_max: int = 1,
    current_year: int | None = None,
    progress: Callable[[str], None] | None = None,
    evidence_fn: Callable[[str], Awaitable[dict | None]] | None = None,
    document_budget: int = 3,
) -> AssigneeDiscoveryResult:
    """Search assignees one at a time. A failure for one assignee does not stop the others."""
    from datetime import datetime, timezone

    year_now = current_year or datetime.now(timezone.utc).year
    earliest = min_publication_year(publication_filter, year_now)
    quota = patents_allowed(len(assignees), single_max)
    selected_ids = {
        (item.get("patent_number") or "").strip()
        for item in selected_candidates
        if item.get("patent_number")
    }
    families = {family_key(item) for item in selected_candidates}
    result = AssigneeDiscoveryResult()

    for assignee in assignees:
        name = (assignee or "").strip()
        if not name:
            continue
        if progress:
            progress(f"Assignee search: {name}")
        queries = build_assignee_queries(compound_name, name, material_terms, jurisdictions)
        try:
            found = await search_fn([{"query": query, "intent": "assignee"} for query in queries])
        except Exception as exc:
            logger.warning("[ASSIGNEE SEARCH] %s failed: %s", name, type(exc).__name__)
            result.notes.append({
                "assignee": name,
                "status": "search_failed",
                "error_type": type(exc).__name__,
            })
            continue

        allocation = allocate_assignee_patents(
            found or [],
            name,
            jurisdictions=jurisdictions,
            min_year=earliest,
            material_terms=material_terms or [compound_name],
            already_selected=selected_ids,
            already_families=families,
            quota=quota,
            defer_insufficient=evidence_fn is not None,
        )
        confirmed, document_rejected = await _confirm_with_documents(
            allocation.get("needs_document") or [],
            name,
            material_terms=material_terms or [compound_name],
            jurisdictions=jurisdictions,
            evidence_fn=evidence_fn,
            budget=document_budget,
            remaining=max(0, quota - len(allocation["accepted"]) - len(allocation["satisfied_by_existing"])),
        )
        allocation["accepted"].extend(confirmed)
        allocation["rejected"].extend(document_rejected)
        for publication in allocation["satisfied_by_existing"]:
            for candidate in selected_candidates:
                if candidate.get("patent_number") == publication:
                    sources = list(candidate.get("discovery_sources") or ["GENERAL"])
                    if "ASSIGNEE" not in sources:
                        sources.append("ASSIGNEE")
                    candidate["discovery_sources"] = sources
                    candidate["competitor_name"] = candidate.get("competitor_name") or name
        for candidate in allocation["accepted"]:
            publication = candidate.get("patent_number")
            candidate["discovery_source"] = "COMPETITOR"
            candidate["competitor_name"] = name
            candidate["discovery_sources"] = ["ASSIGNEE"]
            result.added.append(candidate)
            selected_ids.add(publication)
            families.add(family_key(candidate))

        if allocation["accepted"] or allocation["satisfied_by_existing"]:
            result.notes.append({
                "assignee": name,
                "status": "selected",
                "patents": [
                    item.get("patent_number") for item in allocation["accepted"]
                ] + allocation["satisfied_by_existing"],
                "rejected": len(allocation["rejected"]),
            })
        else:
            result.notes.append({
                "assignee": name,
                "status": "no_qualifying_patent",
                "rejected": len(allocation["rejected"]),
            })
            logger.info("[ASSIGNEE SEARCH] No qualifying patent for %s", name)

    if progress:
        progress("Deduplication")
    return result
