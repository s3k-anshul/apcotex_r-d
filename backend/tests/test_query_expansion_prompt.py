"""
tests/test_query_expansion_prompt.py

Phase 2: optional attribute_constraint / polymerization_medium must
appear in the prompt sent to the LLM when set, and the unconstrained
prompt must stay identical to the historical base format.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.pipeline.schemas import LLMCompoundSearchProfile
from app.services.pipeline.search_service import SearchService
from app.services.prompts.patent_prompts import (
    PATENT_QUERY_EXPANSION_PROMPT,
    build_query_expansion_constraint_suffix,
    build_query_expansion_prompt,
)
from tests.fixtures import load_fixture


def _base_kwargs() -> dict:
    return {
        "compound_name": "Low Acrylonitrile NBR",
        "competitors": "None",
        "websites": "None",
        "jurisdictions": "US, EP",
        "publication_filter": "None",
    }


def _mock_profile() -> LLMCompoundSearchProfile:
    data = load_fixture("llm_query_expansion_low_acn_nbr")
    return LLMCompoundSearchProfile.model_validate(data)


def test_unconstrained_prompt_identical_to_historical_base():
    """Regression: omitted / any must not change the prompt at all."""
    kwargs = _base_kwargs()
    historical = PATENT_QUERY_EXPANSION_PROMPT.format(**kwargs)
    via_builder = build_query_expansion_prompt(**kwargs)
    via_builder_any = build_query_expansion_prompt(
        **kwargs, attribute_constraint=None, polymerization_medium="any"
    )
    via_builder_blank = build_query_expansion_prompt(
        **kwargs, attribute_constraint="  ", polymerization_medium="ANY"
    )
    assert via_builder == historical
    assert via_builder_any == historical
    assert via_builder_blank == historical
    assert build_query_expansion_constraint_suffix(None, "any") == ""


def test_attribute_constraint_appended_to_prompt():
    kwargs = _base_kwargs()
    constraint = "acrylonitrile content 15-20 wt%"
    prompt = build_query_expansion_prompt(
        **kwargs, attribute_constraint=constraint, polymerization_medium="any"
    )
    historical = PATENT_QUERY_EXPANSION_PROMPT.format(**kwargs)
    assert prompt.startswith(historical)
    assert prompt != historical
    assert "OPTIONAL USER ATTRIBUTE CONSTRAINT (ACTIVE)" in prompt
    assert constraint in prompt
    assert "at least 2–3" in prompt or "at least 2-3" in prompt
    assert "OPTIONAL POLYMERIZATION MEDIUM CONSTRAINT" not in prompt


def test_aqueous_medium_bias_appended_to_prompt():
    kwargs = _base_kwargs()
    prompt = build_query_expansion_prompt(
        **kwargs, polymerization_medium="aqueous"
    )
    assert "OPTIONAL POLYMERIZATION MEDIUM CONSTRAINT (ACTIVE): aqueous / emulsion" in prompt
    assert "emulsifier" in prompt
    assert "n-butyllithium" in prompt
    assert "DEPRIORITIZE" in prompt


def test_emulsion_medium_uses_same_aqueous_block():
    prompt = build_query_expansion_prompt(
        **_base_kwargs(), polymerization_medium="emulsion"
    )
    assert "aqueous / emulsion" in prompt


def test_solvent_medium_bias_appended_to_prompt():
    prompt = build_query_expansion_prompt(
        **_base_kwargs(), polymerization_medium="solvent"
    )
    assert "OPTIONAL POLYMERIZATION MEDIUM CONSTRAINT (ACTIVE): solvent" in prompt
    assert "solution polymerization" in prompt
    assert "DEPRIORITIZE" in prompt
    assert "latex" in prompt  # deprioritized aqueous term mentioned


def test_both_constraints_appended_together():
    constraint = "styrene content 15-25 wt%"
    prompt = build_query_expansion_prompt(
        **_base_kwargs(),
        attribute_constraint=constraint,
        polymerization_medium="aqueous",
    )
    assert constraint in prompt
    assert "OPTIONAL USER ATTRIBUTE CONSTRAINT (ACTIVE)" in prompt
    assert "OPTIONAL POLYMERIZATION MEDIUM CONSTRAINT (ACTIVE): aqueous / emulsion" in prompt


@pytest.mark.asyncio
async def test_generate_strategy_sends_constraint_text_to_llm():
    """Mocked LLM: capture the prompt actually passed to generate_structured."""
    captured: dict = {}
    profile = _mock_profile()

    async def _fake_generate_structured(*, prompt, **kwargs):
        captured.setdefault("prompt", prompt)
        return profile, "mock", {}

    service = SearchService()
    with patch(
        "app.services.pipeline.search_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake_generate_structured),
    ):
        await service.generate_strategy(
            compound_name="Low Acrylonitrile NBR",
            jurisdictions=["US"],
            attribute_constraint="acrylonitrile content 15-20 wt%",
            polymerization_medium="aqueous",
        )

    assert "prompt" in captured
    assert "OPTIONAL USER ATTRIBUTE CONSTRAINT (ACTIVE)" in captured["prompt"]
    assert "acrylonitrile content 15-20 wt%" in captured["prompt"]
    assert "OPTIONAL POLYMERIZATION MEDIUM CONSTRAINT (ACTIVE): aqueous / emulsion" in captured["prompt"]


@pytest.mark.asyncio
async def test_generate_strategy_unconstrained_prompt_matches_historical():
    captured: dict = {}
    profile = _mock_profile()

    async def _fake_generate_structured(*, prompt, **kwargs):
        captured.setdefault("prompt", prompt)
        return profile, "mock", {}

    expected = PATENT_QUERY_EXPANSION_PROMPT.format(
        compound_name="Low Acrylonitrile NBR",
        competitors="None",
        websites="None",
        jurisdictions="US",
        publication_filter="None",
    )

    service = SearchService()
    with patch(
        "app.services.pipeline.search_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake_generate_structured),
    ):
        await service.generate_strategy(
            compound_name="Low Acrylonitrile NBR",
            jurisdictions=["US"],
        )

    assert captured["prompt"] == expected
