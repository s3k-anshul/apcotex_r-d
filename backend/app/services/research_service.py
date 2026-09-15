"""
app/services/research_service.py

Business logic for the Research Runs module.
Routes call service methods; service calls repository methods.
No SQLAlchemy, no HTTP, no response schemas here.
"""
import asyncio
import hashlib
import json
import logging
import math
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

# Module-level task registry to prevent garbage collection
_background_tasks = set()
# Global reference to prevent garbage collection
_active_task = None

from app.core.audit_actions import AuditAction, AuditEntityType
from app.models.research_run import ResearchRun, RunStatus
from app.models.user import User, UserRole
from app.repositories.research_repository import ResearchRepository
from app.schemas.research import (
    ResearchRunCreate,
    ResearchRunFilters,
    ResearchRunList,
    ResearchRunSummary,
)
from app.services.audit_service import AuditService
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.utils.exceptions import AppException, ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)


async def _heal_cancelled_run(run_id: uuid.UUID) -> None:
    """Best-effort: if a cancelled worker left a run in an active status, mark CANCELLED."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.future import select

    from app.db.database import engine

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await session.execute(select(ResearchRun).where(ResearchRun.id == run_id))
            run = result.scalar_one_or_none()
            if run and run.status in RunStatus.active_states():
                run.status = RunStatus.CANCELLED
                await session.commit()
                logger.warning(
                    "[RESEARCH REQUEST] Healed stuck run %s → CANCELLED after worker cancel",
                    run_id,
                )
    except Exception:
        logger.exception("[RESEARCH REQUEST] Failed to heal cancelled run %s", run_id)


class ResearchService:
    """Orchestrates all research-run business operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = ResearchRepository(session)
        self._audit_service = AuditService(session)

    # ── Cache key ─────────────────────────────────────────────────────────────

    @staticmethod
    def generate_cache_key(
        compound_name: str,
        selected_sources: list[str],
        publication_filter: dict | None,
        competitors: list[str],
        mentioned_websites: list[str],
        jurisdictions: list[str],
        attribute_constraint: str | None = None,
        polymerization_medium: str = "any",
    ) -> str:
        """
        Produce a deterministic 32-char hex cache key from the run's
        significant parameters.
        """
        medium = (polymerization_medium or "any").strip().lower()
        constraint = (attribute_constraint or "").strip().lower() or None
        canonical = {
            "compound": compound_name.strip().lower(),
            "sources": sorted(selected_sources) if selected_sources else [],
            "filter": publication_filter or {},
            "competitors": sorted([c.lower() for c in competitors]) if competitors else [],
            "websites": sorted([w.lower() for w in mentioned_websites]) if mentioned_websites else [],
            "jurisdictions": sorted([j.upper() for j in jurisdictions]) if jurisdictions else [],
            "attribute_constraint": constraint,
            "polymerization_medium": medium,
        }
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_run(
        self, data: ResearchRunCreate, current_user: User
    ) -> ResearchRun:
        """
        Create a new ResearchRun for the authenticated user.

        De-duplication: if a non-failed run with an identical cache key
        already exists for this user, return it instead of creating a new one.
        """
        logger.info("[RESEARCH REQUEST] ResearchService.create_run() started")
        try:
            medium_value = (
                data.polymerization_medium.value
                if hasattr(data.polymerization_medium, "value")
                else str(data.polymerization_medium or "any")
            )
            cache_key = self.generate_cache_key(
                data.compound_name,
                data.selected_sources,
                data.publication_filter,
                data.competitors,
                data.mentioned_websites,
                data.jurisdictions,
                attribute_constraint=data.attribute_constraint,
                polymerization_medium=medium_value,
            )
            logger.info("[RESEARCH REQUEST] Cache key generated: %s", cache_key)

            existing = await self._repo.get_by_cache_key(cache_key)
            # if existing and existing.created_by == current_user.id and existing.status == RunStatus.COMPLETED:
            #     logger.info(
            #         "Cache hit — returning completed run %s for user %s",
            #         existing.id,
            #         current_user.id,
            #     )
            #     return existing

            logger.info(
                "[RESEARCH REQUEST] Payload details - Compound: %s | Jurisdictions: %s | "
                "DateFilter: %s | Competitors: %s | Websites: %s | "
                "AttributeConstraint: %s | PolymerizationMedium: %s",
                data.compound_name,
                data.jurisdictions,
                data.publication_filter,
                data.competitors,
                data.mentioned_websites,
                data.attribute_constraint,
                medium_value,
            )

            logger.info("[RESEARCH REQUEST] Creating ResearchRun object")
            run = ResearchRun(
                compound_name=data.compound_name,
                competitors=data.competitors,
                mentioned_websites=data.mentioned_websites,
                publication_filter=data.publication_filter,
                selected_sources=data.selected_sources,
                jurisdictions=data.jurisdictions,
                attribute_constraint=data.attribute_constraint,
                polymerization_medium=medium_value,
                status=RunStatus.PENDING,
                cache_key=cache_key,
                report_version=1,
                created_by=current_user.id,
            )
            logger.info("[RESEARCH REQUEST] Calling repo.create()")
            run = await self._repo.create(run)
            logger.info("[RESEARCH REQUEST] ResearchRun created in DB: %s", run.id)
            # Commit the transaction so the background task can see the run in its own session
            await self._repo._session.commit()
            logger.info("[RESEARCH REQUEST] Transaction committed")

            # Log research creation
            await self._audit_service.log(
                user_id=str(current_user.id),
                action=AuditAction.RESEARCH_CREATED,
                entity_type=AuditEntityType.RESEARCH_RUN,
                entity_id=str(run.id),
                detail={
                    "compound": data.compound_name,
                    "competitors": data.competitors or [],
                    "websites": data.mentioned_websites or [],
                    "jurisdictions": data.publication_filter or {},
                },
            )

            # Spawn background pipeline
            logger.info("[RESEARCH REQUEST] Creating PipelineOrchestrator")
            orchestrator = PipelineOrchestrator(run.id)
            logger.info("[RESEARCH REQUEST] PipelineOrchestrator created")
            logger.info("[RESEARCH REQUEST] Starting pipeline execution")
            
            # Use asyncio.ensure_future to run the pipeline in the background
            # Keep a strong reference to prevent garbage collection
            global _active_task
            run_id_for_callback = run.id
            _active_task = asyncio.ensure_future(orchestrator.execute())
            logger.info("[RESEARCH REQUEST] Pipeline task created: %s", _active_task)
            
            # Add error handler for the background task
            def task_done_callback(t):
                try:
                    result = t.result()
                    if result == RunStatus.COMPLETED:
                        logger.info("[RESEARCH REQUEST] Pipeline task completed successfully")
                    else:
                        logger.error("[RESEARCH REQUEST] TASK EXECUTION COMPLETED - PIPELINE FAILED")
                except asyncio.CancelledError:
                    logger.warning(
                        "[RESEARCH REQUEST] Pipeline task was CANCELLED for run %s — "
                        "scheduling DB status heal",
                        run_id_for_callback,
                    )
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(
                            _heal_cancelled_run(run_id_for_callback)
                        )
                    except RuntimeError:
                        logger.error(
                            "[RESEARCH REQUEST] No running loop to heal cancelled run %s",
                            run_id_for_callback,
                        )
                except Exception as e:
                    logger.error("[RESEARCH REQUEST] Pipeline task failed: %s", e)
                finally:
                    # Clear global reference when done
                    global _active_task
                    if _active_task == t:
                        _active_task = None
            
            _active_task.add_done_callback(task_done_callback)

            return run
        except Exception as e:
            logger.error("[RESEARCH REQUEST FAILED] Stage: ResearchService.create_run() | Exception: %s | Message: %s", type(e).__name__, str(e))
            raise

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_runs(
        self, filters: ResearchRunFilters, current_user: User
    ) -> ResearchRunList:
        """
        Return a paginated list of runs.
        - ADMIN users can list all runs and filter by user_id.
        - SCIENTIST users only see their own runs (user_id filter is ignored).
        """
        enforce_user_id: uuid.UUID | None = None
        if current_user.role != UserRole.ADMIN:
            enforce_user_id = current_user.id

        runs, total = await self._repo.list_active(
            filters=filters, enforce_user_id=enforce_user_id
        )

        pages = max(1, math.ceil(total / filters.page_size))
        items = [ResearchRunSummary.model_validate(r) for r in runs]

        return ResearchRunList(
            items=items,
            total=total,
            page=filters.page,
            page_size=filters.page_size,
            pages=pages,
        )

    # ── Get single ────────────────────────────────────────────────────────────

    async def get_run(
        self, run_id: uuid.UUID, current_user: User
    ) -> ResearchRun:
        """
        Fetch a single non-deleted run.
        - ADMIN users can access any run.
        - SCIENTIST users can only access their own.
        """
        if current_user.role == UserRole.ADMIN:
            run = await self._repo.get_active_by_id(run_id)
        else:
            run = await self._repo.get_active_by_id_and_user(run_id, current_user.id)

        if run is None:
            raise NotFoundError(resource="ResearchRun")

        # Stale run detection using Heartbeat
        from datetime import datetime, timezone, timedelta
        from app.models.research_run import RunStatus
        from app.core.telemetry import ACTIVE_RUNS_HEARTBEAT
        
        # Inject heartbeat data if available
        hb = ACTIVE_RUNS_HEARTBEAT.get(str(run.id), {})
        run.stage = hb.get("stage")
        run.progress = hb.get("progress")
        run.error = hb.get("error")
        
        if run.status in RunStatus.active_states():
            last_hb = hb.get("last_heartbeat")
            # If no heartbeat within 10 minutes, or no heartbeat ever but updated_at is > 10 mins old
            # (uvicorn --reload can cancel mid-SEARCHING; do not leave runs stuck for 30+ minutes)
            stale_threshold = timedelta(minutes=10)
            now = datetime.now(timezone.utc)
            
            is_stale = False
            if last_hb and (now - last_hb) > stale_threshold:
                is_stale = True
            elif not last_hb and run.updated_at and (now - run.updated_at) > stale_threshold:
                is_stale = True
                
            if is_stale:
                logger.warning(f"Run {run.id} detected as stale (heartbeat missing for >10 mins). Marking as FAILED.")
                run.status = RunStatus.FAILED
                run.error = (
                    "Run timed out or background worker crashed/reloaded. "
                    "Previously active status was abandoned without a terminal update."
                )
                await self._repo._session.commit()

        return run

    # ── Delete (soft) ─────────────────────────────────────────────────────────

    async def delete_run(
        self, run_id: uuid.UUID, current_user: User
    ) -> None:
        """
        Soft-delete a run.
        - ADMIN users can delete any run.
        - SCIENTIST users can only delete their own.
        - Cannot delete a run that is actively processing.
        """
        run = await self.get_run(run_id, current_user)

        if run.is_active:
            raise AppException(
                status_code=409,
                code="RUN_IN_PROGRESS",
                message=(
                    f"Cannot delete a run with status '{run.status.value}'. "
                    "Cancel it first."
                ),
            )

        await self._repo.soft_delete(run)
        logger.info(
            "Soft-deleted ResearchRun %s by user %s", run_id, current_user.id
        )

    # ── Refresh ───────────────────────────────────────────────────────────────

    async def refresh_run(
        self, run_id: uuid.UUID, current_user: User
    ) -> ResearchRun:
        """
        Re-queue a completed / failed / cancelled run.

        Placeholder — Phase 2 will enqueue a background task.
        Currently just resets the status to PENDING and bumps report_version.
        Only terminal-state runs can be refreshed.
        """
        run = await self.get_run(run_id, current_user)

        if not run.is_terminal:
            raise AppException(
                status_code=409,
                code="RUN_NOT_TERMINAL",
                message=(
                    f"Can only refresh runs in a terminal state "
                    f"(COMPLETED, FAILED, CANCELLED). Current status: {run.status.value}."
                ),
            )

        run.status = RunStatus.PENDING
        run.report_version += 1
        run.cache_key = self.generate_cache_key(
            run.compound_name,
            run.selected_sources or [],
            run.publication_filter,
            run.competitors or [],
            run.mentioned_websites or [],
            run.jurisdictions or [],
            attribute_constraint=getattr(run, "attribute_constraint", None),
            polymerization_medium=getattr(run, "polymerization_medium", None) or "any",
        )

        run = await self._repo.update(run)
        logger.info(
            "Refreshed ResearchRun %s → v%s by user %s",
            run_id,
            run.report_version,
            current_user.id,
        )

        # Spawn background pipeline
        orchestrator = PipelineOrchestrator(run.id)
        asyncio.create_task(orchestrator.execute())

        return run
