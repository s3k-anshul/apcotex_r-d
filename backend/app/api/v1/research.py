"""
app/api/v1/research.py

Research Run API endpoints.
All routes are thin — they parse inputs, call the service, and return responses.
Zero business logic lives here.

Routes:
  POST   /api/v1/research-runs               → create a new run
  GET    /api/v1/research-runs               → paginated list with filters
  GET    /api/v1/research-runs/{run_id}      → single run detail
  DELETE /api/v1/research-runs/{run_id}      → soft delete
  POST   /api/v1/research-runs/{run_id}/refresh → re-queue (placeholder)
  GET    /api/v1/research-runs/{run_id}/report  → get report content
  GET    /api/v1/research-runs/{run_id}/download → download report file
"""
import json
import logging
import os
import uuid
import markdown
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.utils.exceptions import AppException, NotFoundError
from app.models.report_file import ReportFile
from app.models.report_metadata import ReportMetadata
from app.models.research_run import RunStatus
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.research import (
    ResearchRunCreate,
    ResearchRunFilters,
    ResearchRunList,
    ResearchRunResponse,
)
from app.services.research_service import ResearchService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/research-runs", tags=["Research Runs"])


# ── Helper: parse filter query params ─────────────────────────────────────────

def _parse_filters(
    page: int = Query(default=1, ge=1, description="Page number (1-based)."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
    compound: str | None = Query(default=None, description="Substring match on compound name."),
    status: RunStatus | None = Query(default=None, description="Filter by run status."),
    date_from: str | None = Query(default=None, description="ISO-8601 lower bound on created_at."),
    date_to: str | None = Query(default=None, description="ISO-8601 upper bound on created_at."),
    user_id: uuid.UUID | None = Query(default=None, description="Admin only: filter by user UUID."),
) -> ResearchRunFilters:
    from datetime import datetime, timezone

    def _parse_dt(s: str | None):
        if s is None:
            return None
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    return ResearchRunFilters(
        page=page,
        page_size=page_size,
        compound=compound,
        status=status,
        date_from=_parse_dt(date_from),
        date_to=_parse_dt(date_to),
        user_id=user_id,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=SuccessResponse[ResearchRunResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a research run",
    description=(
        "Create a new patent-research run for the given compound. "
        "If an identical non-failed run already exists for this user "
        "(matched by cache key), the existing run is returned instead."
    ),
)
async def create_research_run(
    body: ResearchRunCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[ResearchRunResponse]:
    logger.info("[RESEARCH REQUEST] Request received")
    try:
        svc = ResearchService(session)
        logger.info("[RESEARCH REQUEST] Request validation successful")
        logger.info("[RESEARCH REQUEST] Calling ResearchService.create_run()")
        import sys
        from app.services.pipeline import search_service
        logger.info("SEARCH SERVICE PATH: %s", search_service.__file__)
        
        # 2. Create the run via the service.create_run(body, current_user)
        run = await svc.create_run(body, current_user)
        logger.info("[RESEARCH REQUEST] ResearchRun created: %s", run.id)
        return SuccessResponse(data=ResearchRunResponse.model_validate(run))
    except Exception as e:
        logger.error("[RESEARCH REQUEST FAILED] Stage: API endpoint | Exception: %s | Message: %s", type(e).__name__, str(e))
        raise


@router.get(
    "",
    response_model=SuccessResponse[ResearchRunList],
    summary="List research runs",
    description=(
        "Return a paginated list of research runs. "
        "Admins see all runs; scientists see only their own. "
        "Supports filtering by compound name, status, date range, and user (admin only)."
    ),
)
async def list_research_runs(
    filters: ResearchRunFilters = Depends(_parse_filters),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[ResearchRunList]:
    svc = ResearchService(session)
    result = await svc.list_runs(filters, current_user)
    return SuccessResponse(data=result)


@router.get(
    "/assignees",
    summary="Suggest assignee names",
    description="Partial-name suggestions from stored patent assignees and patent search records.",
)
async def suggest_assignees(
    q: str = Query(min_length=2, max_length=80),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.pipeline.assignee_suggestions import AssigneeSuggestionService

    names = await AssigneeSuggestionService(session).suggest(q)
    return SuccessResponse(data={"suggestions": names})


@router.get(
    "/{run_id}",
    response_model=SuccessResponse[ResearchRunResponse],
    summary="Get a research run",
    description=(
        "Return the full detail of a single research run. "
        "Admins can access any run; scientists only their own."
    ),
)
async def get_research_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[ResearchRunResponse]:
    svc = ResearchService(session)
    run = await svc.get_run(run_id, current_user)
    return SuccessResponse(data=ResearchRunResponse.model_validate(run))


@router.delete(
    "/{run_id}",
    response_model=SuccessResponse[dict],
    summary="Delete a research run",
    description=(
        "Soft-delete a research run (sets deleted_at). "
        "Cannot delete a run that is actively processing. "
        "Admins can delete any run; scientists only their own."
    ),
)
async def delete_research_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[dict]:
    svc = ResearchService(session)
    await svc.delete_run(run_id, current_user)
    return SuccessResponse(data={"deleted": True, "id": str(run_id)})


@router.post(
    "/{run_id}/refresh",
    response_model=SuccessResponse[ResearchRunResponse],
    summary="Refresh a research run",
    description=(
        "Re-queue a completed, failed, or cancelled run. "
        "Increments report_version and resets status to PENDING. "
        "Phase 2 will enqueue an actual background processing task."
    ),
)
async def refresh_research_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[ResearchRunResponse]:
    service = ResearchService(session)
    run = await service.refresh_run(run_id, current_user)
    return SuccessResponse(data=ResearchRunResponse.model_validate(run))


@router.get(
    "/{run_id}/report",
    summary="Get the HTML/Markdown report and extracted JSON data",
    description="Returns the raw HTML/Markdown report text for frontend rendering, plus extracted JSON data.",
)
async def get_report_content(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Ensure user has access
    service = ResearchService(session)
    run = await service.get_run(run_id, current_user)
    
    if run.status not in (RunStatus.COMPLETED, RunStatus.COMPLETED_PARTIAL):
        raise AppException(400, "REPORT_NOT_READY", "The report is not ready yet.")
        
    # Get the latest report metadata
    result = await session.execute(
        select(ReportMetadata).where(ReportMetadata.research_run_id == run_id).order_by(ReportMetadata.version.desc())
    )
    meta = result.scalars().first()
    if not meta:
        raise NotFoundError("ReportMetadata")
        
    # Find the markdown and json files
    file_res = await session.execute(
        select(ReportFile).where(ReportFile.report_metadata_id == meta.id)
    )
    files = file_res.scalars().all()
    
    markdown_text = ""
    json_data = []
    
    for f in files:
        if f.file_name.endswith(".md") and os.path.exists(f.file_path):
            with open(f.file_path, "r", encoding="utf-8") as file:
                markdown_text = file.read()
        elif f.file_type.value == "JSON" and os.path.exists(f.file_path):
            with open(f.file_path, "r", encoding="utf-8") as file:
                try:
                    json_data = json.load(file)
                except:
                    pass
                    
    html_text = markdown.markdown(markdown_text, extensions=["tables"])
    structured_report = meta.structured_data if meta.structured_data else {}
    
    return SuccessResponse(data={"html": html_text, "markdown": markdown_text, "extractions": json_data, "structuredReport": structured_report})


@router.get(
    "/{run_id}/download",
    summary="Download the generated report",
    description="Download the report as a PDF or DOCX file.",
)
async def download_report(
    run_id: uuid.UUID,
    format: str = Query("pdf", description="Format to download (pdf or docx)"),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Ensure user has access
    service = ResearchService(session)
    run = await service.get_run(run_id, current_user)
    
    if run.status not in (RunStatus.COMPLETED, RunStatus.COMPLETED_PARTIAL):
        raise AppException(400, "REPORT_NOT_READY", "The report is not ready yet.")
        
    result = await session.execute(
        select(ReportMetadata).where(ReportMetadata.research_run_id == run_id).order_by(ReportMetadata.version.desc())
    )
    meta = result.scalars().first()
    if not meta:
        raise NotFoundError("ReportMetadata")
        
    file_res = await session.execute(
        select(ReportFile).where(ReportFile.report_metadata_id == meta.id)
    )
    files = file_res.scalars().all()
    
    target_ext = f".{format.lower()}"
    target_file = next((f for f in files if f.file_name.endswith(target_ext)), None)
    
    if not target_file or not os.path.exists(target_file.file_path):
        raise NotFoundError("ReportFile")
        
    return FileResponse(
        target_file.file_path, 
        filename=target_file.file_name,
        media_type="application/pdf" if format.lower() == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
