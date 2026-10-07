"""
app/services/saved_recipe_service.py

Persistence, listing, update, and six-month retention cleanup for SavedRecipe.
"""
from __future__ import annotations

import calendar
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.saved_recipe import SavedRecipe, SavedRecipeKind, SavedRecipeStatus
from app.models.user import User, UserRole
from app.core.audit_actions import AuditAction, AuditEntityType
from app.services.audit_service import AuditService
from app.schemas.recipe import (
    SavedRecipeCreate,
    SavedRecipeResponse,
    SavedRecipeUpdate,
    SavedRecipeBatchCreate,
    SavedRecipeBatchItemResult,
    SavedRecipeBatchResponse,
)

logger = logging.getLogger(__name__)

# Six calendar months (not a fixed day count like 182).
RETENTION_MONTHS = 6


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def add_calendar_months(dt: datetime, months: int) -> datetime:
    """Add calendar months, clamping day to the last valid day of the target month."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _expiry_from_now() -> datetime:
    return add_calendar_months(_utcnow(), RETENTION_MONTHS)


def _user_display(user: User | None) -> str | None:
    if not user:
        return None
    return user.full_name or user.username or user.email


def to_saved_recipe_response(
    recipe: SavedRecipe,
    *,
    creator: User | None = None,
    updater: User | None = None,
    parent: SavedRecipe | None = None,
) -> SavedRecipeResponse:
    creator = creator or getattr(recipe, "creator", None)
    updater = updater or getattr(recipe, "updater", None)
    parent = parent or getattr(recipe, "parent", None)
    kind = recipe.recipe_kind
    kind_value = kind.value if hasattr(kind, "value") else str(kind or "NORMAL")
    source_trial = getattr(recipe, "source_trial", None)
    feedback_text = None
    if source_trial is not None:
        feedback_text = getattr(source_trial, "feedback_text", None)
    return SavedRecipeResponse(
        id=recipe.id,
        recipe_name=recipe.recipe_name,
        recipe_data=recipe.recipe_data or {},
        target_properties=recipe.target_properties or [],
        competitor_properties=recipe.competitor_properties or [],
        created_by=recipe.created_by,
        created_by_name=_user_display(creator),
        updated_by=recipe.updated_by,
        updated_by_name=_user_display(updater),
        created_at=recipe.created_at,
        updated_at=recipe.updated_at,
        expires_at=recipe.expires_at,
        parent_recipe_id=recipe.parent_recipe_id,
        parent_recipe_name=parent.recipe_name if parent else None,
        revision_number=recipe.revision_number,
        recipe_kind=kind_value,
        optimization_number=recipe.revision_number or 0,
        status=recipe.status.value if hasattr(recipe.status, "value") else str(recipe.status),
        source_cycle_id=recipe.source_cycle_id,
        source_candidate_id=recipe.source_candidate_id,
        source_trial_id=recipe.source_trial_id,
        source_optimized_id=recipe.source_optimized_id,
        source_feedback_text=feedback_text,
        notes=recipe.notes,
        is_revision=bool(recipe.parent_recipe_id) or (recipe.revision_number or 0) > 0,
    )


class SavedRecipeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _next_revision_number(self, parent: SavedRecipe) -> int:
        """Next optimization number continues the parent lineage (not reset per parent)."""
        result = await self.session.execute(
            select(func.max(SavedRecipe.revision_number)).where(
                SavedRecipe.parent_recipe_id == parent.id
            )
        )
        latest_child = result.scalar_one_or_none() or 0
        base = max(int(parent.revision_number or 0), int(latest_child))
        return base + 1

    def _resolve_kind(self, data: SavedRecipeCreate) -> SavedRecipeKind:
        raw = (data.recipe_kind or "").strip().upper()
        if raw == SavedRecipeKind.OPTIMIZED.value:
            return SavedRecipeKind.OPTIMIZED
        if raw == SavedRecipeKind.NORMAL.value:
            return SavedRecipeKind.NORMAL
        if data.parent_recipe_id and data.source_trial_id:
            return SavedRecipeKind.OPTIMIZED
        return SavedRecipeKind.NORMAL

    async def save_recipe(self, data: SavedRecipeCreate, current_user: User) -> SavedRecipe:
        parent = None
        revision_number = 0
        if data.parent_recipe_id:
            parent = await self.session.get(SavedRecipe, data.parent_recipe_id)
            if not parent:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent recipe not found")
            if parent.expires_at <= _utcnow():
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parent recipe has expired")
            if current_user.role != UserRole.ADMIN and parent.created_by != current_user.id:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to reference this parent recipe")

        if data.source_trial_id:
            from app.models.customer_trial import CustomerTrial

            trial = await self.session.get(CustomerTrial, data.source_trial_id)
            if trial is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Source feedback not found")
            if current_user.role != UserRole.ADMIN and trial.created_by != current_user.id:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to reference this feedback")
            if data.parent_recipe_id and trial.saved_recipe_id != data.parent_recipe_id:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Source feedback is not linked to the parent recipe",
                )

        if data.source_cycle_id:
            from app.models.recipe_cycle import RecipeCycle

            cycle = await self.session.get(RecipeCycle, data.source_cycle_id)
            if cycle is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Source recipe cycle not found")
            if current_user.role != UserRole.ADMIN and cycle.created_by != current_user.id:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to reference this recipe cycle")

        if parent is not None:
            revision_number = await self._next_revision_number(parent)

        recipe = SavedRecipe(
            recipe_name=data.recipe_name.strip(),
            recipe_data=data.recipe_data,
            target_properties=data.target_properties or [],
            competitor_properties=data.competitor_properties or [],
            created_by=current_user.id,
            updated_by=current_user.id,
            expires_at=_expiry_from_now(),
            parent_recipe_id=data.parent_recipe_id,
            revision_number=revision_number,
            recipe_kind=self._resolve_kind(data),
            status=SavedRecipeStatus.ACTIVE,
            source_cycle_id=data.source_cycle_id,
            source_candidate_id=data.source_candidate_id,
            source_trial_id=data.source_trial_id,
            source_optimized_id=data.source_optimized_id,
            notes=data.notes,
        )
        self.session.add(recipe)
        await self.session.flush()

        audit = AuditService(self.session)
        audit_action = (
            AuditAction.OPTIMIZED_RECIPE_SAVED
            if recipe.recipe_kind == SavedRecipeKind.OPTIMIZED
            else AuditAction.RECIPE_CREATED
        )
        await audit.log(
            user_id=str(current_user.id),
            action=audit_action,
            entity_type=AuditEntityType.RECIPE,
            entity_id=str(recipe.id),
            detail={
                "recipe_name": recipe.recipe_name,
                "recipe_kind": recipe.recipe_kind.value if hasattr(recipe.recipe_kind, "value") else str(recipe.recipe_kind or "NORMAL"),
                "parent_recipe_id": str(recipe.parent_recipe_id) if recipe.parent_recipe_id else None,
                "revision_number": recipe.revision_number,
                "source_trial_id": str(recipe.source_trial_id) if recipe.source_trial_id else None,
            },
        )
        await self.session.commit()
        return await self.get_recipe(recipe.id, current_user)

    async def save_recipes_batch(
        self, data: SavedRecipeBatchCreate, current_user: User
    ) -> SavedRecipeBatchResponse:
        results = []
        total_saved = 0
        total_failed = 0
        for item in data.recipes:
            try:
                saved = await self.save_recipe(item, current_user)
                results.append(
                    SavedRecipeBatchItemResult(
                        recipe_name=item.recipe_name,
                        success=True,
                        saved_recipe=to_saved_recipe_response(saved),
                    )
                )
                total_saved += 1
            except Exception as e:
                logger.warning("Failed to save recipe '%s' in batch: %s", item.recipe_name, e)
                results.append(
                    SavedRecipeBatchItemResult(
                        recipe_name=item.recipe_name,
                        success=False,
                        error=str(e),
                    )
                )
                total_failed += 1
        return SavedRecipeBatchResponse(
            results=results,
            total_requested=len(data.recipes),
            total_saved=total_saved,
            total_failed=total_failed,
        )

    async def update_recipe(
        self, recipe_id: uuid.UUID, data: SavedRecipeUpdate, current_user: User
    ) -> SavedRecipe:
        recipe = await self.get_recipe(recipe_id, current_user)
        if recipe.expires_at <= _utcnow():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot edit an expired recipe")

        if data.recipe_name is not None:
            recipe.recipe_name = data.recipe_name.strip()
        if data.recipe_data is not None:
            recipe.recipe_data = data.recipe_data
        if data.target_properties is not None:
            recipe.target_properties = data.target_properties
        if data.competitor_properties is not None:
            recipe.competitor_properties = data.competitor_properties
        if data.notes is not None:
            recipe.notes = data.notes
        recipe.updated_by = current_user.id
        recipe.updated_at = _utcnow()
        await self.session.flush()

        audit = AuditService(self.session)
        audit_action = (
            AuditAction.OPTIMIZED_RECIPE_UPDATED
            if recipe.recipe_kind == SavedRecipeKind.OPTIMIZED
            else AuditAction.RECIPE_UPDATED
        )
        await audit.log(
            user_id=str(current_user.id),
            action=audit_action,
            entity_type=AuditEntityType.RECIPE,
            entity_id=str(recipe.id),
            detail={
                "recipe_name": recipe.recipe_name,
                "recipe_kind": recipe.recipe_kind.value if hasattr(recipe.recipe_kind, "value") else str(recipe.recipe_kind or "NORMAL"),
                "parent_recipe_id": str(recipe.parent_recipe_id) if recipe.parent_recipe_id else None,
                "revision_number": recipe.revision_number,
            },
        )
        await self.session.commit()
        return await self.get_recipe(recipe_id, current_user)

    async def get_recipe(self, recipe_id: uuid.UUID, current_user: User) -> SavedRecipe:
        result = await self.session.execute(
            select(SavedRecipe)
            .where(SavedRecipe.id == recipe_id)
            .options(
                selectinload(SavedRecipe.creator),
                selectinload(SavedRecipe.updater),
                selectinload(SavedRecipe.parent),
                selectinload(SavedRecipe.source_trial),
            )
        )
        recipe = result.scalar_one_or_none()
        if not recipe:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved recipe not found")
        if current_user.role != UserRole.ADMIN and recipe.created_by != current_user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to access this recipe")
        return recipe

    async def list_recipes(
        self,
        current_user: User,
        *,
        include_expired: bool = False,
        selectable_only: bool = False,
        kind: str | None = None,
    ) -> list[SavedRecipe]:
        q = (
            select(SavedRecipe)
            .options(
                selectinload(SavedRecipe.creator),
                selectinload(SavedRecipe.updater),
                selectinload(SavedRecipe.parent),
                selectinload(SavedRecipe.source_trial),
            )
            .order_by(SavedRecipe.created_at.desc())
        )
        if current_user.role != UserRole.ADMIN:
            q = q.where(SavedRecipe.created_by == current_user.id)

        if kind:
            normalized = kind.strip().upper()
            if normalized not in {SavedRecipeKind.NORMAL.value, SavedRecipeKind.OPTIMIZED.value}:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "kind must be NORMAL or OPTIMIZED")
            q = q.where(SavedRecipe.recipe_kind == SavedRecipeKind(normalized))

        now = _utcnow()
        if selectable_only or not include_expired:
            q = q.where(
                and_(
                    SavedRecipe.status == SavedRecipeStatus.ACTIVE,
                    SavedRecipe.expires_at > now,
                )
            )

        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def delete_recipe_permanently(
        self, recipe_id: uuid.UUID, current_user: User
    ) -> dict:
        """
        Admin-only permanent deletion of a saved recipe row.
        CustomerTrial.saved_recipe_id becomes NULL; recipe_snapshot is preserved.
        Child revisions keep parent_recipe_id NULL via ON DELETE SET NULL —
        they are NOT cascade-deleted.
        """
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only administrators can permanently delete saved recipes",
            )

        recipe = await self.get_recipe(recipe_id, current_user)
        detail = {
            "recipe_id": str(recipe.id),
            "recipe_name": recipe.recipe_name,
            "revision_number": recipe.revision_number,
            "recipe_kind": recipe.recipe_kind.value
            if hasattr(recipe.recipe_kind, "value")
            else str(recipe.recipe_kind),
            "parent_recipe_id": str(recipe.parent_recipe_id)
            if recipe.parent_recipe_id
            else None,
            "deleted_by": str(current_user.id),
            "deleted_by_name": current_user.full_name
            or current_user.username
            or current_user.email,
            "deleted_at": _utcnow().isoformat(),
        }

        await self.session.delete(recipe)
        await self.session.flush()

        audit = AuditService(self.session)
        del_action = (
            AuditAction.OPTIMIZED_RECIPE_DELETED
            if recipe.recipe_kind == SavedRecipeKind.OPTIMIZED
            else AuditAction.ADMIN_RECIPE_DELETED
        )
        await audit.log(
            user_id=str(current_user.id),
            action=del_action,
            entity_type=AuditEntityType.RECIPE,
            entity_id=str(recipe_id),
            detail=detail,
        )
        await self.session.commit()
        logger.info(
            "[SAVED_RECIPE] Admin %s permanently deleted recipe %s (%s)",
            current_user.username,
            recipe_id,
            detail["recipe_name"],
        )
        return detail

    async def delete_expired_recipes(self) -> int:
        """
        Permanently delete expired saved recipes.
        Feedback rows keep recipe_snapshot; saved_recipe_id becomes NULL via ON DELETE SET NULL.
        Child revisions with expired parents keep parent_recipe_id NULL via ON DELETE SET NULL.
        """
        now = _utcnow()
        result = await self.session.execute(
            select(SavedRecipe).where(
                or_(
                    SavedRecipe.expires_at <= now,
                    SavedRecipe.status == SavedRecipeStatus.EXPIRED,
                )
            )
        )
        expired = list(result.scalars().all())
        count = len(expired)
        for recipe in expired:
            await self.session.delete(recipe)
        if count:
            await self.session.commit()
            logger.info("[SAVED_RECIPE] Deleted %d expired recipe(s)", count)
        return count


async def run_saved_recipe_cleanup_once() -> int:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        svc = SavedRecipeService(session)
        return await svc.delete_expired_recipes()
