"""
Assignee name suggestions.

Local rows come from assignees already stored on extracted patents.
When fewer than ten matches exist, company names are read from Serper
patent bibliographic assignee fields. The lookup is for the company only.
It does not include the research compound or synthesis terms.

Serper does not filter by assignee. A company name can be absent from the
assignee field on the first page, so a small number of additional pages are
read and then filtered to names that actually contain the query.
"""
from __future__ import annotations

import logging
import re
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.patent_extraction import PatentExtraction

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 10
_CACHE_TTL_SECONDS = 300
_CACHE_MAX = 64
_suggestion_cache: dict[str, tuple[float, list[str]]] = {}


def normalize_suggestion_key(name: str) -> str:
    """Case, punctuation, and whitespace folding. Legal suffixes stay in the key."""
    text = (name or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def suggestion_matches(name: str, query: str) -> bool:
    needle = normalize_suggestion_key(query)
    key = normalize_suggestion_key(name)
    return bool(needle) and needle in key


def matches_partial(name: str, query: str) -> bool:
    return suggestion_matches(name, query)


def merge_suggestions(*groups: list[str], query: str, limit: int = MAX_SUGGESTIONS) -> list[str]:
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    order: list[str] = []
    for group in groups:
        for name in group:
            cleaned = " ".join((name or "").split())
            if not cleaned or not suggestion_matches(cleaned, query):
                continue
            key = normalize_suggestion_key(cleaned)
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
            if key not in display:
                display[key] = cleaned
                order.append(key)
    ranked = sorted(order, key=lambda key: (-counts[key], order.index(key)))
    return [display[key] for key in ranked[:limit]]


def _cache_get(query: str) -> list[str] | None:
    item = _suggestion_cache.get(normalize_suggestion_key(query))
    if not item:
        return None
    stored_at, names = item
    if time.time() - stored_at > _CACHE_TTL_SECONDS:
        _suggestion_cache.pop(normalize_suggestion_key(query), None)
        return None
    return list(names)


def _cache_put(query: str, names: list[str]) -> None:
    key = normalize_suggestion_key(query)
    if len(_suggestion_cache) >= _CACHE_MAX:
        oldest = min(_suggestion_cache, key=lambda item: _suggestion_cache[item][0])
        _suggestion_cache.pop(oldest, None)
    _suggestion_cache[key] = (time.time(), list(names))


def clear_suggestion_cache() -> None:
    _suggestion_cache.clear()


async def gather_assignee_suggestions(
    query: str,
    fetch_page,
    *,
    max_pages: int = 3,
    limit: int = MAX_SUGGESTIONS,
) -> list[str]:
    """Read bibliographic assignee fields until ten matches or the page cap."""
    collected: list[str] = []
    pages = max(1, min(int(max_pages), 3))
    for page in range(1, pages + 1):
        if len(merge_suggestions(collected, query=query, limit=limit)) >= limit:
            break
        status, records = await fetch_page(query, page)
        kept = 0
        excluded = 0
        excluded_sample: list[str] = []
        for record in records or []:
            assignee = record.get("assignee") if isinstance(record, dict) else record
            parts = assignee if isinstance(assignee, list) else [assignee]
            for part in parts:
                cleaned = " ".join(str(part or "").split())
                if not cleaned:
                    excluded += 1
                    continue
                if suggestion_matches(cleaned, query):
                    collected.append(cleaned)
                    kept += 1
                else:
                    excluded += 1
                    if len(excluded_sample) < 5:
                        excluded_sample.append(cleaned)
        logger.info(
            "[ASSIGNEE SUGGEST] query=%r page=%d http=%s records=%d kept=%d excluded=%d excluded_sample=%s",
            query,
            page,
            status,
            len(records or []),
            kept,
            excluded,
            excluded_sample,
        )
        if not records:
            break
    names = merge_suggestions(collected, query=query, limit=limit)
    logger.info("[ASSIGNEE SUGGEST] query=%r suggestions=%d names=%s", query, len(names), names)
    return names


class AssigneeSuggestionService:
    def __init__(self, session: AsyncSession, remote_lookup=None):
        self.session = session
        self.remote_lookup = remote_lookup if remote_lookup is not None else serper_assignee_names

    async def suggest(self, query: str, limit: int = MAX_SUGGESTIONS) -> list[str]:
        cleaned = (query or "").strip()
        if len(cleaned) < 2:
            return []
        limit = max(1, min(limit, MAX_SUGGESTIONS))
        cached = _cache_get(cleaned)
        if cached is not None:
            return merge_suggestions(cached, query=cleaned, limit=limit)
        local = await self._from_extractions(cleaned, limit)
        if len(local) >= limit:
            _cache_put(cleaned, local)
            return local[:limit]
        remote: list[str] = []
        try:
            remote = await self.remote_lookup(cleaned)
        except Exception as exc:
            logger.warning("Assignee suggestion lookup failed: %s", type(exc).__name__)
        names = merge_suggestions(local, remote, query=cleaned, limit=limit)
        if remote or local:
            _cache_put(cleaned, names)
        return names

    async def _from_extractions(self, query: str, limit: int) -> list[str]:
        escaped = query.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        result = await self.session.execute(
            select(PatentExtraction.assignee)
            .where(PatentExtraction.assignee.is_not(None))
            .where(PatentExtraction.assignee.ilike(f"%{escaped}%", escape="\\"))
            .distinct()
            .limit(max(limit, MAX_SUGGESTIONS))
        )
        return merge_suggestions(
            [row for row in result.scalars().all() if row],
            query=query,
            limit=limit,
        )


async def _serper_page(query: str, page: int) -> tuple[int, list]:
    api_key = (settings.SERPER_API_KEY or "").strip()
    if not api_key:
        return 0, []
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    # Company name only. Serper's assignee: operator does not restrict the assignee field.
    payload = {"q": query, "page": page}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post("https://google.serper.dev/patents", headers=headers, json=payload)
    if response.status_code != 200:
        logger.warning("Assignee suggestion search returned HTTP %s", response.status_code)
        return response.status_code, []
    body = response.json()
    return response.status_code, body.get("patents") or body.get("organic") or []


async def serper_assignee_names(query: str) -> list[str]:
    """Bibliographic assignee names from a bounded number of Serper patent pages."""
    if not (settings.SERPER_API_KEY or "").strip():
        return []
    return await gather_assignee_suggestions(
        query,
        _serper_page,
        max_pages=settings.ASSIGNEE_SUGGESTION_MAX_PAGES,
        limit=MAX_SUGGESTIONS,
    )
