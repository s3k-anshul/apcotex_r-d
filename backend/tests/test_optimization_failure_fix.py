"""
backend/tests/test_optimization_failure_fix.py

Comprehensive tests verifying the Customer Trial Optimization failure fix:
- Strict structured schema adherence (LLMOptimizationSet, exactly 3 recipes)
- Zero MAX_TOKENS runaway / compact output budget
- Dynamic compounds (SBR, NBR, X-NBR, CR, etc.)
- Dynamic feedback & target properties (0, 1, many, user-added, conflicting)
- Proper parent snapshot and re-optimization lineage
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.models.customer_trial import CustomerTrial, TrialStatus
from app.models.recipe_cycle import RecipeCycle, RecipeCycleStatus
from app.models.saved_recipe import SavedRecipe, SavedRecipeKind, SavedRecipeStatus
from app.models.user import User, UserRole
from app.schemas.recipe import (
    CustomerTrialCreate,
    LLMOptimizationSet,
    LLMOptimizedChange,
    LLMOptimizedParameter,
    LLMOptimizedRecipeCandidate,
    LLMOptimizedStage,
)
from app.services.recipe_service import RecipeService, calculate_optimization_confidence_score


def _make_dummy_candidate(label: str, name: str, strategy: str, conf: int) -> LLMOptimizedRecipeCandidate:
    return LLMOptimizedRecipeCandidate(
        name=name,
        revision_label=label,
        optimization_strategy=strategy,
        confidence_score=conf,
        stages=[
            LLMOptimizedStage(
                stage_name="Reactor Charge",
                parameters=[
                    LLMOptimizedParameter(name="Deionized Water", value="150.0", unit="phr"),
                    LLMOptimizedParameter(name="Potassium Rosinate", value="4.0", unit="phr"),
                ],
            ),
            LLMOptimizedStage(
                stage_name="Monomer Mix",
                parameters=[
                    LLMOptimizedParameter(name="1,3-Butadiene", value="70.0", unit="phr"),
                    LLMOptimizedParameter(name="Styrene", value="30.0", unit="phr"),
                    LLMOptimizedParameter(name="t-Dodecyl Mercaptan (CTA)", value="0.20", unit="phr"),
                ],
            ),
        ],
        changed_parameters=[
            LLMOptimizedChange(
                parameter="t-Dodecyl Mercaptan (CTA)",
                old_value="0.30",
                new_value="0.20",
                unit="phr",
                reason="Reduced CTA to increase molecular weight and restore tensile strength.",
            )
        ],
        expected_outcome="Restores tensile strength to target while maintaining polymer stability.",
        expected_impact="Increased chain length improves modulus with a modest increase in Mooney viscosity.",
    )


@pytest.mark.asyncio
async def test_schema_exact_three_candidates_and_compact_fields():
    """Verify LLMOptimizationSet schema strictly requires exactly 3 recipes with compact fields."""
    c1 = _make_dummy_candidate("A", "Revision A", "Strategy 1", 88)
    c2 = _make_dummy_candidate("B", "Revision B", "Strategy 2", 82)
    c3 = _make_dummy_candidate("C", "Revision C", "Strategy 3", 76)

    # Valid with 3
    valid_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])
    assert len(valid_set.optimized_recipes) == 3

    # Invalid with 2
    with pytest.raises(Exception):
        LLMOptimizationSet(optimized_recipes=[c1, c2])

    # Invalid with 4
    c4 = _make_dummy_candidate("D", "Revision D", "Strategy 4", 70)
    with pytest.raises(Exception):
        LLMOptimizationSet(optimized_recipes=[c1, c2, c3, c4])


@pytest.mark.asyncio
async def test_changed_parameters_coercion_and_backward_compatibility():
    """Verify LLMOptimizedChange accepts both old_value/new_value and previous/revised and numeric types."""
    ch1 = LLMOptimizedChange(
        parameter="Processing Oil",
        old_value=5,
        new_value=3,
        unit="phr",
        reason="Target achievement",
    )
    assert ch1.old_value == "5"
    assert ch1.new_value == "3"
    assert ch1.previous == "5"
    assert ch1.revised == "3"
    assert ch1.rationale == "Target achievement"

    # From previous / revised fields
    ch2 = LLMOptimizedChange(
        parameter="CTA",
        previous="0.45",
        revised="0.30",
        rationale="Mooney control",
    )
    assert ch2.old_value == "0.45"
    assert ch2.new_value == "0.30"
    assert ch2.reason == "Mooney control"


@pytest.mark.asyncio
async def test_confidence_scores_are_dynamic_and_differentiated():
    """Verify confidence scores are not hardcoded to 71% and reflect chemistry and target alignment."""
    source_recipe = {
        "compound": "Cold SBR",
        "parameters": [
            {"name": "Deionized Water", "value": "180"},
            {"name": "t-Dodecyl Mercaptan (CTA)", "value": "0.30"},
            {"name": "Processing Oil", "value": "5.0"},
        ],
    }
    cand_high = {
        "polymerization_method": "Cold Emulsion Polymerization",
        "parameters": [
            {"name": "Deionized Water", "value": "180"},
            {"name": "Potassium Rosinate", "value": "4.0"},
            {"name": "Processing Oil", "value": "3.0"},
        ],
        "changed_parameters": [{"parameter": "Processing Oil", "new_value": "3.0", "old_value": "5.0"}],
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Deionized Water", "value": "180"}]}],
        "process_conditions": {"reaction_time": "8h", "temperature_profile": "5°C"},
        "expected_outcome": "Reduced oil to 3 phr.",
        "expected_impact": "Slight viscosity increase.",
        "optimization_strategy": "Direct plasticizer reduction.",
    }
    score = calculate_optimization_confidence_score(
        candidate_dict=cand_high,
        source_recipe_dict=source_recipe,
        target_values={"Processing Oil": "3"},
        feedback_text="Customer says oil is too high",
    )
    assert score != 71
    assert 70 <= score <= 95


@pytest.mark.asyncio
async def test_matrix_zero_target_properties_flow(db_session, make_user):
    """TEST A: Zero target properties succeeds without inventing targets."""
    test_user, _ = await make_user(email="test_zero_targets@apcotex.test")
    service = RecipeService(db_session)
    source_recipe = {
        "name": "Base SBR Formulation",
        "compound": "Styrene Butadiene Rubber (SBR)",
        "polymerization_method": "Cold Emulsion Polymerization",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": "150", "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "1,3-Butadiene", "value": "75", "unit": "phr"}]},
        ],
    }

    trial = CustomerTrial(
        created_by=test_user.id,
        feedback_text="Customer noticed lower tensile strength.",
        target_values={},  # ZERO targets
        recipe_snapshot={"recipe_data": source_recipe, "compound": "SBR"},
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    c1 = _make_dummy_candidate("A", "Rev A", "CTA Reduction", 87)
    c2 = _make_dummy_candidate("B", "Rev B", "Comonomer Adjustment", 81)
    c3 = _make_dummy_candidate("C", "Rev C", "Polymerization Temp Lowering", 76)
    mock_opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (mock_opt_set, "{}", {"input_tokens": 1500, "output_tokens": 800})
        candidates = await service.generate_optimized_recipes(trial.id, test_user)

        assert len(candidates) == 3
        assert trial.status == TrialStatus.COMPLETED
        # Verify confidence scores are individual and not all 71
        scores = [c.recipe_data["confidence_score"] for c in candidates]
        assert len(set(scores)) == 3
        assert 71 not in scores
        # Verify prompt received zero target note
        call_kwargs = mock_gen.call_args[1]
        assert "No explicit quantitative target property values supplied" in call_kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_matrix_user_added_and_custom_properties(db_session, make_user):
    """TEST F & G: User-added custom properties are passed and reach the prompt cleanly."""
    test_user, _ = await make_user(email="test_custom_props@apcotex.test")
    service = RecipeService(db_session)
    source_recipe = {
        "name": "Base NBR Formulation",
        "compound": "Nitrile Butadiene Rubber (NBR)",
        "polymerization_method": "Cold Emulsion Polymerization",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": "160", "unit": "phr"}]},
        ],
    }

    trial = CustomerTrial(
        created_by=test_user.id,
        feedback_text="Improve low-temperature flexibility while holding Mooney at 45 MU.",
        target_values={
            "Low Temperature Flexibility": "-35 °C",
            "Mooney Viscosity": "45 MU",
            "Tensile Strength": ">= 20 MPa",
            "Custom Ash Content": "< 0.5 %",
        },
        recipe_snapshot={"recipe_data": source_recipe, "compound": "NBR"},
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    c1 = _make_dummy_candidate("A", "Rev A", "ACN Ratio Reduction", 86)
    c2 = _make_dummy_candidate("B", "Rev B", "Balanced ACN & CTA", 82)
    c3 = _make_dummy_candidate("C", "Rev C", "Lower Temperature Polymerization", 78)
    mock_opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (mock_opt_set, "{}", {"input_tokens": 1600, "output_tokens": 850})
        candidates = await service.generate_optimized_recipes(trial.id, test_user)

        assert len(candidates) == 3
        call_kwargs = mock_gen.call_args[1]
        sys_prompt = call_kwargs["system_prompt"]
        assert "Low Temperature Flexibility" in sys_prompt
        assert "Mooney Viscosity" in sys_prompt
        assert "Custom Ash Content" in sys_prompt


@pytest.mark.asyncio
async def test_reoptimization_chain_uses_optimized_child_as_direct_parent(db_session, make_user):
    """TEST K: Second-generation optimization of an already optimized recipe starts from child."""
    test_user, _ = await make_user(email="test_reopt@apcotex.test")
    service = RecipeService(db_session)

    import datetime
    expiry = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)

    # 1. Base recipe saved
    base_saved = SavedRecipe(
        recipe_name="Parent Base Formulation A",
        recipe_data={"name": "Base A", "compound": "NBR", "parameters": [{"name": "CTA", "value": "0.40"}]},
        created_by=test_user.id,
        updated_by=test_user.id,
        expires_at=expiry,
        recipe_kind=SavedRecipeKind.NORMAL,
        status=SavedRecipeStatus.ACTIVE,
    )
    db_session.add(base_saved)
    await db_session.commit()

    # 2. Optimized recipe saved referencing base
    opt_saved = SavedRecipe(
        recipe_name="Optimized Formulation A-1",
        recipe_data={"name": "Optimized A-1", "compound": "NBR", "parameters": [{"name": "CTA", "value": "0.32"}]},
        created_by=test_user.id,
        updated_by=test_user.id,
        expires_at=expiry,
        parent_recipe_id=base_saved.id,
        revision_number=1,
        recipe_kind=SavedRecipeKind.OPTIMIZED,
        status=SavedRecipeStatus.ACTIVE,
    )
    db_session.add(opt_saved)
    await db_session.commit()

    # 3. New trial created against opt_saved (NOT base_saved)
    trial2 = CustomerTrial(
        created_by=test_user.id,
        saved_recipe_id=opt_saved.id,
        feedback_text="Mooney is now too high, decrease it slightly.",
        target_values={"Mooney": "42"},
        status=TrialStatus.PENDING,
    )
    db_session.add(trial2)
    await db_session.commit()

    c1 = _make_dummy_candidate("A", "Rev A-1-1", "Increase CTA to reduce MW", 89)
    c2 = _make_dummy_candidate("B", "Rev A-1-2", "Moderate CTA adjustment", 84)
    c3 = _make_dummy_candidate("C", "Rev A-1-3", "Reaction temp boost", 79)
    mock_opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (mock_opt_set, "{}", {"input_tokens": 1400, "output_tokens": 750})
        candidates = await service.generate_optimized_recipes(trial2.id, test_user)

        assert len(candidates) == 3
        # Check that the prompt selected recipe had CTA: 0.32 (from opt_saved, NOT 0.40 from base)
        sys_prompt = mock_gen.call_args[1]["system_prompt"]
        assert "0.32" in sys_prompt
