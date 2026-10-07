"""
tests/test_recipe_template_stages.py

Comprehensive tests for:
1. 6 canonical synthesis stages in exact Excel template order.
2. Separate process conditions structure.
3. Dynamic ingredients (no hardcoding of NBR/monomers).
4. Normalization and fallback for missing or legacy stages.
5. Backwards compatibility with legacy flat recipes.
"""
import pytest
from app.services.recipe_service import _normalize_recipe_stages, CANONICAL_STAGE_NAMES
from app.services.prompts.patent_prompts import RECIPE_GENERATION_SYSTEM_PROMPT


def test_canonical_stage_names_order():
    """Verify that canonical stages match the client Excel template in exact sequence."""
    expected = [
        "Reactor Charge",
        "Emulsifier Solution",
        "Catalyst Solution",
        "Monomer Mix",
        "Chemical Stripping",
        "Post Addition",
    ]
    assert CANONICAL_STAGE_NAMES == expected


def test_normalize_empty_recipe_generates_all_six_stages():
    """When a recipe dictionary has no stages, all 6 canonical stages are initialized empty."""
    r_dict = {"name": "Empty Recipe", "parameters": []}
    normalized = _normalize_recipe_stages(r_dict)
    
    assert "stages" in normalized
    stages = normalized["stages"]
    assert len(stages) == 6
    assert [s["stage_name"] for s in stages] == CANONICAL_STAGE_NAMES
    for s in stages:
        assert s["parameters"] == []


def test_normalize_preserves_dynamic_ingredients_and_order():
    """Verify that LLM-provided stages with dynamic ingredients are placed in canonical order."""
    r_dict = {
        "name": "Carboxylated SBR Candidate",
        "stages": [
            {
                "stage_name": "Monomer Mix",
                "parameters": [
                    {"name": "Styrene", "value": 60, "unit": "phr"},
                    {"name": "Butadiene", "value": 37, "unit": "phr"},
                    {"name": "Itaconic acid", "value": 3, "unit": "phr"},
                    {"name": "tert-Dodecyl mercaptan", "value": 0.5, "unit": "phr"},
                ],
            },
            {
                "stage_name": "Reactor Charge",
                "parameters": [
                    {"name": "Deionized Water", "value": 85, "unit": "phr"},
                    {"name": "Sodium dodecyl sulfate", "value": 1.2, "unit": "phr"},
                ],
            },
            {
                "stage_name": "Chemical Stripping",
                "parameters": [
                    {"name": "Sodium formaldehyde sulfoxylate", "value": 0.12, "unit": "phr"},
                    {"name": "tert-Butyl hydroperoxide", "value": 0.10, "unit": "phr"},
                ],
            },
            {
                "stage_name": "Catalyst Solution",
                "parameters": [
                    {"name": "Potassium persulfate", "value": 0.4, "unit": "phr"},
                    {"name": "DI Water", "value": 10, "unit": "phr"},
                ],
            },
            {
                "stage_name": "Post Addition",
                "parameters": [
                    {"name": "1,2-Benzisothiazolin-3-one", "value": 0.05, "unit": "phr"},
                    {"name": "Polydimethylsiloxane emulsion", "value": 0.08, "unit": "phr"},
                ],
            },
        ],
    }
    
    normalized = _normalize_recipe_stages(r_dict)
    stages = normalized["stages"]
    
    # When emulsifier (Sodium dodecyl sulfate) is charged directly in Reactor Charge,
    # redundant empty "Emulsifier Solution: Not applicable" stage is cleanly omitted (Option B).
    assert len(stages) == 5
    stage_names = [s["stage_name"] for s in stages]
    assert "Emulsifier Solution" not in stage_names
    assert stage_names == [
        "Reactor Charge",
        "Catalyst Solution",
        "Monomer Mix",
        "Chemical Stripping",
        "Post Addition",
    ]
    
    # Stage 1: Reactor Charge (contains DI Water and SDS emulsifier)
    assert stages[0]["stage_name"] == "Reactor Charge"
    assert len(stages[0]["parameters"]) == 2
    assert stages[0]["parameters"][0]["name"] == "Deionized Water"
    assert stages[0]["parameters"][1]["name"] == "Sodium dodecyl sulfate"
    
    # Stage 2: Catalyst Solution
    assert stages[1]["stage_name"] == "Catalyst Solution"
    assert len(stages[1]["parameters"]) == 2
    assert stages[1]["parameters"][0]["name"] == "Potassium persulfate"
    
    # Stage 3: Monomer Mix (dynamic monomers: Styrene, Butadiene, Itaconic acid)
    assert stages[2]["stage_name"] == "Monomer Mix"
    assert len(stages[2]["parameters"]) == 4
    assert [p["name"] for p in stages[2]["parameters"]] == [
        "Styrene",
        "Butadiene",
        "Itaconic acid",
        "tert-Dodecyl mercaptan",
    ]
    
    # Stage 4: Chemical Stripping (dynamic stripping chemicals)
    assert stages[3]["stage_name"] == "Chemical Stripping"
    assert len(stages[3]["parameters"]) == 2
    assert stages[3]["parameters"][0]["name"] == "Sodium formaldehyde sulfoxylate"
    
    # Stage 5: Post Addition
    assert stages[4]["stage_name"] == "Post Addition"
    assert len(stages[4]["parameters"]) == 2
    assert stages[4]["parameters"][0]["name"] == "1,2-Benzisothiazolin-3-one"
    
    # Flat parameters list must be synchronized with all stage parameters
    assert len(normalized["parameters"]) == 2 + 2 + 4 + 2 + 2


def test_normalize_with_separate_emulsifier_solution_preserves_all_six_stages():
    """Option A: When a separate Emulsifier Solution feed is present, all 6 canonical stages exist."""
    r_dict = {
        "name": "Candidate with Separate Emulsifier Feed",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "DI Water", "value": 60, "unit": "phr"}]},
            {"stage_name": "Emulsifier Solution", "parameters": [{"name": "Potassium oleate", "value": 2.2, "unit": "phr"}]},
            {"stage_name": "Catalyst Solution", "parameters": [{"name": "KPS", "value": 0.3, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "Monomer 1", "value": 70, "unit": "phr"}]},
            {"stage_name": "Chemical Stripping", "parameters": [{"name": "Shortstop", "value": 0.1, "unit": "phr"}]},
            {"stage_name": "Post Addition", "parameters": [{"name": "Stabilizer", "value": 0.5, "unit": "phr"}]},
        ],
    }
    normalized = _normalize_recipe_stages(r_dict)
    stages = normalized["stages"]
    assert len(stages) == 6
    assert [s["stage_name"] for s in stages] == CANONICAL_STAGE_NAMES
    assert stages[1]["stage_name"] == "Emulsifier Solution"
    assert len(stages[1]["parameters"]) == 1
    assert stages[1]["is_applicable"] is True


def test_process_conditions_separate_from_ingredients():
    """Verify that process conditions structure is maintained separately from stages."""
    r_dict = {
        "name": "NBR Recipe with Process Conditions",
        "stages": [],
        "process_conditions": {
            "reaction_time": {"value": 8.5, "unit": "h"},
            "feeding_hours": {
                "monomer": "4.5 h continuous feed",
                "emulsifier": "3.0 h delayed feed",
                "catalyst": "Batch charge at t=0 and t=4h",
            },
            "temperature_profile": [
                {"stage": "initiation", "value": "10", "unit": "°C"},
                {"stage": "feed_stage", "value": "12", "unit": "°C"},
                {"stage": "finishing", "value": "15", "unit": "°C"},
            ],
        },
    }
    
    normalized = _normalize_recipe_stages(r_dict)
    assert "process_conditions" in normalized
    pc = normalized["process_conditions"]
    assert pc["reaction_time"]["value"] == 8.5
    assert pc["feeding_hours"]["monomer"] == "4.5 h continuous feed"
    assert len(pc["temperature_profile"]) == 3
    assert pc["temperature_profile"][0]["value"] == "10"


def test_system_prompt_enforces_excel_template_stages():
    """Verify that system prompt explicitly specifies the 6 canonical stages and process conditions."""
    for stage in CANONICAL_STAGE_NAMES:
        assert stage in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "process_conditions" in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "Chemical Stripping" in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "Post Addition" in RECIPE_GENERATION_SYSTEM_PROMPT


def test_confidence_score_high_alignment():
    """Verify that high patent evidence and target alignment produce score >= 50 naturally."""
    from app.services.recipe_service import calculate_recipe_confidence_score

    recipe = {
        "name": "Recipe 1 - Low ACN Ratio Baseline",
        "compound": "Low Acrylonitrile NBR",
        "polymerization_method": "Cold Emulsion Polymerization",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Deionized Water", "value": 55, "unit": "phr", "source": "patent"}]},
            {"stage_name": "Emulsifier Solution", "parameters": [{"name": "Sodium oleate", "value": 1.2, "unit": "phr", "source": "patent"}]},
            {"stage_name": "Catalyst Solution", "parameters": [{"name": "Potassium persulfate", "value": 0.35, "unit": "phr", "source": "patent"}]},
            {"stage_name": "Monomer Mix", "parameters": [
                {"name": "Butadiene", "value": 74, "unit": "wt%", "source": "patent"},
                {"name": "Acrylonitrile", "value": 26, "unit": "wt%", "source": "patent"},
                {"name": "t-Dodecyl mercaptan", "value": 0.15, "unit": "phr", "source": "inferred"},
            ]},
            {"stage_name": "Chemical Stripping", "parameters": [], "omission_reason": "No separate stripping required."},
            {"stage_name": "Post Addition", "parameters": [{"name": "Phenolic antioxidant", "value": 0.1, "unit": "phr", "source": "inferred"}]},
        ],
        "parameters": [
            {"name": "Deionized Water", "value": 55, "unit": "phr", "source": "patent"},
            {"name": "Sodium oleate", "value": 1.2, "unit": "phr", "source": "patent"},
            {"name": "Potassium persulfate", "value": 0.35, "unit": "phr", "source": "patent"},
            {"name": "Butadiene", "value": 74, "unit": "wt%", "source": "patent"},
            {"name": "Acrylonitrile", "value": 26, "unit": "wt%", "source": "patent"},
            {"name": "t-Dodecyl mercaptan", "value": 0.15, "unit": "phr", "source": "inferred"},
            {"name": "Phenolic antioxidant", "value": 0.1, "unit": "phr", "source": "inferred"},
        ],
        "process_conditions": {
            "reaction_time": {"value": 8, "unit": "h"},
            "feeding_hours": {"monomer": "4 h", "emulsifier": "4 h", "catalyst": "Continuous 4 h"},
            "temperature_profile": [{"stage": "initial", "value": "10", "unit": "°C"}],
        },
        "patent_references": ["US9815984B2", "US10093750B2"],
    }

    target_properties = [
        {"feature": "BACN", "min": "20", "max": "28", "unit": "%"},
        {"feature": "Mooney", "min": "40", "max": "55", "unit": "MU"},
    ]
    patent_context = {
        "patents": [
            {
                "patent": "US9815984B2",
                "synthesis_method": "Cold emulsion polymerization",
                "disclosed_parameters": ["Acrylonitrile", "Butadiene", "Water", "Potassium persulfate"],
            },
            {
                "patent": "US10093750B2",
                "synthesis_method": "Emulsion polymerization",
                "disclosed_parameters": ["Sodium oleate", "t-Dodecyl mercaptan"],
            },
        ]
    }

    score = calculate_recipe_confidence_score(recipe, target_properties, [], patent_context)
    assert score >= 50, f"Expected score >= 50 for strong recipe, got {score}"
    assert score <= 100


def test_confidence_score_sparse_context_yields_lower_score():
    """Verify that when evidence is sparse and unaligned, score drops below 50 without forcing."""
    from app.services.recipe_service import calculate_recipe_confidence_score

    sparse_recipe = {
        "name": "Sparse Recipe",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": []},
            {"stage_name": "Emulsifier Solution", "parameters": []},
            {"stage_name": "Catalyst Solution", "parameters": []},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "Monomer A", "value": 10, "unit": "phr"}]},
            {"stage_name": "Chemical Stripping", "parameters": []},
            {"stage_name": "Post Addition", "parameters": []},
        ],
        "parameters": [{"name": "Monomer A", "value": 10, "unit": "phr", "source": "ai_generated"}],
        "process_conditions": {},
        "patent_references": [],
    }

    target_properties = [{"feature": "BACN", "min": "40", "max": "50", "unit": "%"}]
    patent_context = {"patents": []}

    score = calculate_recipe_confidence_score(sparse_recipe, target_properties, [], patent_context)
    # Must NOT force 50+ when unsupported!
    assert score < 50, f"Expected sparse score < 50, got {score}"


def test_omission_reason_attached_to_empty_stages():
    """Verify that empty stages receive scientifically coherent AI omission reasons."""
    r_dict = {
        "name": "Recipe Without Stripping",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 100, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "Styrene", "value": 50, "unit": "wt%"}]},
        ],
    }
    normalized = _normalize_recipe_stages(r_dict, target_compound="SBR")
    
    stages_by_name = {s["stage_name"]: s for s in normalized["stages"]}
    
    # Chemical Stripping was omitted
    strip_stage = stages_by_name["Chemical Stripping"]
    assert strip_stage["parameters"] == []
    assert strip_stage["is_applicable"] is False
    assert strip_stage["omission_reason"] is not None
    assert "stripping" in strip_stage["omission_reason"].lower()
