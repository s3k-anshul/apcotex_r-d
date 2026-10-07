import uuid
import pytest
from app.models.recipe_cycle import RecipeCycle
from app.models.recipe_candidate import RecipeCandidate
from app.models.saved_recipe import SavedRecipe, SavedRecipeKind
from app.models.user import User, UserRole
from app.schemas.recipe import SavedRecipeBatchCreate, SavedRecipeCreate, RecipeCycleCreate, RecipePropertyDef
from app.services.recipe_service import RecipeService, calculate_recipe_confidence_score, check_patent_copying
from app.services.saved_recipe_service import SavedRecipeService


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


def test_calculate_recipe_confidence_score_dynamic_and_no_71():
    """Verify confidence score is calculated per-recipe dynamically without static 71% fallback."""
    # Recipe 1: Baseline formulation with direct citations and strong alignment
    r1 = {
        "parameters": [
            {"name": "Water (Reaction Medium)", "value": 180, "unit": "phr", "source": "patent", "patent_ref": "US1000"},
            {"name": "Monomer A", "value": 60, "unit": "phr", "source": "patent", "patent_ref": "US1000"},
            {"name": "Monomer B", "value": 40, "unit": "phr", "source": "patent", "patent_ref": "US1000"},
            {"name": "Potassium persulfate (Initiator)", "value": 0.35, "unit": "phr", "source": "patent", "patent_ref": "US1000"},
            {"name": "t-Dodecyl mercaptan (CTA)", "value": 0.30, "unit": "phr", "source": "patent", "patent_ref": "US1000"},
            {"name": "Sodium oleate (Emulsifier)", "value": 2.5, "unit": "phr", "source": "patent", "patent_ref": "US1000"},
        ],
        "stages": [
            {"stage_name": "Reactor Charge", "is_applicable": True, "parameters": [{"name": "Water", "value": 180, "unit": "phr"}]},
            {"stage_name": "Emulsifier Solution", "is_applicable": True, "parameters": [{"name": "Soap", "value": 2.5, "unit": "phr"}]},
            {"stage_name": "Catalyst Solution", "is_applicable": True, "parameters": [{"name": "Initiator", "value": 0.35, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "is_applicable": True, "parameters": [{"name": "Monomer A", "value": 60, "unit": "phr"}]},
            {"stage_name": "Chemical Stripping", "is_applicable": True, "parameters": [{"name": "Shortstop", "value": 0.15, "unit": "phr"}]},
            {"stage_name": "Post Addition", "is_applicable": True, "parameters": [{"name": "Antioxidant", "value": 0.5, "unit": "phr"}]},
        ],
        "process_conditions": {
            "reaction_time": {"value": 8, "unit": "h"},
            "temperature_profile": [{"stage": "Polymerization", "value": 10, "unit": "°C"}],
        },
        "patent_references": ["US1000"],
    }

    # Recipe 2: Higher CTA, redox system, different ratio
    r2 = {
        "parameters": [
            {"name": "Water (Reaction Medium)", "value": 200, "unit": "phr", "source": "inferred"},
            {"name": "Monomer A", "value": 70, "unit": "phr", "source": "inferred"},
            {"name": "Monomer B", "value": 30, "unit": "phr", "source": "inferred"},
            {"name": "Redox Catalyst (Initiator)", "value": 0.15, "unit": "phr", "source": "inferred"},
            {"name": "t-Dodecyl mercaptan (CTA)", "value": 0.55, "unit": "phr", "source": "inferred"},
        ],
        "stages": [
            {"stage_name": "Reactor Charge", "is_applicable": True, "parameters": [{"name": "Water", "value": 200, "unit": "phr"}]},
            {"stage_name": "Catalyst Solution", "is_applicable": True, "parameters": [{"name": "Redox", "value": 0.15, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "is_applicable": True, "parameters": [{"name": "Monomer A", "value": 70, "unit": "phr"}]},
        ],
        "process_conditions": {
            "reaction_time": {"value": 10, "unit": "h"},
        },
        "patent_references": [],
    }

    # Recipe 3: Minimal stages, different parameters
    r3 = {
        "parameters": [
            {"name": "Water", "value": 120, "unit": "phr", "source": "ai_generated"},
            {"name": "Monomer A", "value": 50, "unit": "phr", "source": "ai_generated"},
            {"name": "Monomer B", "value": 50, "unit": "phr", "source": "ai_generated"},
        ],
        "stages": [
            {"stage_name": "Reactor Charge", "is_applicable": True, "parameters": [{"name": "Water", "value": 120, "unit": "phr"}]},
            {"stage_name": "Monomer Mix", "is_applicable": True, "parameters": [{"name": "Monomer A", "value": 50, "unit": "phr"}]},
        ],
        "patent_references": [],
    }

    patent_context = {
        "patents": [{"patent_number": "US1000", "title": "SBR", "synthesis_methods": ["emulsion"]}],
        "compound_name": "Styrene Butadiene Rubber",
    }
    target_props = [{"feature": "Mooney", "min": 40, "max": 50, "unit": "MU"}]

    score1 = calculate_recipe_confidence_score(r1, target_props, [], patent_context)
    score2 = calculate_recipe_confidence_score(r2, target_props, [], patent_context)
    score3 = calculate_recipe_confidence_score(r3, target_props, [], patent_context)

    # Must be distinct numbers
    assert score1 != score2
    assert score2 != score3
    assert score1 != score3

    # Must not be hardcoded 71%
    assert not (score1 == 71.0 and score2 == 71.0 and score3 == 71.0)
    # R1 has higher patent overlap, process completeness, and full canonical stages
    assert score1 > score2 > score3


def test_check_patent_copying():
    """Verify check_patent_copying flags verbatim clones and passes differentiated candidates."""
    patent_context = {
        "patents": [
            {
                "patent_number": "US1234567A",
                "example_highlights": ["Example 1: Butadiene 72.0 phr, Styrene 28.0 phr, Potassium persulfate 0.30 phr, t-DDM 0.25 phr"],
                "disclosed_parameters": ["Butadiene 72.0", "Styrene 28.0", "Potassium persulfate 0.30", "t-DDM 0.25"],
            }
        ]
    }

    # Exact clone recipe where all parameters match patent disclosed example
    verbatim_recipe = {
        "parameters": [
            {"name": "Butadiene", "value": 72.0},
            {"name": "Styrene", "value": 28.0},
            {"name": "Potassium persulfate", "value": 0.30},
            {"name": "t-DDM", "value": 0.25},
        ]
    }
    res1 = check_patent_copying(verbatim_recipe, patent_context)
    assert res1["is_verbatim_copy"] is True

    # Differentiated recipe with altered stoichiometry and AI-derived CTA/initiator
    differentiated_recipe = {
        "parameters": [
            {"name": "Butadiene", "value": 65.0, "source": "ai_generated"},
            {"name": "Styrene", "value": 35.0, "source": "ai_generated"},
            {"name": "Potassium persulfate", "value": 0.45, "source": "ai_generated"},
            {"name": "t-DDM", "value": 0.18, "source": "ai_generated"},
        ]
    }
    res2 = check_patent_copying(differentiated_recipe, patent_context)
    assert res2["is_verbatim_copy"] is False
    assert res2["ai_adaptation_ratio"] == 1.0


@pytest.mark.asyncio
async def test_update_candidate_recipe_data_persists_user_edits(db_session, mock_user):
    """Verify user additions, deletions, and custom stages are authoritative and not overridden by auto-enrichment."""
    service = RecipeService(db_session)
    db_session.add(mock_user)
    await db_session.commit()

    # Create cycle and candidate
    cycle_data = RecipeCycleCreate(
        target_product="Carboxylated NBR",
        target_properties=[RecipePropertyDef(id="p1", feature="BACN", unit="%", min="25", max="30")],
    )
    cycle = await service.create_cycle(cycle_data, mock_user)
    candidate = RecipeCandidate(
        cycle_id=cycle.id,
        name="Candidate 1",
        rank=1,
        recipe_data={
            "stages": [
                {
                    "stage_name": "Reactor Charge",
                    "parameters": [{"name": "Initial Water", "value": 180, "unit": "phr"}],
                    "is_applicable": True,
                },
                {
                    "stage_name": "Emulsifier Solution",
                    "parameters": [{"name": "Sodium Lauryl Sulfate", "value": 2.0, "unit": "phr"}],
                    "is_applicable": True,
                },
            ]
        },
    )
    db_session.add(candidate)
    await db_session.commit()
    await db_session.refresh(candidate)

    # User modifies candidate:
    # 1. Adds new custom parameter "Electrolyte (KCl)" to Reactor Charge
    # 2. Deletes "Emulsifier Solution" stage entirely
    # 3. Adds new custom stage "Post Stabilization" with parameter "Buffer (Na2CO3)"
    edited_data = {
        "stages": [
            {
                "stage_name": "Reactor Charge",
                "parameters": [
                    {"name": "Initial Water", "value": 180, "unit": "phr"},
                    {"name": "Electrolyte (KCl)", "value": 0.25, "unit": "phr"},
                ],
                "is_applicable": True,
            },
            {
                "stage_name": "Post Stabilization",
                "parameters": [
                    {"name": "Buffer (Na2CO3)", "value": 0.5, "unit": "phr"},
                ],
                "is_applicable": True,
            },
        ],
        "process_conditions": {
            "reaction_time": {"value": 12, "unit": "h"}
        }
    }

    updated_candidate = await service.update_candidate_recipe_data(
        cycle_id=cycle.id,
        candidate_id=candidate.id,
        recipe_data=edited_data,
        current_user=mock_user,
        name="Edited Carboxylated NBR Baseline",
    )

    # Verification:
    assert updated_candidate.name == "Edited Carboxylated NBR Baseline"
    stages = updated_candidate.recipe_data["stages"]
    stage_names = [s["stage_name"] for s in stages]

    # Custom stage persisted
    assert "Post Stabilization" in stage_names
    # Deleted stage did NOT re-appear
    assert "Emulsifier Solution" not in stage_names

    # Added parameter persisted
    reactor_stage = next(s for s in stages if s["stage_name"] == "Reactor Charge")
    param_names = [p["name"] for p in reactor_stage["parameters"]]
    assert "Electrolyte (KCl)" in param_names
    electrolyte_param = next(p for p in reactor_stage["parameters"] if p["name"] == "Electrolyte (KCl)")
    assert electrolyte_param["value"] == 0.25
    assert electrolyte_param["unit"] == "phr"

    # Reload from DB directly to verify persistence
    await db_session.refresh(candidate)
    db_stages = candidate.recipe_data["stages"]
    assert len(db_stages) == 2
    assert db_stages[0]["stage_name"] == "Reactor Charge"
    assert db_stages[1]["stage_name"] == "Post Stabilization"
    assert candidate.recipe_data["process_conditions"]["reaction_time"]["value"] == 12


@pytest.mark.asyncio
async def test_save_recipes_batch_creates_independent_records(db_session, mock_user):
    """Verify batch save saves multiple recipes atomically with independent names and correct NORMAL kind."""
    recipe_svc = RecipeService(db_session)
    saved_svc = SavedRecipeService(db_session)
    db_session.add(mock_user)
    await db_session.commit()

    cycle_data = RecipeCycleCreate(
        target_product="Low Styrene SBR",
    )
    cycle = await recipe_svc.create_cycle(cycle_data, mock_user)
    c1 = RecipeCandidate(
        cycle_id=cycle.id,
        name="Candidate 1",
        rank=1,
        recipe_data={"compound": "Low Styrene SBR", "stages": [{"stage_name": "Reactor Charge", "parameters": []}]},
    )
    c2 = RecipeCandidate(
        cycle_id=cycle.id,
        name="Candidate 2",
        rank=2,
        recipe_data={"compound": "Low Styrene SBR", "stages": [{"stage_name": "Reactor Charge", "parameters": []}]},
    )
    db_session.add_all([c1, c2])
    await db_session.commit()
    await db_session.refresh(c1)
    await db_session.refresh(c2)

    batch_payload = SavedRecipeBatchCreate(
        recipes=[
            SavedRecipeCreate(
                recipe_name="Low Styrene Baseline Formulation",
                recipe_data={"compound": "Low Styrene SBR", "variant": "Baseline"},
                source_cycle_id=cycle.id,
                source_candidate_id=c1.id,
                recipe_kind=SavedRecipeKind.NORMAL,
            ),
            SavedRecipeCreate(
                recipe_name="High CTA Modified SBR",
                recipe_data={"compound": "Low Styrene SBR", "variant": "High CTA"},
                source_cycle_id=cycle.id,
                source_candidate_id=c2.id,
                recipe_kind=SavedRecipeKind.NORMAL,
            ),
        ]
    )

    result = await saved_svc.save_recipes_batch(batch_payload, current_user=mock_user)
    assert result.total_requested == 2
    assert result.total_saved == 2
    assert len(result.results) == 2
    assert all(r.success is True for r in result.results)

    # Verify both records exist independently in saved_recipes
    r1 = await saved_svc.get_recipe(result.results[0].saved_recipe.id, mock_user)
    r2 = await saved_svc.get_recipe(result.results[1].saved_recipe.id, mock_user)

    assert r1.recipe_name == "Low Styrene Baseline Formulation"
    assert r1.recipe_kind == SavedRecipeKind.NORMAL
    assert r1.parent_recipe_id is None
    assert r1.recipe_data["variant"] == "Baseline"

    assert r2.recipe_name == "High CTA Modified SBR"
    assert r2.recipe_kind == SavedRecipeKind.NORMAL
    assert r2.parent_recipe_id is None
    assert r2.recipe_data["variant"] == "High CTA"
