"""
app/api/v1/recipe.py

Recipe Simulator API endpoints.
"""
import re
import uuid
from typing import Any
from fastapi import APIRouter, Depends, Response, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.recipe import (
    RecipeCycleCreate, RecipeCycleUpdate,
    RecipeCycleResponse, RecipeCycleDetailResponse,
    RecipeCandidateResponse,
    CustomerTrialCreate, CustomerTrialUpdate,
    CustomerTrialResponse,
    OptimizedRecipeCandidateResponse,
    SavedRecipeCreate, SavedRecipeUpdate, SavedRecipeResponse,
    SavedRecipeBatchCreate, SavedRecipeBatchResponse,
    CandidateRecipeDataUpdate,
    OptimizedCandidateUpdate,
    to_customer_trial_response,
)
from app.services.recipe_service import RecipeService
from app.services.saved_recipe_service import SavedRecipeService, to_saved_recipe_response

router = APIRouter(prefix="/recipe", tags=["Recipe Simulator"])


@router.post("/cycles", response_model=SuccessResponse[RecipeCycleResponse])
async def create_recipe_cycle(
    data: RecipeCycleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    cycle = await svc.create_cycle(data, current_user)
    return SuccessResponse(data=cycle)


@router.get("/cycles", response_model=SuccessResponse[list[RecipeCycleDetailResponse]])
async def list_recipe_cycles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    cycles = await svc.list_cycles_for_user(current_user)
    return SuccessResponse(data=cycles)


@router.get("/cycles/{cycle_id}", response_model=SuccessResponse[RecipeCycleDetailResponse])
async def get_recipe_cycle(
    cycle_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    cycle = await svc.get_cycle(cycle_id, current_user)
    return SuccessResponse(data=cycle)


@router.patch("/cycles/{cycle_id}", response_model=SuccessResponse[RecipeCycleResponse])
async def update_recipe_cycle(
    cycle_id: uuid.UUID,
    data: RecipeCycleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    cycle = await svc.update_cycle(cycle_id, data, current_user)
    return SuccessResponse(data=cycle)


@router.post("/cycles/{cycle_id}/generate", response_model=SuccessResponse[list[RecipeCandidateResponse]])
async def generate_recipes(
    cycle_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    candidates = await svc.generate_recipes(cycle_id, current_user)
    return SuccessResponse(data=candidates)


@router.get("/cycles/{cycle_id}/candidates", response_model=SuccessResponse[list[RecipeCandidateResponse]])
async def get_candidates(
    cycle_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    cycle = await svc.get_cycle(cycle_id, current_user)
    return SuccessResponse(data=cycle.candidates)


@router.post("/cycles/{cycle_id}/select/{candidate_id}", response_model=SuccessResponse[RecipeCycleResponse])
async def select_candidate(
    cycle_id: uuid.UUID,
    candidate_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    cycle = await svc.select_candidate(cycle_id, candidate_id, current_user)
    return SuccessResponse(data=cycle)


@router.patch(
    "/cycles/{cycle_id}/candidates/{candidate_id}",
    response_model=SuccessResponse[RecipeCandidateResponse],
)
async def update_candidate_recipe(
    cycle_id: uuid.UUID,
    candidate_id: uuid.UUID,
    data: CandidateRecipeDataUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist user edits onto a generated candidate before Save This Recipe."""
    svc = RecipeService(db)
    candidate = await svc.update_candidate_recipe_data(
        cycle_id, candidate_id, data.recipe_data, current_user, name=data.name
    )
    return SuccessResponse(data=candidate)


# ── Saved recipes ─────────────────────────────────────────────────────────────

@router.get("/saved", response_model=SuccessResponse[list[SavedRecipeResponse]])
async def list_saved_recipes(
    selectable_only: bool = False,
    include_expired: bool = False,
    kind: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = SavedRecipeService(db)
    recipes = await svc.list_recipes(
        current_user,
        include_expired=include_expired,
        selectable_only=selectable_only,
        kind=kind,
    )
    return SuccessResponse(data=[to_saved_recipe_response(r) for r in recipes])


@router.post("/saved", response_model=SuccessResponse[SavedRecipeResponse], status_code=status.HTTP_201_CREATED)
async def create_saved_recipe(
    data: SavedRecipeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = SavedRecipeService(db)
    recipe = await svc.save_recipe(data, current_user)
    return SuccessResponse(data=to_saved_recipe_response(recipe))


@router.post("/saved/batch", response_model=SuccessResponse[SavedRecipeBatchResponse], status_code=status.HTTP_201_CREATED)
async def create_saved_recipes_batch(
    data: SavedRecipeBatchCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = SavedRecipeService(db)
    result = await svc.save_recipes_batch(data, current_user)
    return SuccessResponse(data=result)


@router.get("/saved/{recipe_id}", response_model=SuccessResponse[SavedRecipeResponse])
async def get_saved_recipe(
    recipe_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = SavedRecipeService(db)
    recipe = await svc.get_recipe(recipe_id, current_user)
    return SuccessResponse(data=to_saved_recipe_response(recipe))


@router.patch("/saved/{recipe_id}", response_model=SuccessResponse[SavedRecipeResponse])
async def update_saved_recipe(
    recipe_id: uuid.UUID,
    data: SavedRecipeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = SavedRecipeService(db)
    recipe = await svc.update_recipe(recipe_id, data, current_user)
    return SuccessResponse(data=to_saved_recipe_response(recipe))


@router.delete("/saved/{recipe_id}", response_model=SuccessResponse[dict])
async def delete_saved_recipe(
    recipe_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Permanently delete a saved recipe. Admin only.
    Related Customer Trial Feedback rows keep recipe_snapshot;
    saved_recipe_id is set NULL via FK ON DELETE SET NULL.
    """
    svc = SavedRecipeService(db)
    detail = await svc.delete_recipe_permanently(recipe_id, current_user)
    return SuccessResponse(data=detail)


@router.post("/trials", response_model=SuccessResponse[CustomerTrialResponse])
async def create_trial(
    data: CustomerTrialCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    trial = await svc.create_trial(data, current_user)
    return SuccessResponse(data=to_customer_trial_response(trial))


@router.get("/trials/{trial_id}", response_model=SuccessResponse[CustomerTrialResponse])
async def get_trial(
    trial_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    trial = await svc.get_trial(trial_id, current_user)
    return SuccessResponse(data=to_customer_trial_response(trial))


@router.patch("/trials/{trial_id}", response_model=SuccessResponse[CustomerTrialResponse])
async def update_trial(
    trial_id: uuid.UUID,
    data: CustomerTrialUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    trial = await svc.update_trial(trial_id, data, current_user)
    return SuccessResponse(data=to_customer_trial_response(trial))


@router.post("/trials/{trial_id}/optimize", response_model=SuccessResponse[list[OptimizedRecipeCandidateResponse]])
async def generate_optimization(
    trial_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    opts = await svc.generate_optimized_recipes(trial_id, current_user, force_regenerate=True)
    return SuccessResponse(data=opts)


@router.get("/trials/{trial_id}/optimized", response_model=SuccessResponse[list[OptimizedRecipeCandidateResponse]])
async def get_optimized(
    trial_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    opts = await svc.generate_optimized_recipes(trial_id, current_user, force_regenerate=False)
    return SuccessResponse(data=opts)


@router.patch("/trials/{trial_id}/optimized/{candidate_id}", response_model=SuccessResponse[OptimizedRecipeCandidateResponse])
async def update_optimized_candidate(
    trial_id: uuid.UUID,
    candidate_id: uuid.UUID,
    data: OptimizedCandidateUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist user edits onto a generated optimized candidate before Save."""
    svc = RecipeService(db)
    candidate = await svc.update_optimized_recipe_data(
        trial_id, candidate_id, data.recipe_data, current_user, name=data.name
    )
    return SuccessResponse(data=candidate)


@router.post("/trials/{trial_id}/select/{optimized_id}", response_model=SuccessResponse[CustomerTrialResponse])
async def select_optimized(
    trial_id: uuid.UUID,
    optimized_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = RecipeService(db)
    trial = await svc.select_optimized(trial_id, optimized_id, current_user)
    return SuccessResponse(data=to_customer_trial_response(trial))


@router.post("/export/pdf")
async def export_recipes_to_pdf(
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
):
    """
    Export current recipes directly from UI state to a single structured PDF file.
    Preserves all 5 candidate recipes in order without regenerating or querying LLM.
    """
    recipes = payload.get("recipes", [])
    compound = payload.get("compound", "Polymer Formulation")
    cycle_info = payload.get("cycle_info", {})
    from app.services.recipe_pdf_service import RecipePdfService
    pdf_bytes = RecipePdfService.generate_recipes_pdf(
        recipes=recipes,
        compound_name=compound,
        cycle_info=cycle_info,
    )
    safe_compound = re.sub(r"[^a-zA-Z0-9_\-]", "_", compound)
    filename = f"Apcotex_Recipes_{safe_compound}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/cycles/{cycle_id}/export/pdf")
async def export_cycle_recipes_to_pdf(
    cycle_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Export all candidates for a persisted cycle to a structured PDF file.
    """
    svc = RecipeService(db)
    cycle = await svc.get_cycle(cycle_id, current_user)
    candidates_data = [
        c.recipe_data if c.recipe_data else {
            "name": c.name,
            "display_name": c.display_name,
            "rank": c.rank,
            "confidence_score": c.confidence_score,
            "target_fit_score": c.target_fit_score,
            "targets_met": c.targets_met,
            "targets_total": c.targets_total,
            "predicted_properties": c.predicted_properties,
            "patent_references": c.patent_references,
        }
        for c in (cycle.candidates or [])
    ]
    from app.services.recipe_pdf_service import RecipePdfService
    pdf_bytes = RecipePdfService.generate_recipes_pdf(
        recipes=candidates_data,
        compound_name=cycle.compound_name,
        cycle_info={
            "target_properties": cycle.target_properties,
            "process_type": cycle.process_type,
            "temperature_range": cycle.temperature_range,
        },
    )
    safe_compound = re.sub(r"[^a-zA-Z0-9_\-]", "_", cycle.compound_name)
    filename = f"Apcotex_Recipes_{safe_compound}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


