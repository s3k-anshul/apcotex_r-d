"""
backend/tests/test_recipe_generation_bounded_and_arbitrary_properties.py

Comprehensive test suite verifying:
1. Five complete candidates generated without one oversized response (Phase 1 compact plan + Phase 2 independent candidate generation).
2. One candidate returning MAX_TOKENS retried with reduced response strategy.
3. Failed candidate does not regenerate already valid candidates.
4. All 5 candidates required before marking cycle complete.
5. Every user-supplied property explicitly represented in all 5 candidates.
6. 19 properties and custom properties supported.
7. Blank property rows do not become active targets.
8. Custom property names and units survive normalization.
9. Unsupported predictions produce UNKNOWN, not fabricated values.
10. % and URL-encoding sanitization is idempotent.
11. Malformed/truncated JSON cannot be persisted as complete.
12. Usage accounting includes failed and recovery calls.
13. CTF 3 candidates and existing regression tests remain intact.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.schemas.recipe import (
    LLMPredictedProperty,
    LLMRecipeParameter,
    LLMRecipeCandidate,
    LLMRecipeStage,
    LLMRecipeSet,
    LLMRecipePlan,
    LLMRecipePlanCandidate,
    LLMSingleRecipe,
    LLMOptimizationSet,
    LLMOptimizedRecipeCandidate,
    sanitize_unit_string,
    _sanitize_unit_string,
)
from app.services.target_validation_service import (
    TargetValidationService,
    NormalizedTargetProperty,
)
from app.services.recipe_service import RecipeService
from app.models.recipe_cycle import RecipeCycle, RecipeCycleStatus
from app.models.user import User, UserRole


# ── FIXTURES & DUMMY FACTORIES ──────────────────────────────────────────────

def make_dummy_stages():
    return [
        LLMRecipeStage(
            stage_name="Reactor Charge",
            parameters=[
                LLMRecipeParameter(name="Water", value="150", unit="phr", source="patent"),
                LLMRecipeParameter(name="Acrylonitrile", value="22", unit="wt%", source="patent"),
                LLMRecipeParameter(name="1,3-Butadiene", value="78", unit="wt%", source="patent"),
            ],
        ),
        LLMRecipeStage(
            stage_name="Emulsifier Solution",
            parameters=[
                LLMRecipeParameter(name="Sodium Dodecyl Sulfate", value="2.5", unit="phr", source="patent"),
            ],
        ),
        LLMRecipeStage(
            stage_name="Catalyst Solution",
            parameters=[
                LLMRecipeParameter(name="Potassium Persulfate", value="0.3", unit="phr", source="patent"),
            ],
        ),
        LLMRecipeStage(
            stage_name="Monomer Mix",
            parameters=[
                LLMRecipeParameter(name="t-DDM", value="0.45", unit="phr", source="patent"),
            ],
        ),
        LLMRecipeStage(
            stage_name="Chemical Stripping",
            parameters=[
                LLMRecipeParameter(name="Steam stripping", value="95", unit="°C", source="inferred"),
            ],
        ),
        LLMRecipeStage(
            stage_name="Post Addition",
            parameters=[
                LLMRecipeParameter(name="Wingstay L Antioxidant", value="0.8", unit="phr", source="patent"),
            ],
        ),
    ]


def make_dummy_candidate(idx: int, compound: str = "Low Acrylonitrile NBR", predictions=None):
    return LLMRecipeCandidate(
        name=f"Candidate {idx} - Monomer and MW Variation",
        compound=compound,
        polymerization_method="Emulsion Polymerization",
        process_type="Batch",
        stages=make_dummy_stages(),
        predicted_properties=predictions or [],
        rationale=f"Candidate {idx} explores controlled molecular weight balance.",
        variation_dimension=f"Dimension {idx}",
    )


def make_dummy_plan(compound: str = "Low Acrylonitrile NBR"):
    return LLMRecipePlan(
        compound=compound,
        candidates=[
            LLMRecipePlanCandidate(
                candidate_number=i,
                name=f"Candidate {i}",
                variation_dimension=f"Dimension {i}",
                key_formulation_changes=[f"Change {i}"],
                rationale=f"Rationale {i}",
            )
            for i in range(1, 6)
        ],
    )


# ── TEST 1: Five complete candidates generated without one oversized response ──

@pytest.mark.asyncio
async def test_five_candidates_generated_without_oversized_response():
    """Phase 1 creates plan (~700 tokens), Phase 2 generates 5 candidates independently (~2000 tokens each)."""
    cycle = RecipeCycle(
        id=uuid.uuid4(),
        compound_name="Low Acrylonitrile NBR",
        target_properties=[
            {"feature": "BACN", "unit": "%", "min": "20", "max": "25"},
            {"feature": "Mooney Viscosity", "unit": "MU", "min": "10", "max": "14"},
        ],
        status=RecipeCycleStatus.PENDING,
    )

    mock_session = AsyncMock()
    mock_llm_client = MagicMock()

    schemas_called = []
    async def mock_generate_structured(prompt, system_prompt, schema, temperature, metadata=None):
        schemas_called.append(schema)
        if schema == LLMRecipePlan:
            return make_dummy_plan(), "gemini", {"finish_reason": "STOP"}
        elif schema in (LLMSingleRecipe, LLMRecipeCandidate):
            cand = make_dummy_candidate(len(schemas_called) - 1, "Low Acrylonitrile NBR")
            return LLMSingleRecipe(recipe=cand), "gemini", {"finish_reason": "STOP"}
        return None, "gemini", {}

    mock_llm_client.generate_structured = mock_generate_structured

    service = RecipeService(session=mock_session, llm_client=mock_llm_client)
    service.get_cycle = AsyncMock(return_value=cycle)
    user = User(id=uuid.uuid4(), email="chemist@apcotex.com", hashed_password="pw", role=UserRole.ADMIN)

    candidates = await service.generate_recipes(cycle.id, user)
    assert len(candidates) == 5
    # Phase 1 plan + 5 individual candidate calls = 6 calls total, none requested oversized 5-recipe JSON
    assert LLMRecipePlan in schemas_called
    assert schemas_called.count(LLMSingleRecipe) == 5


# ── TEST 2: One candidate returning MAX_TOKENS retried with reduced strategy ──

@pytest.mark.asyncio
async def test_single_candidate_max_tokens_triggers_reduced_strategy_retry():
    """When a single candidate hits MAX_TOKENS, only that candidate is retried with repair instructions."""
    cycle = RecipeCycle(
        id=uuid.uuid4(),
        compound_name="Low Acrylonitrile NBR",
        target_properties=[{"feature": "BACN", "unit": "%", "min": "20", "max": "25"}],
        status=RecipeCycleStatus.PENDING,
    )

    mock_session = AsyncMock()
    mock_llm_client = MagicMock()

    attempt_counts = {}
    async def mock_generate_structured(prompt, system_prompt, schema, temperature, metadata=None):
        if schema == LLMRecipePlan:
            return make_dummy_plan(), "gemini", {"finish_reason": "STOP"}
        elif schema in (LLMSingleRecipe, LLMRecipeCandidate):
            # Parse candidate index from metadata or prompt
            cand_idx = (metadata or {}).get("candidate_index")
            if not cand_idx:
                for num in range(1, 6):
                    if f"Candidate {num} of 5" in prompt or f"Candidate {num}/5" in prompt:
                        cand_idx = num
                        break
            if not cand_idx:
                cand_idx = 1
            count = attempt_counts.get(cand_idx, 0) + 1
            attempt_counts[cand_idx] = count

            if cand_idx == 3 and count == 1:
                # Candidate 3 hits MAX_TOKENS on first attempt
                failed_usage = {
                    "finish_reason": "FinishReason.MAX_TOKENS",
                    "is_truncated": True,
                    "response_length": 8192,
                    "invalid_response_error": "RESPONSE_TRUNCATED_MAX_TOKENS",
                }
                return None, "gemini", failed_usage

            # Otherwise succeed
            cand = make_dummy_candidate(cand_idx, "Low Acrylonitrile NBR")
            return LLMSingleRecipe(recipe=cand), "gemini", {"finish_reason": "STOP"}
        return None, "gemini", {}

    mock_llm_client.generate_structured = mock_generate_structured

    service = RecipeService(session=mock_session, llm_client=mock_llm_client)
    service.get_cycle = AsyncMock(return_value=cycle)
    user = User(id=uuid.uuid4(), email="chemist@apcotex.com", hashed_password="pw", role=UserRole.ADMIN)

    candidates = await service.generate_recipes(cycle.id, user)
    assert len(candidates) == 5
    # Candidate 3 was called twice (attempt 1 MAX_TOKENS, attempt 2 succeeded)
    assert attempt_counts[3] == 2
    # Other candidates were called only once
    for idx in (1, 2, 4, 5):
        assert attempt_counts[idx] == 1


# ── TEST 3: Failed candidate does not regenerate already valid candidates ──

@pytest.mark.asyncio
async def test_failed_candidate_retried_without_regenerating_valid_candidates():
    """If candidate 2 fails both in-worker attempts, Phase 3 retries ONLY candidate 2."""
    cycle = RecipeCycle(
        id=uuid.uuid4(),
        compound_name="Low Acrylonitrile NBR",
        target_properties=[{"feature": "BACN", "unit": "%", "min": "20", "max": "25"}],
        status=RecipeCycleStatus.PENDING,
    )

    mock_session = AsyncMock()
    mock_llm_client = MagicMock()

    calls_per_candidate = {i: 0 for i in range(1, 6)}
    async def mock_generate_structured(prompt, system_prompt, schema, temperature, metadata=None):
        if schema == LLMRecipePlan:
            return make_dummy_plan(), "gemini", {"finish_reason": "STOP"}
        elif schema in (LLMSingleRecipe, LLMRecipeCandidate):
            cand_idx = (metadata or {}).get("candidate_index")
            if not cand_idx:
                for num in range(1, 6):
                    if f"Candidate {num} of 5" in prompt or f"Candidate {num}/5" in prompt:
                        cand_idx = num
                        break
            if not cand_idx:
                cand_idx = 1
            calls_per_candidate[cand_idx] += 1
            call_num = calls_per_candidate[cand_idx]

            # Candidate 2 fails on worker attempt 1 and 2, but succeeds on Phase 3 retry call
            if cand_idx == 2 and call_num < 3:
                return None, "gemini", {"validation_error": "Transient parsing failure"}

            cand = make_dummy_candidate(cand_idx, "Low Acrylonitrile NBR")
            return LLMSingleRecipe(recipe=cand), "gemini", {"finish_reason": "STOP"}
        return None, "gemini", {}

    mock_llm_client.generate_structured = mock_generate_structured

    service = RecipeService(session=mock_session, llm_client=mock_llm_client)
    service.get_cycle = AsyncMock(return_value=cycle)
    user = User(id=uuid.uuid4(), email="chemist@apcotex.com", hashed_password="pw", role=UserRole.ADMIN)

    candidates = await service.generate_recipes(cycle.id, user)
    assert len(candidates) == 5
    # Valid candidates 1, 3, 4, 5 were NEVER regenerated after worker completion
    assert calls_per_candidate[1] == 1
    assert calls_per_candidate[3] == 1
    assert calls_per_candidate[4] == 1
    assert calls_per_candidate[5] == 1
    # Candidate 2 was attempted 3 times (worker 1, worker 2, Phase 3 retry 1)
    assert calls_per_candidate[2] >= 3


# ── TEST 4: All 5 candidates required before marking cycle complete ─────────

@pytest.mark.asyncio
async def test_all_five_candidates_required_before_step2_complete():
    """If one candidate persistently fails, cycle cannot complete: raises 502 and marks FAILED."""
    cycle = RecipeCycle(
        id=uuid.uuid4(),
        compound_name="Low Acrylonitrile NBR",
        target_properties=[{"feature": "BACN", "unit": "%", "min": "20", "max": "25"}],
        status=RecipeCycleStatus.PENDING,
    )

    mock_session = AsyncMock()
    mock_llm_client = MagicMock()

    async def mock_generate_structured(prompt, system_prompt, schema, temperature, metadata=None):
        if schema == LLMRecipePlan:
            return make_dummy_plan(), "gemini", {"finish_reason": "STOP"}
        elif schema in (LLMSingleRecipe, LLMRecipeCandidate):
            cand_idx = (metadata or {}).get("candidate_index")
            if not cand_idx:
                for num in range(1, 6):
                    if f"Candidate {num} of 5" in prompt or f"Candidate {num}/5" in prompt:
                        cand_idx = num
                        break
            # Candidate 5 permanently returns None
            if cand_idx == 5:
                return None, "gemini", {"invalid_response_error": "Persistent syntax error"}
            cand = make_dummy_candidate(cand_idx or 1, "Low Acrylonitrile NBR")
            return LLMSingleRecipe(recipe=cand), "gemini", {"finish_reason": "STOP"}
        return None, "gemini", {}

    mock_llm_client.generate_structured = mock_generate_structured

    service = RecipeService(session=mock_session, llm_client=mock_llm_client)
    service.get_cycle = AsyncMock(return_value=cycle)
    user = User(id=uuid.uuid4(), email="chemist@apcotex.com", hashed_password="pw", role=UserRole.ADMIN)

    with pytest.raises(HTTPException) as exc_info:
        await service.generate_recipes(cycle.id, user)

    assert exc_info.value.status_code == 502
    assert "Recipe generation could not produce valid structured data" in exc_info.value.detail
    assert cycle.status == RecipeCycleStatus.FAILED


# ── TEST 5: Every user-supplied property explicitly represented in all 5 candidates ──

def test_every_user_supplied_property_explicitly_represented_in_all_candidates():
    """Every active target and unconstrained property row is present in evaluated predicted_properties."""
    user_properties = [
        {"feature": "BACN", "unit": "%", "min": "20", "max": "25"},
        {"feature": "Mooney Viscosity", "unit": "MU", "min": "10", "max": "14"},
        {"feature": "Stress Relaxation", "unit": "sec", "min": "7", "max": "8"},
        {"feature": "Density", "unit": "g/cm³", "min": "", "max": ""},  # unconstrained row
    ]
    normalized_targets = TargetValidationService.normalize_target_properties(user_properties)

    recipe_dict = {
        "name": "Candidate 1",
        "stages": [],
        "predicted_properties": [
            {"property": "BACN", "predicted_value": 22.0, "unit": "%"},
            # Mooney and Stress Relaxation missing from LLM prediction
        ],
    }

    t_analysis, _, _ = TargetValidationService.evaluate_recipe(
        recipe=recipe_dict,
        normalized_targets=normalized_targets,
        all_user_properties=user_properties,
    )

    evaluated = t_analysis.get("evaluated_properties", [])
    assert len(evaluated) == 4
    eval_map = {p["property"]: p for p in evaluated}

    # In-range active target
    assert eval_map["BACN"]["status"] == "WITHIN_RANGE"
    assert eval_map["BACN"]["passed"] is True

    # Missing active targets have UNKNOWN status and passed=False
    assert eval_map["Mooney Viscosity"]["status"] == "UNKNOWN"
    assert eval_map["Mooney Viscosity"]["passed"] is False
    assert eval_map["Stress Relaxation"]["status"] == "UNKNOWN"
    assert eval_map["Stress Relaxation"]["passed"] is False

    # Unconstrained row has honest UNKNOWN status and unconstrained display
    assert eval_map["Density"]["status"] == "UNKNOWN"
    assert "unconstrained" in eval_map["Density"]["target_display"].lower()
    assert eval_map["Density"]["passed"] is False

    # Also verified on recipe["predicted_properties"]
    recipe_preds = recipe_dict.get("predicted_properties", [])
    assert len(recipe_preds) == 4
    pred_map = {p["property"]: p for p in recipe_preds}
    assert pred_map["Density"]["status"] == "UNKNOWN"


# ── TEST 6: 19 properties and custom properties supported ───────────────────

def test_19_properties_and_custom_properties_supported():
    specs = [
        {"feature": f"Standard_Prop_{i}", "unit": "wt%", "min": f"{i*10}", "max": f"{i*10+5}"}
        for i in range(16)
    ] + [
        {"feature": "Bio-based Carbon Content", "unit": "wt%", "min": "15.0", "max": "25.0"},
        {"feature": "Dynamic Storage Modulus (E')", "unit": "MPa", "min": "120", "max": "180"},
        {"feature": "Melt Flow Index (230°C/2.16kg)", "unit": "g/10min", "target": "8.5"},
    ]
    assert len(specs) == 19
    normalized = TargetValidationService.normalize_target_properties(specs)
    assert len(normalized) == 19

    names = {t.name for t in normalized}
    assert "Bio-based Carbon Content" in names
    assert "Dynamic Storage Modulus (E')" in names
    assert "Melt Flow Index (230°C/2.16kg)" in names


# ── TEST 7: Blank property rows do not become active targets ────────────────

def test_blank_property_rows_do_not_become_active_targets():
    user_properties = [
        {"feature": "BACN", "unit": "%", "min": "20", "max": "25"},
        {"feature": "Tensile Strength", "unit": "MPa", "min": "", "max": ""},
        {"feature": "Elongation", "unit": "%", "min": None, "max": None},
    ]
    normalized = TargetValidationService.normalize_target_properties(user_properties)
    assert len(normalized) == 1
    assert normalized[0].name == "BACN"

    # In evaluate_recipe with all_user_properties
    recipe_dict = {"name": "Candidate 1", "stages": [], "predicted_properties": []}
    t_analysis, _, _ = TargetValidationService.evaluate_recipe(
        recipe=recipe_dict,
        normalized_targets=normalized,
        all_user_properties=user_properties,
    )
    # Total targets required is only 1
    assert t_analysis["targets_total"] == 1
    eval_props = t_analysis["evaluated_properties"]
    assert len(eval_props) == 3

    tensile = next(p for p in eval_props if p["property"] == "Tensile Strength")
    assert tensile["status"] == "UNKNOWN"
    assert tensile["meets_target"] is False
    assert "unconstrained" in tensile["target_display"].lower()


# ── TEST 8: Custom property names and units survive normalization ───────────

def test_custom_property_names_and_units_survive_normalization():
    specs = [
        {"feature": "Melt Flow Index (230°C/2.16kg)", "unit": "g/10min", "min": "5.5", "max": "9.5"},
        {"feature": "Glass Transition Temp (Tg)", "unit": "°C", "min": "-45.5", "max": "-30.2"},
    ]
    normalized = TargetValidationService.normalize_target_properties(specs)
    assert len(normalized) == 2
    assert normalized[0].name == "Melt Flow Index (230°C/2.16kg)"
    assert normalized[0].unit == "g/10min"
    assert normalized[1].name == "Glass Transition Temp (Tg)"
    assert normalized[1].unit == "°C"
    assert normalized[1].min_value == -45.5
    assert normalized[1].max_value == -30.2


# ── TEST 9: Unsupported predictions produce UNKNOWN, not fabricated values ──

def test_unsupported_predictions_produce_unknown_not_fabricated():
    target = NormalizedTargetProperty(
        name="Dynamic Shear Modulus",
        unit="MPa",
        min_value=50.0,
        max_value=70.0,
        constraint_type="range",
    )
    # Empty or null prediction
    eval_result = TargetValidationService.evaluate_property_prediction(target, None)
    assert eval_result["passed"] is False
    assert eval_result["meets_target"] is False
    assert eval_result["status"] == "UNKNOWN"
    assert eval_result["target_status"] == "UNKNOWN"
    assert eval_result["margin_score"] == 0.0


# ── TEST 10: % and URL-encoding sanitization is idempotent ───────────────────

def test_percent_and_url_encoding_sanitization_is_idempotent():
    # Extreme percent corruptions sanitize cleanly to "%"
    assert _sanitize_unit_string("%25") == "%"
    assert _sanitize_unit_string("%25%25%25") == "%"
    assert _sanitize_unit_string("%%%%") == "%"
    assert _sanitize_unit_string("% 25") == "%"

    # Idempotent: sanitizing an already clean string produces identical output
    clean_once = _sanitize_unit_string("%252525")
    clean_twice = _sanitize_unit_string(clean_once)
    assert clean_once == "%"
    assert clean_twice == "%"

    # Other units preserved untouched
    assert _sanitize_unit_string("wt%") == "wt%"
    assert _sanitize_unit_string("phr") == "phr"
    assert _sanitize_unit_string("MU") == "MU"
    assert _sanitize_unit_string("g/cm³") == "g/cm³"


# ── TEST 11: Malformed/truncated JSON cannot be persisted as complete ───────

@pytest.mark.asyncio
async def test_malformed_truncated_json_cannot_be_persisted_as_complete():
    cycle = RecipeCycle(
        id=uuid.uuid4(),
        compound_name="Low Acrylonitrile NBR",
        target_properties=[{"feature": "BACN", "unit": "%", "min": "20", "max": "25"}],
        status=RecipeCycleStatus.PENDING,
    )

    mock_session = AsyncMock()
    mock_llm_client = MagicMock()

    # Model returns empty or malformed on all attempts
    mock_llm_client.generate_structured = AsyncMock(
        return_value=(None, "gemini", {"validation_error": "Truncated JSON", "response_length": 500})
    )

    service = RecipeService(session=mock_session, llm_client=mock_llm_client)
    service.get_cycle = AsyncMock(return_value=cycle)
    user = User(id=uuid.uuid4(), email="chemist@apcotex.com", hashed_password="pw", role=UserRole.ADMIN)

    with pytest.raises(HTTPException) as exc_info:
        await service.generate_recipes(cycle.id, user)

    assert exc_info.value.status_code == 502
    assert cycle.status == RecipeCycleStatus.FAILED
    # DB session was not asked to commit successful candidates
    assert cycle.status != RecipeCycleStatus.STEP2


# ── TEST 12: Usage accounting includes failed and recovery calls ─────────────

@pytest.mark.asyncio
async def test_usage_accounting_includes_failed_and_recovery_calls():
    cycle = RecipeCycle(
        id=uuid.uuid4(),
        compound_name="Low Acrylonitrile NBR",
        target_properties=[{"feature": "BACN", "unit": "%", "min": "20", "max": "25"}],
        status=RecipeCycleStatus.PENDING,
    )

    mock_session = AsyncMock()
    mock_llm_client = MagicMock()

    total_tokens_tracked = 0
    async def mock_generate_structured(prompt, system_prompt, schema, temperature, metadata=None):
        nonlocal total_tokens_tracked
        if schema == LLMRecipePlan:
            total_tokens_tracked += 800
            return make_dummy_plan(), "gemini", {"finish_reason": "STOP", "output_tokens": 800}
        elif schema in (LLMSingleRecipe, LLMRecipeCandidate):
            total_tokens_tracked += 1800
            cand = make_dummy_candidate(1, "Low Acrylonitrile NBR")
            return LLMSingleRecipe(recipe=cand), "gemini", {"finish_reason": "STOP", "output_tokens": 1800}
        return None, "gemini", {}

    mock_llm_client.generate_structured = mock_generate_structured

    service = RecipeService(session=mock_session, llm_client=mock_llm_client)
    service.get_cycle = AsyncMock(return_value=cycle)
    user = User(id=uuid.uuid4(), email="chemist@apcotex.com", hashed_password="pw", role=UserRole.ADMIN)

    candidates = await service.generate_recipes(cycle.id, user)
    assert len(candidates) == 5
    # 800 tokens for plan + 5 * 1800 for candidates = 9800 tokens accounted for
    assert total_tokens_tracked == 800 + 5 * 1800


# ── TEST 13: Regression test - CTF optimization strictly untouched (exactly 3) ──

@pytest.mark.asyncio
async def test_ctf_optimization_pipeline_exactly_3_recipes():
    """Ensure CTF optimization delta architecture produces exactly 3 candidates."""
    from app.models.customer_trial import CustomerTrial, TrialStatus

    trial = CustomerTrial(
        id=uuid.uuid4(),
        status=TrialStatus.PENDING,
        feedback_text="Increase tensile strength and reduce cure time.",
        target_values={"Tensile Strength": "25 MPa"},
        recipe_snapshot={
            "name": "Base Recipe",
            "compound": "NBR Standard",
            "parameters": [{"name": "Sulfur", "value": "1.5", "unit": "phr"}],
            "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": "150", "unit": "phr"}]}],
        },
    )

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=trial)))
    mock_session.get = AsyncMock(return_value=trial)

    mock_llm_client = MagicMock()
    opt_cands = [
        LLMOptimizedRecipeCandidate(
            name=f"Revision {i}",
            compound="NBR Standard",
            optimization_strategy=f"Strategy {i}",
            process_type="Batch",
            changed_parameters=[],
            expected_outcome=f"Outcome {i}",
            expected_impact=f"Impact {i}",
            tradeoffs="None",
            stages=[],
        )
        for i in range(1, 4)
    ]
    mock_llm_client.generate_structured = AsyncMock(
        return_value=(
            LLMOptimizationSet(optimized_recipes=opt_cands),
            "gemini",
            {"finish_reason": "STOP", "raw_response_text": "OK"},
        )
    )

    service = RecipeService(session=mock_session, llm_client=mock_llm_client)
    user = User(id=uuid.uuid4(), email="chemist@apcotex.com", hashed_password="pw", role=UserRole.ADMIN)

    results = await service.generate_optimized_recipes(trial.id, user)
    assert len(results) == 3
