import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError
from app.schemas.recipe import (
    LLMOptimizationSet,
    LLMOptimizedRecipeCandidate,
    LLMOptimizedStage,
    LLMOptimizedParameter,
    LLMOptimizedChange,
    LLMProcessConditions,
    LLMReactionTime,
    LLMCatalystSystem,
    LLMActivatorSystem,
    LLMCoagulationSystem,
    LLMPredictedProperty,
)
from app.services.llm.schema_normalizer import normalize_gemini_schema
from app.services.llm.base import LLMInvalidRequestError


def _make_dummy_candidate(name: str = "Revision A - Test Candidate") -> LLMOptimizedRecipeCandidate:
    return LLMOptimizedRecipeCandidate(
        name=name,
        optimization_strategy="Targeted modifier adjustment",
        confidence_score=85,
        stages=[
            LLMOptimizedStage(
                stage_name="Reactor Charge",
                parameters=[
                    LLMOptimizedParameter(name="Water", value="100.0", unit="phr")
                ],
            )
        ],
        process_conditions=LLMProcessConditions(
            reaction_time=LLMReactionTime(value="5.5", unit="hours"),
            temperature_range="8-10 °C",
        ),
        catalyst_system=LLMCatalystSystem(
            applicable=True,
            primary_catalyst="Sodium formaldehyde sulfoxylate / pinane hydroperoxide",
            dosage="0.1 phr",
        ),
        activator_system=LLMActivatorSystem(
            applicable=True,
            activator_name="EDTA-iron complex",
            dosage="0.005 phr",
        ),
        coagulation_system=LLMCoagulationSystem(
            applicable=True,
            coagulant="NaCl",
            dosage="5.0 phr",
        ),
        changed_parameters=[
            LLMOptimizedChange(
                parameter="Carboxylic acid content",
                old_value="7.0 phr",
                new_value="8.5 phr",
                unit="phr",
                reason="Increase carboxylation to enhance hardness",
            )
        ],
        expected_outcome="Hardness increases to target range 70-75 Shore A.",
        expected_impact="Greater carboxyl crosslink density increases modulus and hardness.",
        predicted_properties=[
            LLMPredictedProperty(
                property="Hardness",
                predicted_value=72.0,
                unit="Shore A",
                status="MEETS_TARGET",
                reasoning="Higher methacrylic acid incorporation improves crosslink density",
            )
        ],
    )


class TestPhase2CTFGeminiSchema:
    def test_llm_optimization_set_schema_has_no_min_max_items(self):
        """Verify that LLMOptimizationSet JSON schema does not emit minItems or maxItems on optimized_recipes."""
        schema = LLMOptimizationSet.model_json_schema()
        recipes_prop = schema["properties"]["optimized_recipes"]
        assert "minItems" not in recipes_prop, "minItems must not be present on optimized_recipes array"
        assert "maxItems" not in recipes_prop, "maxItems must not be present on optimized_recipes array"

    def test_normalize_gemini_schema_strips_min_max_items_recursively(self):
        """Verify normalize_gemini_schema recursively removes minItems and maxItems from any schema structure."""
        test_schema = {
            "type": "object",
            "properties": {
                "items_list": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "sub_list": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string"},
                            }
                        },
                    },
                }
            },
        }
        normalized = normalize_gemini_schema(test_schema)
        assert "minItems" not in normalized["properties"]["items_list"]
        assert "maxItems" not in normalized["properties"]["items_list"]
        sub_list = normalized["properties"]["items_list"]["items"]["properties"]["sub_list"]
        assert "minItems" not in sub_list

    def test_llm_optimization_set_validator_enforces_exactly_three(self):
        """Pydantic field validator must strictly enforce len(optimized_recipes) == 3."""
        c1 = _make_dummy_candidate("Revision A")
        c2 = _make_dummy_candidate("Revision B")
        c3 = _make_dummy_candidate("Revision C")
        c4 = _make_dummy_candidate("Revision D")

        # 3 candidates -> OK
        opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])
        assert len(opt_set.optimized_recipes) == 3

        # 2 candidates -> ValueError
        with pytest.raises(ValidationError) as exc_info:
            LLMOptimizationSet(optimized_recipes=[c1, c2])
        assert "exactly 3" in str(exc_info.value).lower()

        # 4 candidates -> ValueError
        with pytest.raises(ValidationError) as exc_info:
            LLMOptimizationSet(optimized_recipes=[c1, c2, c3, c4])
        assert "exactly 3" in str(exc_info.value).lower()

    def test_candidate_full_chemistry_components(self):
        """Verify catalyst, activator, and coagulation systems serialize and validate properly."""
        cand = _make_dummy_candidate()
        assert cand.catalyst_system.primary_catalyst.startswith("Sodium formaldehyde")
        assert cand.activator_system.activator_name == "EDTA-iron complex"
        assert cand.coagulation_system.coagulant == "NaCl"
        assert len(cand.changed_parameters) == 1
        assert cand.changed_parameters[0].parameter == "Carboxylic acid content"
        assert len(cand.predicted_properties) == 1
        assert cand.predicted_properties[0].property == "Hardness"

    def test_normalized_llm_optimization_set_gemini_compatible(self):
        """Verify full normalized schema contains neither additionalProperties, minItems, nor maxItems."""
        raw_schema = LLMOptimizationSet.model_json_schema()
        norm_schema = normalize_gemini_schema(raw_schema)

        def _assert_no_unsupported_keys(node):
            if isinstance(node, dict):
                assert "additionalProperties" not in node
                assert "minItems" not in node
                assert "maxItems" not in node
                for v in node.values():
                    _assert_no_unsupported_keys(v)
            elif isinstance(node, list):
                for item in node:
                    _assert_no_unsupported_keys(item)

        _assert_no_unsupported_keys(norm_schema)

    @pytest.mark.asyncio
    async def test_llm_invalid_request_aborts_immediately_without_retry(self):
        """RecipeService.generate_optimized_recipes must not perform retry when encountering LLMInvalidRequestError."""
        from app.services.recipe_service import RecipeService

        mock_session = AsyncMock()
        mock_provider = AsyncMock()
        mock_provider.generate_structured.side_effect = LLMInvalidRequestError("400 INVALID_ARGUMENT")

        service = RecipeService(session=mock_session)

        import uuid
        from app.models.user import User, UserRole

        trial_id = uuid.uuid4()
        user_id = uuid.uuid4()
        current_user = MagicMock(spec=User)
        current_user.id = user_id
        current_user.role = UserRole.ADMIN

        trial = MagicMock()
        trial.id = trial_id
        trial.recipe_id = uuid.uuid4()
        trial.created_by = user_id
        trial.saved_recipe_id = None
        trial.selected_candidate_id = None
        trial.cycle_id = None
        trial.customer_feedback = "hardness is too low"
        trial.feedback_text = "hardness is too low"
        trial.target_values = {}
        trial.optimization_mode = "STRICT_TARGET"
        trial.target_properties = []
        trial.optimized_candidates = []
        trial.recipe_snapshot = {
            "name": "Base Recipe",
            "compound": "NBR",
            "stages": [{"stage_name": "Reactor Charge", "parameters": []}],
        }
        trial.measured_properties = []
        trial.trial_notes = "Customer trial notes"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = trial
        mock_session.execute.return_value = mock_result

        service.llm_client = mock_provider
        with pytest.raises(Exception):
            await service.generate_optimized_recipes(
                trial_id=trial_id,
                current_user=current_user,
                force_regenerate=True,
            )

        # The LLM provider should only be called ONCE (not retried)
        assert mock_provider.generate_structured.call_count == 1, (
            f"Expected 1 call, but got {mock_provider.generate_structured.call_count}. "
            "LLMInvalidRequestError should not be retried."
        )

    @pytest.mark.asyncio
    async def test_customer_feedback_reaches_system_prompt(self):
        """Customer trial feedback must be formatted into the LLM system prompt."""
        from app.services.recipe_service import RecipeService
        import uuid
        from app.models.user import User, UserRole

        mock_session = AsyncMock()
        mock_provider = AsyncMock()
        c1 = _make_dummy_candidate("Candidate 1")
        c2 = _make_dummy_candidate("Candidate 2")
        c3 = _make_dummy_candidate("Candidate 3")
        opt_set = LLMOptimizationSet(optimized_recipes=[c1, c2, c3])
        mock_provider.generate_structured.return_value = (opt_set, "{}", {"prompt_tokens": 100, "completion_tokens": 200})

        service = RecipeService(session=mock_session)
        service.llm_client = mock_provider

        trial_id = uuid.uuid4()
        user_id = uuid.uuid4()
        current_user = MagicMock(spec=User)
        current_user.id = user_id
        current_user.role = UserRole.ADMIN

        feedback_message = "Hardness is too low, please increase to 75 Shore A"
        trial = MagicMock()
        trial.id = trial_id
        trial.recipe_id = uuid.uuid4()
        trial.created_by = user_id
        trial.saved_recipe_id = None
        trial.selected_candidate_id = None
        trial.cycle_id = None
        trial.customer_feedback = feedback_message
        trial.feedback_text = feedback_message
        trial.target_values = {}
        trial.optimization_mode = "GENERAL"
        trial.target_properties = []
        trial.optimized_candidates = []
        trial.recipe_snapshot = {
            "name": "Base Recipe",
            "compound": "NBR",
            "stages": [{"stage_name": "Reactor Charge", "parameters": []}],
        }
        trial.measured_properties = []
        trial.trial_notes = "Standard production test notes"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = trial
        mock_session.execute.return_value = mock_result

        candidates = await service.generate_optimized_recipes(
            trial_id=trial_id,
            current_user=current_user,
            force_regenerate=True,
        )

        assert len(candidates) == 3
        # Verify LLM was called with customer feedback in prompt
        call_kwargs = mock_provider.generate_structured.call_args.kwargs
        system_prompt = call_kwargs.get("system_prompt", "")
        assert feedback_message in system_prompt, "Customer feedback must be present in the prompt"

