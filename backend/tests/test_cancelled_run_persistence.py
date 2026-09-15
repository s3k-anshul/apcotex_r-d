"""Regression: cancelled/reloaded workers must not leave runs stuck in SEARCHING."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.research_run import ResearchRun, RunStatus
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.research_service import ResearchService


@pytest.mark.asyncio
async def test_orchestrator_cancelled_error_persists_cancelled_status():
    orch = PipelineOrchestrator(run_id=uuid.uuid4())
    run = MagicMock()
    run.id = orch.run_id
    run.status = RunStatus.SEARCHING
    run.compound_name = "Example Polymer X"
    run.jurisdictions = ["US"]
    run.publication_filter = None
    run.competitors = []
    run.mentioned_websites = []

    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = run
    session.execute = AsyncMock(return_value=result)

    async def _raise_cancel(*_a, **_k):
        raise asyncio.CancelledError()

    with patch(
        "app.services.pipeline.orchestrator.get_background_session",
        new=AsyncMock(return_value=session),
    ), patch.object(
        orch, "_update_status", new=AsyncMock()
    ) as update_status, patch.object(
        orch.search_service,
        "generate_strategy",
        new=AsyncMock(side_effect=_raise_cancel),
    ), patch(
        "app.services.pipeline.orchestrator.set_current_run_id"
    ), patch(
        "app.services.pipeline.orchestrator.set_current_stage"
    ):
        # AsyncSession context manager support
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(asyncio.CancelledError):
            await orch.execute()

    update_status.assert_awaited()
    assert update_status.await_args.args[2] == RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_get_run_marks_stale_active_run_failed_after_10_minutes():
    svc = ResearchService(session=AsyncMock())
    run = MagicMock(spec=ResearchRun)
    run.id = uuid.uuid4()
    run.status = RunStatus.SEARCHING
    run.is_terminal = False
    run.updated_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    run.created_by = uuid.uuid4()

    user = MagicMock()
    user.role = MagicMock()
    user.role.__eq__ = lambda self, other: False
    user.id = run.created_by

    # Bypass role enum comparison issues
    from app.models.user import UserRole

    user.role = UserRole.ADMIN

    svc._repo.get_active_by_id = AsyncMock(return_value=run)
    svc._repo._session = AsyncMock()
    svc._repo._session.commit = AsyncMock()

    with patch("app.core.telemetry.ACTIVE_RUNS_HEARTBEAT", {}):
        out = await svc.get_run(run.id, user)

    assert out.status == RunStatus.FAILED
    assert "background worker" in (out.error or "").lower() or "timed out" in (out.error or "").lower()
    svc._repo._session.commit.assert_awaited()
