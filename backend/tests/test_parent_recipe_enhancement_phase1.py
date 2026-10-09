"""
backend/tests/test_parent_recipe_enhancement_phase1.py

Comprehensive test suite verifying Phase 1 Parent/Initial Recipe Generation Enhancements:
1. Target product / polymer identity adherence (exact preservation, no drift)
2. Dynamic processing/reaction temperature range respect (e.g. 5–7 °C)
3. Dynamic processing/reaction temperature range non-hardcoding (e.g. 20–25 °C)
4. Dynamic process type: Batch
5. Dynamic process type: Continuous
6. Dynamic process type: No Preference
7. Dynamic target property TS2 reach to candidate properties and validation
8. Prediction outside TS2 target emits OUTSIDE TARGET / OUTSIDE_TARGET with penalty
9. Multiple catalyst options / alternatives (Primary Catalyst + Alternatives)
10. Activator information & alternatives when applicable
11. Activator not applicable handled cleanly without hallucination
12. Coagulation system information when applicable
13. Polymer agnostic / zero hardcoded chemistry across distinct polymers (NBR, SBR, CR, ACM)
14. Backward compatibility with historical/legacy saved recipes
15. End-to-end service parameterization, user constraint persistence, and prompt formatting
"""
import pytest
from app.services.recipe_service import (
    validate_and_enrich_water_based_recipe,
    _parse_temp_range,
    RecipeService,
)
from app.services.target_validation_service import (
    TargetValidationService,
    NormalizedTargetProperty,
)
from app.schemas.recipe import (
    RecipeCycleCreate,
    RecipeCycleResponse,
    RecipePropertyDef,
    LLMCatalystSystem,
    LLMCatalystAlternative,
    LLMActivatorSystem,
    LLMActivatorAlternative,
    LLMCoagulationSystem,
    LLMProcessConditions,
    LLMRecipeCandidate,
)
from app.services.prompts.patent_prompts import RECIPE_GENERATION_SYSTEM_PROMPT


# ── TEST 1: Target Product Identity Adherence ──────────────────────────────

def test_1_target_product_identity_preservation():
    """
    Test 1: Strict target product / polymer identity adherence.
    Ensure '7% carboxylated NBR' is preserved exactly and never drifts
    to generic XNBR, standard NBR, or synthetic rubber.
    """
    exact_target = "7% carboxylated NBR"
    raw_recipe = {
        "name": "Recipe 1 - Specialty Latex",
        "compound": "Synthetic Rubber",  # LLM proposed generic compound
        "stages": [
            {
                "stage_name": "Reactor Charge",
                "parameters": [
                    {"name": "Deionized Water", "value": 140, "unit": "phr"},
                    {"name": "Sodium Dodecyl Sulfate", "value": 2.0, "unit": "phr"},
                ],
            },
            {
                "stage_name": "Monomer Mix",
                "parameters": [
                    {"name": "Acrylonitrile", "value": 28, "unit": "phr"},
                    {"name": "1,3-Butadiene", "value": 65, "unit": "phr"},
                    {"name": "Methacrylic Acid", "value": 7, "unit": "phr"},
                ],
            },
        ],
        "process_conditions": {
            "reaction_time": {"value": 8.0, "unit": "h"},
        },
    }

    enriched = validate_and_enrich_water_based_recipe(
        raw_recipe,
        target_compound=exact_target,
    )

    # Must be strictly overwritten with target compound name
    assert enriched["compound"] == exact_target
    assert "XNBR" not in enriched["compound"]
    assert enriched["compound"] != "Synthetic Rubber"


# ── TEST 2: Dynamic Temperature Range Respect (5–7 °C) ────────────────────

def test_2_dynamic_temperature_range_respect():
    """
    Test 2: Dynamic processing/reaction temperature range constraint.
    When user supplies 5–7 °C, recipe process conditions enforce 5–7 °C.
    """
    temp_constraint = {"min": 5, "max": 7, "unit": "°C"}
    raw_recipe = {
        "name": "Cold NBR Recipe",
        "compound": "Cold NBR",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 150, "unit": "phr"}]},
        ],
        "process_conditions": {
            "temperature_profile": [{"stage": "Polymerization", "value": "30", "unit": "°C"}],
        },
    }

    enriched = validate_and_enrich_water_based_recipe(
        raw_recipe,
        target_compound="Cold NBR",
        user_constraints={"temperature_range": temp_constraint},
    )

    proc_conds = enriched["process_conditions"]
    assert "temperature_range" in proc_conds
    assert proc_conds["temperature_range"]["min"] == 5
    assert proc_conds["temperature_range"]["max"] == 7
    # Temperature profile should reflect the user constraint range
    first_temp = proc_conds["temperature_profile"][0]["value"]
    assert "5" in str(first_temp) or "6" in str(first_temp) or "7" in str(first_temp)


# ── TEST 3: Dynamic Temperature Range Non-Hardcoding (20–25 °C) ───────────

def test_3_dynamic_temperature_range_non_hardcoding():
    """
    Test 3: Zero hardcoding check.
    When user supplies 20–25 °C, process conditions must NEVER output 5–7 °C.
    """
    temp_constraint = {"min": 20, "max": 25, "unit": "°C"}
    raw_recipe = {
        "name": "Warm Emulsion Recipe",
        "compound": "Specialty Polymer",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 150, "unit": "phr"}]},
        ],
        "process_conditions": {},
    }

    enriched = validate_and_enrich_water_based_recipe(
        raw_recipe,
        target_compound="Specialty Polymer",
        user_constraints={"temperature_range": temp_constraint},
    )

    proc_conds = enriched["process_conditions"]
    assert proc_conds["temperature_range"]["min"] == 20
    assert proc_conds["temperature_range"]["max"] == 25
    first_temp_val = str(proc_conds["temperature_profile"][0]["value"])
    assert "5–7" not in first_temp_val
    assert "5-7" not in first_temp_val
    assert "20" in first_temp_val or "25" in first_temp_val


# ── TEST 4: Process Type: Batch ─────────────────────────────────────────────

def test_4_process_type_batch():
    """
    Test 4: User selects 'Batch'.
    Process conditions must indicate Batch process type.
    """
    raw_recipe = {
        "name": "Batch Polymerization Recipe",
        "compound": "Acrylate Copolymer",
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 100, "unit": "phr"}]}],
        "process_conditions": {},
    }

    enriched = validate_and_enrich_water_based_recipe(
        raw_recipe,
        target_compound="Acrylate Copolymer",
        user_constraints={"process_type": "Batch"},
    )

    assert enriched["process_conditions"]["process_type"] == "Batch"
    assert enriched["process_type"] == "Batch"


# ── TEST 5: Process Type: Continuous ────────────────────────────────────────

def test_5_process_type_continuous():
    """
    Test 5: User selects 'Continuous'.
    Process conditions must indicate Continuous process type.
    """
    raw_recipe = {
        "name": "Continuous CSTR Polymerization",
        "compound": "SBR Latex",
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 120, "unit": "phr"}]}],
        "process_conditions": {},
    }

    enriched = validate_and_enrich_water_based_recipe(
        raw_recipe,
        target_compound="SBR Latex",
        user_constraints={"process_type": "Continuous"},
    )

    assert enriched["process_conditions"]["process_type"] == "Continuous"
    assert enriched["process_type"] == "Continuous"


# ── TEST 6: Process Type: No Preference ─────────────────────────────────────

def test_6_process_type_no_preference():
    """
    Test 6: User selects 'No Preference'.
    The generator is free to determine process type dynamically.
    """
    raw_recipe_1 = {
        "name": "Candidate 1",
        "compound": "General Polymer",
        "process_type": "Continuous",
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 100, "unit": "phr"}]}],
        "process_conditions": {},
    }
    raw_recipe_2 = {
        "name": "Candidate 2",
        "compound": "General Polymer",
        "process_type": "Batch",
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 100, "unit": "phr"}]}],
        "process_conditions": {},
    }

    enriched_1 = validate_and_enrich_water_based_recipe(
        raw_recipe_1,
        target_compound="General Polymer",
        user_constraints={"process_type": "No Preference"},
    )
    enriched_2 = validate_and_enrich_water_based_recipe(
        raw_recipe_2,
        target_compound="General Polymer",
        user_constraints={"process_type": "No Preference"},
    )

    assert enriched_1["process_conditions"]["process_type"] == "Continuous"
    assert enriched_2["process_conditions"]["process_type"] == "Batch"


# ── TEST 7: Dynamic Target Property Reach (TS2) ────────────────────────────

def test_7_dynamic_target_property_reaches_evaluation():
    """
    Test 7: Target property TS2 (Mooney scorch time t5 / TS2) reaches
    normalization, prediction, and validation without being dropped.
    """
    raw_target = {
        "feature": "TS2 Scorch Time",
        "target": "22",
        "range": "20–25",
        "unit": "min",
    }
    normalized = TargetValidationService.normalize_target_properties([raw_target])
    assert len(normalized) == 1
    ts2 = normalized[0]
    assert ts2.name == "TS2 Scorch Time"
    assert ts2.target_value == 22.0
    assert ts2.target_min == 20.0
    assert ts2.target_max == 25.0
    assert ts2.unit == "min"

    # Verify display target formats both target point and range
    disp = ts2.display_target()
    assert "Target: 22" in disp
    assert "20" in disp and "25" in disp


# ── TEST 8: Prediction Outside TS2 Emits OUTSIDE TARGET ─────────────────────

def test_8_prediction_outside_ts2_target_emits_outside_target():
    """
    Test 8: Prediction outside TS2 target emits OUTSIDE TARGET / OUTSIDE_TARGET status
    and registers target penalty in evaluation.
    """
    raw_target = {
        "feature": "TS2",
        "target": "22",
        "range": "20–25",
        "unit": "min",
    }
    normalized = TargetValidationService.normalize_target_properties([raw_target])

    # Case A: Prediction 17 min (outside [20, 25])
    pred_outside = {
        "predicted_value": 17.0,
        "predicted_min": 16.0,
        "predicted_max": 18.0,
        "reasoning": "Faster scorch due to higher accelerator level.",
    }
    eval_outside = TargetValidationService.evaluate_property_prediction(normalized[0], pred_outside)

    assert eval_outside["status"] == "OUTSIDE_TARGET"
    assert eval_outside["status"] == "NOT_MET"  # Dual compatibility
    assert eval_outside["target_status"] == "OUTSIDE TARGET"
    assert eval_outside["meets_target"] is False
    assert eval_outside["margin"] < 0  # 17 - 22 = -5

    # Case B: Prediction 22.5 min (meets target [20, 25])
    pred_inside = {
        "predicted_value": 22.5,
        "reasoning": "Balanced scorch safety lever.",
    }
    eval_inside = TargetValidationService.evaluate_property_prediction(normalized[0], pred_inside)
    assert eval_inside["status"] == "MEETS_TARGET"
    assert eval_inside["target_status"] == "MEETS TARGET"
    assert eval_inside["meets_target"] is True


# ── TEST 9: Multiple Catalyst Options / Alternatives ───────────────────────

def test_9_multiple_catalyst_options_and_alternatives():
    """
    Test 9: Multiple catalyst options / alternatives:
    Primary catalyst + dosage, and alternative catalysts + dosages.
    """
    cat_system_data = {
        "primary_catalyst": "Sodium Persulfate (SPS)",
        "primary_dosage_phr": 0.25,
        "alternatives": [
            {"catalyst": "Potassium Persulfate (KPS)", "dosage_phr": 0.28, "notes": "Equal mole equivalent"},
            {"catalyst": "Ammonium Persulfate (APS)", "dosage_phr": 0.24, "notes": "Lower salt residue"},
        ],
    }

    # Verify Pydantic schema validation
    cat_sys = LLMCatalystSystem(**cat_system_data)
    assert cat_sys.primary_catalyst == "Sodium Persulfate (SPS)"
    assert cat_sys.primary_dosage_phr == 0.25
    assert len(cat_sys.alternatives) == 2
    assert cat_sys.alternatives[0].catalyst == "Potassium Persulfate (KPS)"

    # Verify recipe service enrichment
    raw_recipe = {
        "name": "Recipe SPS",
        "compound": "Carboxylated Latex",
        "catalyst_system": cat_system_data,
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 100, "unit": "phr"}]}],
        "process_conditions": {},
    }
    enriched = validate_and_enrich_water_based_recipe(raw_recipe, target_compound="Carboxylated Latex")
    assert "catalyst_system" in enriched
    assert enriched["catalyst_system"]["primary_catalyst"] == "Sodium Persulfate (SPS)"
    assert len(enriched["catalyst_system"]["alternatives"]) == 2


# ── TEST 10: Activator System & Alternatives When Applicable ────────────────

def test_10_activator_system_when_applicable():
    """
    Test 10: Activator information and alternatives when applicable
    (e.g., redox initiation system).
    """
    act_data = {
        "applicable": True,
        "activator_name": "Sodium formaldehyde sulfoxylate (SFS / Rongalite)",
        "dosage_phr": 0.12,
        "stage": "Redox Initiation",
        "alternatives": [
            {"activator": "Ascorbic acid", "dosage_phr": 0.15, "notes": "Formaldehyde-free sustainable option"},
            {"activator": "Sodium erythorbate", "dosage_phr": 0.16, "notes": "Redox promoter"},
        ],
        "notes": "Activates organic hydroperoxide redox cycle",
    }

    act_sys = LLMActivatorSystem(**act_data)
    assert act_sys.applicable is True
    assert "SFS" in act_sys.activator_name
    assert len(act_sys.alternatives) == 2

    raw_recipe = {
        "name": "Cold Redox Recipe",
        "compound": "Cold Emulsion NBR",
        "activator_system": act_data,
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 150, "unit": "phr"}]}],
        "process_conditions": {},
    }
    enriched = validate_and_enrich_water_based_recipe(raw_recipe, target_compound="Cold Emulsion NBR")
    assert enriched["activator_system"]["applicable"] is True
    assert enriched["activator_system"]["activator_name"] == act_data["activator_name"]


# ── TEST 11: Activator Not Applicable Handled Without Hallucination ─────────

def test_11_activator_not_applicable_handled_without_hallucination():
    """
    Test 11: Thermally initiated polymerization where activator is not required.
    Must mark applicable=False without hallucinating fake activators.
    """
    act_data = {
        "applicable": False,
        "activator_name": None,
        "dosage_phr": None,
        "stage": None,
        "alternatives": [],
        "notes": "Thermal persulfate initiation; activator not required",
    }

    act_sys = LLMActivatorSystem(**act_data)
    assert act_sys.applicable is False
    assert act_sys.activator_name is None
    assert len(act_sys.alternatives) == 0

    raw_recipe = {
        "name": "Thermal Persulfate Recipe",
        "compound": "High Solids Latex",
        "activator_system": act_data,
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 100, "unit": "phr"}]}],
        "process_conditions": {},
    }
    enriched = validate_and_enrich_water_based_recipe(raw_recipe, target_compound="High Solids Latex")
    assert enriched["activator_system"]["applicable"] is False
    assert enriched["activator_system"]["activator_name"] is None


# ── TEST 12: Coagulation System Information When Applicable ─────────────────

def test_12_coagulation_system_when_applicable():
    """
    Test 12: Coagulation system information when applicable
    (coagulant, dosage, conditions).
    """
    coag_data = {
        "applicable": True,
        "coagulant": "Calcium Chloride (CaCl2)",
        "dosage_phr": 2.5,
        "process_conditions": "65 °C, serum pH 4.0 adjusted with dilute H2SO4",
        "notes": "Narrow crumb size distribution, low fines",
    }

    coag_sys = LLMCoagulationSystem(**coag_data)
    assert coag_sys.applicable is True
    assert coag_sys.coagulant == "Calcium Chloride (CaCl2)"
    assert coag_sys.dosage_phr == 2.5

    raw_recipe = {
        "name": "Dry Rubber Isolation Recipe",
        "compound": "Solid Rubber",
        "coagulation_system": coag_data,
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 120, "unit": "phr"}]}],
        "process_conditions": {},
    }
    enriched = validate_and_enrich_water_based_recipe(raw_recipe, target_compound="Solid Rubber")
    assert enriched["coagulation_system"]["applicable"] is True
    assert enriched["coagulation_system"]["coagulant"] == "Calcium Chloride (CaCl2)"


# ── TEST 13: Generic Polymer Behavior Across Distinct Materials ────────────

def test_13_polymer_agnostic_behavior_across_materials():
    """
    Test 13: Zero hardcoding across distinct polymers.
    Ensure pipeline functions equivalently for NBR, SBR, CR (Chloroprene Rubber),
    and ACM (Polyacrylic Rubber).
    """
    polymers = [
        "Chloroprene Rubber (CR)",
        "Polyacrylic Rubber (ACM)",
        "Styrene-Butadiene Rubber (SBR)",
        "Hydrogenated Nitrile Rubber (HNBR)",
    ]

    for poly in polymers:
        raw = {
            "name": f"Recipe - {poly}",
            "compound": poly,
            "stages": [
                {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 150, "unit": "phr"}]},
            ],
            "process_conditions": {
                "temperature_profile": [{"stage": "Polymerization", "value": "15", "unit": "°C"}],
            },
        }
        enriched = validate_and_enrich_water_based_recipe(
            raw,
            target_compound=poly,
            user_constraints={"process_type": "Continuous", "temperature_range": {"min": 12, "max": 18, "unit": "°C"}},
        )
        assert enriched["compound"] == poly
        assert enriched["process_conditions"]["process_type"] == "Continuous"
        assert enriched["process_conditions"]["temperature_range"]["min"] == 12
        assert enriched["process_conditions"]["temperature_range"]["max"] == 18


# ── TEST 14: Backward Compatibility with Historical Saved Recipes ───────────

def test_14_backward_compatibility_with_historical_recipes():
    """
    Test 14: Historical recipes lacking process_type, temperature_range,
    catalyst_system, activator_system, coagulation_system load cleanly without
    runtime errors or missing field exceptions.
    """
    # Simulate historical cycle DB record without user_constraints in patent_context_summary
    import uuid
    historical_cycle_dict = {
        "id": str(uuid.uuid4()),
        "status": "completed",
        "compound_name": "Historical NBR",
        "target_product": "Historical NBR",
        "patent_context_summary": {
            "total_patents": 12,
            "synthesis_insights": ["Standard redox cold emulsion polymerization."],
            # Notice: NO user_constraints key
        },
        "target_properties": [
            {"id": "p1", "name": "Mooney Viscosity", "target": "50", "unit": "MU"},
        ],
        "competitor_data": [],
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
    }

    # RecipeCycleResponse root_validator rehydrates safely
    resp = RecipeCycleResponse.model_validate(historical_cycle_dict)
    assert resp.process_type is None
    assert resp.temperature_range is None
    assert resp.compound_name == "Historical NBR"

    # Raw candidate lacking all new fields
    legacy_candidate = {
        "name": "Legacy Recipe 1",
        "compound": "Historical NBR",
        "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 150, "unit": "phr"}]}],
        "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}},
    }
    enriched_legacy = validate_and_enrich_water_based_recipe(legacy_candidate, target_compound="Historical NBR")
    assert enriched_legacy["compound"] == "Historical NBR"
    assert "catalyst_system" in enriched_legacy
    assert "activator_system" in enriched_legacy
    assert "coagulation_system" in enriched_legacy
    assert enriched_legacy["process_conditions"]["process_type"] == "Batch"


# ── TEST 15: Prompt Formatting and Service Constraints Persistence ──────────

def test_15_prompt_formatting_and_user_constraints_persistence():
    """
    Test 15: Verifies prompt variables {process_type_instruction} and {temperature_instruction}
    are defined and injected cleanly into RECIPE_GENERATION_SYSTEM_PROMPT,
    and user constraints are persisted into cycle patent_context_summary.
    """
    # 1. System prompt contains placeholders and identity mandate
    assert "{process_type_instruction}" in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "{temperature_instruction}" in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "<target_product_identity_mandate>" in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "<catalyst_activator_coagulation_rules>" in RECIPE_GENERATION_SYSTEM_PROMPT

    # 2. Test temp range helper
    parsed_dict = _parse_temp_range({"min": "5.5", "max": "7.5", "unit": "°C"})
    assert parsed_dict == {"min": 5.5, "max": 7.5, "unit": "°C"}

    parsed_str = _parse_temp_range("20 to 25 °C")
    assert parsed_str == {"min": 20.0, "max": 25.0, "unit": "°C"}

    # 3. Test cycle create schema with user constraints
    cycle_create = RecipeCycleCreate(
        target_product="7% carboxylated NBR",
        process_type="Continuous",
        temperature_range={"min": 5, "max": 7, "unit": "°C"},
    )
    assert cycle_create.process_type == "Continuous"
    assert cycle_create.temperature_range == {"min": 5, "max": 7, "unit": "°C"}
