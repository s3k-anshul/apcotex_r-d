"""
tests/test_research_request_schema.py

Phase 1: optional attribute_constraint / polymerization_medium on
ResearchRunCreate — defaults, validation, and reachability into the
ResearchRun object that the orchestrator reads.
"""
import inspect
import uuid

from app.models.research_run import ResearchRun
from app.schemas.research import PolymerizationMedium, ResearchRunCreate
from app.services.pipeline.search_service import SearchService
from app.services.research_service import ResearchService


def test_create_request_without_new_fields_defaults():
    """Backward compatible: omitted fields get None / any."""
    body = ResearchRunCreate(compound_name="Low Acrylonitrile NBR")
    assert body.attribute_constraint is None
    assert body.polymerization_medium == PolymerizationMedium.ANY
    assert body.competitors == []
    assert body.jurisdictions == []


def test_create_request_with_both_new_fields():
    body = ResearchRunCreate(
        compound_name="Low Acrylonitrile NBR",
        attribute_constraint="acrylonitrile content 15-20 wt%",
        polymerization_medium="aqueous",
        jurisdictions=["US", "EP"],
    )
    assert body.attribute_constraint == "acrylonitrile content 15-20 wt%"
    assert body.polymerization_medium == PolymerizationMedium.AQUEOUS


def test_blank_attribute_constraint_normalizes_to_none():
    body = ResearchRunCreate(
        compound_name="NBR",
        attribute_constraint="   ",
    )
    assert body.attribute_constraint is None


def test_invalid_polymerization_medium_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ResearchRunCreate(
            compound_name="NBR",
            polymerization_medium="plasma",
        )


def test_fields_persist_onto_research_run_for_orchestrator():
    """
    Simulate create_run persistence: values on ResearchRunCreate must be
    readable from the ResearchRun instance the orchestrator loads.
    """
    data = ResearchRunCreate(
        compound_name="Low Styrene SBR",
        attribute_constraint="styrene content 15-25 wt%",
        polymerization_medium=PolymerizationMedium.EMULSION,
    )
    medium_value = data.polymerization_medium.value
    run = ResearchRun(
        compound_name=data.compound_name,
        competitors=data.competitors,
        mentioned_websites=data.mentioned_websites,
        publication_filter=data.publication_filter,
        selected_sources=data.selected_sources,
        jurisdictions=data.jurisdictions,
        attribute_constraint=data.attribute_constraint,
        polymerization_medium=medium_value,
        status="PENDING",
        cache_key="test",
        report_version=1,
        created_by=uuid.uuid4(),
    )
    assert run.attribute_constraint == "styrene content 15-25 wt%"
    assert run.polymerization_medium == "emulsion"

    # Orchestrator reads these via getattr before calling generate_strategy
    assert getattr(run, "attribute_constraint", None) == data.attribute_constraint
    assert (getattr(run, "polymerization_medium", None) or "any") == "emulsion"


def test_generate_strategy_accepts_new_kwargs():
    """Plumbing: SearchService.generate_strategy signature accepts the fields."""
    sig = inspect.signature(SearchService.generate_strategy)
    assert "attribute_constraint" in sig.parameters
    assert "polymerization_medium" in sig.parameters
    assert sig.parameters["polymerization_medium"].default == "any"


def test_cache_key_includes_new_constraints():
    base = ResearchService.generate_cache_key(
        "NBR", [], None, [], [], [], None, "any"
    )
    constrained = ResearchService.generate_cache_key(
        "NBR",
        [],
        None,
        [],
        [],
        [],
        attribute_constraint="acrylonitrile content 15-20 wt%",
        polymerization_medium="aqueous",
    )
    assert base != constrained
    # Defaults must be stable for unconstrained clients
    assert (
        ResearchService.generate_cache_key("NBR", [], None, [], [], [])
        == base
    )
