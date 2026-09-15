"""
tests/test_pipeline_end_to_end_mocked.py

Phase 6: full PipelineOrchestrator.execute() with query expansion, search,
selection, extraction, and report generation all mocked (Phase 0 fixtures).
No real OpenAI / Serper / network calls.
"""
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.research_run import ResearchRun, RunStatus
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.pipeline.schemas import (
    LLMCompoundSearchProfile,
    ParsedPatent,
    PatentExtraction,
    PatentResearchReport,
    PatentSelectionResult,
    ReportPatent,
    ReportPatentDetails,
    ReportPatentMethodology,
)
from tests.fixtures import load_fixture


KEEP_NUMBERS = {"US8123456B2", "EP2473281B1", "WO2018123456A1"}
REJECT_NUMBERS = {
    "US9012345B1",
    "US7654321B2",
    "US8888777B2",
    "US7000111B1",
    "US5551234A",
    "US8200001B2",
    "US9444555B2",
}


def _serper_candidates() -> list[dict]:
    data = load_fixture("serper_patents_low_acn_nbr")
    out = []
    for p in data["patents"]:
        out.append(
            {
                "patent_number": p["publicationNumber"],
                "title": p["title"],
                "snippet": p.get("snippet") or "",
                "url": p["link"],
                "query_matched": "TI=(NBR AND polymerization)",
                "family_id": p["publicationNumber"],
                "publication_date": p.get("publicationDate") or "2015-01-01",
                "priority_date": p.get("priorityDate") or "",
                "filing_date": p.get("filingDate") or "",
                "grant_date": p.get("grantDate") or "",
                "inventor": p.get("inventor") or "",
                "assignee": p.get("assignee") or "",
                "pdf_url": p.get("pdfUrl") or "",
                "source": "serper_patents",
            }
        )
    return out


def _strategy() -> LLMCompoundSearchProfile:
    return LLMCompoundSearchProfile.model_validate(
        load_fixture("llm_query_expansion_low_acn_nbr")
    )


def _selection_result() -> PatentSelectionResult:
    return PatentSelectionResult.model_validate(
        load_fixture("llm_patent_selection_low_acn_nbr")
    )


def _selection_result_medium_any() -> PatentSelectionResult:
    """Same fixture but solvent patent is KEEP when medium is unconstrained."""
    data = load_fixture("llm_patent_selection_low_acn_nbr")
    for c in data["candidates"]:
        if c["patent_number"] == "US9012345B1":
            c["polymerization_medium_mismatch"] = False
            c["final_decision"] = "KEEP"
            c["reason"] = "Solvent synthesis allowed when medium constraint is any"
    return PatentSelectionResult.model_validate(data)


def _make_run(**kwargs) -> ResearchRun:
    defaults = dict(
        id=uuid.uuid4(),
        compound_name="Low Acrylonitrile NBR",
        competitors=[],
        mentioned_websites=[],
        publication_filter=None,
        selected_sources=["google_patents"],
        jurisdictions=["US", "EP", "WO"],
        attribute_constraint=None,
        polymerization_medium="any",
        status=RunStatus.PENDING,
        cache_key="e2e-mock",
        report_version=1,
        created_by=uuid.uuid4(),
    )
    defaults.update(kwargs)
    return ResearchRun(**defaults)


def _parsed(number: str, title: str) -> ParsedPatent:
    return ParsedPatent(
        patent_number=number,
        title=title,
        url=f"https://patents.google.com/patent/{number}",
        abstract=f"Abstract for {number}: emulsion polymerization of nitrile rubber.",
        claims="1. A process for preparing nitrile rubber comprising emulsion polymerization.",
        detailed_description="Detailed description of synthesis examples.",
        examples="Example 1: acrylonitrile and butadiene were copolymerized in aqueous emulsion.",
        assignee="Mock Assignee",
        jurisdiction=number[:2],
        publication_date="2015-01-01",
    )


def _extraction(number: str, title: str) -> PatentExtraction:
    ext = PatentExtraction()
    ext.metadata.patent_number = number
    ext.metadata.patent_title = title
    ext.metadata.assignee = "Mock Assignee"
    ext.metadata.jurisdiction = number[:2]
    ext.metadata.publication_year = "2015"
    ext.raw_text = f"Extraction body for {number}"
    return ext


class _FakeResult:
    def __init__(self, run):
        self._run = run

    def scalar_one_or_none(self):
        return self._run


class _FakeSession:
    def __init__(self, run: ResearchRun):
        self.run = run
        self.added = []

    async def execute(self, _stmt):
        return _FakeResult(self.run)

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            try:
                obj.id = uuid.uuid4()
            except Exception:
                pass
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                try:
                    obj.id = uuid.uuid4()
                except Exception:
                    pass

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def close(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.fixture
def tmp_export_dir(tmp_path: Path) -> Path:
    export = tmp_path / "exports"
    export.mkdir()
    return export


async def _run_mocked_pipeline(
    *,
    run: ResearchRun,
    selection: PatentSelectionResult,
    tmp_export_dir: Path,
    captured: dict,
) -> RunStatus:
    orch = PipelineOrchestrator(run_id=run.id)
    session = _FakeSession(run)

    async def fake_get_background_session():
        return session

    candidates = _serper_candidates()
    fetched_numbers: list[str] = []

    async def fake_fetch(url: str):
        number = url.rstrip("/").split("/")[-1]
        fetched_numbers.append(number)
        title = next(
            (c["title"] for c in candidates if c["patent_number"] == number),
            number,
        )
        return _parsed(number, title)

    async def fake_extract(parsed_patent, url: str = "", profile=None):
        return _extraction(parsed_patent.patent_number, parsed_patent.title)

    async def fake_generate_report(compound_name, extractions, **kwargs):
        patents = []
        refs = []
        for ev in extractions:
            pn = ev.patent_number
            refs.append(pn)
            patents.append(
                ReportPatent(
                    patent_details=ReportPatentDetails(
                        patent_number=pn,
                        patent_title=ev.title or pn,
                        relevance_tier="PRIMARY",
                    ),
                    polymerization_method=ReportPatentMethodology(
                        dynamic_parameters=[
                            "Synthesis method: mocked emulsion polymerization"
                        ]
                    ),
                    experimental_evidence=["Example 1: mocked experimental evidence"],
                    technical_relevance="Relevant to target synthesis research",
                )
            )
        report = PatentResearchReport(
            title=f"Patent Research Report: {compound_name}",
            abstract="Mocked e2e abstract summarizing selected synthesis patents.",
            methodology_patents=patents,
            cross_patent_comparison=[
                "Selected patents disclose synthesis-relevant emulsion routes."
            ],
            conclusion="Mocked e2e conclusion.",
            references=refs,
        )
        return report, {"input_tokens": 100, "output_tokens": 50}

    orch.search_service.generate_strategy = AsyncMock(return_value=_strategy())
    orch.search_service.search_patents = AsyncMock(return_value=candidates)
    orch.fetcher_service.fetch_patent = AsyncMock(side_effect=fake_fetch)
    orch.fetcher_service.fetch_selection_evidence = AsyncMock(
        side_effect=lambda url, **kwargs: {
            "url": url,
            "patent_number": url.rstrip("/").split("/")[-1],
            "title": "",
            "abstract": "Mock abstract for selection enrichment.",
            "claims_excerpt": "1. A process for preparing the target polymer.",
            "assignee": "",
            "publication_date": "2015-01-01",
            "jurisdiction": "",
            "legal_status": "",
            "cpc_ipc": [],
            "evidence_sources": ["title", "abstract", "claims"],
        }
    )
    orch.extractor_service.extract_polymerization_data = AsyncMock(
        side_effect=fake_extract
    )
    orch.extractor_service.validate_extraction = MagicMock(return_value=True)
    orch.report_service.export_dir = str(tmp_export_dir)
    orch.report_service.generate_structured_report = AsyncMock(
        side_effect=fake_generate_report
    )
    orch.report_service.export_to_pdf = AsyncMock(
        return_value=str(tmp_export_dir / "report.pdf")
    )
    orch.report_service.export_to_docx = AsyncMock(
        return_value=str(tmp_export_dir / "report.docx")
    )
    orch._update_status = AsyncMock()
    orch._mark_failed = AsyncMock()

    import app.services.pipeline.orchestrator as orch_mod

    original_sleep = orch_mod.asyncio.sleep
    orch_mod.asyncio.sleep = AsyncMock(return_value=None)

    try:
        with patch(
            "app.services.pipeline.orchestrator.get_background_session",
            new=fake_get_background_session,
        ), patch(
            "app.services.pipeline.orchestrator.llm_client.generate_structured",
            new=AsyncMock(return_value=(selection, "mock", {})),
        ):
            status = await orch.execute()
    finally:
        orch_mod.asyncio.sleep = original_sleep

    report_call = orch.report_service.generate_structured_report.await_args
    evidence_list = report_call.kwargs.get("extractions")
    if evidence_list is None and report_call.args:
        # positional: (compound_name, extractions, ...)
        evidence_list = report_call.args[1] if len(report_call.args) > 1 else []
    evidence_list = evidence_list or []

    captured["fetched_numbers"] = fetched_numbers
    captured["report_patent_numbers"] = {e.patent_number for e in evidence_list}
    captured["strategy_call_kwargs"] = (
        orch.search_service.generate_strategy.await_args.kwargs
    )
    captured["filter_stats"] = dict(orch._filter_stats)
    captured["run_status_updates"] = [
        call.args[2] for call in orch._update_status.await_args_list
    ]
    return status


@pytest.mark.asyncio
async def test_e2e_mocked_aqueous_constraints_selects_expected_patents(
    tmp_export_dir,
):
    """
    Full pipeline with attribute_constraint + polymerization_medium=aqueous:
    keeps emulsion NBR patents; rejects solvent, HNBR, downstream, unrelated.
    """
    run = _make_run(
        attribute_constraint="acrylonitrile content 15-20 wt%",
        polymerization_medium="aqueous",
    )
    captured: dict = {}
    status = await _run_mocked_pipeline(
        run=run,
        selection=_selection_result(),
        tmp_export_dir=tmp_export_dir,
        captured=captured,
    )

    assert status == RunStatus.COMPLETED
    assert captured["strategy_call_kwargs"]["attribute_constraint"] == (
        "acrylonitrile content 15-20 wt%"
    )
    assert captured["strategy_call_kwargs"]["polymerization_medium"] == "aqueous"

    assert set(captured["fetched_numbers"]) == KEEP_NUMBERS
    assert REJECT_NUMBERS.isdisjoint(set(captured["fetched_numbers"]))
    assert captured["report_patent_numbers"] == KEEP_NUMBERS

    assert captured["filter_stats"]["selection_keep"] == 3
    assert captured["filter_stats"]["selection_reject_variant"] >= 1
    assert captured["filter_stats"]["selection_reject_downstream"] >= 1
    assert captured["filter_stats"]["selection_reject_medium"] >= 1
    assert RunStatus.COMPLETED in captured["run_status_updates"]

    md_files = list(tmp_export_dir.glob("*.md"))
    assert md_files, "markdown report should be written"
    md_text = md_files[0].read_text(encoding="utf-8")
    assert "LOW ACRYLONITRILE NBR" in md_text.upper()
    assert "US8123456B2" in md_text
    assert "EP2473281B1" in md_text
    assert "WO2018123456A1" in md_text


@pytest.mark.asyncio
async def test_e2e_mocked_unconstrained_medium_can_keep_solvent_patent(
    tmp_export_dir,
):
    """
    When polymerization_medium is any, the same solvent title can KEEP
    (selection fixture adjusted) — proves medium check is constraint-gated.
    """
    run = _make_run(polymerization_medium="any")
    captured: dict = {}
    status = await _run_mocked_pipeline(
        run=run,
        selection=_selection_result_medium_any(),
        tmp_export_dir=tmp_export_dir,
        captured=captured,
    )

    assert status == RunStatus.COMPLETED
    assert "US9012345B1" in captured["fetched_numbers"]
    assert "US9012345B1" in captured["report_patent_numbers"]
    assert "US7654321B2" not in captured["fetched_numbers"]
    assert "US8888777B2" not in captured["fetched_numbers"]
    assert captured["filter_stats"]["selection_reject_medium"] == 0
    assert KEEP_NUMBERS.issubset(set(captured["fetched_numbers"]))
