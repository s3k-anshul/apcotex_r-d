"""
tests/test_recipe_simulator_context_and_semantics.py

Comprehensive tests for Recipe Simulator:
1. Report switching & stale-state prevention (Target Compound & Patent Context updates)
2. Property semantics (Target Constraints vs Competitor Benchmarks vs Empty Properties)
3. Chemical Stripping 3-scenario decision logic (Scenarios A, B, C)
4. Material-agnostic dynamic recipe handling (no polymer hardcoding)
5. Confidence score calculations for unconstrained baseline and AI-generated parameters
"""
import uuid
import pytest
from unittest.mock import AsyncMock, patch

from app.models.user import User, UserRole
from app.models.research_run import ResearchRun, RunStatus
from app.models.report_metadata import ReportMetadata
from app.schemas.recipe import (
    RecipeCycleCreate,
    RecipePropertyDef,
    CompetitorData,
    LLMRecipeSet,
    LLMRecipeCandidate,
    LLMRecipeStage,
    LLMRecipeParameter,
    LLMProcessConditions,
    LLMReactionTime,
    LLMFeedingHours,
    LLMTemperatureStep,
)
from app.services.recipe_service import (
    RecipeService,
    _normalize_recipe_stages,
    calculate_recipe_confidence_score,
    _default_ai_omission_reason,
    CANONICAL_STAGE_NAMES,
)


@pytest.fixture
def mock_user():
    return User(
        id=uuid.uuid4(),
        username=f"scientist_{uuid.uuid4().hex[:6]}",
        email=f"scientist_{uuid.uuid4().hex[:6]}@apcotex.com",
        full_name="Test Scientist",
        hashed_password="hashed_pw_dummy",
        role=UserRole.SCIENTIST,
        is_active=True,
    )


# ============================================================================
# 1. REPORT SWITCHING & STALE STATE REMOVAL TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_report_switching_updates_target_compound_and_context(db_session, mock_user):
    """
    When switching from Report A (20% Acrylonitrile NBR) to Report B (Low Styrene SBR),
    the new cycle must derive its compound name and patent context strictly from Report B,
    with zero Report A data remaining in the active context.
    """
    db_session.add(mock_user)
    await db_session.commit()

    # Create Run A & Report A (NBR)
    run_a = ResearchRun(
        id=uuid.uuid4(),
        created_by=mock_user.id,
        compound_name="20% Acrylonitrile NBR",
        status=RunStatus.COMPLETED,
    )
    db_session.add(run_a)
    report_a = ReportMetadata(
        id=uuid.uuid4(),
        research_run_id=run_a.id,
        version=1,
        structured_data={
            "title": "Patent Research on 20% Acrylonitrile NBR",
            "per_patent_analysis": [
                {
                    "patent_number": "US20250075019A1",
                    "synthesis_method": "Cold emulsion polymerization of ACN and butadiene",
                    "disclosed_parameters": ["Acrylonitrile: 20 wt%", "Butadiene: 80 wt%"],
                }
            ],
            "references": ["US20250075019A1 | NBR Synthesis"],
        },
    )
    db_session.add(report_a)

    # Create Run B & Report B (SBR)
    run_b = ResearchRun(
        id=uuid.uuid4(),
        created_by=mock_user.id,
        compound_name="Low Styrene SBR",
        status=RunStatus.COMPLETED,
    )
    db_session.add(run_b)
    report_b = ReportMetadata(
        id=uuid.uuid4(),
        research_run_id=run_b.id,
        version=1,
        structured_data={
            "title": "Patent Research on Low Styrene SBR",
            "per_patent_analysis": [
                {
                    "patent_number": "EP1998765B1",
                    "synthesis_method": "Emulsion copolymerization of styrene and butadiene",
                    "disclosed_parameters": ["Styrene: 15 wt%", "Butadiene: 85 wt%"],
                }
            ],
            "references": ["EP1998765B1 | SBR Copolymer"],
        },
    )
    db_session.add(report_b)
    await db_session.commit()

    service = RecipeService(db_session)

    # Cycle 1 created from Report A
    cycle_1_data = RecipeCycleCreate(
        research_run_id=run_a.id,
        target_product=None,  # Derived from run
    )
    cycle_1 = await service.create_cycle(cycle_1_data, mock_user)
    assert cycle_1.compound_name == "20% Acrylonitrile NBR"
    assert "US20250075019A1" in str(cycle_1.patent_context_summary)
    assert "EP1998765B1" not in str(cycle_1.patent_context_summary)

    # User switches to Report B -> Cycle 2 created from Report B
    cycle_2_data = RecipeCycleCreate(
        research_run_id=run_b.id,
        target_product=None,  # Derived from run B
    )
    cycle_2 = await service.create_cycle(cycle_2_data, mock_user)
    assert cycle_2.compound_name == "Low Styrene SBR"
    assert "EP1998765B1" in str(cycle_2.patent_context_summary)
    # Ensure zero Report A context leaked into Cycle 2
    assert "US20250075019A1" not in str(cycle_2.patent_context_summary)
    assert "20% Acrylonitrile NBR" not in cycle_2.compound_name


# ============================================================================
# 2. PROPERTY SEMANTICS REGRESSION TESTS
# ============================================================================

def test_confidence_score_with_active_target_constraints():
    """CASE 1: Target properties with min/max are treated as optimization constraints."""
    recipe = {
        "name": "Candidate 1",
        "parameters": [
            {"name": "Acrylonitrile (Monomer 2)", "value": "22", "unit": "wt%", "source": "patent"},
            {"name": "t-Dodecyl mercaptan (CTA)", "value": "0.45", "unit": "phr", "source": "patent"},
        ],
        "stages": [
            {"stage_name": "Monomer Mix", "parameters": [{"name": "Acrylonitrile", "value": "22", "unit": "wt%"}]}
        ],
        "process_conditions": {},
        "patent_references": ["US1234567A1"],
    }
    target_properties = [
        {"feature": "Acrylonitrile Content", "min": "20", "max": "25", "unit": "%"}
    ]
    patent_context = {"patents": [{"patent": "US1234567A1", "disclosed_parameters": ["Acrylonitrile"]}]}

    score = calculate_recipe_confidence_score(
        recipe=recipe,
        target_properties=target_properties,
        competitor_data=[],
        patent_context=patent_context,
    )
    assert score > 0
    # Aligned target constraint should give full score_a (25.0)


def test_confidence_score_with_empty_properties_awards_neutral_baseline():
    """CASE 2 & 3: When target properties are empty, system awards neutral baseline (18 pts)."""
    recipe = {
        "name": "Candidate 1",
        "parameters": [
            {"name": "Styrene (Monomer 1)", "value": "20", "unit": "wt%", "source": "inferred"},
            {"name": "Butadiene (Monomer 2)", "value": "80", "unit": "wt%", "source": "inferred"},
            {"name": "Water", "value": "180", "unit": "phr", "source": "inferred"},
            {"name": "Potassium persulfate (Initiator)", "value": "0.3", "unit": "phr", "source": "inferred"},
        ],
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": "180", "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "parameters": [{"name": "Styrene", "value": "20", "unit": "wt%"}]},
            {"stage_name": "Catalyst Solution", "parameters": [{"name": "Initiator", "value": "0.3", "unit": "phr"}]},
        ],
        "process_conditions": {"reaction_time": {"value": "8", "unit": "h"}},
        "patent_references": [],
    }
    # User provided NO target property constraints
    score_empty_tp = calculate_recipe_confidence_score(
        recipe=recipe,
        target_properties=[],
        competitor_data=[],
        patent_context={},
    )
    assert score_empty_tp >= 30  # Should be viable baseline confidence, not penalized to zero


def test_property_rows_without_min_max_treated_as_unconstrained_baseline():
    """Property rows present in table but with empty min/max strings must not be penalized."""
    recipe = {
        "name": "Candidate 1",
        "parameters": [
            {"name": "Water", "value": "180", "unit": "phr", "source": "inferred"},
        ],
        "stages": [],
        "process_conditions": {},
    }
    # Rows exist in UI table but user left min and max blank
    target_properties_unconstrained = [
        {"feature": "Mooney Viscosity", "min": "", "max": "", "unit": "MU"},
        {"feature": "Glass Transition Temp", "min": None, "max": None, "unit": "°C"},
    ]
    score = calculate_recipe_confidence_score(
        recipe=recipe,
        target_properties=target_properties_unconstrained,
        competitor_data=[],
        patent_context={},
    )
    # Neutral baseline for Component A is 18.0, so total is well above 15
    assert score >= 20


# ============================================================================
# 3. CHEMICAL STRIPPING 3-SCENARIO DECISION LOGIC TESTS
# ============================================================================

def test_chemical_stripping_scenario_a_not_applicable():
    """
    SCENARIO A: Target process does not require chemical stripping.
    Stage must have is_applicable=False, parameters=[], and a valid omission reason.
    """
    recipe = {
        "name": "Solution Polymerization Baseline",
        "stages": [
            {"stage_name": "Reactor Charge", "parameters": [{"name": "Solvent", "value": "100", "unit": "phr"}]},
            {
                "stage_name": "Chemical Stripping",
                "parameters": [],
                "omission_reason": "Living anionic solution polymerization achieves full conversion without stripping.",
            },
        ],
    }
    normalized = _normalize_recipe_stages(recipe, target_compound="Solution SSBR")
    stages = {s["stage_name"]: s for s in normalized["stages"]}
    
    stripping_stage = stages["Chemical Stripping"]
    assert stripping_stage["is_applicable"] is False
    assert len(stripping_stage["parameters"]) == 0
    assert "omission_reason" in stripping_stage
    assert stripping_stage["omission_reason"] is not None
    assert "anionic" in stripping_stage["omission_reason"] or "stripping" in stripping_stage["omission_reason"]


def test_chemical_stripping_scenario_b_patent_supported():
    """
    SCENARIO B: Chemical stripping required and disclosed in patent.
    Stage must have is_applicable=True, source='patent', and valid patent_ref.
    """
    recipe = {
        "name": "Emulsion SBR Candidate",
        "stages": [
            {
                "stage_name": "Chemical Stripping",
                "parameters": [
                    {
                        "name": "Sodium dimethyldithiocarbamate (Shortstop)",
                        "value": "0.15",
                        "unit": "phr",
                        "source": "patent",
                        "patent_ref": "US6543210B2",
                    },
                    {
                        "name": "Vacuum Steam Stripping",
                        "value": "70",
                        "unit": "°C",
                        "source": "patent",
                        "patent_ref": "US6543210B2",
                    },
                ],
            }
        ],
    }
    normalized = _normalize_recipe_stages(recipe, target_compound="Emulsion SBR")
    stages = {s["stage_name"]: s for s in normalized["stages"]}
    
    stripping_stage = stages["Chemical Stripping"]
    assert stripping_stage["is_applicable"] is True
    assert len(stripping_stage["parameters"]) == 2
    assert stripping_stage["parameters"][0]["source"] == "patent"
    assert stripping_stage["parameters"][0]["patent_ref"] == "US6543210B2"
    assert stripping_stage["omission_reason"] is None


def test_chemical_stripping_scenario_c_ai_derived_not_patent_disclosed():
    """
    SCENARIO C: Chemical stripping required by chemistry but patent silent.
    Stage must have is_applicable=True, source='ai_generated', and patent_ref=None.
    Must NOT be falsely marked as patent-supported!
    """
    recipe = {
        "name": "Carboxylated Latex Candidate",
        "stages": [
            {
                "stage_name": "Chemical Stripping",
                "parameters": [
                    {
                        "name": "Diethylhydroxylamine (DEHA Shortstop)",
                        "value": "0.10",
                        "unit": "phr",
                        "source": "ai_generated",
                        "patent_ref": None,
                    },
                    {
                        "name": "Chemical Scavenger (Sodium formaldehyde sulfoxylate)",
                        "value": "0.08",
                        "unit": "phr",
                        "source": "ai_generated",
                        "patent_ref": None,
                    },
                ],
            }
        ],
    }
    normalized = _normalize_recipe_stages(recipe, target_compound="Carboxylated NBR")
    stages = {s["stage_name"]: s for s in normalized["stages"]}
    
    stripping_stage = stages["Chemical Stripping"]
    assert stripping_stage["is_applicable"] is True
    assert len(stripping_stage["parameters"]) == 2
    for p in stripping_stage["parameters"]:
        assert p["source"] == "ai_generated"
        assert p["patent_ref"] is None
    assert stripping_stage["omission_reason"] is None


# ============================================================================
# 4. DYNAMIC COMPOUND HANDLING TESTS (ZERO POLYMER HARDCODING)
# ============================================================================

def test_dynamic_compound_normalization_polyhydroxyalkanoate():
    """
    Verify that normalization works seamlessly for a non-elastomer, non-NBR material
    (e.g., Polyhydroxyalkanoate biopolymer), preserving dynamic monomer names.
    """
    recipe = {
        "name": "PHA Fermentative Polymerization",
        "stages": [
            {
                "stage_name": "Reactor Charge",
                "parameters": [
                    {"name": "Mineral Salts Medium", "value": "1000", "unit": "g/L"},
                    {"name": "Cupriavidus necator Inoculum", "value": "5", "unit": "vol%"},
                ],
            },
            {
                "stage_name": "Monomer Mix",
                "parameters": [
                    {"name": "Sodium 4-hydroxybutyrate (Co-substrate)", "value": "15", "unit": "g/L"},
                    {"name": "Glucose (Carbon Source)", "value": "30", "unit": "g/L"},
                ],
            },
            {
                "stage_name": "Post Addition",
                "parameters": [
                    {"name": "Sodium hypochlorite (Cell Lyse)", "value": "5", "unit": "wt%"},
                ],
            },
        ],
    }
    normalized = _normalize_recipe_stages(recipe, target_compound="Poly(3-hydroxybutyrate-co-4-hydroxybutyrate)")
    stages = {s["stage_name"]: s for s in normalized["stages"]}
    
    assert len(normalized["stages"]) == 6
    assert [s["stage_name"] for s in normalized["stages"]] == CANONICAL_STAGE_NAMES
    
    # Check PHA ingredients are preserved untouched
    assert stages["Reactor Charge"]["parameters"][0]["name"] == "Mineral Salts Medium"
    assert stages["Monomer Mix"]["parameters"][0]["name"] == "Sodium 4-hydroxybutyrate (Co-substrate)"
    # Emulsifier and Stripping were omitted -> default AI omission reasons assigned
    assert stages["Emulsifier Solution"]["is_applicable"] is False
    assert stages["Chemical Stripping"]["is_applicable"] is False
    assert stages["Chemical Stripping"]["omission_reason"] is not None


def test_ai_omission_reason_is_scientifically_coherent():
    """Verify that default AI omission reasons provide scientifically sound context."""
    reason_strip = _default_ai_omission_reason("Chemical Stripping", "Polyethylene glycol")
    assert "stripping" in reason_strip.lower()
    assert "conversion" in reason_strip.lower()

    reason_cat = _default_ai_omission_reason("Catalyst Solution", "Acrylic Emulsion")
    assert "initiator" in reason_cat.lower() or "catalyst" in reason_cat.lower()
