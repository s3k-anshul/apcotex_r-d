"""
tests/test_dynamic_target_profile.py

Regression suite for free-form compound interpretation:
profile completeness, numeric/range recovery, deterministic query repair,
and zero-query Serper protection.

Compound-agnostic — no NBR/SBR/HNBR special-case branches under test.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.pipeline.schemas import (
    GeneratedQuery,
    LLMCompoundSearchProfile,
    TargetNumericConstraint,
)
from app.services.pipeline.search_service import (
    SearchPreparationError,
    SearchService,
    assess_profile_completeness,
    build_deterministic_queries,
    extract_base_material_candidates,
    extract_modifications_and_attributes,
    extract_numeric_constraints,
    merge_recovered_into_profile,
    validate_generated_query,
)
from tests.fixtures import load_fixture


def _gq(query: str, intent: str = "discovery", scope: str = "full_text") -> GeneratedQuery:
    return GeneratedQuery(
        query=query,
        required_concepts=["x"],
        alternative_concepts=[],
        intent=intent,
        scope=scope,
    )


def _incomplete_profile(original: str, **kwargs) -> LLMCompoundSearchProfile:
    data = {"original_input": original, "synthesis_intent": True}
    data.update(kwargs)
    return LLMCompoundSearchProfile.model_validate(data)


# ---------------------------------------------------------------------------
# TEST 1 — Low Acrylonitrile NBR
# ---------------------------------------------------------------------------

def test_low_acrylonitrile_nbr_profile_and_queries():
    text = "Low Acrylonitrile NBR"
    bases = extract_base_material_candidates(text)
    mods, attrs, _ = extract_modifications_and_attributes(text)
    assert any("nbr" == b.lower() for b in bases)
    assert any("low" in a.lower() and "acrylonitrile" in a.lower() for a in attrs)
    assert not extract_numeric_constraints(text)

    profile = merge_recovered_into_profile(_incomplete_profile(text), text)
    assert profile.base_material
    assert any("nbr" == b.lower() for b in profile.base_material)
    assert any("low" in a.lower() for a in profile.target_attributes)

    queries = build_deterministic_queries(profile)
    assert len(queries) >= 15
    exprs = [q.query.lower() for q in queries]
    assert any("polymerization" in e or "polymerisation" in e for e in exprs)
    assert any("low" not in e for e in exprs)
    assert any("low" in e or "acrylonitrile" in e for e in exprs)


# ---------------------------------------------------------------------------
# TEST 2 — Low Styrene SBR (no NBR branch)
# ---------------------------------------------------------------------------

def test_low_styrene_sbr_dynamic_detection():
    text = "Low Styrene SBR"
    bases = extract_base_material_candidates(text)
    mods, attrs, _ = extract_modifications_and_attributes(text)
    assert any("sbr" == b.lower() for b in bases)
    assert any("styrene" in a.lower() for a in attrs)
    assert not any("nbr" == b.lower() for b in bases)

    profile = merge_recovered_into_profile(_incomplete_profile(text), text)
    queries = build_deterministic_queries(profile)
    assert len(queries) >= 10
    blob = " ".join(q.query.lower() for q in queries)
    assert "sbr" in blob


# ---------------------------------------------------------------------------
# TEST 3 — 7% carboxylated NBR (regression for production failure)
# ---------------------------------------------------------------------------

def test_seven_percent_carboxylated_nbr_complete_profile():
    text = "7% carboxylated NBR"
    numerics = extract_numeric_constraints(text)
    assert numerics
    assert numerics[0].value == 7.0
    assert numerics[0].unit in ("%", "wt%")
    assert numerics[0].operator == "="

    mods, _, _ = extract_modifications_and_attributes(text)
    assert any("carboxyl" in m for m in mods)

    bases = extract_base_material_candidates(text)
    assert any("nbr" == b.lower() for b in bases)
    assert not any("7%" in b for b in bases)

    profile = merge_recovered_into_profile(
        _incomplete_profile(text, target_modifications=["carboxylated"]),
        text,
    )
    assert profile.base_material
    assert profile.numeric_constraints
    assert profile.target_modifications

    queries = build_deterministic_queries(profile)
    profile.search_queries = queries
    complete, reasons = assess_profile_completeness(profile, text)
    assert complete, reasons
    assert len(queries) > 0


@pytest.mark.asyncio
async def test_seven_percent_carboxylated_nbr_never_sends_zero_queries_to_serper():
    incomplete = _incomplete_profile(
        "7% carboxylated NBR",
        target_modifications=["carboxylated", "carboxylic acid functionalized"],
    )
    service = SearchService()
    serper_calls = []

    async def _fake_llm(*, prompt, **kwargs):
        return incomplete, "mock", {}

    async def _fake_search(queries):
        serper_calls.append(len(queries))
        return [{"patent_number": "US1", "title": "t", "snippet": "", "url": ""}]

    with patch(
        "app.services.pipeline.search_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake_llm),
    ):
        profile = await service.generate_strategy("7% carboxylated NBR")

    assert profile.base_material
    assert any("nbr" == b.lower() for b in profile.base_material)
    assert profile.numeric_constraints
    assert profile.numeric_constraints[0].value == 7.0
    assert len(profile.search_queries) > 0

    with patch.object(service, "search_patents", new=AsyncMock(side_effect=_fake_search)):
        await service.search_patents(profile.search_queries)
    assert serper_calls and serper_calls[0] > 0


# ---------------------------------------------------------------------------
# TEST 4 — NBR with 18–22 wt% acrylonitrile
# ---------------------------------------------------------------------------

def test_nbr_acrylonitrile_range_preserved():
    text = "NBR with 18–22 wt% acrylonitrile"
    numerics = extract_numeric_constraints(text)
    assert len(numerics) >= 1
    c = numerics[0]
    assert c.lower_bound == 18.0
    assert c.upper_bound == 22.0
    assert "wt%" in c.unit.replace(" ", "")
    assert "acrylonitrile" in c.attribute

    bases = extract_base_material_candidates(text)
    assert any("nbr" == b.lower() for b in bases)

    profile = merge_recovered_into_profile(_incomplete_profile(text), text)
    queries = build_deterministic_queries(profile)
    assert len(queries) >= 15
    blob = " ".join(q.query for q in queries)
    assert "18" in blob or "22" in blob or "acrylonitrile" in blob.lower()


# ---------------------------------------------------------------------------
# TEST 5 — SBR containing 20–25 wt% styrene
# ---------------------------------------------------------------------------

def test_sbr_styrene_range_dynamic():
    text = "SBR containing 20–25 wt% styrene"
    c = extract_numeric_constraints(text)[0]
    assert c.lower_bound == 20.0
    assert c.upper_bound == 25.0
    assert "wt%" in c.unit.replace(" ", "")
    assert "styrene" in c.attribute
    assert any("sbr" == b.lower() for b in extract_base_material_candidates(text))
    profile = merge_recovered_into_profile(_incomplete_profile(text), text)
    assert len(build_deterministic_queries(profile)) > 0


# ---------------------------------------------------------------------------
# TEST 6 — HNBR with 80–90% hydrogenation (HNBR is TARGET, not excluded)
# ---------------------------------------------------------------------------

def test_hnbr_hydrogenation_range_not_excluded():
    text = "HNBR with 80–90% hydrogenation"
    bases = extract_base_material_candidates(text)
    assert any("hnbr" == b.lower() for b in bases)
    c = extract_numeric_constraints(text)[0]
    assert c.lower_bound == 80.0
    assert c.upper_bound == 90.0
    assert "hydrogen" in c.attribute

    profile = merge_recovered_into_profile(_incomplete_profile(text), text)
    assert not any("hnbr" == e.lower() for e in (profile.excluded_variants or []))
    assert not any("hnbr" == e.lower() for e in (profile.identity_exclusions or []))
    queries = build_deterministic_queries(profile)
    assert any("hnbr" in q.query.lower() for q in queries)


# ---------------------------------------------------------------------------
# TEST 7 — Carboxylated NBR with 2% carboxyl content
# ---------------------------------------------------------------------------

def test_carboxylated_nbr_with_carboxyl_content():
    text = "Carboxylated NBR with 2% carboxyl content"
    mods, _, _ = extract_modifications_and_attributes(text)
    assert any("carboxyl" in m for m in mods)
    assert any("nbr" == b.lower() for b in extract_base_material_candidates(text))
    c = extract_numeric_constraints(text)[0]
    assert c.value == 2.0
    assert "carboxyl" in c.attribute
    profile = merge_recovered_into_profile(_incomplete_profile(text), text)
    assert len(build_deterministic_queries(profile)) > 0


# ---------------------------------------------------------------------------
# TEST 8 — less than 20 wt% acrylonitrile NBR
# ---------------------------------------------------------------------------

def test_less_than_comparison_operator():
    text = "less than 20 wt% acrylonitrile NBR"
    c = extract_numeric_constraints(text)[0]
    assert c.operator == "<"
    assert c.value == 20.0
    assert "wt%" in c.unit.replace(" ", "")
    assert "acrylonitrile" in c.attribute
    assert any("nbr" == b.lower() for b in extract_base_material_candidates(text))


# ---------------------------------------------------------------------------
# TEST 9 — at least 80% hydrogenated NBR
# ---------------------------------------------------------------------------

def test_at_least_hydrogenated_nbr():
    text = "at least 80% hydrogenated NBR"
    c = extract_numeric_constraints(text)[0]
    assert c.operator == ">="
    assert c.value == 80.0
    mods, _, transforms = extract_modifications_and_attributes(text)
    assert any("hydrogen" in m for m in mods) or any("hydrogen" in t for t in transforms)
    profile = merge_recovered_into_profile(_incomplete_profile(text), text)
    assert len(build_deterministic_queries(profile)) > 0


# ---------------------------------------------------------------------------
# TEST 10 — Arbitrary non-NBR/SBR chemical
# ---------------------------------------------------------------------------

def test_arbitrary_non_elastomer_input():
    text = "Zephyr Elastomer Z with 12-15 wt% vinyl content"
    bases = extract_base_material_candidates(text)
    assert bases
    assert not any(b.lower() in {"nbr", "sbr", "hnbr"} for b in bases)
    c = extract_numeric_constraints(text)[0]
    assert c.lower_bound == 12.0
    assert c.upper_bound == 15.0
    assert "vinyl" in c.attribute
    profile = merge_recovered_into_profile(_incomplete_profile(text), text)
    queries = build_deterministic_queries(profile)
    assert len(queries) > 0
    blob = " ".join(q.query.lower() for q in queries)
    assert "zephyr" in blob or "elastomer" in blob


# ---------------------------------------------------------------------------
# TEST 11 — Malformed / incomplete LLM response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_incomplete_llm_response_triggers_recovery_no_zero_serper():
    incomplete = LLMCompoundSearchProfile(
        original_input="7% carboxylated NBR",
        synthesis_intent=True,
    )
    is_complete, reasons = assess_profile_completeness(
        incomplete, "7% carboxylated NBR"
    )
    assert not is_complete
    assert any("base_material" in r for r in reasons)

    service = SearchService()

    async def _fake_llm(*, prompt, **kwargs):
        return incomplete, "mock", {}

    with patch(
        "app.services.pipeline.search_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake_llm),
    ):
        profile = await service.generate_strategy("7% carboxylated NBR")

    assert profile.base_material
    assert len(profile.search_queries) > 0

    with pytest.raises(SearchPreparationError) as exc:
        await service.search_patents([])
    assert "SEARCH_PREPARATION_FAILURE" in str(exc.value)


# ---------------------------------------------------------------------------
# TEST 12 — LLM returns modifications but no base_material
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_mods_without_base_recovers_from_original_input():
    incomplete = _incomplete_profile(
        "Carboxylated NBR with 2% carboxyl content",
        target_modifications=["carboxylated"],
    )
    service = SearchService()

    async def _fake_llm(*, prompt, **kwargs):
        return incomplete, "mock", {}

    with patch(
        "app.services.pipeline.search_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake_llm),
    ):
        profile = await service.generate_strategy(
            "Carboxylated NBR with 2% carboxyl content"
        )

    assert any("nbr" == b.lower() for b in profile.base_material)
    assert len(profile.search_queries) > 0


# ---------------------------------------------------------------------------
# TEST 13 — LLM returns zero search queries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_zero_search_queries_uses_deterministic_fallback():
    profile_in = LLMCompoundSearchProfile(
        original_input="Low Styrene SBR",
        synthesis_intent=True,
        base_material=["SBR", "styrene butadiene rubber"],
        target_attributes=["low styrene"],
        search_queries=[],
    )
    service = SearchService()

    async def _fake_llm(*, prompt, **kwargs):
        return profile_in, "mock", {}

    with patch(
        "app.services.pipeline.search_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake_llm),
    ):
        profile = await service.generate_strategy("Low Styrene SBR")

    assert len(profile.search_queries) > 0
    with pytest.raises(SearchPreparationError):
        await SearchService().search_patents([])


# ---------------------------------------------------------------------------
# TEST 14 — Publication date range + scientific numeric range coexist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publication_filter_and_scientific_range_preserved_independently():
    text = "NBR with 18–22 wt% acrylonitrile"
    pub_filter = {"date_range": "custom", "year_from": 2020, "year_to": 2025}
    incomplete = _incomplete_profile(text)
    service = SearchService()
    captured = {}

    async def _fake_llm(*, prompt, **kwargs):
        captured["prompt"] = prompt
        return incomplete, "mock", {}

    with patch(
        "app.services.pipeline.search_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake_llm),
    ):
        profile = await service.generate_strategy(
            compound_name=text,
            publication_filter=pub_filter,
        )

    assert profile.numeric_constraints
    assert profile.numeric_constraints[0].lower_bound == 18.0
    assert profile.numeric_constraints[0].upper_bound == 22.0
    assert (
        "2020" in captured["prompt"]
        or "year_from" in captured["prompt"]
        or str(pub_filter) in captured["prompt"]
    )
    assert not any(
        c.attribute and "year" in c.attribute.lower()
        for c in profile.numeric_constraints
    )


# ---------------------------------------------------------------------------
# TEST 15 — Existing fixture still parses (regression)
# ---------------------------------------------------------------------------

def test_existing_query_expansion_fixture_still_valid():
    data = load_fixture("llm_query_expansion_low_acn_nbr")
    profile = LLMCompoundSearchProfile.model_validate(data)
    assert len(profile.search_queries) == 15
    discovery = _gq(
        '(NBR OR "nitrile rubber") AND (polymerization OR polymerisation)',
        intent="base polymerization discovery",
    )
    ok, reason = validate_generated_query(discovery, profile)
    assert ok, reason
    bad = _gq("temperature emulsifier conversion")
    ok2, reason2 = validate_generated_query(bad, profile)
    assert not ok2


@pytest.mark.asyncio
async def test_generate_strategy_with_complete_fixture_keeps_queries():
    data = load_fixture("llm_query_expansion_low_acn_nbr")
    fixture_profile = LLMCompoundSearchProfile.model_validate(data)
    service = SearchService()

    async def _fake_llm(*, prompt, **kwargs):
        return fixture_profile.model_copy(deep=True), "mock", {}

    with patch(
        "app.services.pipeline.search_service.llm_client.generate_structured",
        new=AsyncMock(side_effect=_fake_llm),
    ):
        profile = await service.generate_strategy("Low Acrylonitrile NBR")

    assert len(profile.search_queries) >= 10
    assert profile.base_material


def test_numeric_constraint_schema_roundtrip():
    c = TargetNumericConstraint(
        attribute="acrylonitrile",
        lower_bound=18,
        upper_bound=22,
        unit="wt%",
        operator="range",
        raw_span="18-22 wt%",
    )
    profile = LLMCompoundSearchProfile(
        original_input="x",
        numeric_constraints=[c],
        base_material=["NBR"],
        search_queries=[_gq("NBR AND polymerization")],
    )
    dumped = profile.model_dump()
    again = LLMCompoundSearchProfile.model_validate(dumped)
    assert again.numeric_constraints[0].lower_bound == 18.0
