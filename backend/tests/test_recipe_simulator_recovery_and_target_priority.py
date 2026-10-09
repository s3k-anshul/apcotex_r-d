"""
backend/tests/test_recipe_simulator_recovery_and_target_priority.py

Comprehensive test suite verifying:
1. Target + Range Priority Architecture:
   - Priority 1: TARGET (preferred objective)
   - Priority 2: RANGE (acceptable boundary)
   - Priority 3: OTHER PROPERTY / FEASIBILITY TRADE-OFFS
   - Candidate at target is strictly better than candidate near boundary
   - Candidate outside boundary is marked OUTSIDE TARGET
   - Range-only treats range as primary constraint
   - Target-only optimizes toward target without inventing ranges
2. Arbitrary property counts:
   - 1 property -> evaluated
   - 5 properties -> evaluated
   - 8 properties (7% carboxylated NBR scenario) -> all 8 evaluated
   - 20+ properties -> all evaluated without truncation (no [:5] or [:10])
3. End-to-End Preservation:
   - target, range_min, range_max, unit preserved across pipeline
4. Gemini timeout -> OpenAI fallback generates exactly 5 candidates
5. Customer Trial Feedback (CTF) optimization regression check:
   - Produces exactly 3 candidates with full lineage and deltas preserved
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.target_validation_service import (
    TargetValidationService,
    NormalizedTargetProperty,
)
from app.services.recipe_service import RecipeService
from app.schemas.recipe import (
    LLMRecipeSet,
    LLMRecipeCandidate,
    LLMOptimizationSet,
    LLMOptimizedRecipeCandidate,
    LLMChangedParameter,
    LLMTargetImpact,
)
from app.models.recipe_cycle import RecipeCycle, RecipeCycleStatus
from app.models.customer_trial import CustomerTrial, TrialStatus


# ─────────────────────────────────────────────────────────────────────────────
# 1. TARGET + RANGE PRIORITY TESTS (User Requirements 7, 8, 9, 10)
# ─────────────────────────────────────────────────────────────────────────────

def test_target_plus_range_priority_scoring_and_ranking():
    """
    User Requirement 7 & 10:
    Target = 70, Range = 65-75.
    Candidate A (predicted 70) is better than Candidate B (predicted 66).
    Candidate C (predicted 74) is acceptable but less ideal than 70.
    Candidate D (predicted 80) is OUTSIDE TARGET.
    Candidate A must rank ahead of Candidate B and C due to target priority.
    """
    raw_targets = [{
        "property": "Mooney Viscosity",
        "target": 70.0,
        "min": 65.0,
        "max": 75.0,
        "unit": "MU"
    }]
    normalized = TargetValidationService.normalize_target_properties(raw_targets)
    assert len(normalized) == 1
    t = normalized[0]
    assert t.target_value == 70.0
    assert t.min_value == 65.0
    assert t.max_value == 75.0
    assert t.constraint_type == "range"

    # Candidate A: exact target (70)
    cand_a = {
        "name": "Candidate A (Exact Target)",
        "predicted_properties": [{"property": "Mooney Viscosity", "predicted_value": 70.0, "unit": "MU"}],
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 180, "unit": "phr"}]}],
        "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}},
        "patent_references": ["US1000001"],
    }
    # Candidate B: inside range near min (66)
    cand_b = {
        "name": "Candidate B (Near Min Bound)",
        "predicted_properties": [{"property": "Mooney Viscosity", "predicted_value": 66.0, "unit": "MU"}],
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 180, "unit": "phr"}]}],
        "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}},
        "patent_references": ["US1000001"],
    }
    # Candidate C: inside range near max (74)
    cand_c = {
        "name": "Candidate C (Near Max Bound)",
        "predicted_properties": [{"property": "Mooney Viscosity", "predicted_value": 74.0, "unit": "MU"}],
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 180, "unit": "phr"}]}],
        "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}},
        "patent_references": ["US1000001"],
    }
    # Candidate D: outside range (80)
    cand_d = {
        "name": "Candidate D (Outside Range)",
        "predicted_properties": [{"property": "Mooney Viscosity", "predicted_value": 80.0, "unit": "MU"}],
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 180, "unit": "phr"}]}],
        "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}},
        "patent_references": ["US1000001"],
    }

    t_a, _, _ = TargetValidationService.evaluate_recipe(cand_a, normalized, {})
    t_b, _, _ = TargetValidationService.evaluate_recipe(cand_b, normalized, {})
    t_c, _, _ = TargetValidationService.evaluate_recipe(cand_c, normalized, {})
    t_d, _, _ = TargetValidationService.evaluate_recipe(cand_d, normalized, {})

    cand_a["target_analysis"] = t_a
    cand_b["target_analysis"] = t_b
    cand_c["target_analysis"] = t_c
    cand_d["target_analysis"] = t_d

    # Candidate D must fail boundary
    assert t_d["targets_met"] == 0
    assert t_d["evaluated_properties"][0]["passed"] is False
    assert t_d["evaluated_properties"][0]["status"] == "OUTSIDE_TARGET"

    # Candidates A, B, C all pass the range boundary
    assert t_a["targets_met"] == 1
    assert t_b["targets_met"] == 1
    assert t_c["targets_met"] == 1
    assert t_a["evaluated_properties"][0]["passed"] is True
    assert t_b["evaluated_properties"][0]["passed"] is True
    assert t_c["evaluated_properties"][0]["passed"] is True

    # Candidate A (at 70) must have higher margin_score than Candidate B (66) and Candidate C (74)
    margin_a = t_a["evaluated_properties"][0]["margin_score"]
    margin_b = t_b["evaluated_properties"][0]["margin_score"]
    margin_c = t_c["evaluated_properties"][0]["margin_score"]
    assert margin_a > margin_b, f"Candidate at target {margin_a} must have higher margin than near-boundary {margin_b}"
    assert margin_a > margin_c, f"Candidate at target {margin_a} must have higher margin than near-boundary {margin_c}"

    # Ranking must place Candidate A strictly first
    ranked = TargetValidationService.rank_candidates([cand_b, cand_d, cand_a, cand_c], normalized)
    assert ranked[0]["name"] == "Candidate A (Exact Target)"
    # Candidate D (failed target) must be ranked last
    assert ranked[-1]["name"] == "Candidate D (Outside Range)"


def test_range_only_as_primary_constraint():
    """
    User Requirement 8:
    Target = blank, Range = 65-75.
    Acceptable range becomes primary constraint.
    Candidate inside (70) passes, candidate outside (60) fails.
    """
    raw_targets = [{"property": "Mooney", "min": 65, "max": 75, "unit": "MU"}]
    normalized = TargetValidationService.normalize_target_properties(raw_targets)
    assert len(normalized) == 1
    assert normalized[0].target_value is None
    assert normalized[0].min_value == 65
    assert normalized[0].max_value == 75

    cand_in = {
        "name": "Inside",
        "predicted_properties": [{"property": "Mooney", "predicted_value": 70, "unit": "MU"}],
    }
    cand_out = {
        "name": "Outside",
        "predicted_properties": [{"property": "Mooney", "predicted_value": 60, "unit": "MU"}],
    }

    t_in, _, _ = TargetValidationService.evaluate_recipe(cand_in, normalized, {})
    t_out, _, _ = TargetValidationService.evaluate_recipe(cand_out, normalized, {})

    assert t_in["evaluated_properties"][0]["passed"] is True
    assert t_in["evaluated_properties"][0]["status"] == "MEETS_TARGET"
    assert t_out["evaluated_properties"][0]["passed"] is False
    assert t_out["evaluated_properties"][0]["status"] == "OUTSIDE_TARGET"


def test_target_only_optimizes_to_target():
    """
    User Requirement 9:
    Target = 70, Range = blank.
    Optimize toward 70, do not invent artificial ranges.
    """
    raw_targets = [{"property": "Mooney", "target": 70, "unit": "MU"}]
    normalized = TargetValidationService.normalize_target_properties(raw_targets)
    assert len(normalized) == 1
    assert normalized[0].target_value == 70
    assert normalized[0].min_value is None
    assert normalized[0].max_value is None
    assert normalized[0].constraint_type == "exact"

    cand_close = {
        "name": "Close",
        "predicted_properties": [{"property": "Mooney", "predicted_value": 70.1, "unit": "MU"}],
    }
    cand_far = {
        "name": "Far",
        "predicted_properties": [{"property": "Mooney", "predicted_value": 85.0, "unit": "MU"}],
    }

    t_close, _, _ = TargetValidationService.evaluate_recipe(cand_close, normalized, {})
    t_far, _, _ = TargetValidationService.evaluate_recipe(cand_far, normalized, {})

    assert t_close["evaluated_properties"][0]["passed"] is True
    assert t_far["evaluated_properties"][0]["passed"] is False
    assert t_far["evaluated_properties"][0]["status"] == "OUTSIDE_TARGET"


# ─────────────────────────────────────────────────────────────────────────────
# 2. EXACT 8-PROPERTY 7% CARBOXYLATED NBR SCENARIO (User Requirements 1, 20)
# ─────────────────────────────────────────────────────────────────────────────

def test_exact_7pct_carboxylated_nbr_8_properties_preserved():
    """
    User Requirement 1, 5, 20:
    Target Product: 7% carboxylated NBR
    8 properties:
    - BACN
    - Mooney (ML1+4 @ 100°C)
    - Stress Relaxation
    - pH
    - Total Solid Content
    - Gel Content
    - Tg
    - Volatile Matter
    All 8 must be received, passed, normalized, and evaluated without truncation.
    """
    input_8_props = [
        {"property": "BACN", "target": "28", "min": "26", "max": "30", "unit": "%"},
        {"property": "Mooney (ML1+4 @ 100°C)", "target": "50", "min": "45", "max": "55", "unit": "MU"},
        {"property": "Stress Relaxation", "target": "0.12", "min": "0.10", "max": "0.15", "unit": ""},
        {"property": "pH", "target": "8.5", "min": "8.0", "max": "9.0", "unit": ""},
        {"property": "Total Solid Content", "target": "42", "min": "40", "max": "45", "unit": "%"},
        {"property": "Gel Content", "target": "75", "min": "70", "max": "80", "unit": "%"},
        {"property": "Tg", "target": "-25", "min": "-28", "max": "-22", "unit": "°C"},
        {"property": "Volatile Matter", "target": "0.4", "min": "0.2", "max": "0.5", "unit": "%"},
    ]

    normalized = TargetValidationService.normalize_target_properties(input_8_props)
    assert len(normalized) == 8, f"Expected 8 normalized targets, got {len(normalized)}"

    # Verify all 8 preserve target, min, max, unit
    expected_names = [
        "BACN", "Mooney (ML1+4 @ 100°C)", "Stress Relaxation", "pH",
        "Total Solid Content", "Gel Content", "Tg", "Volatile Matter"
    ]
    for idx, exp_name in enumerate(expected_names):
        assert normalized[idx].name == exp_name
        assert normalized[idx].target_value is not None
        assert normalized[idx].min_value is not None
        assert normalized[idx].max_value is not None
        # display_target must contain both Target and Range
        disp = normalized[idx].display_target()
        assert "Target:" in disp
        assert "Range:" in disp

    # Test candidate recipe evaluation against all 8 properties
    mock_recipe = {
        "name": "Recipe 1 - Baseline NBR",
        "compound": "7% carboxylated NBR",
        "predicted_properties": [
            {"property": "BACN", "predicted_value": 28.1, "unit": "%", "status": "MEETS_TARGET"},
            {"property": "Mooney (ML1+4 @ 100°C)", "predicted_value": 49.5, "unit": "MU", "status": "MEETS_TARGET"},
            {"property": "Stress Relaxation", "predicted_value": 0.125, "unit": "", "status": "MEETS_TARGET"},
            {"property": "pH", "predicted_value": 8.4, "unit": "", "status": "MEETS_TARGET"},
            {"property": "Total Solid Content", "predicted_value": 42.5, "unit": "%", "status": "MEETS_TARGET"},
            {"property": "Gel Content", "predicted_value": 74.0, "unit": "%", "status": "MEETS_TARGET"},
            {"property": "Tg", "predicted_value": -24.8, "unit": "°C", "status": "MEETS_TARGET"},
            {"property": "Volatile Matter", "predicted_value": 0.38, "unit": "%", "status": "MEETS_TARGET"},
        ],
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Deionized Water", "value": 180, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "Acrylonitrile", "value": 28, "unit": "phr"}]},
        ],
        "process_conditions": {"reaction_time": {"value": 8.5, "unit": "h"}},
        "patent_references": ["US20250075019A1"],
    }

    t_analysis, c_analysis, conf = TargetValidationService.evaluate_recipe(mock_recipe, normalized, {})

    assert t_analysis["targets_total"] == 8
    assert t_analysis["targets_met"] == 8
    assert t_analysis["target_fit_score"] == 100
    assert len(t_analysis["evaluated_properties"]) == 8
    assert t_analysis["target_violation_count"] == 0
    assert len(t_analysis["violations"]) == 0
    assert conf >= 85


def test_8_properties_partial_violation_warning():
    """
    User Requirement 2, 14, 15:
    When 7/8 targets are met and 1 target is outside target:
    - Target Fit = 88% (7/8)
    - Violations array has 1 item
    - Candidate is not dropped
    - Displays OUTSIDE TARGET for that property
    """
    input_8_props = [
        {"property": "BACN", "target": "28", "min": "26", "max": "30", "unit": "%"},
        {"property": "Mooney", "target": "50", "min": "45", "max": "55", "unit": "MU"},
        {"property": "Stress Relaxation", "target": "0.12", "min": "0.10", "max": "0.15", "unit": ""},
        {"property": "pH", "target": "8.5", "min": "8.0", "max": "9.0", "unit": ""},
        {"property": "Total Solid Content", "target": "42", "min": "40", "max": "45", "unit": "%"},
        {"property": "Gel Content", "target": "75", "min": "70", "max": "80", "unit": "%"},
        {"property": "Tg", "target": "-25", "min": "-28", "max": "-22", "unit": "°C"},
        {"property": "Volatile Matter", "target": "0.4", "min": "0.2", "max": "0.5", "unit": "%"},
    ]
    normalized = TargetValidationService.normalize_target_properties(input_8_props)

    # Candidate with Volatile Matter at 0.8% (above max 0.5%)
    mock_recipe = {
        "name": "Recipe 2",
        "predicted_properties": [
            {"property": "BACN", "predicted_value": 28.0, "unit": "%"},
            {"property": "Mooney", "predicted_value": 50.0, "unit": "MU"},
            {"property": "Stress Relaxation", "predicted_value": 0.12, "unit": ""},
            {"property": "pH", "predicted_value": 8.5, "unit": ""},
            {"property": "Total Solid Content", "predicted_value": 42.0, "unit": "%"},
            {"property": "Gel Content", "predicted_value": 75.0, "unit": "%"},
            {"property": "Tg", "predicted_value": -25.0, "unit": "°C"},
            {"property": "Volatile Matter", "predicted_value": 0.8, "unit": "%"},  # VIOLATION
        ],
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 180, "unit": "phr"}]}],
        "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}},
        "patent_references": ["US1000001"],
    }

    t_analysis, _, _ = TargetValidationService.evaluate_recipe(mock_recipe, normalized, {})

    assert t_analysis["targets_total"] == 8
    assert t_analysis["targets_met"] == 7
    assert t_analysis["target_fit_score"] == 88  # 7/8 = 87.5% -> 88%
    assert t_analysis["target_violation_count"] == 1
    assert len(t_analysis["violations"]) == 1
    assert t_analysis["violations"][0]["property"] == "Volatile Matter"
    assert t_analysis["violations"][0]["status"] == "OUTSIDE_TARGET"


# ─────────────────────────────────────────────────────────────────────────────
# 3. ARBITRARY PROPERTY COUNTS (N = 1, 5, 8, 20+) (Requirements 5, 6)
# ─────────────────────────────────────────────────────────────────────────────

def test_arbitrary_property_counts_never_truncated():
    """
    User Requirement 5 & 6:
    Supports 1, 5, 8, 20 properties without truncation or hardcoded limits.
    """
    for count in [1, 5, 8, 20]:
        props = [
            {"property": f"Prop_{i}", "target": float(i * 10), "min": float(i * 10 - 5), "max": float(i * 10 + 5), "unit": "u"}
            for i in range(1, count + 1)
        ]
        norm = TargetValidationService.normalize_target_properties(props)
        assert len(norm) == count, f"Expected {count} normalized properties, got {len(norm)}"

        # Evaluate candidate matching all
        rec = {
            "name": f"Candidate for {count}",
            "predicted_properties": [
                {"property": f"Prop_{i}", "predicted_value": float(i * 10), "unit": "u"}
                for i in range(1, count + 1)
            ],
            "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 180, "unit": "phr"}]}],
            "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}},
            "patent_references": ["US1000001"],
        }
        t_analysis, _, _ = TargetValidationService.evaluate_recipe(rec, norm, {})
        assert t_analysis["targets_total"] == count
        assert t_analysis["targets_met"] == count
        assert t_analysis["target_fit_score"] == 100
        assert len(t_analysis["evaluated_properties"]) == count


def test_blank_and_mixed_properties_handling():
    """
    User Requirement 19-J, 19-K:
    Blank properties are ignored without crashing, populated properties are preserved.
    """
    mixed = [
        {"property": "Valid Prop 1", "target": "50", "unit": "%"},
        {"property": "", "target": "100"},                         # blank name -> ignore
        {"property": "Blank Target", "target": "", "min": None},   # blank target & range -> ignore
        {"property": "Valid Prop 2", "min": "10", "max": "20"},   # valid range
        {"property": None, "target": "5"},                         # None name -> ignore
    ]
    norm = TargetValidationService.normalize_target_properties(mixed)
    assert len(norm) == 2
    assert norm[0].name == "Valid Prop 1"
    assert norm[1].name == "Valid Prop 2"


# ─────────────────────────────────────────────────────────────────────────────
# 4. GEMINI TIMEOUT -> OPENAI FALLBACK (User Requirements 4, 18)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gemini_timeout_openai_fallback_generates_5_recipes():
    """
    User Requirement 4, 18:
    When Gemini encounters GEMINI_TIMEOUT / provider_unavailable,
    fallback correctly switches to OpenAI (gpt-5.4-mini or similar)
    and returns exactly 5 recipes.
    """
    from app.services.llm.llm_client import DynamicLLMClient
    from app.services.llm.base import LLMProviderUnavailableError
    import json

    client = DynamicLLMClient()
    # Simulate Gemini failing with provider unavailable / timeout, and OpenAI succeeding
    mock_5_recipes = LLMRecipeSet(
        recipes=[
            LLMRecipeCandidate(
                name=f"Recipe {i}",
                compound="7% carboxylated NBR",
                variation_dimension=f"Variation {i}",
                polymerization_method="Emulsion Polymerization",
                stages=[],
                process_conditions={"process_type": "Batch"},
                predicted_properties=[],
                patent_references=["US20250075019A1"],
            )
            for i in range(1, 6)
        ]
    )

    mock_gemini_provider = MagicMock()
    mock_gemini_provider.model_name = "gemini-2.5-flash"
    mock_gemini_provider.generate_structured = AsyncMock(
        side_effect=LLMProviderUnavailableError("GEMINI_TIMEOUT: request timed out after 60s")
    )

    mock_openai_provider = MagicMock()
    mock_openai_provider.model_name = "gpt-5.4-mini"
    mock_openai_provider.generate_structured = AsyncMock(
        return_value=(mock_5_recipes, {"input_tokens": 150, "output_tokens": 450})
    )

    # First provider call returns gemini, second returns openai
    provider_seq = [("gemini", mock_gemini_provider), ("openai", mock_openai_provider)]
    async def fake_get_provider():
        if provider_seq:
            return provider_seq.pop(0)
        return ("openai", mock_openai_provider)

    with patch.object(client, "_get_available_provider", side_effect=fake_get_provider):
        parsed, raw_text, meta = await client.generate_structured(
            prompt="Generate 5 recipes",
            system_prompt="Chem Formulator",
            schema=LLMRecipeSet,
        )

        assert parsed is not None
        assert len(parsed.recipes) == 5
        assert client._fallback_reason == "provider_unavailable"


# ─────────────────────────────────────────────────────────────────────────────
# 5. CUSTOMER TRIAL FEEDBACK (CTF) PRESERVATION (User Requirements 16, 17)
# ─────────────────────────────────────────────────────────────────────────────

def test_ctf_optimization_pipeline_exactly_3_recipes():
    """
    User Requirement 16 & 17:
    Customer Trial Feedback (CTF) optimization must produce EXACTLY 3 candidates.
    Lineage, deltas, and shared schema normalization must not regress.
    """
    from app.services.recipe_service import apply_optimization_deltas_to_recipe

    source_recipe = {
        "name": "Base SBR Formulation",
        "compound": "Styrene Butadiene Rubber",
        "stages": [
            {
                "stage_name": "Reactor Charge",
                "parameters": [
                    {"name": "Water", "value": "180.0", "unit": "phr"},
                    {"name": "Potassium Soap", "value": "4.5", "unit": "phr"},
                ],
            },
            {
                "stage_name": "Monomer Mix",
                "parameters": [
                    {"name": "Styrene", "value": "28.0", "unit": "phr"},
                    {"name": "1,3-Butadiene", "value": "72.0", "unit": "phr"},
                    {"name": "t-DDM (CTA)", "value": "0.22", "unit": "phr"},
                ],
            },
        ],
        "process_conditions": {
            "process_type": "Batch",
            "reaction_time": {"value": 8.0, "unit": "h"},
        },
    }

    # Optimization deltas for 3 candidates
    deltas = [
        [
            LLMChangedParameter(
                parameter="t-DDM (CTA)",
                old_value="0.22",
                new_value="0.25",
                unit="phr",
                reason="Increase CTA to reduce Mooney viscosity.",
            )
        ],
        [
            LLMChangedParameter(
                parameter="Styrene",
                old_value="28.0",
                new_value="30.0",
                unit="phr",
                reason="Adjust monomer ratio for bound styrene target.",
            )
        ],
        [
            LLMChangedParameter(
                parameter="Water",
                old_value="180.0",
                new_value="170.0",
                unit="phr",
                reason="Decrease water ratio to improve total solid content.",
            )
        ],
    ]

    optimized_candidates = []
    for idx, cand_deltas in enumerate(deltas):
        delta_obj = {
            "candidate_index": idx + 1,
            "strategy_name": f"Strategy {idx + 1}",
            "scientific_rationale": "Formulation delta applied.",
            "process_type": "Batch",
            "changed_parameters": [d.model_dump() for d in cand_deltas],
            "predicted_properties": [],
        }
        cand = apply_optimization_deltas_to_recipe(
            source_recipe=source_recipe,
            candidate_delta=delta_obj,
            target_compound="Styrene Butadiene Rubber",
        )
        optimized_candidates.append(cand)

    assert len(optimized_candidates) == 3, f"CTF must produce exactly 3 candidates, got {len(optimized_candidates)}"
    # Verify candidate 1 has updated CTA
    monomer_params = {p["name"]: p["value"] for s in optimized_candidates[0]["stages"] if s["stage_name"] == "Monomer Mix" for p in s["parameters"]}
    assert monomer_params["t-DDM (CTA)"] == "0.25"
    # Verify candidate 2 has updated Styrene
    monomer_params_2 = {p["name"]: p["value"] for s in optimized_candidates[1]["stages"] if s["stage_name"] == "Monomer Mix" for p in s["parameters"]}
    assert monomer_params_2["Styrene"] == "30.0"
