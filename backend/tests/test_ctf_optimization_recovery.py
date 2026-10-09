"""
backend/tests/test_ctf_optimization_recovery.py

Regression test suite for CTF Optimized-Recipe Selection and Re-Optimization:
- TEST 1: optimization_strategy > 200 characters is accepted without truncation or error
- TEST 2: Gemini returns exactly 3 valid candidates -> success
- TEST 3: Gemini returns 2 candidates -> request missing 1 -> final result = exactly 3
- TEST 4: Gemini returns 1 candidate -> request missing 2 -> final result = exactly 3
- TEST 5: Gemini returns duplicate candidate during recovery -> duplicate rejected -> another candidate requested
- TEST 6: Gemini returns invalid candidate + valid candidates -> preserve valid -> recover missing
- TEST 7: Selected optimized recipe as source -> CTF optimization succeeds -> exactly 3 new revisions -> lineage preserved
- TEST 8: Original recipe as source -> existing behavior unchanged
- TEST 9: GENERAL mode with no target properties -> exactly 3 candidates
- TEST 10: STRICT_TARGET mode -> exactly 3 candidates -> target evaluation preserved
- TEST 11: Customer feedback 'hardness is too low' -> feedback appears in optimization context
- TEST 12: Repeated optimization: Original -> Optimized -> Re-optimized -> lineage intact
"""
import datetime
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.models.customer_trial import CustomerTrial, TrialStatus
from app.models.recipe_cycle import RecipeCycle, RecipeCycleStatus
from app.models.saved_recipe import SavedRecipe, SavedRecipeKind, SavedRecipeStatus
from app.models.user import User, UserRole
from app.schemas.recipe import (
    CustomerTrialCreate,
    LLMAdditionalOptimizationCandidates,
    LLMOptimizationSet,
    LLMOptimizedChange,
    LLMOptimizedParameter,
    LLMOptimizedRecipeCandidate,
    LLMOptimizedStage,
    LLMProcessConditions,
    LLMReactionTime,
)
from app.services.recipe_service import (
    RecipeService,
    extract_valid_candidates_from_response,
    is_materially_duplicate_candidate,
)


def _make_candidate(
    label: str = "A",
    name: str = None,
    strategy: str = None,
    param_name: str = None,
    old_val: str = None,
    new_val: str = None,
    conf: int = 85,
) -> LLMOptimizedRecipeCandidate:
    if name is None:
        name = f"Revision {label} - Standard Optimization"
    if strategy is None:
        if label == "B":
            strategy = "Comonomer ratio adjustment to modulate glass transition temperature and modulus."
        elif label == "C":
            strategy = "Thermal process condition optimization to alter polymerization kinetics."
        else:
            strategy = "Conservative modifier adjustment to control chain length and viscosity."

    if param_name is None:
        if label == "B":
            param_name = "Styrene Comonomer"
            old_val = old_val or "30.0"
            new_val = new_val or "26.0"
        elif label == "C":
            param_name = "Polymerization Temperature"
            old_val = old_val or "10.0"
            new_val = new_val or "6.0"
        else:
            param_name = "t-Dodecyl Mercaptan (CTA)"
            old_val = old_val or "0.30"
            new_val = new_val or "0.20"
    else:
        old_val = old_val or "0.30"
        new_val = new_val or "0.20"

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
                    LLMOptimizedParameter(name=param_name, value=new_val, unit="phr"),
                ],
            ),
        ],
        process_conditions=LLMProcessConditions(
            reaction_time=LLMReactionTime(value="6.0", unit="hours"),
            temperature_range="5-10 °C",
        ),
        changed_parameters=[
            LLMOptimizedChange(
                parameter=param_name,
                old_value=old_val,
                new_value=new_val,
                unit="phr",
                reason=f"Tuned {param_name} to meet target properties.",
            )
        ],
        expected_outcome=f"Adjusted {param_name} to achieve target property values.",
        expected_impact=f"Modification of {param_name} modifies molecular architecture appropriately.",
    )


# ==============================================================================
# TEST 1: optimization_strategy > 200 characters is accepted without error
# ==============================================================================
def test_test1_optimization_strategy_over_200_chars_accepted():
    """Verify that a scientifically thorough optimization_strategy > 200 characters is accepted."""
    long_strategy = (
        "Thermodynamically optimized copolymerization protocol: Increase chain-transfer agent "
        "(t-dodecyl mercaptan) dosing sequentially across the monomer feed stage from 0.22 phr to 0.35 phr "
        "to constrain peak molecular weight development and attenuate Mooney viscosity build-up. Concurrently, "
        "raise emulsifier (potassium disproportionated rosinate) concentration by 0.5 phr to preserve latex colloidal "
        "stability and minimize coagulum generation under higher conversion shear."
    )
    assert len(long_strategy) > 200, f"Test setup error: strategy is {len(long_strategy)} chars, needs > 200"

    cand = _make_candidate(strategy=long_strategy)
    assert cand.optimization_strategy == long_strategy

    opt_set = LLMOptimizationSet(
        optimized_recipes=[
            cand,
            _make_candidate(label="B", name="Revision B", strategy=long_strategy),
            _make_candidate(label="C", name="Revision C", strategy=long_strategy),
        ]
    )
    assert len(opt_set.optimized_recipes) == 3
    assert opt_set.optimized_recipes[0].optimization_strategy == long_strategy


# ==============================================================================
# TEST 2: Gemini returns exactly 3 valid candidates -> success
# ==============================================================================
@pytest.mark.asyncio
async def test_test2_gemini_returns_exactly_3_valid_candidates_success(db_session, make_user):
    """Verify direct success when Gemini returns exactly 3 valid candidates on initial attempt."""
    user, _ = await make_user(email="test2_user@apcotex.test")
    service = RecipeService(db_session)

    trial = CustomerTrial(
        created_by=user.id,
        feedback_text="Customer reported high Mooney viscosity.",
        target_values={"Mooney Viscosity": "45"},
        recipe_snapshot={
            "recipe_data": {
                "name": "Base SBR Formulation",
                "compound": "SBR",
                "parameters": [{"name": "CTA", "value": "0.20", "unit": "phr"}],
            }
        },
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    c1 = _make_candidate("A", "Rev A", "Increase CTA", "t-Dodecyl Mercaptan (CTA)", "0.20", "0.32", 88)
    c2 = _make_candidate("B", "Rev B", "Adjust Temperature", "Polymerization Temp", "5", "8", 82)
    c3 = _make_candidate("C", "Rev C", "Monomer Balancing", "Styrene", "30", "28", 78)
    opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (opt_set, "{}", {"prompt_tokens": 500, "completion_tokens": 600})

        candidates = await service.generate_optimized_recipes(trial.id, user)
        assert len(candidates) == 3
        assert mock_gen.call_count == 1
        assert trial.status == TrialStatus.COMPLETED


# ==============================================================================
# TEST 3: Gemini returns 2 candidates -> request missing 1 -> total exactly 3
# ==============================================================================
@pytest.mark.asyncio
async def test_test3_gemini_returns_2_candidates_recovers_missing_1(db_session, make_user):
    """Verify targeted recovery when initial response yields 2 candidates and missing 1 is recovered."""
    user, _ = await make_user(email="test3_user@apcotex.test")
    service = RecipeService(db_session)

    trial = CustomerTrial(
        created_by=user.id,
        feedback_text="Tensile strength needs improvement.",
        target_values={"Tensile": "22 MPa"},
        recipe_snapshot={
            "recipe_data": {
                "name": "Base Formulation",
                "compound": "NBR",
                "parameters": [{"name": "CTA", "value": "0.30"}],
            }
        },
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    c1 = _make_candidate("A", "Rev A", "Lower CTA", "CTA", "0.30", "0.22", 87)
    c2 = _make_candidate("B", "Rev B", "Higher ACN Ratio", "Acrylonitrile", "28", "33", 83)
    c3 = _make_candidate("C", "Rev C", "Redox Initiator Boost", "Pinane Hydroperoxide", "0.08", "0.12", 79)

    raw_2_candidates_json = json.dumps({
        "optimized_recipes": [c1.model_dump(), c2.model_dump()]
    })

    recovery_set = LLMAdditionalOptimizationCandidates(additional_recipes=[c3])

    call_count = 0

    async def mock_generate_structured(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call returns 2 candidates (failing exact 3 schema validator)
            # but extract_valid_candidates_from_response extracts both valid candidates
            return (None, raw_2_candidates_json, {"raw_response_text": raw_2_candidates_json})
        else:
            # Recovery call requesting missing 1 candidate
            return (recovery_set, json.dumps(recovery_set.model_dump()), {})

    with patch.object(service.llm_client, "generate_structured", side_effect=mock_generate_structured):
        candidates = await service.generate_optimized_recipes(trial.id, user)
        assert len(candidates) == 3
        assert call_count == 2
        names = [c.recipe_data["name"] for c in candidates]
        assert "Rev A" in names
        assert "Rev B" in names
        assert "Rev C" in names


# ==============================================================================
# TEST 4: Gemini returns 1 candidate -> request missing 2 -> total exactly 3
# ==============================================================================
@pytest.mark.asyncio
async def test_test4_gemini_returns_1_candidate_recovers_missing_2(db_session, make_user):
    """Verify targeted recovery when initial response yields 1 candidate and missing 2 are recovered."""
    user, _ = await make_user(email="test4_user@apcotex.test")
    service = RecipeService(db_session)

    trial = CustomerTrial(
        created_by=user.id,
        feedback_text="Hardness is too high.",
        target_values={"Hardness": "65 Shore A"},
        recipe_snapshot={
            "recipe_data": {
                "name": "Base NBR Formulation",
                "compound": "NBR",
                "parameters": [{"name": "ACN", "value": "35"}],
            }
        },
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    c1 = _make_candidate("A", "Rev A", "Reduce ACN", "ACN", "35", "30", 86)
    c2 = _make_candidate("B", "Rev B", "Increase Plasticizer", "Processing Oil", "5", "8", 81)
    c3 = _make_candidate("C", "Rev C", "Adjust Crosslink Density", "DVB", "0.2", "0.1", 76)

    raw_1_candidate_json = json.dumps({"optimized_recipes": [c1.model_dump()]})
    recovery_set = LLMAdditionalOptimizationCandidates(additional_recipes=[c2, c3])

    call_count = 0

    async def mock_generate_structured(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return (None, raw_1_candidate_json, {"raw_response_text": raw_1_candidate_json})
        else:
            return (recovery_set, json.dumps(recovery_set.model_dump()), {})

    with patch.object(service.llm_client, "generate_structured", side_effect=mock_generate_structured):
        candidates = await service.generate_optimized_recipes(trial.id, user)
        assert len(candidates) == 3
        assert call_count == 2


# ==============================================================================
# TEST 5: Gemini returns duplicate candidate during recovery -> rejected & retried
# ==============================================================================
@pytest.mark.asyncio
async def test_test5_duplicate_candidate_rejected_during_recovery(db_session, make_user):
    """Verify deterministic duplicate detection rejects a duplicate returned in recovery round 1."""
    user, _ = await make_user(email="test5_user@apcotex.test")
    service = RecipeService(db_session)

    trial = CustomerTrial(
        created_by=user.id,
        feedback_text="Viscosity control needed.",
        recipe_snapshot={
            "recipe_data": {
                "name": "Base Formulation",
                "compound": "SBR",
                "parameters": [{"name": "CTA", "value": "0.25"}],
            }
        },
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    c1 = _make_candidate("A", "Rev A", "Increase CTA", "CTA", "0.25", "0.35", 85)
    c2 = _make_candidate("B", "Rev B", "Lower Temp", "Temp", "10", "6", 80)
    # Duplicate of c1 with identical changed parameter modification
    c_dup = _make_candidate("C", "Rev C Duplicate", "Increase CTA duplicate", "CTA", "0.25", "0.35", 84)
    # Distinct candidate for round 2
    c3 = _make_candidate("C", "Rev C Distinct", "Emulsifier modification", "Emulsifier", "3.5", "4.5", 77)

    raw_2_json = json.dumps({"optimized_recipes": [c1.model_dump(), c2.model_dump()]})
    call_count = 0

    async def mock_generate_structured(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return (None, raw_2_json, {"raw_response_text": raw_2_json})
        elif call_count == 2:
            # Recovery Round 1 returns duplicate of c1
            dup_set = LLMAdditionalOptimizationCandidates(additional_recipes=[c_dup])
            return (dup_set, json.dumps(dup_set.model_dump()), {})
        else:
            # Recovery Round 2 returns distinct c3
            valid_set = LLMAdditionalOptimizationCandidates(additional_recipes=[c3])
            return (valid_set, json.dumps(valid_set.model_dump()), {})

    with patch.object(service.llm_client, "generate_structured", side_effect=mock_generate_structured):
        candidates = await service.generate_optimized_recipes(trial.id, user)
        assert len(candidates) == 3
        # Should have called LLM 3 times: initial + round 1 (dup rejected) + round 2 (distinct accepted)
        assert call_count == 3
        names = [c.recipe_data["name"] for c in candidates]
        assert "Rev C Duplicate" not in names
        assert "Rev C Distinct" in names


# ==============================================================================
# TEST 6: Invalid candidate + valid candidates -> preserves valid & recovers missing
# ==============================================================================
@pytest.mark.asyncio
async def test_test6_invalid_candidate_with_valid_candidates_recovers_missing(db_session, make_user):
    """Verify that when 1 candidate is malformed in the payload, valid candidates are preserved."""
    user, _ = await make_user(email="test6_user@apcotex.test")
    service = RecipeService(db_session)

    trial = CustomerTrial(
        created_by=user.id,
        feedback_text="Improve reaction conversion.",
        recipe_snapshot={
            "recipe_data": {
                "name": "Base Formulation",
                "compound": "SBR",
                "parameters": [{"name": "Water", "value": "150"}],
            }
        },
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    c1 = _make_candidate("A", "Rev A", "Strategy 1", "CTA", "0.20", "0.25", 85)
    c2 = _make_candidate("B", "Rev B", "Strategy 2", "Temp", "5", "8", 82)
    c3 = _make_candidate("C", "Rev C", "Strategy 3", "Water", "150", "140", 78)

    # Payload with 2 valid candidates and 1 malformed candidate
    malformed_candidate = {"name": "Malformed Candidate", "stages": "invalid_not_a_list", "confidence_score": "not_int"}
    raw_mixed_json = json.dumps({
        "optimized_recipes": [c1.model_dump(), c2.model_dump(), malformed_candidate]
    })

    recovery_set = LLMAdditionalOptimizationCandidates(additional_recipes=[c3])
    call_count = 0

    async def mock_generate_structured(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return (None, raw_mixed_json, {"raw_response_text": raw_mixed_json})
        else:
            return (recovery_set, json.dumps(recovery_set.model_dump()), {})

    with patch.object(service.llm_client, "generate_structured", side_effect=mock_generate_structured):
        candidates = await service.generate_optimized_recipes(trial.id, user)
        assert len(candidates) == 3
        assert call_count == 2
        names = [c.recipe_data["name"] for c in candidates]
        assert "Rev A" in names
        assert "Rev B" in names
        assert "Rev C" in names


# ==============================================================================
# TEST 7: Selected optimized recipe as source -> lineage preserved
# ==============================================================================
@pytest.mark.asyncio
async def test_test7_selected_optimized_recipe_as_source_preserves_lineage(db_session, make_user):
    """Verify that optimizing an already optimized saved recipe preserves lineage and parent references."""
    user, _ = await make_user(email="test7_user@apcotex.test")
    service = RecipeService(db_session)
    expiry = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)

    # 1. Base recipe
    base_recipe = SavedRecipe(
        recipe_name="Base Commercial NBR",
        recipe_data={
            "name": "Base Commercial NBR",
            "compound": "NBR",
            "parameters": [{"name": "CTA", "value": "0.35"}],
        },
        created_by=user.id,
        updated_by=user.id,
        expires_at=expiry,
        recipe_kind=SavedRecipeKind.NORMAL,
        status=SavedRecipeStatus.ACTIVE,
    )
    db_session.add(base_recipe)
    await db_session.commit()

    # 2. Optimized recipe (Revision 1)
    opt_recipe = SavedRecipe(
        recipe_name="Optimized NBR Rev 1",
        recipe_data={
            "name": "Optimized NBR Rev 1",
            "compound": "NBR",
            "parameters": [{"name": "CTA", "value": "0.28"}],
            "catalyst_system": {"primary_catalyst": "SFS / PHP"},
        },
        created_by=user.id,
        updated_by=user.id,
        expires_at=expiry,
        parent_recipe_id=base_recipe.id,
        revision_number=1,
        recipe_kind=SavedRecipeKind.OPTIMIZED,
        status=SavedRecipeStatus.ACTIVE,
    )
    db_session.add(opt_recipe)
    await db_session.commit()

    # 3. Create trial on opt_recipe
    trial = await service.create_trial(
        CustomerTrialCreate(
            saved_recipe_id=opt_recipe.id,
            feedback_text="Customer tested Rev 1: Mooney is slightly high.",
            target_values={"Mooney": "44"},
        ),
        current_user=user,
    )

    # Verify trial snapshot lineage
    assert trial.recipe_snapshot["parent_recipe_id"] == str(base_recipe.id)
    assert trial.recipe_snapshot["revision_number"] == 1
    assert trial.recipe_snapshot["recipe_kind"] == "OPTIMIZED"

    c1 = _make_candidate("A", "Rev 2A", "CTA further reduction", "CTA", "0.28", "0.24", 88)
    c2 = _make_candidate("B", "Rev 2B", "Temp tuning", "Temp", "8", "6", 82)
    c3 = _make_candidate("C", "Rev 2C", "Monomer ratio adjustment", "ACN", "33", "30", 77)
    opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (opt_set, "{}", {"prompt_tokens": 600, "completion_tokens": 700})

        candidates = await service.generate_optimized_recipes(trial.id, user)
        assert len(candidates) == 3
        # Ensure source recipe passed in prompt is the optimized child (CTA: 0.28, not 0.35)
        sys_prompt = mock_gen.call_args[1]["system_prompt"]
        assert "0.28" in sys_prompt


# ==============================================================================
# TEST 8: Original recipe as source -> existing behavior unchanged
# ==============================================================================
@pytest.mark.asyncio
async def test_test8_original_recipe_as_source_behavior_unchanged(db_session, make_user):
    """Verify original recipe source functions cleanly as baseline."""
    user, _ = await make_user(email="test8_user@apcotex.test")
    service = RecipeService(db_session)
    expiry = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)

    base_recipe = SavedRecipe(
        recipe_name="Original Baseline SBR",
        recipe_data={
            "name": "Original Baseline SBR",
            "compound": "SBR",
            "parameters": [{"name": "Water", "value": "150"}],
        },
        created_by=user.id,
        updated_by=user.id,
        expires_at=expiry,
        recipe_kind=SavedRecipeKind.NORMAL,
        status=SavedRecipeStatus.ACTIVE,
    )
    db_session.add(base_recipe)
    await db_session.commit()

    trial = await service.create_trial(
        CustomerTrialCreate(
            saved_recipe_id=base_recipe.id,
            feedback_text="Initial evaluation trial.",
        ),
        current_user=user,
    )

    c1 = _make_candidate("A", "Rev A", "Strategy 1")
    c2 = _make_candidate("B", "Rev B", "Strategy 2")
    c3 = _make_candidate("C", "Rev C", "Strategy 3")
    opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (opt_set, "{}", {"prompt_tokens": 400, "completion_tokens": 500})
        candidates = await service.generate_optimized_recipes(trial.id, user)
        assert len(candidates) == 3


# ==============================================================================
# TEST 9: GENERAL mode with no target properties -> exactly 3 candidates
# ==============================================================================
@pytest.mark.asyncio
async def test_test9_general_mode_no_targets_returns_3_candidates(db_session, make_user):
    """Verify that omitting target properties activates GENERAL mode without errors."""
    user, _ = await make_user(email="test9_user@apcotex.test")
    service = RecipeService(db_session)

    trial = CustomerTrial(
        created_by=user.id,
        feedback_text="Improve batch reproducibility.",
        target_values={},  # No targets
        recipe_snapshot={"recipe_data": {"name": "Base SBR", "compound": "SBR"}},
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    c1 = _make_candidate("A", "Rev A", "Strategy 1")
    c2 = _make_candidate("B", "Rev B", "Strategy 2")
    c3 = _make_candidate("C", "Rev C", "Strategy 3")
    opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (opt_set, "{}", {"prompt_tokens": 400, "completion_tokens": 500})
        candidates = await service.generate_optimized_recipes(trial.id, user)
        assert len(candidates) == 3
        # Check system prompt notes absence of quantitative target properties
        sys_prompt = mock_gen.call_args[1]["system_prompt"]
        assert "No explicit quantitative target property values supplied" in sys_prompt


# ==============================================================================
# TEST 10: STRICT_TARGET mode -> target evaluation preserved
# ==============================================================================
@pytest.mark.asyncio
async def test_test10_strict_target_mode_preserves_target_evaluation(db_session, make_user):
    """Verify STRICT_TARGET mode correctly evaluates targets on all 3 candidates."""
    user, _ = await make_user(email="test10_user@apcotex.test")
    service = RecipeService(db_session)

    trial = CustomerTrial(
        created_by=user.id,
        feedback_text="Target alignment required.",
        target_values={"Mooney Viscosity": "45 MU", "Tensile Strength": ">= 20 MPa"},
        recipe_snapshot={"recipe_data": {"name": "Base NBR", "compound": "NBR"}},
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    c1 = _make_candidate("A", "Rev A", "Strategy 1")
    c2 = _make_candidate("B", "Rev B", "Strategy 2")
    c3 = _make_candidate("C", "Rev C", "Strategy 3")
    opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (opt_set, "{}", {"prompt_tokens": 400, "completion_tokens": 500})
        candidates = await service.generate_optimized_recipes(trial.id, user)
        assert len(candidates) == 3
        # Verify target_analysis exists for each candidate in recipe_data
        for cand in candidates:
            assert cand.recipe_data.get("target_analysis") is not None
            assert "targets_total" in cand.recipe_data["target_analysis"]


# ==============================================================================
# TEST 11: Customer feedback 'hardness is too low' appears in prompt context
# ==============================================================================
@pytest.mark.asyncio
async def test_test11_customer_feedback_influences_context(db_session, make_user):
    """Verify customer feedback 'hardness is too low' reaches system prompt and guides candidates."""
    user, _ = await make_user(email="test11_user@apcotex.test")
    service = RecipeService(db_session)
    feedback_str = "Customer reports hardness is too low, please raise Shore A."

    trial = CustomerTrial(
        created_by=user.id,
        feedback_text=feedback_str,
        recipe_snapshot={"recipe_data": {"name": "Base Compound", "compound": "Carboxylated NBR"}},
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    c1 = _make_candidate("A", "Rev A", "Increase Methacrylic Acid to boost hardness", "Methacrylic Acid", "5.0", "7.5", 88)
    c2 = _make_candidate("B", "Rev B", "Add multifunctional crosslinker", "DVB", "0.0", "0.3", 83)
    c3 = _make_candidate("C", "Rev C", "Adjust monomer glass transition", "Styrene", "20", "25", 79)
    opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (opt_set, "{}", {"prompt_tokens": 400, "completion_tokens": 500})
        candidates = await service.generate_optimized_recipes(trial.id, user)
        assert len(candidates) == 3
        sys_prompt = mock_gen.call_args[1]["system_prompt"]
        assert feedback_str in sys_prompt


# ==============================================================================
# TEST 12: Repeated optimization: Original -> Optimized -> Re-optimized lineage intact
# ==============================================================================
@pytest.mark.asyncio
async def test_test12_repeated_optimization_lineage_remains_intact(db_session, make_user):
    """Verify multi-generation optimization: Original -> Optimized A -> Re-optimized B retains full lineage."""
    user, _ = await make_user(email="test12_user@apcotex.test")
    service = RecipeService(db_session)
    expiry = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)

    # 1. Base recipe
    base_recipe = SavedRecipe(
        recipe_name="Base Parent SBR",
        recipe_data={"name": "Base SBR", "compound": "SBR", "parameters": [{"name": "CTA", "value": "0.30"}]},
        created_by=user.id,
        updated_by=user.id,
        expires_at=expiry,
        recipe_kind=SavedRecipeKind.NORMAL,
        status=SavedRecipeStatus.ACTIVE,
    )
    db_session.add(base_recipe)
    await db_session.commit()

    # 2. Optimized Generation 1
    opt_gen1 = SavedRecipe(
        recipe_name="Optimized SBR Gen 1",
        recipe_data={"name": "Gen 1 SBR", "compound": "SBR", "parameters": [{"name": "CTA", "value": "0.25"}]},
        created_by=user.id,
        updated_by=user.id,
        expires_at=expiry,
        parent_recipe_id=base_recipe.id,
        revision_number=1,
        recipe_kind=SavedRecipeKind.OPTIMIZED,
        status=SavedRecipeStatus.ACTIVE,
    )
    db_session.add(opt_gen1)
    await db_session.commit()

    # 3. Optimized Generation 2
    opt_gen2 = SavedRecipe(
        recipe_name="Optimized SBR Gen 2",
        recipe_data={"name": "Gen 2 SBR", "compound": "SBR", "parameters": [{"name": "CTA", "value": "0.22"}]},
        created_by=user.id,
        updated_by=user.id,
        expires_at=expiry,
        parent_recipe_id=opt_gen1.id,
        revision_number=2,
        recipe_kind=SavedRecipeKind.OPTIMIZED,
        status=SavedRecipeStatus.ACTIVE,
    )
    db_session.add(opt_gen2)
    await db_session.commit()

    # 4. Create trial on Generation 2
    trial_gen3 = await service.create_trial(
        CustomerTrialCreate(
            saved_recipe_id=opt_gen2.id,
            feedback_text="Third iteration optimization feedback.",
        ),
        current_user=user,
    )

    # Verify lineage in trial snapshot
    assert trial_gen3.recipe_snapshot["parent_recipe_id"] == str(opt_gen1.id)
    assert trial_gen3.recipe_snapshot["revision_number"] == 2

    c1 = _make_candidate("A", "Gen 3A", "Strategy Gen3 A")
    c2 = _make_candidate("B", "Gen 3B", "Strategy Gen3 B")
    c3 = _make_candidate("C", "Gen 3C", "Strategy Gen3 C")
    opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (opt_set, "{}", {"prompt_tokens": 400, "completion_tokens": 500})
        candidates = await service.generate_optimized_recipes(trial_gen3.id, user)
        assert len(candidates) == 3
        # Ensure source recipe passed in prompt is Gen 2 (CTA: 0.22)
        sys_prompt = mock_gen.call_args[1]["system_prompt"]
        assert "0.22" in sys_prompt
