"""
app/api/v1/endpoints/settings.py

Administrator-only LLM provider selection.
API keys stay in server environment configuration and are never written here.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.dependencies.auth import require_role
from app.db.session import get_db
from app.models.app_config import AppConfig
from app.models.user import User, UserRole
from app.services.llm.provider_registry import (
    PROVIDER_DEFINITIONS,
    SELECTABLE_PROVIDER_IDS,
    get_provider_status,
)

router = APIRouter()


class ProviderInfo(BaseModel):
    id: str
    name: str
    description: str
    capabilities: List[str]
    status: str


class LLMSettingsResponse(BaseModel):
    active_provider: str
    providers: List[ProviderInfo]


class LLMSettingsUpdate(BaseModel):
    provider_id: str
    api_key: str | None = None


def _active_provider_id(config: AppConfig | None) -> str:
    from app.core.config import settings

    active_provider = settings.PRIMARY_LLM
    if config and isinstance(config.value, dict) and "provider_id" in config.value:
        active_provider = config.value["provider_id"]
    return active_provider


@router.get("/llm", response_model=LLMSettingsResponse)
async def get_llm_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """Return the active provider and the providers an administrator may select."""
    result = await db.execute(select(AppConfig).where(AppConfig.key == "active_llm_provider"))
    config = result.scalar_one_or_none()
    providers = []
    for pid in SELECTABLE_PROVIDER_IDS:
        pdef = PROVIDER_DEFINITIONS[pid]
        providers.append(
            ProviderInfo(
                id=pid,
                name=pdef["name"],
                description=pdef["description"],
                capabilities=pdef["capabilities"],
                status=get_provider_status(pid),
            )
        )
    return LLMSettingsResponse(
        active_provider=_active_provider_id(config),
        providers=providers,
    )


@router.put("/llm")
async def update_llm_settings(
    data: LLMSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """Select the primary provider. Secrets are not accepted on this endpoint."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Administrator access required")
    if data.api_key:
        raise HTTPException(
            status_code=400,
            detail="API keys are configured on the server and cannot be set through the API",
        )

    pid = data.provider_id.lower()
    if pid not in SELECTABLE_PROVIDER_IDS:
        raise HTTPException(status_code=400, detail=f"Provider '{pid}' is not selectable")

    pdef = PROVIDER_DEFINITIONS[pid]
    status_str = get_provider_status(pid)
    if status_str != "Configured":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot select {pdef['name']} because its status is '{status_str}'. Configure the key on the server.",
        )

    result = await db.execute(select(AppConfig).where(AppConfig.key == "active_llm_provider"))
    config = result.scalar_one_or_none()

    if config:
        config.value = {"provider_id": pid}
    else:
        config = AppConfig(key="active_llm_provider", value={"provider_id": pid})
        db.add(config)

    await db.commit()
    return {"status": "success", "active_provider": pid}
