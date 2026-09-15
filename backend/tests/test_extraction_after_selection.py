"""
tests/test_extraction_after_selection.py

Phase 4: full-text fetch runs ONLY for patents in selected_candidates.
No real network — fetcher and extractor are mocked.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.pipeline.schemas import CompoundSearchProfile, ParsedPatent, PatentExtraction


def _candidate(number: str, title: str) -> dict:
    return {
        "patent_number": number,
        "title": title,
        "snippet": "test snippet",
        "url": f"https://patents.google.com/patent/{number}",
    }


def _parsed(number: str, title: str) -> ParsedPatent:
    return ParsedPatent(
        patent_number=number,
        title=title,
        url=f"https://patents.google.com/patent/{number}",
        abstract="Example abstract for extraction.",
        claims="1. A process for preparing nitrile rubber.",
    )


def _extraction(number: str, title: str) -> PatentExtraction:
    ext = PatentExtraction()
    ext.metadata.patent_number = number
    ext.metadata.patent_title = title
    return ext


@pytest.mark.asyncio
async def test_fetch_called_only_for_selected_patent_numbers():
    orch = PipelineOrchestrator(run_id=uuid.uuid4())
    orch._reset_filter_stats()

    selected = [
        _candidate("US8123456B2", "Emulsion polymerization of NBR"),
        _candidate("EP2473281B1", "Aqueous copolymerization of acrylonitrile-butadiene"),
    ]
    # Rejected / never-selected patents must NOT be fetched
    rejected_numbers = {"US8888777B2", "US7654321B2", "US9012345B1"}

    fetched_urls: list[str] = []

    async def fake_fetch(url: str):
        fetched_urls.append(url)
        # Derive patent number from URL path
        number = url.rstrip("/").split("/")[-1]
        assert number not in rejected_numbers
        return _parsed(number, f"Title for {number}")

    async def fake_extract(parsed_patent, url: str = "", profile=None):
        return _extraction(parsed_patent.patent_number, parsed_patent.title)

    orch.fetcher_service.fetch_patent = AsyncMock(side_effect=fake_fetch)
    orch.extractor_service.extract_polymerization_data = AsyncMock(side_effect=fake_extract)
    orch.extractor_service.validate_extraction = MagicMock(return_value=True)

    # Avoid real sleep between fetches
    import app.services.pipeline.orchestrator as orch_mod

    original_sleep = orch_mod.asyncio.sleep
    orch_mod.asyncio.sleep = AsyncMock(return_value=None)
    try:
        extractions, parsed_map = await orch._fetch_and_extract_selected(
            selected, CompoundSearchProfile(original_input="NBR")
        )
    finally:
        orch_mod.asyncio.sleep = original_sleep

    assert orch.fetcher_service.fetch_patent.await_count == 2
    fetched_numbers = {u.rstrip("/").split("/")[-1] for u in fetched_urls}
    assert fetched_numbers == {"US8123456B2", "EP2473281B1"}
    assert rejected_numbers.isdisjoint(fetched_numbers)

    assert set(parsed_map.keys()) == {"US8123456B2", "EP2473281B1"}
    assert {e.metadata.patent_number for e in extractions} == {
        "US8123456B2",
        "EP2473281B1",
    }
    assert orch._filter_stats["reached_fetch"] == 2
    assert orch._filter_stats["fetch_failures"] == 0


@pytest.mark.asyncio
async def test_fetch_failure_skips_extraction_for_that_patent():
    orch = PipelineOrchestrator(run_id=uuid.uuid4())
    orch._reset_filter_stats()

    selected = [
        _candidate("US8123456B2", "Good patent"),
        _candidate("US0000000A", "Will fail fetch"),
    ]

    async def fake_fetch(url: str):
        number = url.rstrip("/").split("/")[-1]
        if number == "US0000000A":
            return None
        return _parsed(number, "Good patent")

    async def fake_extract(parsed_patent, url: str = "", profile=None):
        return _extraction(parsed_patent.patent_number, parsed_patent.title)

    orch.fetcher_service.fetch_patent = AsyncMock(side_effect=fake_fetch)
    orch.extractor_service.extract_polymerization_data = AsyncMock(side_effect=fake_extract)
    orch.extractor_service.validate_extraction = MagicMock(return_value=True)

    import app.services.pipeline.orchestrator as orch_mod

    original_sleep = orch_mod.asyncio.sleep
    orch_mod.asyncio.sleep = AsyncMock(return_value=None)
    try:
        extractions, parsed_map = await orch._fetch_and_extract_selected(
            selected, CompoundSearchProfile(original_input="NBR")
        )
    finally:
        orch_mod.asyncio.sleep = original_sleep

    assert orch.fetcher_service.fetch_patent.await_count == 2
    assert orch.extractor_service.extract_polymerization_data.await_count == 1
    assert list(parsed_map.keys()) == ["US8123456B2"]
    assert len(extractions) == 1
    assert orch._filter_stats["fetch_failures"] == 1
