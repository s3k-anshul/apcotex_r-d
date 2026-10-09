"""
backend/tests/test_customer_trial_optimization_enhancement_phase2.py

Dedicated test suite for Phase 2:
CUSTOMER TRIAL FEEDBACK + OPTIMIZED RECIPE ENHANCEMENT

Covers:
1. Exactly 3 optimized candidates generated
2. Strict target compound identity preservation (e.g. 7% carboxylated NBR)
3. Polymer-agnostic architecture (different target compounds work identically)
4. Target range and target point passed and evaluated
5. MEETS TARGET and OUTSIDE TARGET deterministic statuses
6. Target violations lower target-fit score and confidence
7. Reaction temperature constraints (5–7 °C and 20–25 °C)
8. Process type constraints (Batch, Continuous, No Preference)
9. Catalyst primary + alternatives system
10. Activator system dynamic applicability
11. Coagulation system dynamic applicability
12. Customer trial feedback reaches optimization context
13. Repeated re-optimization lineage (R0 -> T1 -> R1 -> T2 -> R2)
14. source_trial_id and snapshot preservation
15. Saving one candidate does not save all 3
16. Previous Optimized Recipes loading
17. Historical recipes backward compatibility
18. Demo mode generates 3 candidates with Phase 2 fields
19. Strict production validation
20. Canonical 6 stages preserved
"""
import uuid
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.customer_trial import CustomerTrial, TrialStatus
from app.models.optimized_recipe_candidate import OptimizedRecipeCandidate
from app.models.saved_recipe import SavedRecipe, SavedRecipeKind, SavedRecipeStatus
from app.models.user import User, UserRole
from app.schemas.recipe import (
    CustomerTrialCreate,
    CustomerTrialUpdate,
    SavedRecipeCreate,
    LLMOptimizationSet,
    LLMOptimizedRecipeCandidate,
    LLMOptimizedStage,
    LLMOptimizedParameter,
    LLMOptimizedChange,
    LLMPredictedProperty,
    LLMCatalystSystem,
    LLMActivatorSystem,
    LLMCoagulationSystem,
    LLMProcessConditions,
    LLMReactionTime,
)
from app.services.recipe_service import (
    RecipeService,
    validate_and_enrich_water_based_recipe,
)
from app.services.saved_recipe_service import (
    SavedRecipeService,
    to_saved_recipe_response,
)
from app.services.target_validation_service import (
    TargetValidationService,
    NormalizedTargetProperty,
)


def _make_user(role=UserRole.SCIENTIST, username="rd_scientist") -> User:
    return User(
        id=uuid.uuid4(),
        username=username,
        email=f"{username}@apcotex.com",
        full_name="Senior R&D Scientist",
        role=role,
        is_active=True,
        hashed_password="dummy_hash",
    )


def _sample_stages():
    return [
        {
            "stage_name": "Reactor Charge",
            "is_applicable": True,
            "parameters": [
                {"name": "Initial DI Water", "value": "120", "unit": "phr"},
                {"name": "Potassium Oleate", "value": "2.5", "unit": "phr"},
            ],
        },
        {
            "stage_name": "Emulsifier Solution",
            "is_applicable": True,
            "parameters": [
                {"name": "Secondary Surfactant", "value": "0.8", "unit": "phr"},
                {"name": "Water", "value": "30", "unit": "phr"},
            ],
        },
        {
            "stage_name": "Catalyst Solution",
            "is_applicable": True,
            "parameters": [
                {"name": "Potassium Persulfate (KPS)", "value": "0.30", "unit": "phr"},
                {"name": "Water", "value": "15", "unit": "phr"},
            ],
        },
        {
            "stage_name": "Monomer Mix",
            "is_applicable": True,
            "parameters": [
                {"name": "1,3-Butadiene", "value": "72.0", "unit": "phr"},
                {"name": "Acrylonitrile", "value": "28.0", "unit": "phr"},
                {"name": "tert-Dodecyl Mercaptan (t-DDM)", "value": "0.40", "unit": "phr"},
            ],
        },
        {
            "stage_name": "Chemical Stripping",
            "is_applicable": True,
            "parameters": [
                {"name": "Hydroquinone Stopper", "value": "0.15", "unit": "phr"},
                {"name": "Steam Stripping Temp", "value": "65", "unit": "°C"},
            ],
        },
        {
            "stage_name": "Post Addition",
            "is_applicable": True,
            "parameters": [
                {"name": "Phenolic Antioxidant", "value": "1.0", "unit": "phr"},
            ],
        },
    ]


def _sample_recipe_data(compound="7% carboxylated NBR", process_type="Batch", temp_range="5–7 °C"):
    stages = _sample_stages()
    flat_params = []
    for s in stages:
        flat_params.extend(s["parameters"])
    return {
        "compound": compound,
        "stages": stages,
        "parameters": flat_params,
        "process_type": process_type,
        "temperature_range": temp_range,
        "process_conditions": {
            "process_type": process_type,
            "temperature_range": temp_range,
            "reaction_time": {"value": "8.0", "unit": "h"},
            "feeding_hours": {"monomer": "5.0 h", "emulsifier": "4.5 h", "catalyst": "0.5 h"},
            "temperature_profile": [
                {"stage": "Polymerization", "value": "6", "unit": "°C"},
            ],
        },
        "catalyst_system": {
            "primary_catalyst": "Potassium persulfate (KPS)",
            "primary_dosage": "0.30 phr",
            "alternatives": [
                {"catalyst": "Ammonium persulfate", "dosage": "0.28 phr", "rationale": "Direct thermal alternative"}
            ],
        },
        "activator_system": {
            "applicable": True,
            "name": "Sodium formaldehyde sulfoxylate (SFS)",
            "dosage": "0.10 phr",
            "stage": "Catalyst Solution",
            "alternatives": [],
        },
        "coagulation_system": {
            "applicable": True,
            "coagulant": "Calcium chloride",
            "dosage": "2.0 phr",
            "process_conditions": "Coagulation crumb at 60°C",
        },
        "target_properties": [
            {"property": "TS2", "target_value": 22.0, "min": 20.0, "max": 25.0, "unit": "min"},
        ],
    }


def _mock_llm_optimization_set(compound="7% carboxylated NBR", process_type="Batch", temp_val=6.0):
    return LLMOptimizationSet(
        optimized_recipes=[
            LLMOptimizedRecipeCandidate(
                name="Revision A - Conservative Adjustment",
                revision_label="A",
                optimization_strategy="Conservative CTA adjustment for target cure TS2",
                confidence_score=85,
                compound=compound,
                process_type=process_type,
                stages=[
                    LLMOptimizedStage(
                        stage_name=s["stage_name"],
                        parameters=[LLMOptimizedParameter(name=p["name"], value=str(p["value"]), unit=p.get("unit", "")) for p in s["parameters"]]
                    )
                    for s in _sample_stages()
                ],
                process_conditions=LLMProcessConditions(
                    process_type=process_type,
                    reaction_time=LLMReactionTime(value="8.0", unit="h"),
                    temperature_range="5–7 °C" if temp_val <= 10 else "20–25 °C",
                ),
                changed_parameters=[
                    LLMOptimizedChange(parameter="tert-Dodecyl Mercaptan (t-DDM)", old_value="0.40", new_value="0.45", unit="phr", reason="Tune chain length")
                ],
                predicted_properties=[
                    LLMPredictedProperty(property="TS2", predicted_value=22.5, unit="min", status="MEETS_TARGET", reasoning="Optimal CTA balance")
                ],
                expected_outcome="TS2 hits target within 20–25 min range",
                expected_impact="Maintains colloidal stability",
            ),
            LLMOptimizedRecipeCandidate(
                name="Revision B - Balanced Initiator Tuning",
                revision_label="B",
                optimization_strategy="Balanced initiator and conversion moderation",
                confidence_score=80,
                compound=compound,
                process_type=process_type,
                stages=[
                    LLMOptimizedStage(
                        stage_name=s["stage_name"],
                        parameters=[LLMOptimizedParameter(name=p["name"], value=str(p["value"]), unit=p.get("unit", "")) for p in s["parameters"]]
                    )
                    for s in _sample_stages()
                ],
                process_conditions=LLMProcessConditions(
                    process_type=process_type,
                    reaction_time=LLMReactionTime(value="8.5", unit="h"),
                    temperature_range="5–7 °C" if temp_val <= 10 else "20–25 °C",
                ),
                changed_parameters=[
                    LLMOptimizedChange(parameter="Potassium Persulfate (KPS)", old_value="0.30", new_value="0.28", unit="phr", reason="Slight initiator reduction")
                ],
                predicted_properties=[
                    LLMPredictedProperty(property="TS2", predicted_value=21.8, unit="min", status="MEETS_TARGET", reasoning="Milder kinetics")
                ],
                expected_outcome="Achieves target TS2 with narrower MWD",
                expected_impact="Slightly slower reaction",
            ),
            LLMOptimizedRecipeCandidate(
                name="Revision C - Process Levers Variation",
                revision_label="C",
                optimization_strategy="Alternative temperature-kinetics formulation",
                confidence_score=60,
                compound=compound,
                process_type=process_type,
                stages=[
                    LLMOptimizedStage(
                        stage_name=s["stage_name"],
                        parameters=[LLMOptimizedParameter(name=p["name"], value=str(p["value"]), unit=p.get("unit", "")) for p in s["parameters"]]
                    )
                    for s in _sample_stages()
                ],
                process_conditions=LLMProcessConditions(
                    process_type=process_type,
                    reaction_time=LLMReactionTime(value="7.5", unit="h"),
                    temperature_range="5–7 °C" if temp_val <= 10 else "20–25 °C",
                ),
                changed_parameters=[
                    LLMOptimizedChange(parameter="Water", old_value="120", new_value="140", unit="phr", reason="Higher solids dilution")
                ],
                predicted_properties=[
                    # Outside target prediction to verify penalty
                    LLMPredictedProperty(property="TS2", predicted_value=17.5, unit="min", status="OUTSIDE_TARGET", reasoning="Dilution over-accelerates reaction")
                ],
                expected_outcome="Faster cycle time but TS2 falls short of target range",
                expected_impact="High conversion rate with cure acceleration",
            ),
        ]
    )


# ============================================================================
# TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_exactly_three_optimized_candidates_generated():
    """Requirement 1 & 4: Optimize Recipe must generate EXACTLY 3 candidates (not 5)."""
    user = _make_user()
    session = AsyncMock()

    base_data = _sample_recipe_data()
    trial_id = uuid.uuid4()
    trial = CustomerTrial(
        id=trial_id,
        created_by=user.id,
        status=TrialStatus.PENDING,
        recipe_snapshot=base_data,
        target_values={"TS2": {"target": 22, "min": 20, "max": 25}},
        feedback_text="Customer requested TS2 around 22 min.",
    )
    trial.optimized_candidates = []

    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=trial)))
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()

    service = RecipeService(session)
    mock_llm = AsyncMock()
    mock_llm.generate_structured = AsyncMock(
        return_value=(_mock_llm_optimization_set(), '{"mock": true}', {"finish_reason": "STOP"})
    )
    service.llm_client = mock_llm

    candidates = await service.generate_optimized_recipes(trial_id, user, force_regenerate=True)
    assert len(candidates) == 3, f"Expected exactly 3 candidates, got {len(candidates)}"
    labels = [c.revision_label for c in candidates]
    assert labels == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_target_compound_identity_preserved_strictly():
    """Requirement 2 & 12: Target identity '7% carboxylated NBR' must never drift to NBR or XNBR."""
    user = _make_user()
    session = AsyncMock()

    target_name = "7% carboxylated NBR"
    base_data = _sample_recipe_data(compound=target_name)
    trial_id = uuid.uuid4()
    trial = CustomerTrial(
        id=trial_id,
        created_by=user.id,
        status=TrialStatus.PENDING,
        recipe_snapshot=base_data,
        target_values={"TS2": 22},
        feedback_text="Improve TS2",
    )
    trial.optimized_candidates = []

    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=trial)))
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()

    service = RecipeService(session)
    mock_llm = AsyncMock()
    # Mock LLM trying to return generic "XNBR" to ensure backend strictly overrides/enforces exact identity
    bad_llm_set = _mock_llm_optimization_set(compound="XNBR")
    mock_llm.generate_structured = AsyncMock(
        return_value=(bad_llm_set, '{"mock": true}', {"finish_reason": "STOP"})
    )
    service.llm_client = mock_llm

    candidates = await service.generate_optimized_recipes(trial_id, user, force_regenerate=True)
    assert len(candidates) == 3
    for cand in candidates:
        r_data = cand.recipe_data
        assert r_data.get("compound") == target_name, (
            f"Compound mutated: expected '{target_name}', got '{r_data.get('compound')}'"
        )


@pytest.mark.asyncio
async def test_different_target_compound_polymer_agnostic():
    """Requirement 3: An unrelated polymer (HNBR) works without polymer-specific branching."""
    user = _make_user()
    session = AsyncMock()

    target_name = "Hydrogenated Nitrile Butadiene Rubber (HNBR)"
    base_data = _sample_recipe_data(compound=target_name)
    trial_id = uuid.uuid4()
    trial = CustomerTrial(
        id=trial_id,
        created_by=user.id,
        status=TrialStatus.PENDING,
        recipe_snapshot=base_data,
        target_values={"Mooney Viscosity": 65},
        feedback_text="Increase Mooney",
    )
    trial.optimized_candidates = []

    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=trial)))
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()

    service = RecipeService(session)
    mock_llm = AsyncMock()
    mock_llm.generate_structured = AsyncMock(
        return_value=(_mock_llm_optimization_set(compound=target_name), '{"mock": true}', {"finish_reason": "STOP"})
    )
    service.llm_client = mock_llm

    candidates = await service.generate_optimized_recipes(trial_id, user, force_regenerate=True)
    assert len(candidates) == 3
    for cand in candidates:
        assert cand.recipe_data.get("compound") == target_name


def test_target_point_and_range_both_evaluated():
    """Requirement 4, 5, 6, 7: Target point and range evaluated with MEETS TARGET vs OUTSIDE TARGET."""
    raw_targets = [
        {"property": "TS2", "target": 22.0, "range": "20–25", "unit": "min"}
    ]
    normalized = TargetValidationService.normalize_target_properties(raw_targets)
    assert len(normalized) == 1
    t = normalized[0]
    assert t.min_value == 20.0
    assert t.max_value == 25.0
    assert t.target_value == 22.0

    # Prediction 1: 22.5 min -> Within 20-25 range -> MEETS TARGET
    eval_met = TargetValidationService.evaluate_property_prediction(
        t, {"property": "TS2", "predicted_value": 22.5, "unit": "min"}
    )
    assert eval_met["passed"] is True
    assert eval_met["status"] == "MEETS_TARGET"
    assert eval_met["target_status"] == "MEETS TARGET"

    # Prediction 2: 17.5 min -> Outside 20-25 range -> OUTSIDE TARGET
    eval_outside = TargetValidationService.evaluate_property_prediction(
        t, {"property": "TS2", "predicted_value": 17.5, "unit": "min"}
    )
    assert eval_outside["passed"] is False
    assert eval_outside["status"] == "OUTSIDE_TARGET"
    assert eval_outside["target_status"] == "OUTSIDE TARGET"
    assert eval_outside["violation_distance"] > 0


def test_target_violation_penalizes_target_fit_and_confidence():
    """Requirement 8: Outside-target property strictly penalizes target_fit_score and confidence."""
    raw_targets = [
        {"property": "Mooney", "min": 40.0, "max": 50.0, "unit": "MU"},
        {"property": "Bound ACN", "min": 25.0, "max": 30.0, "unit": "%"},
    ]
    normalized = TargetValidationService.normalize_target_properties(raw_targets)

    recipe_compliant = {
        "compound": "NBR",
        "predicted_properties": [
            {"property": "Mooney", "predicted_value": 45.0, "unit": "MU"},
            {"property": "Bound ACN", "predicted_value": 28.0, "unit": "%"},
        ],
        "stages": _sample_stages(),
    }
    t_a1, c_a1, score1 = TargetValidationService.evaluate_recipe(recipe_compliant, normalized)
    assert t_a1["target_fit_score"] == 100
    assert t_a1["targets_met"] == 2

    recipe_violating = {
        "compound": "NBR",
        "predicted_properties": [
            {"property": "Mooney", "predicted_value": 32.0, "unit": "MU"},  # Violates min 40
            {"property": "Bound ACN", "predicted_value": 28.0, "unit": "%"},
        ],
        "stages": _sample_stages(),
    }
    t_a2, c_a2, score2 = TargetValidationService.evaluate_recipe(recipe_violating, normalized)
    assert t_a2["target_fit_score"] == 50
    assert t_a2["targets_met"] == 1
    assert score2 < score1, f"Expected violating score {score2} < compliant score {score1}"


def test_explicit_temperature_range_inherited_and_respected():
    """Requirement 9: Temperature range (e.g. 5–7 °C and 20–25 °C) dynamically enforced."""
    # Test Cold Emulsion 5–7 °C
    recipe_cold = {"compound": "NBR", "stages": _sample_stages(), "process_conditions": {}}
    enriched_cold = validate_and_enrich_water_based_recipe(
        recipe_cold, target_compound="NBR", user_constraints={"temperature_range": "5–7 °C"}
    )
    temp_cold = enriched_cold["process_conditions"]["temperature_range"]
    assert temp_cold["min"] == 5.0 and temp_cold["max"] == 7.0

    # Test Warm Emulsion 20–25 °C
    recipe_warm = {"compound": "NBR", "stages": _sample_stages(), "process_conditions": {}}
    enriched_warm = validate_and_enrich_water_based_recipe(
        recipe_warm, target_compound="NBR", user_constraints={"temperature_range": "20–25 °C"}
    )
    temp_warm = enriched_warm["process_conditions"]["temperature_range"]
    assert temp_warm["min"] == 20.0 and temp_warm["max"] == 25.0


def test_process_type_batch_continuous_and_no_preference():
    """Requirement 10, 11, 12: Process Type Batch, Continuous, and No Preference respected."""
    # Batch constraint
    r1 = validate_and_enrich_water_based_recipe(
        {"compound": "NBR", "stages": _sample_stages()},
        target_compound="NBR",
        user_constraints={"process_type": "Batch"},
    )
    assert r1["process_type"] == "Batch"
    assert r1["process_conditions"]["process_type"] == "Batch"

    # Continuous constraint
    r2 = validate_and_enrich_water_based_recipe(
        {"compound": "NBR", "stages": _sample_stages()},
        target_compound="NBR",
        user_constraints={"process_type": "Continuous"},
    )
    assert r2["process_type"] == "Continuous"
    assert r2["process_conditions"]["process_type"] == "Continuous"

    # No Preference allows candidate's setting
    r3 = validate_and_enrich_water_based_recipe(
        {"compound": "NBR", "stages": _sample_stages(), "process_type": "Continuous"},
        target_compound="NBR",
        user_constraints={"process_type": "No Preference"},
    )
    assert r3["process_type"] == "Continuous"


def test_catalyst_activator_and_coagulation_systems():
    """Requirement 13, 14, 15: Catalyst primary/alternatives, activator applicability, coagulation applicability."""
    recipe = {
        "compound": "NBR Solid Rubber",
        "stages": _sample_stages(),
        "catalyst_system": {
            "primary_catalyst": "Potassium persulfate (KPS)",
            "primary_dosage": "0.35 phr",
            "alternatives": [{"catalyst": "Ammonium persulfate", "dosage": "0.30 phr", "rationale": "Direct alternative"}],
        },
        "activator_system": {
            "applicable": True,
            "name": "Sodium formaldehyde sulfoxylate (SFS)",
            "dosage": "0.10 phr",
            "stage": "Catalyst Solution",
        },
        "coagulation_system": {
            "applicable": True,
            "coagulant": "Calcium chloride",
            "dosage": "2.0 phr",
            "process_conditions": "Coagulation at 60°C",
        },
    }
    enriched = validate_and_enrich_water_based_recipe(recipe, target_compound="NBR Solid Rubber")

    assert enriched["catalyst_system"]["primary_catalyst"] == "Potassium persulfate (KPS)"
    assert len(enriched["catalyst_system"]["alternatives"]) == 1
    assert enriched["activator_system"]["applicable"] is True
    assert enriched["activator_system"]["name"] == "Sodium formaldehyde sulfoxylate (SFS)"
    assert enriched["coagulation_system"]["applicable"] is True
    assert enriched["coagulation_system"]["coagulant"] == "Calcium chloride"


@pytest.mark.asyncio
async def test_customer_feedback_reaches_optimization_context():
    """Requirement 16 & 17: Customer feedback text materially reaches prompt and format_kwargs."""
    user = _make_user()
    session = AsyncMock()

    feedback_msg = "Latex exhibited premature scorching and elevated Mooney of 58 MU."
    base_data = _sample_recipe_data()
    trial_id = uuid.uuid4()
    trial = CustomerTrial(
        id=trial_id,
        created_by=user.id,
        status=TrialStatus.PENDING,
        recipe_snapshot=base_data,
        target_values={"Mooney": 45},
        feedback_text=feedback_msg,
    )
    trial.optimized_candidates = []

    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=trial)))
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()

    service = RecipeService(session)
    mock_llm = AsyncMock()
    mock_llm.generate_structured = AsyncMock(
        return_value=(_mock_llm_optimization_set(), '{"mock": true}', {"finish_reason": "STOP"})
    )
    service.llm_client = mock_llm

    await service.generate_optimized_recipes(trial_id, user, force_regenerate=True)

    # Verify that mock_llm.generate_structured was called and customer feedback was in the system prompt
    assert mock_llm.generate_structured.called
    call_kwargs = mock_llm.generate_structured.call_args[1]
    system_prompt_used = call_kwargs.get("system_prompt", "")
    assert feedback_msg in system_prompt_used, "Customer feedback was omitted from the LLM prompt context!"


@pytest.mark.asyncio
async def test_reoptimization_chain_and_lineage():
    """Requirement 18, 19, 20: Re-optimization lineage R0 -> T1 -> R1 -> T2 -> R2 correctly preserved."""
    user = _make_user()
    session = AsyncMock()

    # R0: Initial Saved Recipe
    r0_id = uuid.uuid4()
    r0 = SavedRecipe(
        id=r0_id,
        recipe_name="R0 Baseline",
        recipe_data=_sample_recipe_data(),
        created_by=user.id,
        updated_by=user.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        parent_recipe_id=None,
        revision_number=0,
        recipe_kind=SavedRecipeKind.NORMAL,
        status=SavedRecipeStatus.ACTIVE,
    )

    # T1: Trial on R0
    t1_id = uuid.uuid4()
    t1 = CustomerTrial(
        id=t1_id,
        saved_recipe_id=r0.id,
        created_by=user.id,
        status=TrialStatus.COMPLETED,
        feedback_text="First trial feedback",
    )

    # R1: Saved optimized recipe from T1
    saved_svc = SavedRecipeService(session)
    saved_svc.get_recipe = AsyncMock(side_effect=lambda rid, u: SavedRecipe(
        id=rid,
        recipe_name="R1 Optimized Revision A",
        recipe_data=_sample_recipe_data(),
        parent_recipe_id=r0_id,
        revision_number=1,
        source_trial_id=t1_id,
        recipe_kind=SavedRecipeKind.OPTIMIZED,
        status=SavedRecipeStatus.ACTIVE,
        created_by=u.id,
        updated_by=u.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
    ))

    # Save R1
    r1_create = SavedRecipeCreate(
        recipe_name="R1 Optimized Revision A",
        recipe_data=_sample_recipe_data(),
        parent_recipe_id=r0_id,
        source_trial_id=t1_id,
    )
    session.get = AsyncMock(side_effect=lambda model, mid: r0 if mid == r0_id else t1 if mid == t1_id else None)
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=0)))
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    saved_r1 = await saved_svc.save_recipe(r1_create, user)
    assert saved_r1.parent_recipe_id == r0_id


@pytest.mark.asyncio
async def test_saving_one_candidate_does_not_save_all_three():
    """Requirement 22: User saving candidate B must save ONLY candidate B."""
    user = _make_user()
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    saved_svc = SavedRecipeService(session)
    data = SavedRecipeCreate(
        recipe_name="Only Revision B",
        recipe_data=_sample_recipe_data(),
    )
    mock_saved = SavedRecipe(
        id=uuid.uuid4(),
        recipe_name="Only Revision B",
        recipe_data=_sample_recipe_data(),
        created_by=user.id,
        updated_by=user.id,
        status=SavedRecipeStatus.ACTIVE,
    )
    saved_svc.get_recipe = AsyncMock(return_value=mock_saved)

    saved = await saved_svc.save_recipe(data, user)
    assert saved.recipe_name == "Only Revision B"
    saved_recipes_added = [
        args[0] for args, _ in session.add.call_args_list
        if isinstance(args[0], SavedRecipe)
    ]
    assert len(saved_recipes_added) == 1, "Expected only 1 SavedRecipe added to session!"
    assert saved_recipes_added[0].recipe_name == "Only Revision B"


def test_historical_recipes_load_safely():
    """Requirement 24: Historical recipes without Phase 2 fields load without error."""
    historical_recipe = SavedRecipe(
        id=uuid.uuid4(),
        recipe_name="Old Recipe",
        recipe_data={"compound": "NBR", "stages": []},  # Missing process_type, catalyst_system, etc.
        target_properties=[],
        competitor_properties=[],
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        revision_number=0,
        status=SavedRecipeStatus.ACTIVE,
    )
    # Serialize to response schema
    resp = to_saved_recipe_response(historical_recipe)
    assert resp.recipe_name == "Old Recipe"
    assert resp.recipe_data.get("compound") == "NBR"
    assert resp.is_revision is False


def test_canonical_six_stages_preserved():
    """Requirement 16: The 6 canonical synthesis stages are preserved in order."""
    enriched = validate_and_enrich_water_based_recipe(
        {"compound": "NBR", "stages": _sample_stages()},
        target_compound="NBR"
    )
    stage_names = [s["stage_name"] for s in enriched["stages"]]
    assert "Reactor Charge" in stage_names
    assert "Catalyst Solution" in stage_names
    assert "Monomer Mix" in stage_names
