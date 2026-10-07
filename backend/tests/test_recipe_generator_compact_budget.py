"""
tests/test_recipe_generator_compact_budget.py

Unit and integration tests for Recipe Simulator generation fix:
- Strict output-token budget and compact schema configuration.
- Preservation of schema required fields in Gemini schema normalizer.
- Compact synthesis context builder from completed patent report.
- Exactly 5 recipes generated in one structured call.
- Dynamic chemistry across polymers (Low Styrene SBR, Low ACN NBR, EPDM) with zero hardcoding.
- Target properties vs no target properties semantics.
- Patent support verification and deterministic application-side confidence calculation.
- 1-shot safe retry and graceful error handling on malformed JSON (no 500 crash or leaked internals).
"""
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.recipe_cycle import RecipeCycle, RecipeCycleStatus
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
from app.services.llm.schema_normalizer import normalize_gemini_schema
from app.services.recipe_service import (
    RecipeService,
    _normalize_recipe_stages,
    calculate_recipe_confidence_score,
    CANONICAL_STAGE_NAMES,
)


@pytest.fixture
def mock_user():
    return User(
        id=uuid.uuid4(),
        username=f"formulator_{uuid.uuid4().hex[:6]}",
        email="formulator@apcotex.com",
        full_name="Formulator User",
        hashed_password="pw",
        role=UserRole.SCIENTIST,
        is_active=True,
    )


# ============================================================================
# 1. SCHEMA NORMALIZATION & TOKEN BUDGET CONFIGURATION TESTS
# ============================================================================

def test_schema_normalizer_preserves_recipe_required_fields():
    """Gemini schema normalizer must preserve required fields on recipe schemas to prevent runaway generation."""
    raw = LLMRecipeSet.model_json_schema()
    norm = normalize_gemini_schema(raw)

    assert "required" in norm
    assert "recipes" in norm["required"]

    cand_schema = norm["properties"]["recipes"]["items"]
    assert "required" in cand_schema
    for req in ["name", "compound", "polymerization_method", "stages", "variation_dimension", "patent_references"]:
        assert req in cand_schema["required"]
    # Flat parameters list is optional for LLM (auto-populated by server)
    assert "parameters" not in cand_schema["required"]

    stage_schema = cand_schema["properties"]["stages"]["items"]
    assert "required" in stage_schema
    assert set(stage_schema["required"]) == {"stage_name", "parameters"}

    param_schema = stage_schema["properties"]["parameters"]["items"]
    assert "required" in param_schema
    assert set(param_schema["required"]) == {"name", "value", "unit", "source"}


def test_recipe_output_token_budget_configured():
    """Settings must define a sensible RECIPE_MAX_OUTPUT_TOKENS (16384)."""
    assert hasattr(settings, "RECIPE_MAX_OUTPUT_TOKENS")
    assert settings.RECIPE_MAX_OUTPUT_TOKENS <= 24576
    assert settings.RECIPE_MAX_OUTPUT_TOKENS >= 8192


# ============================================================================
# 2. COMPACT CONTEXT BUILDER TESTS
# ============================================================================

def test_compact_synthesis_context_builder(db_session):
    """Context builder must extract structured synthesis options and concise patent support without raw dumps."""
    service = RecipeService(db_session)
    patent_context = {
        "source": "completed_patent_report",
        "patents": [
            {
                "patent": "US20250075019A1",
                "synthesis_method": "Cold emulsion polymerization at 10 °C to 65% conversion.",
                "disclosed_parameters": [
                    "Butadiene: 75 phr",
                    "Styrene: 25 phr",
                    "Potassium persulfate: 0.2 phr",
                    "t-Dodecyl mercaptan: 0.22 phr",
                    "Reaction temperature: 10 °C",
                    "Polymerization time: 10 h",
                ],
                "example_highlights": ["Example 1 shows 65% conversion with low coagulum."],
            },
            {
                "patent": "EP3124501B1",
                "synthesis_method": "Continuous cold emulsion copolymerization.",
                "disclosed_parameters": [
                    "Styrene monomer: 23 wt%",
                    "Sodium oleate emulsifier: 3.5 phr",
                    "Temperature: 8 °C",
                ],
                "example_highlights": ["Run B achieves Mooney viscosity 52 MU."],
            },
        ],
    }

    compact_text = service._format_compact_synthesis_context(patent_context)

    # Must contain clear, structured sections
    assert "REPORT-DERIVED SYNTHESIS OPTIONS:" in compact_text
    assert "PATENT SUPPORT (BY PATENT):" in compact_text

    # Must contain synthesis options categorized
    assert "Monomer options/ranges:" in compact_text
    assert "Initiator/catalyst options:" in compact_text
    assert "Emulsifier/surfactant options:" in compact_text
    assert "Chain transfer agent (CTA) options:" in compact_text

    # Must list patents with concise values
    assert "US20250075019A1:" in compact_text
    assert "EP3124501B1:" in compact_text

    # Must be extremely compact (under 300 words, no raw JSON brackets)
    assert "{" not in compact_text
    assert len(compact_text) < 2500


def test_compact_context_builder_empty_context(db_session):
    """When patent context is empty, builder provides clean chemical guidance without error."""
    service = RecipeService(db_session)
    compact_text = service._format_compact_synthesis_context({})
    assert "No patent report context available" in compact_text


# ============================================================================
# 3. DYNAMIC CANDIDATE GENERATION & ZERO HARDCODING
# ============================================================================

def _make_dummy_recipe(compound: str, rank: int, variation: str, monomer1: str, monomer2: str) -> LLMRecipeCandidate:
    return LLMRecipeCandidate(
        name=f"Recipe {rank} - {variation}",
        compound=compound,
        polymerization_method="Emulsion Polymerization",
        variation_dimension=variation,
        patent_references=["US20250075019A1"],
        rationale=f"Targets desired properties by optimizing {variation.lower()}.",
        stages=[
            LLMRecipeStage(
                stage_name="Reactor Charge",
                parameters=[
                    LLMRecipeParameter(name="Water", value="180", unit="phr", source="patent", patent_ref="US20250075019A1"),
                    LLMRecipeParameter(name="Surfactant", value="2.5", unit="phr", source="patent", patent_ref="US20250075019A1"),
                ]
            ),
            LLMRecipeStage(
                stage_name="Catalyst Solution",
                parameters=[
                    LLMRecipeParameter(name="Potassium persulfate (Initiator)", value="0.2", unit="phr", source="patent", patent_ref="US20250075019A1"),
                ]
            ),
            LLMRecipeStage(
                stage_name="Monomer Mix",
                parameters=[
                    LLMRecipeParameter(name=f"{monomer1} (Monomer 1)", value="70", unit="phr", source="patent", patent_ref="US20250075019A1"),
                    LLMRecipeParameter(name=f"{monomer2} (Monomer 2)", value="30", unit="phr", source="patent", patent_ref="US20250075019A1"),
                    LLMRecipeParameter(name="t-Dodecyl mercaptan (CTA)", value="0.25", unit="phr", source="patent", patent_ref="US20250075019A1"),
                ]
            ),
            LLMRecipeStage(stage_name="Emulsifier Solution", parameters=[]),
            LLMRecipeStage(stage_name="Chemical Stripping", parameters=[]),
            LLMRecipeStage(stage_name="Post Addition", parameters=[]),
        ],
        process_conditions=LLMProcessConditions(
            reaction_time=LLMReactionTime(value="8", unit="h"),
            temperature_profile=[LLMTemperatureStep(stage="Polymerization", value="10", unit="°C")],
        ),
    )


@pytest.mark.asyncio
async def test_generate_recipes_dynamic_sbr(db_session, mock_user):
    """Test generating 5 candidates for Low Styrene SBR with dynamic ingredients."""
    db_session.add(mock_user)
    await db_session.commit()

    service = RecipeService(db_session)
    cycle = await service.create_cycle(
        RecipeCycleCreate(
            target_product="Low Styrene SBR",
            target_properties=[RecipePropertyDef(id="mooney", feature="Mooney Viscosity", min="45", max="55", unit="MU")],
        ),
        mock_user,
    )

    variations = ["Primary Monomer Ratio", "CTA Concentration", "Initiator Level", "Reaction Temperature", "Solids Content"]
    mock_recipes = [
        _make_dummy_recipe("Low Styrene SBR", i + 1, variations[i], "1,3-Butadiene", "Styrene")
        for i in range(5)
    ]
    mock_recipe_set = LLMRecipeSet(recipes=mock_recipes)

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = (mock_recipe_set, "{}", {"prompt_token_count": 850, "candidates_token_count": 1200})

        candidates = await service.generate_recipes(cycle.id, mock_user)

    assert len(candidates) == 5
    assert cycle.status == RecipeCycleStatus.STEP2

    # Verify each has a distinct variation dimension
    var_dims = [c.recipe_data["variation_dimension"] for c in candidates]
    assert len(set(var_dims)) == 5

    # Verify ingredients are dynamic SBR monomers
    first_c = candidates[0]
    param_names = [p["name"] for p in first_c.recipe_data["parameters"]]
    assert any("Styrene" in p for p in param_names)
    assert any("Butadiene" in p for p in param_names)

    # Verify confidence score is computed deterministically application-side
    assert first_c.evidence_coverage_score is not None
    assert 0 <= first_c.evidence_coverage_score <= 100
    assert first_c.recipe_data.get("confidence_score") == first_c.evidence_coverage_score


@pytest.mark.asyncio
async def test_generate_recipes_dynamic_nbr(db_session, mock_user):
    """Test generating 5 candidates for Low Acrylonitrile NBR with dynamic ingredients."""
    db_session.add(mock_user)
    await db_session.commit()

    service = RecipeService(db_session)
    cycle = await service.create_cycle(
        RecipeCycleCreate(
            target_product="Low Acrylonitrile NBR",
            target_properties=[RecipePropertyDef(id="bound_acn", feature="Bound ACN", min="18", max="22", unit="%")],
        ),
        mock_user,
    )

    variations = ["ACN Monomer Ratio", "CTA Concentration", "Initiator System", "Temperature Profile", "Conversion Target"]
    mock_recipes = [
        _make_dummy_recipe("Low Acrylonitrile NBR", i + 1, variations[i], "1,3-Butadiene", "Acrylonitrile")
        for i in range(5)
    ]
    mock_recipe_set = LLMRecipeSet(recipes=mock_recipes)

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = (mock_recipe_set, "{}", {})
        candidates = await service.generate_recipes(cycle.id, mock_user)

    assert len(candidates) == 5
    first_c = candidates[0]
    param_names = [p["name"] for p in first_c.recipe_data["parameters"]]
    assert any("Acrylonitrile" in p for p in param_names)
    assert any("Butadiene" in p for p in param_names)


@pytest.mark.asyncio
async def test_generate_recipes_generic_polymer_no_hardcoding(db_session, mock_user):
    """Test generating candidates for EPDM proves no NBR/SBR hardcoding exists."""
    db_session.add(mock_user)
    await db_session.commit()

    service = RecipeService(db_session)
    cycle = await service.create_cycle(
        RecipeCycleCreate(target_product="Ethylene Propylene Diene Monomer (EPDM)"),
        mock_user,
    )

    variations = ["Ethylene/Propylene Ratio", "Diene Loading", "Catalyst Concentration", "Polymerization Temperature", "Solvent Ratio"]
    mock_recipes = [
        _make_dummy_recipe("EPDM", i + 1, variations[i], "Ethylene", "Propylene")
        for i in range(5)
    ]
    mock_recipe_set = LLMRecipeSet(recipes=mock_recipes)

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = (mock_recipe_set, "{}", {})
        candidates = await service.generate_recipes(cycle.id, mock_user)

    assert len(candidates) == 5
    first_c = candidates[0]
    param_names = [p["name"] for p in first_c.recipe_data["parameters"]]
    assert any("Ethylene" in p for p in param_names)
    assert any("Propylene" in p for p in param_names)


# ============================================================================
# 4. TARGET PROPERTIES VS UNCONSTRAINED BASELINE
# ============================================================================

@pytest.mark.asyncio
async def test_no_target_properties_generates_standard_baseline(db_session, mock_user):
    """When no target properties are given, generation proceeds with baseline mode without error."""
    db_session.add(mock_user)
    await db_session.commit()

    service = RecipeService(db_session)
    cycle = await service.create_cycle(
        RecipeCycleCreate(target_product="Low Styrene SBR", target_properties=[]),
        mock_user,
    )

    variations = ["Var 1", "Var 2", "Var 3", "Var 4", "Var 5"]
    mock_recipes = [
        _make_dummy_recipe("Low Styrene SBR", i + 1, variations[i], "1,3-Butadiene", "Styrene")
        for i in range(5)
    ]
    mock_recipe_set = LLMRecipeSet(recipes=mock_recipes)

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = (mock_recipe_set, "{}", {})
        candidates = await service.generate_recipes(cycle.id, mock_user)

    assert len(candidates) == 5
    # Verify the prompt sent to LLM contains the baseline instruction
    sent_prompt = mock_llm.call_args.kwargs["system_prompt"]
    assert "NO target properties specified" in sent_prompt


# ============================================================================
# 5. ERROR HANDLING, RETRY & MALFORMED JSON SAFETY
# ============================================================================

@pytest.mark.asyncio
async def test_malformed_json_triggers_safe_retry(db_session, mock_user):
    """When LLM returns empty/malformed structured data on attempt 1, it retries safely on attempt 2."""
    db_session.add(mock_user)
    await db_session.commit()

    service = RecipeService(db_session)
    cycle = await service.create_cycle(
        RecipeCycleCreate(target_product="Low Styrene SBR"),
        mock_user,
    )

    variations = ["Var 1", "Var 2", "Var 3", "Var 4", "Var 5"]
    mock_recipes = [
        _make_dummy_recipe("Low Styrene SBR", i + 1, variations[i], "1,3-Butadiene", "Styrene")
        for i in range(5)
    ]
    mock_recipe_set = LLMRecipeSet(recipes=mock_recipes)

    call_count = 0

    async def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate first attempt returning empty or failing
            return None, "malformed text", {}
        # Attempt 2 succeeds
        return mock_recipe_set, "{}", {}

    with patch.object(service.llm_client, "generate_structured", side_effect=mock_generate):
        candidates = await service.generate_recipes(cycle.id, mock_user)

    assert call_count == 2
    assert len(candidates) == 5
    assert cycle.status == RecipeCycleStatus.STEP2


@pytest.mark.asyncio
async def test_malformed_json_exhausted_raises_clean_502(db_session, mock_user):
    """When LLM fails after 2 attempts, returns HTTP 502 with clean error and does NOT save partial recipes."""
    db_session.add(mock_user)
    await db_session.commit()

    service = RecipeService(db_session)
    cycle = await service.create_cycle(
        RecipeCycleCreate(target_product="Low Styrene SBR"),
        mock_user,
    )

    with patch.object(service.llm_client, "generate_structured", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = (None, "malformed response", {})

        with pytest.raises(HTTPException) as exc_info:
            await service.generate_recipes(cycle.id, mock_user)

    assert exc_info.value.status_code == 502
    assert "Recipe generation could not produce valid structured data" in exc_info.value.detail
    # Must not leak technical provider error strings or keys
    assert "Gemini" not in exc_info.value.detail
    assert "key" not in exc_info.value.detail

    # Cycle status updated to FAILED and no candidates saved
    assert cycle.status == RecipeCycleStatus.FAILED
    assert len(cycle.candidates) == 0


# ============================================================================
# 6. STAGE NORMALIZATION & FLAT PARAMETER SYNCHRONIZATION
# ============================================================================

def test_flat_parameters_automatically_synchronized_from_stages():
    """Verify that when the LLM emits parameters only inside stages, backend flattens them into recipe_data['parameters']."""
    r_dict = {
        "name": "Recipe Candidate",
        "stages": [
            {
                "stage_name": "Reactor Charge",
                "parameters": [
                    {"name": "Water", "value": "180", "unit": "phr", "source": "patent"},
                ],
            },
            {
                "stage_name": "Monomer Mix",
                "parameters": [
                    {"name": "1,3-Butadiene", "value": "75", "unit": "phr", "source": "patent"},
                    {"name": "Styrene", "value": "25", "unit": "phr", "source": "patent"},
                ],
            },
        ],
    }

    norm = _normalize_recipe_stages(r_dict, target_compound="Low Styrene SBR")

    assert "parameters" in norm
    assert len(norm["parameters"]) == 3
    param_names = [p["name"] for p in norm["parameters"]]
    assert "Water" in param_names
    assert "1,3-Butadiene" in param_names
    assert "Styrene" in param_names


def test_no_legacy_hardcoded_schema_fields():
    """Verify that LLMRecipeCandidate does not use old hardcoded fields like bd_acn_ratio."""
    fields = LLMRecipeCandidate.model_fields.keys()
    forbidden = [
        "bd_acn_ratio",
        "water",
        "emulsifier",
        "initiator",
        "chain_transfer_agent",
        "coagulant",
        "temperature",
        "conversion",
        "reaction_time",
    ]
    for f in forbidden:
        assert f not in fields, f"Forbidden hardcoded field '{f}' found on LLMRecipeCandidate"
