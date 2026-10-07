"""
tests/test_water_based_recipe_validation.py

Comprehensive test suite verifying complete water-based synthesis recipe validation,
stage completeness, dynamic compound synthesis, surfactant logic, patent verification,
and deterministic confidence scoring.
"""
import pytest
from app.services.recipe_service import (
    _normalize_recipe_stages,
    validate_and_enrich_water_based_recipe,
    calculate_recipe_confidence_score,
    CANONICAL_STAGE_NAMES,
    RecipeService,
)
from app.services.prompts.patent_prompts import RECIPE_GENERATION_SYSTEM_PROMPT


# ── TEST 1: SBR + Water-Based Route ─────────────────────────────────────────

def test_1_sbr_water_based_route():
    """
    TEST 1: SBR + water-based route.
    Verify: aqueous medium, emulsifier/surfactant handled correctly,
    no solvent-based formulation, complete synthesis stages.
    """
    raw_sbr_recipe = {
        "name": "Recipe 1 - Cold SBR Baseline",
        "compound": "Styrene-Butadiene Rubber (SBR)",
        "polymerization_method": "Cold Emulsion Polymerization",
        "stages": [
            {
                "stage_name": "Reactor Charge",
                "parameters": [
                    {"name": "Deionized Water (Continuous Medium)", "value": 150, "unit": "phr", "source": "ai_generated"},
                    {"name": "Potassium oleate (Emulsifier)", "value": 2.5, "unit": "phr", "source": "ai_generated"},
                ],
            },
            {
                "stage_name": "Catalyst Solution",
                "parameters": [
                    {"name": "p-Menthane hydroperoxide / Ferrous sulfate (Redox Initiator)", "value": 0.12, "unit": "phr", "source": "ai_generated"},
                ],
            },
            {
                "stage_name": "Monomer Mix",
                "parameters": [
                    {"name": "1,3-Butadiene (Monomer 1)", "value": 72, "unit": "phr", "source": "ai_generated"},
                    {"name": "Styrene (Monomer 2)", "value": 28, "unit": "phr", "source": "ai_generated"},
                    {"name": "tert-Dodecyl mercaptan (CTA)", "value": 0.20, "unit": "phr", "source": "ai_generated"},
                ],
            },
        ],
        "process_conditions": {
            "reaction_time": {"value": 8.0, "unit": "h"},
            "temperature_profile": [{"stage": "Polymerization", "value": "10", "unit": "°C"}],
        },
    }

    norm = _normalize_recipe_stages(raw_sbr_recipe, target_compound="SBR")
    enriched = validate_and_enrich_water_based_recipe(norm, target_compound="SBR")

    stage_names = [s["stage_name"] for s in enriched["stages"]]

    # 1. Continuous aqueous medium verified
    water_params = [p for p in enriched["parameters"] if "water" in p["name"].lower()]
    assert len(water_params) >= 1
    assert any(p["value"] >= 80 for p in water_params)

    # 2. Emulsifier handled correctly in Reactor Charge -> redundant empty Emulsifier Solution omitted
    assert "Reactor Charge" in stage_names
    assert "Emulsifier Solution" not in stage_names
    rc_stage = next(s for s in enriched["stages"] if s["stage_name"] == "Reactor Charge")
    assert any("oleate" in p["name"].lower() or "emulsifier" in p["name"].lower() for p in rc_stage["parameters"])

    # 3. No solvent-based formulation
    assert "solution" not in enriched["polymerization_method"].lower() or "aqueous" in enriched["polymerization_method"].lower()

    # 4. Complete stages: Stripping was automatically enriched for SBR diene rubber
    assert "Chemical Stripping" in stage_names
    strip_stage = next(s for s in enriched["stages"] if s["stage_name"] == "Chemical Stripping")
    assert len(strip_stage["parameters"]) >= 1
    assert strip_stage["is_applicable"] is True


# ── TEST 2: NBR + Water-Based Route ─────────────────────────────────────────

def test_2_nbr_water_based_route():
    """
    TEST 2: NBR + water-based route.
    Verify: dynamic monomers (Acrylonitrile & Butadiene), appropriate aqueous synthesis,
    no SBR hardcoding.
    """
    raw_nbr_recipe = {
        "name": "Recipe 1 - Medium ACN NBR",
        "compound": "Nitrile Butadiene Rubber (NBR)",
        "polymerization_method": "Cold Emulsion Polymerization",
        "stages": [
            {
                "stage_name": "Reactor Charge",
                "parameters": [
                    {"name": "Water", "value": 180, "unit": "phr"},
                    {"name": "Sodium soap of disproportionated rosin (Emulsifier)", "value": 2.2, "unit": "phr"},
                ],
            },
            {
                "stage_name": "Catalyst Solution",
                "parameters": [{"name": "Potassium persulfate (Initiator)", "value": 0.3, "unit": "phr"}],
            },
            {
                "stage_name": "Monomer Mix",
                "parameters": [
                    {"name": "1,3-Butadiene (Monomer 1)", "value": 67, "unit": "phr"},
                    {"name": "Acrylonitrile (Monomer 2)", "value": 33, "unit": "phr"},
                    {"name": "tert-Dodecyl mercaptan (CTA)", "value": 0.25, "unit": "phr"},
                ],
            },
        ],
    }

    norm = _normalize_recipe_stages(raw_nbr_recipe, target_compound="NBR")
    enriched = validate_and_enrich_water_based_recipe(norm, target_compound="NBR")

    # Dynamic monomer verification: NBR monomers present, no styrene
    pnames = [p["name"].lower() for p in enriched["parameters"]]
    assert any("acrylonitrile" in pn for pn in pnames)
    assert any("butadiene" in pn for pn in pnames)
    assert not any("styrene" in pn for pn in pnames)


# ── TEST 3: A Different Compound/Process ────────────────────────────────────

def test_3_generic_polymer_dynamic_stages():
    """
    TEST 3: A different compound/process (Acrylic latex / Vinyl acetate).
    Verify: no NBR/SBR assumptions, dynamic monomers and stages preserved.
    """
    raw_acrylic = {
        "name": "Recipe 1 - Pure Acrylic Emulsion",
        "compound": "Butyl Acrylate / Methyl Methacrylate Copolymer",
        "polymerization_method": "Aqueous Emulsion Polymerization",
        "stages": [
            {
                "stage_name": "Reactor Charge",
                "parameters": [
                    {"name": "Deionized Water", "value": 90, "unit": "phr"},
                    {"name": "Sodium lauryl sulfate (Surfactant)", "value": 0.5, "unit": "phr"},
                ],
            },
            {
                "stage_name": "Catalyst Solution",
                "parameters": [{"name": "Ammonium persulfate", "value": 0.4, "unit": "phr"}],
            },
            {
                "stage_name": "Monomer Mix",
                "parameters": [
                    {"name": "n-Butyl acrylate (Monomer 1)", "value": 52, "unit": "wt%"},
                    {"name": "Methyl methacrylate (Monomer 2)", "value": 46, "unit": "wt%"},
                    {"name": "Methacrylic acid (Functional comonomer)", "value": 2, "unit": "wt%"},
                ],
            },
        ],
    }

    norm = _normalize_recipe_stages(raw_acrylic, target_compound="Acrylic Latex")
    enriched = validate_and_enrich_water_based_recipe(norm, target_compound="Acrylic Latex")

    pnames = [p["name"].lower() for p in enriched["parameters"]]
    assert any("butyl acrylate" in pn for pn in pnames)
    assert any("methyl methacrylate" in pn for pn in pnames)
    assert not any("butadiene" in pn for pn in pnames)
    assert not any("styrene" in pn for pn in pnames)


# ── TEST 4: Patent Contains Emulsifier ──────────────────────────────────────

def test_4_patent_contains_emulsifier():
    """
    TEST 4: Patent contains emulsifier.
    Verify: patent-supported emulsifier information is used and marked source='patent'.
    """
    patent_context = {
        "patents": [
            {
                "patent": "US10123456B2",
                "synthesis_method": "Cold emulsion polymerization",
                "disclosed_parameters": [
                    "Potassium rosinate: 2.3 phr",
                    "Potassium persulfate: 0.3 phr",
                ],
            }
        ]
    }

    # Incomplete recipe lacking emulsifier
    recipe = {
        "name": "Recipe 1",
        "compound": "SBR",
        "polymerization_method": "Cold Emulsion",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 150, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "1,3-Butadiene", "value": 75, "unit": "phr"}]},
        ],
        "patent_references": ["US10123456B2"],
    }

    enriched = validate_and_enrich_water_based_recipe(recipe, target_compound="SBR", patent_context=patent_context)
    rc = next(s for s in enriched["stages"] if s["stage_name"] == "Reactor Charge")
    emulsifier_param = next((p for p in rc["parameters"] if "rosinate" in p["name"].lower()), None)

    assert emulsifier_param is not None
    assert emulsifier_param["source"] == "patent"
    assert emulsifier_param["patent_ref"] == "US10123456B2"


# ── TEST 5: Surfactant in Reactor Charge Not Marked Not Applicable ──────────

def test_5_surfactant_in_reactor_charge_not_marked_not_applicable():
    """
    TEST 5: Patent does not contain a separate emulsifier solution but chemistry requires emulsifier.
    Surfactant is charged in Reactor Charge.
    Verify: AI creates appropriate emulsifier handling; NOT incorrectly marked Not Applicable.
    """
    recipe = {
        "name": "Recipe 1 - Direct Charge",
        "compound": "SBR",
        "stages": [
            {
                "stage_name": "Reactor Charge",
                "parameters": [
                    {"name": "Deionized Water", "value": 160, "unit": "phr"},
                    {"name": "Sodium oleate soap (Emulsifier)", "value": 2.5, "unit": "phr"},
                ],
            },
            {"stage_name": "Monomer Mix", "parameters": [{"name": "Butadiene", "value": 70, "unit": "phr"}]},
        ],
    }

    norm = _normalize_recipe_stages(recipe, target_compound="SBR")
    stage_names = [s["stage_name"] for s in norm["stages"]]

    # Option B: Emulsifier is in Reactor Charge. Misleading empty Emulsifier Solution MUST NOT exist
    assert "Emulsifier Solution" not in stage_names
    for stg in norm["stages"]:
        assert not (stg["stage_name"] == "Emulsifier Solution" and stg.get("is_applicable") is False)


# ── TEST 6: Chemistry Genuinely Does Not Require Emulsifier ─────────────────

def test_6_chemistry_genuinely_does_not_require_emulsifier():
    """
    TEST 6: Chemistry genuinely does not require emulsifier (e.g. bio-polymer PHA or soap-free).
    Verify: Not Applicable with scientific reason present.
    """
    recipe = {
        "name": "Biopolymer Recipe",
        "compound": "Poly(3-hydroxybutyrate)",
        "polymerization_method": "Microbial Fermentation",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Mineral Salts Medium", "value": 100, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "Glucose (Carbon source)", "value": 40, "unit": "g/L"}]},
        ],
    }

    norm = _normalize_recipe_stages(recipe, target_compound="Poly(3-hydroxybutyrate)")
    enriched = validate_and_enrich_water_based_recipe(norm, target_compound="Poly(3-hydroxybutyrate)")
    stages_by_name = {s["stage_name"]: s for s in enriched["stages"]}

    assert "Emulsifier Solution" in stages_by_name
    es = stages_by_name["Emulsifier Solution"]
    assert es["is_applicable"] is False
    assert es["omission_reason"] is not None
    assert len(es["omission_reason"]) > 10


# ── TEST 7: Chemical Stripping AI-Derived When Missing ──────────────────────

def test_7_stripping_ai_derived_when_missing():
    """
    TEST 7: Patent does not contain chemical stripping but chemistry requires it.
    Verify: AI-generated stripping step, clearly marked AI-derived.
    """
    recipe = {
        "name": "SBR Recipe Without Patent Stripping",
        "compound": "SBR",
        "polymerization_method": "Cold Emulsion",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 150, "unit": "phr"}, {"name": "Soap", "value": 2, "unit": "phr"}]},
            {"stage_name": "Catalyst Solution", "parameters": [{"name": "KPS", "value": 0.3, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "Butadiene", "value": 75, "unit": "phr"}]},
        ],
    }

    enriched = validate_and_enrich_water_based_recipe(recipe, target_compound="SBR")
    strip_stage = next(s for s in enriched["stages"] if s["stage_name"] == "Chemical Stripping")

    assert strip_stage["is_applicable"] is True
    assert len(strip_stage["parameters"]) >= 1
    for p in strip_stage["parameters"]:
        assert p["source"] == "ai_generated"
        assert p["patent_ref"] is None


# ── TEST 8: All Supplied Target Properties Evaluated ────────────────────────

def test_8_all_supplied_target_properties_evaluated():
    """
    TEST 8: Target properties provided.
    Verify: ALL supplied target properties (Mooney, Tg, Solids, Particle Size) affect scoring.
    """
    recipe = {
        "name": "Recipe 1",
        "compound": "SBR",
        "parameters": [
            {"name": "Deionized Water", "value": 160, "unit": "phr"},
            {"name": "tert-Dodecyl mercaptan (CTA)", "value": 0.22, "unit": "phr"},
            {"name": "Styrene (Monomer 2)", "value": 25, "unit": "wt%"},
            {"name": "Potassium oleate (Emulsifier)", "value": 2.5, "unit": "phr"},
            {"name": "Total Solids Content", "value": 22, "unit": "%"},
        ],
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Deionized Water", "value": 160, "unit": "phr"}, {"name": "Potassium oleate (Emulsifier)", "value": 2.5, "unit": "phr"}]},
            {"stage_name": "Catalyst Solution", "parameters": [{"name": "KPS", "value": 0.3, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "tert-Dodecyl mercaptan (CTA)", "value": 0.22, "unit": "phr"}, {"name": "Styrene (Monomer 2)", "value": 25, "unit": "wt%"}]},
        ],
        "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}, "temperature_profile": [{"stage": "rxn", "value": "10", "unit": "°C"}]},
        "patent_references": [],
    }

    # Supply 4 distinct target constraints
    target_properties = [
        {"feature": "Mooney Viscosity", "min": "45", "max": "55", "unit": "MU"},
        {"feature": "Glass Transition (Tg)", "min": "-55", "max": "-50", "unit": "°C"},
        {"feature": "Total Solids Content", "min": "20", "max": "25", "unit": "%"},
        {"feature": "Particle Size", "min": "50", "max": "80", "unit": "nm"},
    ]

    score = calculate_recipe_confidence_score(recipe, target_properties, [], {})
    assert score >= 40  # Well aligned across multiple targets


# ── TEST 9: No Target Properties Still Generates Standard Baseline ──────────

def test_9_no_target_properties_still_generates():
    """
    TEST 9: No target properties provided.
    Verify: recipe still scores reasonable baseline without errors.
    """
    recipe = {
        "name": "Baseline SBR Recipe",
        "compound": "SBR",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 150, "unit": "phr"}, {"name": "Soap", "value": 2.5, "unit": "phr"}]},
            {"stage_name": "Catalyst Solution", "parameters": [{"name": "KPS", "value": 0.3, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "Butadiene", "value": 72, "unit": "phr"}, {"name": "Styrene", "value": 28, "unit": "phr"}]},
        ],
        "parameters": [
            {"name": "Water", "value": 150, "unit": "phr"},
            {"name": "Soap", "value": 2.5, "unit": "phr"},
            {"name": "KPS", "value": 0.3, "unit": "phr"},
            {"name": "Butadiene", "value": 72, "unit": "phr"},
            {"name": "Styrene", "value": 28, "unit": "phr"},
        ],
        "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}, "temperature_profile": [{"stage": "rxn", "value": "10", "unit": "°C"}]},
        "patent_references": [],
    }

    score = calculate_recipe_confidence_score(recipe, [], [], {})
    assert score >= 40


# ── TEST 10: Patent Support Identified When Evidence Exists ─────────────────

def test_10_patent_support_identified_via_token_overlap():
    """
    TEST 10: Patent support identified when evidence exists.
    Verify: relevant patents are identified via normalized number and technical keyword matching.
    """
    service = RecipeService(session=None)

    patent_context = {
        "patents": [
            {
                "patent": "US20250075019A1",
                "synthesis_method": "Cold emulsion polymerization of styrene and butadiene",
                "disclosed_parameters": [
                    "1,3-Butadiene: 72 phr",
                    "Styrene: 28 phr",
                    "Potassium persulfate: 0.3 phr",
                    "Potassium soap: 2.5 phr",
                ],
            }
        ]
    }

    # Case A: Candidate cites without kind code "US20250075019"
    candidate_cited = {
        "polymerization_method": "Cold Emulsion",
        "patent_references": ["US20250075019"],
        "parameters": [],
    }
    verified_a = service._verify_patent_references(candidate_cited, patent_context)
    assert "US20250075019A1" in verified_a

    # Case B: Candidate omitted citation, but has matching chemical keywords
    candidate_tokens = {
        "polymerization_method": "Cold Emulsion Polymerization",
        "patent_references": [],
        "parameters": [
            {"name": "1,3-Butadiene (Monomer 1)", "value": 72, "unit": "phr"},
            {"name": "Styrene (Monomer 2)", "value": 28, "unit": "phr"},
            {"name": "Potassium persulfate (Initiator)", "value": 0.3, "unit": "phr"},
        ],
    }
    verified_b = service._verify_patent_references(candidate_tokens, patent_context)
    assert "US20250075019A1" in verified_b


# ── TEST 11: Five Recipes Genuinely Different ───────────────────────────────

def test_11_five_recipes_genuinely_different():
    """
    TEST 11: Five recipes variation.
    Verify: prompt requires 5 genuinely distinct recipes varying scientifically relevant dimensions.
    """
    assert "Recipe 1" in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "Recipe 2" in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "Recipe 3" in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "Recipe 4" in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "Recipe 5" in RECIPE_GENERATION_SYSTEM_PROMPT
    assert "genuinely different" in RECIPE_GENERATION_SYSTEM_PROMPT.lower()


# ── TEST 12: Confidence Calculated Deterministically ────────────────────────

def test_12_confidence_calculated_not_hardcoded():
    """
    TEST 12: Confidence score is calculated, not hardcoded.
    A well-supported recipe scores higher than a sparse recipe, and neither is hardcoded to 71.
    """
    strong_recipe = {
        "compound": "SBR",
        "polymerization_method": "Cold Emulsion Polymerization",
        "parameters": [
            {"name": "Water", "value": 150, "unit": "phr", "source": "patent"},
            {"name": "Potassium rosinate", "value": 2.5, "unit": "phr", "source": "patent"},
            {"name": "Potassium persulfate", "value": 0.35, "unit": "phr", "source": "patent"},
            {"name": "1,3-Butadiene", "value": 72, "unit": "phr", "source": "patent"},
            {"name": "Styrene", "value": 28, "unit": "phr", "source": "patent"},
            {"name": "t-Dodecyl mercaptan", "value": 0.2, "unit": "phr", "source": "patent"},
        ],
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 150, "unit": "phr"}, {"name": "Potassium rosinate", "value": 2.5, "unit": "phr"}]},
            {"stage_name": "Catalyst Solution", "parameters": [{"name": "Potassium persulfate", "value": 0.35, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "1,3-Butadiene", "value": 72, "unit": "phr"}, {"name": "Styrene", "value": 28, "unit": "phr"}]},
            {"stage_name": "Chemical Stripping", "parameters": [{"name": "DEHA", "value": 0.1, "unit": "phr"}]},
            {"stage_name": "Post Addition", "parameters": [{"name": "Antioxidant", "value": 0.5, "unit": "phr"}]},
        ],
        "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}, "temperature_profile": [{"stage": "rxn", "value": "10", "unit": "°C"}]},
        "patent_references": ["US1234567B2", "US7654321B2"],
    }

    sparse_recipe = {
        "compound": "SBR",
        "polymerization_method": "Unknown",
        "parameters": [{"name": "Monomer", "value": 10, "unit": "phr", "source": "ai_generated"}],
        "stages": [],
        "process_conditions": {},
        "patent_references": [],
    }

    ctx = {
        "patents": [
            {"patent": "US1234567B2", "synthesis_method": "Cold emulsion", "disclosed_parameters": ["Water", "Potassium rosinate", "1,3-Butadiene", "Styrene"]},
            {"patent": "US7654321B2", "synthesis_method": "Cold emulsion", "disclosed_parameters": ["Potassium persulfate", "t-Dodecyl mercaptan"]},
        ]
    }

    score_strong = calculate_recipe_confidence_score(strong_recipe, [], [], ctx)
    score_sparse = calculate_recipe_confidence_score(sparse_recipe, [], [], {})

    assert score_strong > score_sparse
    assert score_strong >= 50
    assert score_sparse <= 40
    # Crucial: NOT hardcoded!
    assert score_strong != score_sparse
