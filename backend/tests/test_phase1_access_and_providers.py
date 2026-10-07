"""Ownership, settings authorization, and LLM fallback policy."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from app.api.v1.settings import LLMSettingsUpdate, update_llm_settings
from app.core.config import settings
from app.models.user import UserRole
from app.schemas.recipe import CustomerTrialCreate, SavedRecipeCreate
from app.services.llm.base import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMQuotaExhaustedError,
)
from app.services.llm.llm_client import is_provider_failure
from app.services.llm.provider_registry import fallback_provider_ids
from app.services.recipe_service import RecipeService
from app.services.saved_recipe_service import SavedRecipeService
from tests.test_saved_recipes import _make_saved, _user


def test_default_user_seeding_is_off():
    assert settings.SEED_DEFAULT_USERS is False


def test_fallback_chain_uses_openai_and_skips_groq():
    assert fallback_provider_ids("gemini", "openai", True) == ["gemini", "openai"]
    assert fallback_provider_ids("gemini", "groq", True) == ["gemini"]
    assert fallback_provider_ids("openai", "gemini", False) == ["openai"]


def test_fallback_only_for_provider_failures():
    assert is_provider_failure(LLMQuotaExhaustedError("quota"))
    assert is_provider_failure(LLMAuthenticationError("auth"))
    assert not is_provider_failure(LLMInvalidRequestError("context"))

    class _NeedsInt(BaseModel):
        value: int

    try:
        _NeedsInt(value="not-a-number")  # type: ignore[arg-type]
    except ValidationError as validation_error:
        assert not is_provider_failure(validation_error)
    assert not is_provider_failure(RuntimeError("unexpected"))


@pytest.mark.asyncio
async def test_scientist_cannot_read_another_scientists_cycle():
    owner = _user()
    other = _user()
    cycle = MagicMock()
    cycle.created_by = owner.id
    result = MagicMock()
    result.scalar_one_or_none.return_value = cycle
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    svc = RecipeService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.get_cycle(uuid.uuid4(), other)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_read_a_scientist_cycle():
    admin = _user(role=UserRole.ADMIN)
    cycle = MagicMock()
    cycle.created_by = uuid.uuid4()
    result = MagicMock()
    result.scalar_one_or_none.return_value = cycle
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    svc = RecipeService(session)

    loaded = await svc.get_cycle(uuid.uuid4(), admin)
    assert loaded is cycle


@pytest.mark.asyncio
async def test_scientist_cannot_trial_another_scientists_recipe():
    owner = _user()
    other = _user()
    saved = _make_saved(created_by=owner.id)
    session = AsyncMock()
    session.get = AsyncMock(return_value=saved)
    svc = RecipeService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.create_trial(
            CustomerTrialCreate(saved_recipe_id=saved.id, feedback_text="private"),
            other,
        )
    assert exc.value.status_code == 403
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_scientist_cannot_reference_another_scientists_parent_recipe():
    owner = _user()
    other = _user()
    parent = _make_saved(created_by=owner.id)
    session = AsyncMock()
    session.get = AsyncMock(return_value=parent)
    svc = SavedRecipeService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.save_recipe(
            SavedRecipeCreate(
                recipe_name="Copied",
                recipe_data={"water": "1"},
                parent_recipe_id=parent.id,
            ),
            other,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_source_feedback_must_belong_to_parent_recipe():
    user = _user()
    parent = _make_saved(created_by=user.id)
    trial = MagicMock()
    trial.created_by = user.id
    trial.saved_recipe_id = uuid.uuid4()
    session = AsyncMock()

    async def _get(model, pk):
        from app.models.customer_trial import CustomerTrial
        from app.models.saved_recipe import SavedRecipe
        if model is CustomerTrial:
            return trial
        if model is SavedRecipe:
            return parent
        return parent

    session.get = _get
    svc = SavedRecipeService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.save_recipe(
            SavedRecipeCreate(
                recipe_name="Mismatch",
                recipe_data={"water": "1"},
                parent_recipe_id=parent.id,
                source_trial_id=uuid.uuid4(),
            ),
            user,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_settings_reject_api_key_and_non_selectable_provider():
    admin = _user(role=UserRole.ADMIN)
    scientist = _user()

    with pytest.raises(HTTPException) as denied:
        await update_llm_settings(
            LLMSettingsUpdate(provider_id="gemini"),
            db=AsyncMock(),
            current_user=scientist,
        )
    assert denied.value.status_code == 403

    with pytest.raises(HTTPException) as key_rejected:
        await update_llm_settings(
            LLMSettingsUpdate(provider_id="gemini", api_key="rejected-by-api"),
            db=AsyncMock(),
            current_user=admin,
        )
    assert key_rejected.value.status_code == 400
    assert "rejected-by-api" not in str(key_rejected.value.detail)

    with pytest.raises(HTTPException) as groq_rejected:
        await update_llm_settings(
            LLMSettingsUpdate(provider_id="groq"),
            db=AsyncMock(),
            current_user=admin,
        )
    assert groq_rejected.value.status_code == 400
