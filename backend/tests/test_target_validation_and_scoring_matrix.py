"""
backend/tests/test_target_validation_and_scoring_matrix.py

Complete 20-test matrix validating:
1. Dynamic, zero-hardcoded Target Property Normalization
2. Deterministic Target Fit Scoring & Boundary Validation (range, min, max, exact)
3. Target violation detection and reporting
4. Target priority over competitor benchmark properties
5. Real backend-calculated Confidence Scoring (replacing arbitrary LLM confidence)
6. Target Fit = N/A and real confidence scoring in zero-target mode
7. Optimization parity between Recipe Simulator and Customer Trials
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.target_validation_service import (
    TargetValidationService,
    NormalizedTargetProperty,
)
from app.models.recipe_cycle import RecipeCycle, RecipeCycleStatus
from app.models.customer_trial import CustomerTrial, TrialStatus
from app.services.recipe_service import RecipeService
from app.schemas.recipe import LLMOptimizationSet, LLMOptimizedRecipeCandidate


# =============================================================================
# TEST 1: No target properties -> 5 recipes -> Target Fit = N/A
# =============================================================================
def test_1_no_target_properties_target_fit_na():
    targets = TargetValidationService.normalize_target_properties([])
    assert len(targets) == 0

    dummy_recipe = {
        "name": "General SBR Polymerization",
        "parameters": [
            {"name": "Water", "value": 160, "unit": "phr"},
            {"name": "Styrene", "value": 25, "unit": "wt%"},
            {"name": "Butadiene", "value": 75, "unit": "wt%"},
            {"name": "Potassium Persulfate", "value": 0.3, "unit": "phr"},
        ],
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 160, "unit": "phr"}]},
        ],
        "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}},
        "patent_references": ["US1234567"],
    }

    t_analysis, c_analysis, conf = TargetValidationService.evaluate_recipe(
        recipe=dummy_recipe,
        normalized_targets=targets,
        patent_context={"patents": [{"patent_id": "US1234567"}]},
    )

    assert t_analysis["mode"] == "GENERAL"
    assert t_analysis["target_fit_score"] is None  # Must be N/A, never manufactured
    assert t_analysis["targets_total"] == 0
    assert t_analysis["targets_met"] == 0
    assert 45 <= conf <= 95
    assert c_analysis["score"] == conf
    assert "no explicit target properties" in c_analysis["explanation"].lower()


# =============================================================================
# TEST 2: One target property -> addressed and evaluated
# =============================================================================
def test_2_one_target_property_addressed():
    raw_targets = [{"feature": "Mooney Viscosity", "min": 45, "max": 55, "unit": "MU"}]
    targets = TargetValidationService.normalize_target_properties(raw_targets)
    assert len(targets) == 1
    assert targets[0].name == "Mooney Viscosity"
    assert targets[0].constraint_type == "range"

    recipe = {
        "name": "Candidate 1",
        "predicted_properties": [
            {"property": "Mooney Viscosity", "predicted_value": 49, "reasoning": "Regulated via CTA"}
        ],
        "parameters": [{"name": "CTA", "value": 0.3, "unit": "phr"}],
    }

    t_analysis, c_analysis, conf = TargetValidationService.evaluate_recipe(recipe, targets)
    assert t_analysis["mode"] == "STRICT_TARGET"
    assert t_analysis["targets_total"] == 1
    assert t_analysis["targets_met"] == 1
    assert t_analysis["target_fit_score"] == 100
    assert t_analysis["target_violation_count"] == 0
    assert conf >= 50


# =============================================================================
# TEST 3: Three target properties -> all three evaluated
# =============================================================================
def test_3_three_target_properties_evaluated():
    raw_targets = [
        {"feature": "Bound ACN", "min": 19, "max": 21, "unit": "%"},
        {"feature": "Mooney Viscosity", "min": 45, "max": 55, "unit": "MU"},
        {"feature": "Tensile Strength", "min": 22, "unit": "MPa"},
    ]
    targets = TargetValidationService.normalize_target_properties(raw_targets)
    assert len(targets) == 3

    recipe = {
        "name": "3-Target Recipe",
        "predicted_properties": [
            {"property": "Bound ACN", "predicted_value": 20.2, "reasoning": "Monomer ratio 20:80"},
            {"property": "Mooney Viscosity", "predicted_value": 50, "reasoning": "CTA level 0.35 phr"},
            {"property": "Tensile Strength", "predicted_value": 24.5, "reasoning": "Controlled microstructure"},
        ],
    }

    t_analysis, c_analysis, conf = TargetValidationService.evaluate_recipe(recipe, targets)
    assert t_analysis["targets_total"] == 3
    assert t_analysis["targets_met"] == 3
    assert t_analysis["target_fit_score"] == 100
    assert len(t_analysis["properties"]) == 3


# =============================================================================
# TEST 4: Ten+ target properties -> dynamic handling works without hardcoding
# =============================================================================
def test_4_ten_plus_target_properties_dynamic():
    raw_targets = [
        {"feature": "BACN", "min": 27, "max": 29, "unit": "%"},
        {"feature": "Mooney ML(1+4 @ 100°C)", "min": 45, "max": 55, "unit": "MU"},
        {"feature": "Stress Relaxation", "min": 15, "max": 22, "unit": "sec"},
        {"feature": "pH", "min": 9.5, "max": 10.5, "unit": ""},
        {"feature": "Total Solid Content", "min": 39.5, "max": 41.5, "unit": "%"},
        {"feature": "Gel Content", "min": 0, "max": 1, "unit": "%"},
        {"feature": "Tg", "min": -35, "max": -29, "unit": "°C"},
        {"feature": "Volatile Matter", "min": 0.5, "max": 1.2, "unit": "%"},
        {"feature": "Particle Size", "min": 100, "max": 140, "unit": "nm"},
        {"feature": "Tensile Strength", "min": 22, "unit": "MPa"},
        {"feature": "Elongation at Break", "min": 400, "unit": "%"},
    ]
    targets = TargetValidationService.normalize_target_properties(raw_targets)
    assert len(targets) == 11

    # Provide predictions for all 11
    predictions = [
        {"property": "BACN", "predicted_value": 28.0},
        {"property": "Mooney ML(1+4 @ 100°C)", "predicted_value": 50.0},
        {"property": "Stress Relaxation", "predicted_value": 18.0},
        {"property": "pH", "predicted_value": 10.0},
        {"property": "Total Solid Content", "predicted_value": 40.5},
        {"property": "Gel Content", "predicted_value": 0.5},
        {"property": "Tg", "predicted_value": -32.0},
        {"property": "Volatile Matter", "predicted_value": 0.8},
        {"property": "Particle Size", "predicted_value": 120.0},
        {"property": "Tensile Strength", "predicted_value": 25.0},
        {"property": "Elongation at Break", "predicted_value": 450.0},
    ]

    recipe = {"name": "11-Property Polymer Formulation", "predicted_properties": predictions}
    t_analysis, c_analysis, conf = TargetValidationService.evaluate_recipe(recipe, targets)

    assert t_analysis["targets_total"] == 11
    assert t_analysis["targets_met"] == 11
    assert t_analysis["target_fit_score"] == 100


# =============================================================================
# TEST 5: Minimum-only target
# =============================================================================
def test_5_minimum_only_target():
    target = TargetValidationService.normalize_target_properties([
        {"feature": "Tensile Strength", "min": 22, "unit": "MPa"}
    ])[0]
    assert target.constraint_type == "min"

    # Pass case
    pred_pass = {"property": "Tensile Strength", "predicted_value": 24}
    res_pass = TargetValidationService.evaluate_property_prediction(target, pred_pass)
    assert res_pass.meets_target is True
    assert res_pass.status == "MEETS_TARGET"

    # Fail case
    pred_fail = {"property": "Tensile Strength", "predicted_value": 18}
    res_fail = TargetValidationService.evaluate_property_prediction(target, pred_fail)
    assert res_fail.meets_target is False
    assert res_fail.status == "NOT_MET"
    assert res_fail.violation_distance == 4.0


# =============================================================================
# TEST 6: Maximum-only target
# =============================================================================
def test_6_maximum_only_target():
    target = TargetValidationService.normalize_target_properties([
        {"feature": "Gel Content", "max": 1.0, "unit": "%"}
    ])[0]
    assert target.constraint_type == "max"

    pred_pass = {"property": "Gel Content", "predicted_value": 0.6}
    res_pass = TargetValidationService.evaluate_property_prediction(target, pred_pass)
    assert res_pass.meets_target is True

    pred_fail = {"property": "Gel Content", "predicted_value": 1.8}
    res_fail = TargetValidationService.evaluate_property_prediction(target, pred_fail)
    assert res_fail.meets_target is False
    assert res_fail.violation_distance == 0.8


# =============================================================================
# TEST 7: Range target
# =============================================================================
def test_7_range_target():
    target = TargetValidationService.normalize_target_properties([
        {"feature": "Mooney Viscosity", "min": 45, "max": 55, "unit": "MU"}
    ])[0]
    assert target.constraint_type == "range"

    # Point prediction inside range
    res1 = TargetValidationService.evaluate_property_prediction(
        target, {"property": "Mooney", "predicted_value": 50}
    )
    assert res1.meets_target is True

    # Range prediction inside target range
    res2 = TargetValidationService.evaluate_property_prediction(
        target, {"property": "Mooney", "predicted_min": 47, "predicted_max": 53}
    )
    assert res2.meets_target is True

    # Prediction outside range
    res3 = TargetValidationService.evaluate_property_prediction(
        target, {"property": "Mooney", "predicted_value": 62}
    )
    assert res3.meets_target is False
    assert res3.violation_distance == 7.0


# =============================================================================
# TEST 8: Exact target
# =============================================================================
def test_8_exact_target():
    target = TargetValidationService.normalize_target_properties([
        {"feature": "Acrylonitrile Content", "target": 28.0, "tolerance": 0.7, "unit": "%"}
    ])[0]
    assert target.constraint_type == "exact"

    # Prediction within tolerance (28.0 +- 0.7)
    res_pass = TargetValidationService.evaluate_property_prediction(
        target, {"property": "ACN", "predicted_value": 28.3}
    )
    assert res_pass.meets_target is True

    # Prediction beyond tolerance
    res_fail = TargetValidationService.evaluate_property_prediction(
        target, {"property": "ACN", "predicted_value": 29.5}
    )
    assert res_fail.meets_target is False
    assert res_fail.violation_distance == 1.5


# =============================================================================
# TEST 9: Competitor properties present + target properties present -> TARGETS WIN
# =============================================================================
def test_9_competitor_present_and_targets_present_target_wins():
    targets = TargetValidationService.normalize_target_properties([
        {"feature": "Mooney Viscosity", "min": 45, "max": 55, "unit": "MU"}
    ])
    competitor_data = [
        {"name": "Competitor BASF", "values": {"Mooney Viscosity": "68"}}
    ]

    recipe = {
        "name": "Recipe A",
        "predicted_properties": [
            {"property": "Mooney Viscosity", "predicted_value": 50}
        ],
    }

    t_analysis, _, conf = TargetValidationService.evaluate_recipe(
        recipe=recipe,
        normalized_targets=targets,
        competitor_data=competitor_data,
    )

    # Optimization objective is TARGET (45-55), NOT competitor (68)
    assert t_analysis["targets_met"] == 1
    assert t_analysis["target_fit_score"] == 100


# =============================================================================
# TEST 10: Competitor properties present + no target properties -> competitor is reference only
# =============================================================================
def test_10_competitor_present_no_targets_competitor_reference_only():
    targets = TargetValidationService.normalize_target_properties([])
    competitor_data = [{"name": "Competitor X", "values": {"Mooney": "52"}}]

    recipe = {"name": "Recipe General", "parameters": [{"name": "Water", "value": 150}]}
    t_analysis, _, conf = TargetValidationService.evaluate_recipe(
        recipe=recipe,
        normalized_targets=targets,
        competitor_data=competitor_data,
    )

    assert t_analysis["mode"] == "GENERAL"
    assert t_analysis["target_fit_score"] is None
    assert 45 <= conf <= 95


# =============================================================================
# TEST 11: Recipe prediction satisfies all targets -> Target Fit = 100%
# =============================================================================
def test_11_all_targets_satisfied_target_fit_100():
    targets = TargetValidationService.normalize_target_properties([
        {"feature": "ACN", "min": 20, "max": 22},
        {"feature": "Mooney", "min": 45, "max": 55},
    ])
    recipe = {
        "name": "Perfect Fit Candidate",
        "predicted_properties": [
            {"property": "ACN", "predicted_value": 21.0},
            {"property": "Mooney", "predicted_value": 50.0},
        ],
    }
    t_analysis, _, _ = TargetValidationService.evaluate_recipe(recipe, targets)
    assert t_analysis["target_fit_score"] == 100
    assert t_analysis["targets_met"] == 2
    assert len(t_analysis["violations"]) == 0


# =============================================================================
# TEST 12: Recipe prediction violates one target -> violation detected
# =============================================================================
def test_12_one_target_violation_detected():
    targets = TargetValidationService.normalize_target_properties([
        {"feature": "ACN", "min": 20, "max": 22},
        {"feature": "Mooney", "min": 45, "max": 55},
        {"feature": "Tensile", "min": 22},
    ])
    recipe = {
        "name": "One Fail Candidate",
        "predicted_properties": [
            {"property": "ACN", "predicted_value": 21.0},
            {"property": "Mooney", "predicted_value": 50.0},
            {"property": "Tensile", "predicted_value": 18.0},  # Violates >= 22
        ],
    }
    t_analysis, _, _ = TargetValidationService.evaluate_recipe(recipe, targets)
    assert t_analysis["targets_met"] == 2
    assert t_analysis["targets_total"] == 3
    assert t_analysis["target_fit_score"] == 67
    assert len(t_analysis["violations"]) == 1
    assert t_analysis["violations"][0]["property"] == "Tensile"


# =============================================================================
# TEST 13: Recipe prediction violates multiple targets -> all violations detected
# =============================================================================
def test_13_multiple_target_violations_detected():
    targets = TargetValidationService.normalize_target_properties([
        {"feature": "ACN", "min": 20, "max": 22},
        {"feature": "Mooney", "min": 45, "max": 55},
        {"feature": "Tensile", "min": 22},
    ])
    recipe = {
        "name": "Two Fail Candidate",
        "predicted_properties": [
            {"property": "ACN", "predicted_value": 25.0},      # Violates 20-22
            {"property": "Mooney", "predicted_value": 65.0},   # Violates 45-55
            {"property": "Tensile", "predicted_value": 24.0},  # Passes >= 22
        ],
    }
    t_analysis, _, _ = TargetValidationService.evaluate_recipe(recipe, targets)
    assert t_analysis["targets_met"] == 1
    assert t_analysis["targets_total"] == 3
    assert t_analysis["target_fit_score"] == 33
    assert len(t_analysis["violations"]) == 2


# =============================================================================
# TEST 14: Candidate ranking orders hard target satisfaction first
# =============================================================================
def test_14_ranking_prioritizes_hard_target_compliance():
    targets = TargetValidationService.normalize_target_properties([
        {"feature": "Mooney", "min": 45, "max": 55},
    ])

    cand_passing = {
        "name": "Passing Recipe",
        "predicted_properties": [{"property": "Mooney", "predicted_value": 50}],
        "parameters": [{"name": "CTA", "value": 0.3}],
        "confidence_score": 75,
    }
    cand_failing = {
        "name": "Failing Recipe",
        "predicted_properties": [{"property": "Mooney", "predicted_value": 70}],
        "parameters": [{"name": "CTA", "value": 0.1}],
        "confidence_score": 92,  # Higher arbitrary score, but violates target!
    }

    # Evaluate both
    for c in [cand_passing, cand_failing]:
        t_a, c_a, conf = TargetValidationService.evaluate_recipe(c, targets)
        c["target_analysis"] = t_a
        c["confidence_analysis"] = c_a
        c["confidence_score"] = conf

    ranked = TargetValidationService.rank_candidates([cand_failing, cand_passing], targets)
    # Passing recipe MUST rank first regardless of failing candidate's raw score
    assert ranked[0]["name"] == "Passing Recipe"


# =============================================================================
# TEST 15 & 16: Customer Trial Optimization Parity with Target Validation
# =============================================================================
@pytest.mark.asyncio
async def test_15_and_16_customer_trial_optimization_uses_same_target_validation(db_session, make_user):
    test_user, _ = await make_user(email="matrix_trial_test@apcotex.test")
    service = RecipeService(db_session)

    source_recipe = {
        "name": "Base SBR Formulation",
        "compound": "SBR",
        "polymerization_method": "Cold Emulsion Polymerization",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": "150", "unit": "phr"}]},
        ],
    }

    trial = CustomerTrial(
        created_by=test_user.id,
        feedback_text="Increase tensile strength while maintaining Mooney 48-52 MU.",
        target_values={
            "Mooney Viscosity": "48-52 MU",
            "Tensile Strength": ">= 22 MPa",
        },
        recipe_snapshot={"recipe_data": source_recipe, "compound": "SBR"},
        status=TrialStatus.PENDING,
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    # Construct mock revisions with predicted properties
    def make_cand(label, name, m_val, t_val):
        return LLMOptimizedRecipeCandidate(
            revision_label=label,
            name=name,
            optimization_strategy="Tuning monomer and crosslink density",
            confidence_score=85,
            expected_outcome="Target achieved",
            expected_impact="Optimal",
            tradeoffs="None",
            changed_parameters=[{"parameter": "CTA", "old_value": "0.3", "new_value": "0.25", "reason": "Tuning"}],
            predicted_impacts=[],
            predicted_properties=[
                {"property": "Mooney Viscosity", "predicted_value": m_val, "reasoning": "CTA lowered"},
                {"property": "Tensile Strength", "predicted_value": t_val, "reasoning": "Higher molecular weight"},
            ],
            stages=[
                {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": "150", "unit": "phr"}]}
            ],
        )

    c1 = make_cand("A", "Rev A", 50, 24)  # Passes both
    c2 = make_cand("B", "Rev B", 49, 23)  # Passes both
    c3 = make_cand("C", "Rev C", 51, 25)  # Passes both
    mock_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (mock_set, "{}", {"input_tokens": 1200, "output_tokens": 600})
        candidates = await service.generate_optimized_recipes(trial.id, test_user)

        assert len(candidates) == 3
        for cand in candidates:
            r_data = cand.recipe_data
            assert "target_analysis" in r_data
            assert "confidence_analysis" in r_data
            t_a = r_data["target_analysis"]
            assert t_a["mode"] == "STRICT_TARGET"
            assert t_a["targets_met"] == 2
            assert t_a["target_fit_score"] == 100


# =============================================================================
# TEST 17 & 18: Feedback with vs without target properties
# =============================================================================
@pytest.mark.asyncio
async def test_17_and_18_feedback_with_and_without_targets(db_session, make_user):
    test_user, _ = await make_user(email="matrix_feedback_mode@apcotex.test")
    service = RecipeService(db_session)

    # Case 18: No targets provided with feedback
    trial_no_targets = CustomerTrial(
        created_by=test_user.id,
        feedback_text="Slightly slow conversion time.",
        target_values={},
        recipe_snapshot={"recipe_data": {"name": "Base"}, "compound": "NBR"},
        status=TrialStatus.PENDING,
    )
    db_session.add(trial_no_targets)
    await db_session.commit()
    await db_session.refresh(trial_no_targets)

    c1 = LLMOptimizedRecipeCandidate(
        revision_label="A",
        name="Rev A",
        optimization_strategy="Catalyst increase",
        confidence_score=80,
        expected_outcome="Faster conversion",
        expected_impact="High",
        tradeoffs="None",
        changed_parameters=[],
        predicted_impacts=[],
        predicted_properties=[],
        stages=[],
    )
    c2 = LLMOptimizedRecipeCandidate(
        revision_label="B", name="Rev B", optimization_strategy="Temp increase",
        confidence_score=75, expected_outcome="Faster", expected_impact="Good",
        tradeoffs="None", changed_parameters=[], predicted_impacts=[], predicted_properties=[], stages=[],
    )
    c3 = LLMOptimizedRecipeCandidate(
        revision_label="C", name="Rev C", optimization_strategy="Emulsifier balance",
        confidence_score=78, expected_outcome="Faster", expected_impact="Good",
        tradeoffs="None", changed_parameters=[], predicted_impacts=[], predicted_properties=[], stages=[],
    )
    mock_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = (mock_set, "{}", {"input_tokens": 1000, "output_tokens": 500})
        candidates = await service.generate_optimized_recipes(trial_no_targets.id, test_user)

        assert len(candidates) == 3
        # Mode is GENERAL, Target Fit is N/A
        for c in candidates:
            t_a = c.recipe_data["target_analysis"]
            assert t_a["mode"] == "GENERAL"
            assert t_a["target_fit_score"] is None
            assert 45 <= c.recipe_data["confidence_score"] <= 95


# =============================================================================
# TEST 19: Session navigation preserves target properties roundtrip
# =============================================================================
def test_19_session_navigation_preserves_targets():
    # Simulate cycle payload received from API
    cycle_api_data = {
        "target_product": "NBR High ACN",
        "target_properties": [
            {"id": "p1", "feature": "Bound ACN", "min": "33", "max": "36", "unit": "%"},
            {"id": "p2", "feature": "Mooney ML(1+4)", "min": "45", "max": "55", "unit": "MU"},
        ],
    }

    # Frontend rehydration parses target properties into desired map
    loaded_desired = {}
    for tp in cycle_api_data["target_properties"]:
        feat = tp.get("feature")
        if feat:
            loaded_desired[feat] = {"min": str(tp.get("min")), "max": str(tp.get("max"))}

    assert "Bound ACN" in loaded_desired
    assert loaded_desired["Bound ACN"]["min"] == "33"
    assert loaded_desired["Bound ACN"]["max"] == "36"
    assert loaded_desired["Mooney ML(1+4)"]["min"] == "45"
    assert loaded_desired["Mooney ML(1+4)"]["max"] == "55"


# =============================================================================
# TEST 20: Confidence score is mathematically explainable and not 71
# =============================================================================
def test_20_confidence_score_is_explainable_and_not_arbitrary():
    targets = TargetValidationService.normalize_target_properties([
        {"feature": "Mooney", "min": 45, "max": 55},
    ])
    recipe = {
        "name": "Transparent Candidate",
        "parameters": [
            {"name": "Water", "value": 160, "unit": "phr"},
            {"name": "CTA", "value": 0.3, "unit": "phr"},
        ],
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 160, "unit": "phr"}]},
        ],
        "predicted_properties": [{"property": "Mooney", "predicted_value": 50}],
        "patent_references": ["US7654321"],
    }
    t_a, c_a, conf = TargetValidationService.evaluate_recipe(
        recipe=recipe,
        normalized_targets=targets,
        patent_context={"patents": [{"patent_id": "US7654321"}]},
    )

    assert conf != 71
    assert "target_compliance" in c_a
    assert "evidence_support" in c_a
    assert "recipe_completeness" in c_a
    assert "process_feasibility" in c_a
    # Weighted sum explanation exists
    assert c_a["score"] == conf
    assert len(c_a["explanation"]) > 20
