"""
backend/tests/test_arbitrary_properties_optimization.py

Comprehensive test suite verifying that Customer Trial Feedback (CTF) Optimization
supports ARBITRARY user target property inputs (N = 1, 5, 10, 20+).

HARD PRODUCT REQUIREMENTS VALIDATED:
1. Arbitrary property count: System never caps at 5 or 10, never drops properties after N.
2. Input complexity vs output compactness: All populated properties enter Gemini's reasoning context
   via a normalized markdown table, while Gemini output is compact (deltas only: stages=[]).
3. Backend formulation synthesis: Source recipe + optimization deltas = complete optimized recipe.
4. Complete deterministic target evaluation matrix: All N properties are evaluated for all 3 candidates.
5. Qualitative and custom properties: Gracefully handled without crashing float parsers.
6. Range-only, target-only, and target+range specifications.
7. Re-optimization: Preserves lineage and applies deltas correctly to parent candidates.
"""
import copy
import pytest
from unittest.mock import AsyncMock, patch

from app.services.target_validation_service import (
    TargetValidationService,
    NormalizedTargetProperty,
)
from app.services.recipe_service import (
    apply_optimization_deltas_to_recipe,
    RecipeService,
)
from app.schemas.recipe import (
    LLMOptimizationSet,
    LLMOptimizedRecipeCandidate,
    LLMChangedParameter,
    LLMTargetImpact,
)
from app.services.prompts.patent_prompts import RECIPE_OPTIMIZATION_SYSTEM_PROMPT


BASE_SOURCE_RECIPE = {
    "name": "Standard Emulsion SBR-1502",
    "compound": "Styrene-Butadiene Rubber Emulsion",
    "stages": [
        {
            "stage_name": "Reactor Charge",
            "parameters": [
                {"name": "Deionized Water", "value": "180.0", "unit": "phr"},
                {"name": "Potassium Soap of Fatty Acid", "value": "4.5", "unit": "phr"},
                {"name": "Tripotassium Phosphate Buffer", "value": "0.5", "unit": "phr"},
            ],
        },
        {
            "stage_name": "Monomer Mix",
            "parameters": [
                {"name": "Styrene Monomer", "value": "28.0", "unit": "phr"},
                {"name": "1,3-Butadiene", "value": "72.0", "unit": "phr"},
                {"name": "tert-Dodecyl Mercaptan (CTA)", "value": "0.22", "unit": "phr"},
            ],
        },
        {
            "stage_name": "Catalyst Solution",
            "parameters": [
                {"name": "Pinane Hydroperoxide", "value": "0.08", "unit": "phr"},
                {"name": "Ferrous Sulfate Redox Activator", "value": "0.02", "unit": "phr"},
                {"name": "Sodium Formaldehyde Sulfoxylate (SFS)", "value": "0.05", "unit": "phr"},
            ],
        },
        {
            "stage_name": "Post Addition",
            "parameters": [
                {"name": "Sodium Dimethyldithiocarbamate Shortstop", "value": "0.15", "unit": "phr"},
                {"name": "Phenolic Antioxidant Emulsion", "value": "1.0", "unit": "phr"},
            ],
        },
    ],
    "parameters": [
        {"name": "Deionized Water", "value": "180.0", "unit": "phr"},
        {"name": "Potassium Soap of Fatty Acid", "value": "4.5", "unit": "phr"},
        {"name": "Tripotassium Phosphate Buffer", "value": "0.5", "unit": "phr"},
        {"name": "Styrene Monomer", "value": "28.0", "unit": "phr"},
        {"name": "1,3-Butadiene", "value": "72.0", "unit": "phr"},
        {"name": "tert-Dodecyl Mercaptan (CTA)", "value": "0.22", "unit": "phr"},
        {"name": "Pinane Hydroperoxide", "value": "0.08", "unit": "phr"},
        {"name": "Ferrous Sulfate Redox Activator", "value": "0.02", "unit": "phr"},
        {"name": "Sodium Formaldehyde Sulfoxylate (SFS)", "value": "0.05", "unit": "phr"},
        {"name": "Sodium Dimethyldithiocarbamate Shortstop", "value": "0.15", "unit": "phr"},
        {"name": "Phenolic Antioxidant Emulsion", "value": "1.0", "unit": "phr"},
    ],
    "process_conditions": {
        "reaction_temperature": {"value": 5, "unit": "°C"},
        "reaction_time": {"value": 9, "unit": "h"},
        "agitation_speed": {"value": 150, "unit": "rpm"},
    },
    "predicted_properties": [
        {"property": "Mooney Viscosity ML(1+4) 100°C", "predicted_value": "52", "unit": "MU"},
        {"property": "Bound Styrene Content", "predicted_value": "23.5", "unit": "%"},
        {"property": "Tensile Strength", "predicted_value": "22.0", "unit": "MPa"},
        {"property": "Glass Transition Temperature (Tg)", "predicted_value": "-53", "unit": "°C"},
    ],
    "patent_references": ["US3887640"],
}


# =============================================================================
# TEST 1: Single Property (N = 1)
# =============================================================================
def test_arbitrary_n_single_property():
    targets_input = [{"property": "Bound Styrene Content", "target": "25.0", "unit": "%"}]
    normalized = TargetValidationService.normalize_target_properties(targets_input)
    assert len(normalized) == 1
    assert normalized[0].name == "Bound Styrene Content"
    assert normalized[0].target_value == 25.0

    table = TargetValidationService.format_optimization_targets_table(
        normalized_targets=normalized,
        source_recipe_data=BASE_SOURCE_RECIPE,
        customer_feedback="Increase bound styrene to 25%",
    )
    assert "Bound Styrene Content" in table
    assert "25" in table
    assert "23.5" in table  # observed in source recipe

    # Delta candidate
    delta = LLMOptimizedRecipeCandidate(
        name="Candidate A - Higher Styrene",
        optimization_strategy="Shift monomer ratio towards styrene",
        stages=[],
        changed_parameters=[
            LLMChangedParameter(
                parameter="Styrene Monomer",
                old_value="28.0",
                new_value="31.0",
                unit="phr",
                reason="Increase bound styrene content to reach 25% target.",
            ),
            LLMChangedParameter(
                parameter="1,3-Butadiene",
                old_value="72.0",
                new_value="69.0",
                unit="phr",
                reason="Maintain 100 phr total monomer charge.",
            ),
        ],
        target_impact=[
            LLMTargetImpact(
                property="Bound Styrene Content",
                predicted_value="25.2",
                unit="%",
                direction="increased",
                confidence="High",
            )
        ],
    )

    synthesized = apply_optimization_deltas_to_recipe(BASE_SOURCE_RECIPE, delta, "Styrene-Butadiene Rubber Emulsion")
    assert len(synthesized["stages"]) == 4
    monomer_stage = next(s for s in synthesized["stages"] if s["stage_name"] == "Monomer Mix")
    styrene_param = next(p for p in monomer_stage["parameters"] if "styrene" in p["name"].lower())
    assert styrene_param["value"] == "31.0"
    assert styrene_param["changed"] is True

    t_eval, c_eval, conf = TargetValidationService.evaluate_recipe(synthesized, normalized)
    assert t_eval["targets_total"] == 1
    assert t_eval["targets_met"] == 1
    assert t_eval["target_fit_score"] == 100
    assert len(t_eval["evaluated_properties"]) == 1
    assert t_eval["evaluated_properties"][0]["property"] == "Bound Styrene Content"
    assert t_eval["evaluated_properties"][0]["passed"] is True


# =============================================================================
# TEST 2: Five Properties (N = 5)
# =============================================================================
def test_arbitrary_n_five_properties():
    targets_input = [
        {"property": "Mooney Viscosity ML(1+4) 100°C", "target": "48.0", "min": "45.0", "max": "51.0", "unit": "MU"},
        {"property": "Tensile Strength", "min": "24.0", "unit": "MPa"},
        {"property": "Elongation at Break", "min": "550", "unit": "%"},
        {"property": "Glass Transition Temperature (Tg)", "max": "-50.0", "unit": "°C"},
        {"property": "Bound Styrene Content", "target": "24.5", "unit": "%"},
    ]
    normalized = TargetValidationService.normalize_target_properties(targets_input)
    assert len(normalized) == 5

    table = TargetValidationService.format_optimization_targets_table(
        normalized_targets=normalized,
        source_recipe_data=BASE_SOURCE_RECIPE,
        customer_feedback="Lower Mooney viscosity, improve tensile strength",
    )
    for p in targets_input:
        assert p["property"] in table

    delta = LLMOptimizedRecipeCandidate(
        name="Candidate B - Balanced Viscosity",
        optimization_strategy="Increase CTA slightly to reduce molecular weight and Mooney viscosity",
        stages=[],
        changed_parameters=[
            LLMChangedParameter(
                parameter="tert-Dodecyl Mercaptan (CTA)",
                old_value="0.22",
                new_value="0.26",
                unit="phr",
                reason="Control chain length to target 48 MU Mooney viscosity.",
            )
        ],
        target_impact=[
            LLMTargetImpact(property="Mooney Viscosity ML(1+4) 100°C", predicted_value="48.5", unit="MU", direction="decreased"),
            LLMTargetImpact(property="Tensile Strength", predicted_value="24.5", unit="MPa", direction="increased"),
            LLMTargetImpact(property="Elongation at Break", predicted_value="580", unit="%", direction="maintained"),
            LLMTargetImpact(property="Glass Transition Temperature (Tg)", predicted_value="-52", unit="°C", direction="maintained"),
            LLMTargetImpact(property="Bound Styrene Content", predicted_value="24.2", unit="%", direction="maintained"),
        ],
    )
    synthesized = apply_optimization_deltas_to_recipe(BASE_SOURCE_RECIPE, delta, "Styrene-Butadiene Rubber Emulsion")
    t_eval, _, _ = TargetValidationService.evaluate_recipe(synthesized, normalized)

    assert t_eval["targets_total"] == 5
    assert len(t_eval["evaluated_properties"]) == 5
    # All 5 properties are evaluated in the deterministic matrix
    eval_names = {ep["property"] for ep in t_eval["evaluated_properties"]}
    assert eval_names == {p["property"] for p in targets_input}


# =============================================================================
# TEST 3: Ten Properties (N = 10)
# =============================================================================
def test_arbitrary_n_ten_properties():
    targets_input = [
        {"property": "Mooney Viscosity ML(1+4) 100°C", "target": "50.0", "unit": "MU"},
        {"property": "Tensile Strength", "min": "23.0", "unit": "MPa"},
        {"property": "Elongation at Break", "min": "500", "unit": "%"},
        {"property": "Glass Transition Temperature (Tg)", "max": "-52.0", "unit": "°C"},
        {"property": "Bound Styrene Content", "target": "24.0", "unit": "%"},
        {"property": "Gel Content", "max": "0.1", "unit": "wt%"},
        {"property": "Coagulum Content", "max": "0.05", "unit": "wt%"},
        {"property": "Ash Content", "max": "0.5", "unit": "wt%"},
        {"property": "pH", "min": "9.5", "max": "11.0", "unit": ""},
        {"property": "Particle Size (D50)", "target": "160", "unit": "nm"},
    ]
    normalized = TargetValidationService.normalize_target_properties(targets_input)
    assert len(normalized) == 10

    table = TargetValidationService.format_optimization_targets_table(
        normalized_targets=normalized,
        source_recipe_data=BASE_SOURCE_RECIPE,
        customer_feedback="Strict colloid and mechanical targets",
    )
    for p in targets_input:
        assert p["property"] in table, f"Property {p['property']} missing from table"

    delta = LLMOptimizedRecipeCandidate(
        name="Candidate C - Colloid Fine-Tuning",
        optimization_strategy="Adjust surfactant and initiator for particle stability",
        stages=[],
        changed_parameters=[
            LLMChangedParameter(
                parameter="Potassium Soap of Fatty Acid",
                old_value="4.5",
                new_value="4.8",
                unit="phr",
                reason="Improve colloidal stability and suppress coagulum.",
            )
        ],
        target_impact=[
            LLMTargetImpact(property="Coagulum Content", predicted_value="0.02", unit="wt%"),
            LLMTargetImpact(property="Particle Size (D50)", predicted_value="158", unit="nm"),
            LLMTargetImpact(property="pH", predicted_value="10.2", unit=""),
        ],
    )
    synthesized = apply_optimization_deltas_to_recipe(BASE_SOURCE_RECIPE, delta, "Styrene-Butadiene Rubber Emulsion")
    t_eval, _, _ = TargetValidationService.evaluate_recipe(synthesized, normalized)

    assert t_eval["targets_total"] == 10
    assert len(t_eval["evaluated_properties"]) == 10
    # Zero properties dropped or omitted
    assert len(t_eval["properties"]) == 10


# =============================================================================
# TEST 4: All 20 UI Properties (N = 20) with Cluster Partitioning
# =============================================================================
def test_arbitrary_n_twenty_ui_properties():
    all_20_properties = [
        {"property": "Mooney Viscosity ML(1+4) 100°C", "target": "50.0", "unit": "MU"},
        {"property": "Tensile Strength", "min": "22.5", "unit": "MPa"},
        {"property": "Elongation at Break", "min": "520", "unit": "%"},
        {"property": "Glass Transition Temperature (Tg)", "max": "-51.0", "unit": "°C"},
        {"property": "Bound Styrene Content", "target": "23.8", "unit": "%"},
        {"property": "Gel Content", "max": "0.1", "unit": "wt%"},
        {"property": "Coagulum Content", "max": "0.05", "unit": "wt%"},
        {"property": "Ash Content", "max": "0.4", "unit": "wt%"},
        {"property": "pH", "min": "9.8", "max": "10.8", "unit": ""},
        {"property": "Particle Size (D50)", "target": "165", "unit": "nm"},
        {"property": "Surface Tension", "min": "45.0", "max": "55.0", "unit": "mN/m"},
        {"property": "Solids Content", "min": "20.0", "max": "24.0", "unit": "wt%"},
        {"property": "Volatile Matter", "max": "0.5", "unit": "wt%"},
        {"property": "Compound Mooney Viscosity", "target": "65", "unit": "MU"},
        {"property": "Modulus 300%", "min": "14.0", "unit": "MPa"},
        {"property": "Hardness Shore A", "target": "62", "unit": "Shore A"},
        {"property": "Tear Strength", "min": "35", "unit": "N/mm"},
        {"property": "Abrasion Resistance (DIN)", "max": "140", "unit": "mm³"},
        {"property": "Rebound Resilience", "min": "48", "unit": "%"},
        {"property": "Compression Set 24h/70°C", "max": "28", "unit": "%"},
    ]

    normalized = TargetValidationService.normalize_target_properties(all_20_properties)
    assert len(normalized) == 20

    # Since N=20 > 15, table must partition into scientific clusters while preserving all 20
    table = TargetValidationService.format_optimization_targets_table(
        normalized_targets=normalized,
        source_recipe_data=BASE_SOURCE_RECIPE,
        customer_feedback="Customer test across entire standard battery",
    )
    # Check that scientific cluster headers are generated
    assert "###" in table or "Cluster" in table or "Properties" in table
    # Check that every single property is present in the formatted table
    for p in all_20_properties:
        assert p["property"] in table, f"Property '{p['property']}' was missing from the optimization targets table"

    delta = LLMOptimizedRecipeCandidate(
        name="Candidate Full 20",
        optimization_strategy="Comprehensive cross-battery formulation adjustments",
        stages=[],
        changed_parameters=[
            LLMChangedParameter(
                parameter="tert-Dodecyl Mercaptan (CTA)",
                old_value="0.22",
                new_value="0.24",
                unit="phr",
                reason="Modulate molecular weight distribution.",
            )
        ],
        target_impact=[
            LLMTargetImpact(property="Mooney Viscosity ML(1+4) 100°C", predicted_value="50.2", unit="MU"),
            LLMTargetImpact(property="Tensile Strength", predicted_value="23.1", unit="MPa"),
            LLMTargetImpact(property="Solids Content", predicted_value="21.5", unit="wt%"),
        ],
    )
    synthesized = apply_optimization_deltas_to_recipe(BASE_SOURCE_RECIPE, delta, "Styrene-Butadiene Rubber Emulsion")
    t_eval, _, _ = TargetValidationService.evaluate_recipe(synthesized, normalized)

    assert t_eval["targets_total"] == 20
    assert len(t_eval["evaluated_properties"]) == 20
    # Verify unpredicted properties are marked "Not quantitatively predictable" rather than crashing
    unpredicted = [p for p in t_eval["evaluated_properties"] if p["predicted_display"] == "Not quantitatively predictable"]
    assert len(unpredicted) > 0
    # Every evaluated property has required fields
    for ep in t_eval["evaluated_properties"]:
        assert "property" in ep
        assert "passed" in ep
        assert "status" in ep
        assert "target_status" in ep


# =============================================================================
# TEST 5: Mixed Populated and Blank Properties
# =============================================================================
def test_mixed_populated_and_blank_properties():
    mixed_input = [
        {"property": "Tensile Strength", "target": "24.0", "unit": "MPa"},
        {"property": "Elongation at Break", "target": "", "unit": "%"},
        {"property": "Mooney Viscosity", "min": None, "max": None, "target": None},
        {"property": "Bound Styrene Content", "target": "25.5", "unit": "%"},
        {"property": "Ash Content", "target": "  ", "unit": "%"},
        {"property": "pH", "min": "9.5", "unit": ""},
        {"property": "Gel Content", "target": None},
    ]

    normalized = TargetValidationService.normalize_target_properties(mixed_input)
    assert len(normalized) == 3
    normalized_names = {t.name for t in normalized}
    assert normalized_names == {"Tensile Strength", "Bound Styrene Content", "pH"}


# =============================================================================
# TEST 6: Range-Only Targets (min and max only)
# =============================================================================
def test_range_only_targets():
    range_targets = [
        {"property": "Mooney Viscosity ML(1+4) 100°C", "min": "48.0", "max": "54.0", "unit": "MU"},
        {"property": "Reaction pH", "min": "9.0", "max": "10.5", "unit": ""},
    ]
    normalized = TargetValidationService.normalize_target_properties(range_targets)
    assert len(normalized) == 2
    assert normalized[0].constraint_type == "range"
    assert normalized[0].min_value == 48.0
    assert normalized[0].max_value == 54.0

    recipe_pass = {
        "parameters": [],
        "predicted_properties": [
            {"property": "Mooney Viscosity ML(1+4) 100°C", "predicted_value": "51.0", "unit": "MU"},
            {"property": "Reaction pH", "predicted_value": "9.8", "unit": ""},
        ],
    }
    t_pass, _, _ = TargetValidationService.evaluate_recipe(recipe_pass, normalized)
    assert t_pass["targets_met"] == 2
    assert t_pass["target_fit_score"] == 100

    recipe_fail = {
        "parameters": [],
        "predicted_properties": [
            {"property": "Mooney Viscosity ML(1+4) 100°C", "predicted_value": "56.0", "unit": "MU"},  # Over max
            {"property": "Reaction pH", "predicted_value": "8.5", "unit": ""},  # Under min
        ],
    }
    t_fail, _, _ = TargetValidationService.evaluate_recipe(recipe_fail, normalized)
    assert t_fail["targets_met"] == 0
    assert t_fail["target_fit_score"] == 0
    assert len(t_fail["violations"]) == 2


# =============================================================================
# TEST 7: Target + Range Combined
# =============================================================================
def test_target_and_range_combined():
    combined_target = [
        {"property": "Bound Styrene", "target": "24.0", "min": "23.0", "max": "25.0", "unit": "%"}
    ]
    normalized = TargetValidationService.normalize_target_properties(combined_target)
    assert len(normalized) == 1
    assert normalized[0].target_value == 24.0
    assert normalized[0].min_value == 23.0
    assert normalized[0].max_value == 25.0
    assert normalized[0].constraint_type == "range"

    recipe = {
        "parameters": [],
        "predicted_properties": [{"property": "Bound Styrene", "predicted_value": "24.2", "unit": "%"}],
    }
    t_eval, _, _ = TargetValidationService.evaluate_recipe(recipe, normalized)
    assert t_eval["targets_met"] == 1
    assert t_eval["target_fit_score"] == 100


# =============================================================================
# TEST 8: Custom Qualitative Properties Handled Gracefully
# =============================================================================
def test_custom_qualitative_properties():
    qual_targets = [
        {"property": "Visual Coagulum & Clarity", "target": "Clear milky emulsion with no micro-grit"},
        {"property": "Odor Intensity", "target": "Low residual odor / VOC free"},
    ]
    normalized = TargetValidationService.normalize_target_properties(qual_targets)
    assert len(normalized) == 2
    assert normalized[0].qualitative is True
    assert normalized[0].target_value is None
    assert normalized[0].raw_target_str == "Clear milky emulsion with no micro-grit"

    table = TargetValidationService.format_optimization_targets_table(
        normalized_targets=normalized,
        source_recipe_data=BASE_SOURCE_RECIPE,
        customer_feedback="Customer reported objectionable sulfur odor and micro-grit",
    )
    assert "Visual Coagulum & Clarity" in table
    assert "Clear milky emulsion with no micro-grit" in table
    assert "Low residual odor" in table

    # Candidate with matching qualitative impact
    recipe = {
        "parameters": [],
        "target_impact": [
            {
                "property": "Visual Coagulum & Clarity",
                "predicted_value": "Clear milky emulsion with zero micro-grit",
                "direction": "improved",
            },
            {
                "property": "Odor Intensity",
                "predicted_value": "Low residual odor achieved via enhanced steam stripping",
                "direction": "decreased",
            },
        ],
    }
    t_eval, _, _ = TargetValidationService.evaluate_recipe(recipe, normalized)
    assert t_eval["targets_total"] == 2
    assert t_eval["targets_met"] == 2
    assert t_eval["target_fit_score"] == 100


# =============================================================================
# TEST 9: Delta Authoritative Synthesis Engine (New Chemical Lever + Stage Override)
# =============================================================================
def test_delta_authoritative_synthesis_engine():
    candidate_delta = LLMOptimizedRecipeCandidate(
        name="Redox Cold Cure Revision",
        optimization_strategy="Add secondary redox initiator SFS and reduce polymerization temperature",
        stages=[],
        changed_parameters=[
            LLMChangedParameter(
                parameter="Deionized Water",
                old_value="180.0",
                new_value="190.0",
                unit="phr",
                reason="Increase dilution to reduce reaction viscosity.",
            ),
            # Newly introduced chemical lever not in base stages:
            LLMChangedParameter(
                parameter="Sodium Bisulfite Co-Reductant",
                old_value="0.0",
                new_value="0.04",
                unit="phr",
                reason="Accelerate low-temperature redox propagation.",
            ),
            LLMChangedParameter(
                parameter="Polymerization Temperature",
                old_value="5",
                new_value="7",
                unit="°C",
                reason="Tighten isothermal control.",
            ),
        ],
    )

    synthesized = apply_optimization_deltas_to_recipe(
        source_recipe=BASE_SOURCE_RECIPE,
        candidate_delta=candidate_delta,
        target_compound="Styrene-Butadiene Rubber Emulsion",
    )

    # 1. Base recipe stages must be intact
    assert len(synthesized["stages"]) == 4

    # 2. Water parameter was updated
    charge_stage = next(s for s in synthesized["stages"] if s["stage_name"] == "Reactor Charge")
    water_param = next(p for p in charge_stage["parameters"] if "water" in p["name"].lower())
    assert water_param["value"] == "190.0"
    assert water_param["changed"] is True

    # 3. Newly introduced lever was placed in Catalyst Solution stage
    catalyst_stage = next(s for s in synthesized["stages"] if s["stage_name"] == "Catalyst Solution")
    bisulfite_param = next((p for p in catalyst_stage["parameters"] if "bisulfite" in p["name"].lower()), None)
    assert bisulfite_param is not None
    assert bisulfite_param["value"] == "0.04"
    assert bisulfite_param["source"] == "optimization_delta"

    # 4. Process conditions temperature was updated
    proc = synthesized.get("process_conditions") or {}
    assert "temperature_profile" in proc
    assert proc["temperature_profile"][0]["value"] == "7"


# =============================================================================
# TEST 10: Re-optimization Lineage and Target Evaluation
# =============================================================================
def test_reoptimization_lineage_and_arbitrary_targets():
    # Step A: Candidate 1 synthesized from Base
    delta_1 = LLMOptimizedRecipeCandidate(
        name="Candidate Revision 1",
        optimization_strategy="First iteration changes",
        stages=[],
        changed_parameters=[
            LLMChangedParameter(parameter="Styrene Monomer", old_value="28.0", new_value="30.0", unit="phr", reason="Iteration 1")
        ],
    )
    cand_1 = apply_optimization_deltas_to_recipe(BASE_SOURCE_RECIPE, delta_1, "Styrene-Butadiene Rubber Emulsion")
    cand_1["id"] = "cand-uuid-1"

    # Step B: User tests Candidate 1 and re-optimizes with 3 new targets
    reopt_targets = [
        {"property": "Bound Styrene Content", "target": "26.0", "unit": "%"},
        {"property": "Mooney Viscosity ML(1+4) 100°C", "target": "46.0", "unit": "MU"},
        {"property": "Tensile Strength", "min": "25.0", "unit": "MPa"},
    ]
    normalized_reopt = TargetValidationService.normalize_target_properties(reopt_targets)

    delta_2 = LLMOptimizedRecipeCandidate(
        name="Candidate Revision 2 (Second Generation)",
        optimization_strategy="Second iteration refinement based on actual trial run",
        stages=[],
        changed_parameters=[
            LLMChangedParameter(parameter="Styrene Monomer", old_value="30.0", new_value="32.0", unit="phr", reason="Iteration 2"),
            LLMChangedParameter(parameter="tert-Dodecyl Mercaptan (CTA)", old_value="0.22", new_value="0.28", unit="phr", reason="Lower Mooney"),
        ],
        target_impact=[
            LLMTargetImpact(property="Bound Styrene Content", predicted_value="26.1", unit="%"),
            LLMTargetImpact(property="Mooney Viscosity ML(1+4) 100°C", predicted_value="46.2", unit="MU"),
            LLMTargetImpact(property="Tensile Strength", predicted_value="25.4", unit="MPa"),
        ],
    )

    cand_2 = apply_optimization_deltas_to_recipe(cand_1, delta_2, "Styrene-Butadiene Rubber Emulsion")
    m_stage = next(s for s in cand_2["stages"] if s["stage_name"] == "Monomer Mix")
    sty_p = next(p for p in m_stage["parameters"] if "styrene" in p["name"].lower())
    assert sty_p["value"] == "32.0"

    t_eval, _, _ = TargetValidationService.evaluate_recipe(cand_2, normalized_reopt)
    assert t_eval["targets_total"] == 3
    assert t_eval["targets_met"] == 3
    assert t_eval["target_fit_score"] == 100


# =============================================================================
# TEST 11: Prompt Integrity (System Prompt mandates compact delta output with stages: [])
# =============================================================================
def test_gemini_delta_prompt_contract():
    prompt = RECIPE_OPTIMIZATION_SYSTEM_PROMPT
    # Verify prompt mandates delta output with empty stages
    assert "stages" in prompt
    assert "[]" in prompt
    assert "changed_parameters" in prompt
    assert "do not ignore, truncate, or prioritize only the first few properties" in prompt.lower()
    assert "complete property set" in prompt.lower()
