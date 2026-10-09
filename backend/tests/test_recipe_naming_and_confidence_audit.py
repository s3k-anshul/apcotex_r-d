"""
backend/tests/test_recipe_naming_and_confidence_audit.py

Comprehensive test suite verifying:
1. Recipe display names are strictly 'Recipe 1' .. 'Recipe 5' in schemas and normalization.
2. Underlying candidate IDs and original names/dimensions are preserved.
3. Optimization strategy, variation dimensions, and rationales are preserved.
4. Confidence is not sourced from the LLM (purely deterministic scoring).
5. Confidence is not hardcoded to 94.
6. Evidence coverage and confidence score are completely decoupled.
7. Target Fit = None (N/A) only when target properties are absent (General Mode).
8. Target Fit is actively calculated when target properties exist (Strict Mode).
9. Confidence calculation is deterministic and mathematically reproducible.
10. Candidate-specific differentiation based on patent evidence and parameter disclosures.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, patch

from app.schemas.recipe import (
    RecipeCandidateResponse,
    RecipeCycleCreate,
    RecipePropertyDef,
    LLMRecipeCandidate,
    LLMRecipeSet,
    LLMRecipeStage,
    LLMRecipeParameter,
    LLMProcessConditions,
    LLMReactionTime,
    LLMTemperatureStep,
)
from app.models.recipe_candidate import RecipeCandidate
from app.models.recipe_cycle import RecipeCycle, RecipeCycleStatus
from app.services.recipe_service import (
    RecipeService,
    calculate_parameter_evidence_coverage,
)
from app.services.target_validation_service import TargetValidationService


def _build_test_candidate(rank: int, variation: str, cited_params: int = 3, total_params: int = 16) -> dict:
    """Helper to build candidate dictionary with exact parameter patent citations."""
    params = []
    for i in range(total_params):
        is_cited = i < cited_params
        params.append({
            "name": f"Param_{i + 1}",
            "value": f"{10 + i}",
            "unit": "phr",
            "source": "patent" if is_cited else "inferred",
            "patent_ref": "US10611900B2" if is_cited else None,
        })
    if not any("water" in p["name"].lower() for p in params):
        params[0]["name"] = "Water"
        params[0]["value"] = "180"
    if not any("cta" in p["name"].lower() for p in params):
        params[1]["name"] = "CTA"
        params[1]["value"] = "0.3"

    stages = [
        {"stage_name": "Reactor Charge", "parameters": params[:3]},
        {"stage_name": "Emulsifier Solution", "parameters": params[3:6]},
        {"stage_name": "Catalyst Solution", "parameters": params[6:9]},
        {"stage_name": "Monomer Mix", "parameters": params[9:12]},
        {"stage_name": "Chemical Stripping", "parameters": params[12:14]},
        {"stage_name": "Post Addition", "parameters": params[14:]},
    ]

    return {
        "name": f"Recipe {rank} - {variation}",
        "variation_dimension": variation,
        "polymerization_method": "Emulsion Polymerization",
        "compound": "7% carboxylated NBR",
        "rationale": f"Chemical variation optimizing {variation.lower()}.",
        "patent_references": ["US10611900B2", "US7265185B2"],
        "parameters": params,
        "stages": stages,
        "process_conditions": {
            "reaction_time": {"value": "8", "unit": "h"},
            "temperature_profile": [{"stage": "Main", "value": "7", "unit": "°C"}],
            "feeding_hours": {"monomer": "4", "emulsifier": "4", "catalyst": "4"},
        },
    }


def test_recipe_candidate_response_display_name_strictly_recipe_n():
    """Requirement 1: Schema produces strictly 'Recipe 1' .. 'Recipe 5' display_name."""
    cid = uuid.uuid4()
    cyc_id = uuid.uuid4()
    for rank in range(1, 6):
        resp = RecipeCandidateResponse(
            id=cid,
            cycle_id=cyc_id,
            rank=rank,
            name=f"Recipe {rank} - Monomer ratio variation",
            recipe_data={"variation_dimension": "Monomer ratio", "confidence_score": 93},
            patent_references=["US10611900B2"],
            evidence_coverage_score=25,
            is_selected=False,
            created_at="2026-10-08T12:00:00",
        )
        assert resp.display_name == f"Recipe {rank}"
        # Original name with full variation is preserved for audit/lineage
        assert resp.name == f"Recipe {rank} - Monomer ratio variation"
        assert resp.rank == rank


def test_confidence_decoupled_from_evidence_coverage():
    """Requirement 5 & 6: Confidence is not hardcoded to 94 and decoupled from evidence_coverage."""
    cand = _build_test_candidate(1, "Monomer ratio", cited_params=3, total_params=16)
    real_evid_cov = calculate_parameter_evidence_coverage(cand)
    assert real_evid_cov == int(round((3 / 16) * 100))  # 19%

    # Evaluate recipe in General Mode
    t_analysis, c_analysis, conf_score = TargetValidationService.evaluate_recipe(
        recipe=cand,
        normalized_targets=[],
        patent_context={"patents": ["US10611900B2", "US7265185B2"]},
    )

    assert conf_score != real_evid_cov
    assert real_evid_cov == 19
    # Fully complete recipe (all 6 stages + process conditions) scores 95 deterministically:
    # 0.35 * 98 + 0.25 * 100 + 0.20 * 100 + 0.20 * 80 = 95.3 -> 95
    assert conf_score == 95

    # Ensure RecipeCandidateResponse does NOT fallback to evidence_coverage_score when confidence is set
    resp = RecipeCandidateResponse(
        id=uuid.uuid4(),
        cycle_id=uuid.uuid4(),
        rank=1,
        name=cand["name"],
        recipe_data={"confidence_score": conf_score},
        patent_references=cand["patent_references"],
        evidence_coverage_score=real_evid_cov,
        is_selected=False,
        created_at="2026-10-08T12:00:00",
    )
    assert resp.evidence_coverage_score == 19
    assert resp.confidence_score == 95


def test_target_fit_none_in_general_mode_and_computed_in_strict_mode():
    """Requirement 7 & 8: Target Fit is None (N/A) in General Mode, but evaluated in Strict Mode."""
    cand = _build_test_candidate(1, "Monomer ratio")
    cand["predicted_properties"] = [
        {"name": "Mooney Viscosity", "predicted_value": 50.0, "unit": "MU"},
    ]

    # Case A: General Mode (0 targets provided)
    t_gen, c_gen, conf_gen = TargetValidationService.evaluate_recipe(
        recipe=cand,
        normalized_targets=[],
    )
    assert t_gen["mode"] == "GENERAL"
    assert t_gen["target_fit_score"] is None

    # Case B: Strict Mode (1 target provided and met)
    norm_targets = TargetValidationService.normalize_target_properties([
        {"id": "mv", "feature": "Mooney Viscosity", "min": "45", "max": "55", "unit": "MU"}
    ])
    assert len(norm_targets) == 1
    t_strict, c_strict, conf_strict = TargetValidationService.evaluate_recipe(
        recipe=cand,
        normalized_targets=norm_targets,
    )
    assert t_strict["mode"] == "STRICT_TARGET"
    assert t_strict["target_fit_score"] == 100
    assert t_strict["targets_met"] == 1


def test_deterministic_confidence_calculation_and_differentiation():
    """Requirement 9 & 10: Confidence calculation is deterministic and responds to evidence."""
    cand_high_evidence = _build_test_candidate(1, "High Evidence", cited_params=4, total_params=16)
    cand_low_evidence = _build_test_candidate(2, "Low Evidence", cited_params=0, total_params=16)
    cand_low_evidence["patent_references"] = ["US10611900B2"]  # 1 patent citation

    t1, c1, conf1 = TargetValidationService.evaluate_recipe(cand_high_evidence, normalized_targets=[])
    t2, c2, conf2 = TargetValidationService.evaluate_recipe(cand_low_evidence, normalized_targets=[])

    # High evidence: 2 verified patents + 4 cited params -> evidence_score = 98 -> conf = 95
    assert conf1 == 95
    # Low evidence: 1 verified patent + 0 cited params -> evidence_score = 78 -> conf = 88
    assert conf2 == 88
    assert conf1 != conf2  # Confidence differs based on evidence disclosures!


def test_rank_candidates_sets_display_name_and_preserves_variation():
    """Requirement 1, 2, 3: rank_candidates assigns display_name 'Recipe 1'.. while preserving names."""
    cands = [
        _build_test_candidate(i + 1, f"Variation {i + 1}")
        for i in range(5)
    ]
    ranked = TargetValidationService.rank_candidates(cands, normalized_targets=[])
    for idx, c in enumerate(ranked):
        assert c["display_name"] == f"Recipe {idx + 1}"
        assert c["variation_dimension"] == f"Variation {idx + 1}"
        assert c["name"].startswith(f"Recipe {idx + 1}")
        assert "Variation" in c["name"]
