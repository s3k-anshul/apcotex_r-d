"""
tests/test_saved_recipes.py

Saved recipe lifecycle: persistence, revisions, retention cleanup,
and feedback linkage without destroying historical feedback.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import HTTPException

from app.models.saved_recipe import SavedRecipe, SavedRecipeKind, SavedRecipeStatus
from app.models.user import User, UserRole
from app.schemas.recipe import SavedRecipeCreate, SavedRecipeUpdate, CustomerTrialCreate
from app.services.saved_recipe_service import (
    SavedRecipeService,
    RETENTION_MONTHS,
    add_calendar_months,
    to_saved_recipe_response,
)


def _user(role=UserRole.SCIENTIST) -> User:
    u = User(
        id=uuid.uuid4(),
        username="scientist1",
        email="s@test.com",
        full_name="Anshul",
        role=role,
        is_active=True,
        hashed_password="x",
    )
    return u


def _make_saved(**kwargs) -> SavedRecipe:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        recipe_name="Low ACN NBR Trial Recipe 01",
        recipe_data={"water": "120 parts", "temperature": "10°C"},
        target_properties=[{"feature": "BACN", "min": "18", "max": "22"}],
        competitor_properties=[],
        created_by=uuid.uuid4(),
        updated_by=None,
        created_at=now,
        updated_at=now,
        expires_at=add_calendar_months(now, RETENTION_MONTHS),
        parent_recipe_id=None,
        revision_number=0,
        status=SavedRecipeStatus.ACTIVE,
        source_cycle_id=None,
        source_candidate_id=None,
        source_trial_id=None,
        source_optimized_id=None,
        notes=None,
    )
    defaults.update(kwargs)
    r = SavedRecipe(**{k: v for k, v in defaults.items() if k not in ("created_at", "updated_at")})
    # TimestampMixin fields set after
    r.created_at = defaults["created_at"]
    r.updated_at = defaults["updated_at"]
    return r


def test_to_saved_recipe_response_marks_revision():
    parent = _make_saved(recipe_name="Parent")
    child = _make_saved(
        recipe_name="Parent - Revision 1",
        parent_recipe_id=parent.id,
        revision_number=1,
    )
    child.parent = parent
    resp = to_saved_recipe_response(child, parent=parent)
    assert resp.is_revision is True
    assert resp.parent_recipe_name == "Parent"
    assert resp.revision_number == 1


def test_retention_is_six_calendar_months():
    assert RETENTION_MONTHS == 6
    # 22 Sep 2026 → 22 Mar 2027
    start = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    assert add_calendar_months(start, 6) == datetime(
        2027, 3, 22, 12, 0, tzinfo=timezone.utc
    )
    # 15 Nov 2026 → 15 May 2027
    start2 = datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)
    assert add_calendar_months(start2, 6) == datetime(
        2027, 5, 15, 8, 0, tzinfo=timezone.utc
    )
    # Day clamp: 31 Aug → 28/29 Feb
    start3 = datetime(2025, 8, 31, tzinfo=timezone.utc)
    assert add_calendar_months(start3, 6) == datetime(
        2026, 2, 28, tzinfo=timezone.utc
    )


@pytest.mark.asyncio
async def test_save_recipe_sets_expiry_and_creator():
    user = _user()
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    saved = _make_saved(created_by=user.id, updated_by=user.id)
    saved.creator = user

    svc = SavedRecipeService(session)

    async def fake_get(recipe_id, current_user):
        return saved

    svc.get_recipe = fake_get  # type: ignore
    svc._next_revision_number = AsyncMock(return_value=1)  # type: ignore

    # Intercept add to capture object
    captured = {}

    def capture_add(obj):
        if isinstance(obj, SavedRecipe):
            captured["recipe"] = obj
            obj.id = saved.id
            obj.creator = user
            obj.parent = None

    session.add = capture_add
    session.get = AsyncMock(return_value=None)

    data = SavedRecipeCreate(
        recipe_name="Custom Name",
        recipe_data={"water": "120 parts"},
        target_properties=[],
        competitor_properties=[],
    )

    # Patch get_recipe after commit to return captured with relationships
    async def get_after(recipe_id, current_user):
        r = captured["recipe"]
        r.creator = user
        r.updater = user
        r.parent = None
        r.created_at = datetime.now(timezone.utc)
        r.updated_at = r.created_at
        return r

    svc.get_recipe = get_after  # type: ignore

    result = await svc.save_recipe(data, user)
    assert captured["recipe"].recipe_name == "Custom Name"
    assert captured["recipe"].recipe_data["water"] == "120 parts"
    assert captured["recipe"].created_by == user.id
    assert captured["recipe"].revision_number == 0
    assert captured["recipe"].expires_at > datetime.now(timezone.utc)
    assert result.recipe_data["water"] == "120 parts"


@pytest.mark.asyncio
async def test_save_revision_increments_revision_number():
    user = _user()
    parent = _make_saved(created_by=user.id)
    trial_id = uuid.uuid4()
    source_trial = MagicMock()
    source_trial.created_by = user.id
    source_trial.saved_recipe_id = parent.id
    session = AsyncMock()
    session.commit = AsyncMock()

    async def _get(model, pk):
        from app.models.customer_trial import CustomerTrial
        if model is CustomerTrial:
            return source_trial
        return parent

    session.get = _get

    captured = {}

    def capture_add(obj):
        if isinstance(obj, SavedRecipe):
            captured["recipe"] = obj
            obj.id = uuid.uuid4()
            obj.creator = user
            obj.parent = parent
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = obj.created_at

    session.add = capture_add

    svc = SavedRecipeService(session)
    svc._next_revision_number = AsyncMock(return_value=2)  # type: ignore

    async def get_after(recipe_id, current_user):
        return captured["recipe"]

    svc.get_recipe = get_after  # type: ignore

    data = SavedRecipeCreate(
        recipe_name="Rev 2 Custom",
        recipe_data={"water": "130"},
        parent_recipe_id=parent.id,
        source_trial_id=uuid.uuid4(),
    )
    result = await svc.save_recipe(data, user)
    assert captured["recipe"].parent_recipe_id == parent.id
    assert captured["recipe"].revision_number == 2
    assert captured["recipe"].source_trial_id is not None
    assert result.recipe_name == "Rev 2 Custom"


@pytest.mark.asyncio
async def test_update_persists_edited_recipe_data():
    user = _user()
    recipe = _make_saved(created_by=user.id, recipe_data={"water": "100"})
    recipe.creator = user
    session = AsyncMock()
    session.commit = AsyncMock()

    svc = SavedRecipeService(session)
    svc.get_recipe = AsyncMock(return_value=recipe)  # type: ignore

    updated = await svc.update_recipe(
        recipe.id,
        SavedRecipeUpdate(recipe_data={"water": "120 parts"}, recipe_name="Edited Name"),
        user,
    )
    assert recipe.recipe_data["water"] == "120 parts"
    assert recipe.recipe_name == "Edited Name"
    assert recipe.updated_by == user.id
    assert updated.recipe_data["water"] == "120 parts"


@pytest.mark.asyncio
async def test_delete_expired_recipes_removes_only_expired():
    user = _user()
    now = datetime.now(timezone.utc)
    expired = _make_saved(
        created_by=user.id,
        expires_at=now - timedelta(days=1),
        recipe_name="Expired",
    )
    active = _make_saved(
        created_by=user.id,
        expires_at=now + timedelta(days=30),
        recipe_name="Active",
    )

    session = AsyncMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()

    # Mock execute to return expired only (query filters)
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [expired]
    session.execute = AsyncMock(return_value=result_mock)

    svc = SavedRecipeService(session)
    count = await svc.delete_expired_recipes()
    assert count == 1
    session.delete.assert_awaited_once_with(expired)
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_create_trial_from_saved_recipe_keeps_snapshot():
    """Feedback stores recipe snapshot and authenticated user."""
    from app.services.recipe_service import RecipeService

    user = _user()
    saved = _make_saved(created_by=user.id, recipe_data={"water": "120"})
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock(return_value=saved)
    session.add = MagicMock()

    svc = RecipeService(session)
    data = CustomerTrialCreate(
        saved_recipe_id=saved.id,
        feedback_text="Mooney too low",
        actual_values={"Mooney": "40"},
        target_values={"Mooney": "47"},
    )
    trial = await svc.create_trial(data, user)
    assert trial.saved_recipe_id == saved.id
    assert trial.created_by == user.id
    assert trial.recipe_snapshot["recipe_data"]["water"] == "120"
    assert trial.feedback_text == "Mooney too low"
    assert trial.actual_values["Mooney"] == "40"


@pytest.mark.asyncio
async def test_create_trial_rejects_expired_saved_recipe():
    from app.services.recipe_service import RecipeService

    user = _user()
    saved = _make_saved(
        created_by=user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=saved)
    svc = RecipeService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_trial(
            CustomerTrialCreate(saved_recipe_id=saved.id, actual_values={}, target_values={}),
            user,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_non_admin_cannot_access_others_recipe():
    owner = _user()
    other = _user()
    other.id = uuid.uuid4()
    recipe = _make_saved(created_by=owner.id)
    recipe.creator = owner

    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = recipe
    session.execute = AsyncMock(return_value=result_mock)

    svc = SavedRecipeService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.get_recipe(recipe.id, other)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_permanently_delete_saved_recipe():
    admin = _user(role=UserRole.ADMIN)
    recipe = _make_saved(created_by=admin.id, recipe_name="To Delete")
    session = AsyncMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    svc = SavedRecipeService(session)
    svc.get_recipe = AsyncMock(return_value=recipe)  # type: ignore

    with patch(
        "app.services.saved_recipe_service.AuditService.log",
        new_callable=AsyncMock,
    ) as audit_log:
        detail = await svc.delete_recipe_permanently(recipe.id, admin)

    assert detail["recipe_name"] == "To Delete"
    assert detail["recipe_id"] == str(recipe.id)
    session.delete.assert_awaited_once_with(recipe)
    session.commit.assert_awaited()
    audit_log.assert_awaited()
    assert audit_log.await_args.kwargs["action"] == "ADMIN_RECIPE_DELETED"
    assert audit_log.await_args.kwargs["entity_type"] == "RECIPE"


@pytest.mark.asyncio
async def test_scientist_cannot_permanently_delete_saved_recipe():
    scientist = _user(role=UserRole.SCIENTIST)
    recipe = _make_saved(created_by=scientist.id)
    session = AsyncMock()
    session.delete = AsyncMock()
    svc = SavedRecipeService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.delete_recipe_permanently(recipe.id, scientist)
    assert exc.value.status_code == 403
    session.delete.assert_not_called()


@pytest.mark.asyncio
async def test_optimization_number_continues_parent_lineage():
    parent = _make_saved(revision_number=2, recipe_name="Optimized A")
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    svc = SavedRecipeService(session)
    assert await svc._next_revision_number(parent) == 3


def test_optimized_kind_when_parent_and_feedback():
    svc = SavedRecipeService(AsyncMock())
    data = SavedRecipeCreate(
        recipe_name="Opt",
        recipe_data={"water": "190"},
        parent_recipe_id=uuid.uuid4(),
        source_trial_id=uuid.uuid4(),
    )
    assert svc._resolve_kind(data) == SavedRecipeKind.OPTIMIZED


def test_normal_kind_without_feedback_link():
    svc = SavedRecipeService(AsyncMock())
    data = SavedRecipeCreate(recipe_name="Original", recipe_data={"water": "180"})
    assert svc._resolve_kind(data) == SavedRecipeKind.NORMAL


def test_customer_trial_response_serializes_without_lazy_candidates():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.models.customer_trial import TrialStatus
    from app.schemas.recipe import to_customer_trial_response

    trial = SimpleNamespace(
        id=uuid.uuid4(),
        cycle_id=None,
        selected_candidate_id=None,
        saved_recipe_id=uuid.uuid4(),
        recipe_snapshot={"recipe_name": "final Recipe 2"},
        status=TrialStatus.PENDING,
        feedback_text="",
        actual_values={},
        target_values={"MH": ""},
        selected_optimized_id=None,
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )
    resp = to_customer_trial_response(trial)
    assert resp.status == "PENDING"
    assert resp.optimized_candidates == []
    assert resp.recipe_snapshot["recipe_name"] == "final Recipe 2"
    assert resp.target_values["MH"] == ""
