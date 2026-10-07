"""
app/repositories/research_repository.py

Data-access layer for the research_runs table.
All DB queries are isolated here — the service layer calls
these methods and never touches SQLAlchemy directly.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.research_run import ResearchRun, RunStatus
from app.schemas.research import ResearchRunFilters


class ResearchRepository:
    """Async repository for ResearchRun CRUD and filtered queries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Base query helpers ────────────────────────────────────────────────────

    def _active_q(self):
        """Base SELECT that filters out soft-deleted rows."""
        return select(ResearchRun).where(ResearchRun.deleted_at.is_(None))

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(self, run: ResearchRun) -> ResearchRun:
        """Persist a new ResearchRun. Flush so DB assigns id and timestamps."""
        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)
        return run

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_id(self, run_id: uuid.UUID) -> ResearchRun | None:
        """Fetch any run by ID, including soft-deleted records."""
        result = await self._session.execute(
            select(ResearchRun).where(ResearchRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_active_by_id(self, run_id: uuid.UUID) -> ResearchRun | None:
        """Fetch a non-deleted run by ID."""
        result = await self._session.execute(
            self._active_q().where(ResearchRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_active_by_id_and_user(
        self, run_id: uuid.UUID, user_id: uuid.UUID
    ) -> ResearchRun | None:
        """Fetch a non-deleted run that belongs to a specific user."""
        result = await self._session.execute(
            self._active_q()
            .where(ResearchRun.id == run_id)
            .where(ResearchRun.created_by == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_cache_key(self, cache_key: str) -> ResearchRun | None:
        """
        Find the most recent active, non-failed run with a matching cache key.
        Used by create_run() to detect duplicate requests.
        """
        result = await self._session.execute(
            self._active_q()
            .where(ResearchRun.cache_key == cache_key)
            .where(ResearchRun.status.notin_([RunStatus.FAILED, RunStatus.CANCELLED]))
            .order_by(ResearchRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_active(
        self,
        filters: ResearchRunFilters,
        enforce_user_id: uuid.UUID | None = None,
    ) -> tuple[list[ResearchRun], int]:
        """
        Return a paginated list of active runs and the total count.

        Args:
            filters:          Query filter & pagination parameters.
            enforce_user_id:  When set, restricts results to this user
                              (used for non-admin callers).
        """
        base = self._active_q()

        # ── Apply filters ─────────────────────────────────────────────────────
        if enforce_user_id is not None:
            base = base.where(ResearchRun.created_by == enforce_user_id)
        elif filters.user_id is not None:
            base = base.where(ResearchRun.created_by == filters.user_id)

        if filters.compound:
            base = base.where(
                ResearchRun.compound_name.ilike(f"%{filters.compound}%")
            )

        if filters.status is not None:
            base = base.where(ResearchRun.status == filters.status)

        if filters.date_from is not None:
            base = base.where(ResearchRun.created_at >= filters.date_from)

        if filters.date_to is not None:
            base = base.where(ResearchRun.created_at <= filters.date_to)

        # ── Count total matching rows ──────────────────────────────────────────
        count_q = select(func.count()).select_from(base.subquery())
        total: int = (await self._session.execute(count_q)).scalar_one()

        # ── Fetch page ────────────────────────────────────────────────────────
        offset = (filters.page - 1) * filters.page_size
        rows_q = (
            base.options(selectinload(ResearchRun.creator))
            .order_by(ResearchRun.created_at.desc())
            .offset(offset)
            .limit(filters.page_size)
        )
        rows = (await self._session.execute(rows_q)).scalars().unique().all()

        return list(rows), total

    # ── Update ────────────────────────────────────────────────────────────────

    async def update(self, run: ResearchRun) -> ResearchRun:
        """Flush pending in-memory changes and refresh the instance."""
        await self._session.flush()
        await self._session.refresh(run)
        return run

    # ── Soft delete ───────────────────────────────────────────────────────────

    async def soft_delete(self, run: ResearchRun) -> ResearchRun:
        """Mark a run as deleted without removing the row from the DB."""
        run.deleted_at = datetime.now(timezone.utc)
        return await self.update(run)
