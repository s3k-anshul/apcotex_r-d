"""
app/schemas/research.py

Pydantic v2 schemas for the Research Runs API.

Schema hierarchy:
  ResearchRunCreate      → POST body
  ResearchRunResponse    → full detail (single-run GET)
  ResearchRunSummary     → lightweight item inside list responses
  ResearchRunList        → paginated list envelope
  ResearchRunFilters     → query-param filter object
"""
import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.models.research_run import RunStatus


class PolymerizationMedium(str, Enum):
    """Optional bias for query expansion / selection (per-run)."""

    AQUEOUS = "aqueous"
    EMULSION = "emulsion"
    SOLVENT = "solvent"
    ANY = "any"


# ── Create ─────────────────────────────────────────────────────────────────────

class ResearchRunCreate(BaseModel):
    """Payload for POST /api/v1/research-runs."""

    compound_name: str = Field(
        ..., min_length=1, max_length=255, description="Name of the target compound."
    )
    competitors: list[str] = Field(
        default_factory=list,
        description="List of competitor company names to include in the search.",
    )
    mentioned_websites: list[str] = Field(
        default_factory=list,
        description="Specific websites to restrict or prioritise.",
    )
    publication_filter: dict | None = Field(
        default=None,
        description=(
            'Optional filter dict, e.g. {"year_from": 2010, "year_to": 2024, '
            '"patent_offices": ["US","EP","WO"]}'
        ),
    )
    selected_sources: list[str] = Field(
        default_factory=list,
        description='Data sources to query, e.g. ["google_patents", "serper_web"].',
    )
    jurisdictions: list[str] = Field(
        default_factory=list,
        description='Patent jurisdictions to search, e.g. ["US", "EP", "IN"].',
    )
    attribute_constraint: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Optional free-text attribute/range constraint supplied by the user for this run. "
            "Omitted/None = no extra constraint."
        ),
    )
    polymerization_medium: PolymerizationMedium = Field(
        default=PolymerizationMedium.ANY,
        description=(
            'Optional polymerization-medium bias: "aqueous", "emulsion", '
            '"solvent", or "any" (default — no bias).'
        ),
    )

    @field_validator("competitors", "mentioned_websites", "selected_sources", "jurisdictions", mode="before")
    @classmethod
    def strip_empty_strings(cls, v: list) -> list:
        return [item for item in v if isinstance(item, str) and item.strip()]

    @field_validator("attribute_constraint", mode="before")
    @classmethod
    def blank_attribute_constraint_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v


# ── Response ────────────────────────────────────────────────────────────────────

class ResearchRunResponse(BaseModel):
    """Full detail representation of a ResearchRun (single-item GET)."""

    id: uuid.UUID
    compound_name: str
    competitors: list[str]
    mentioned_websites: list[str]
    publication_filter: dict | None
    selected_sources: list[str]
    jurisdictions: list[str]
    attribute_constraint: str | None = None
    polymerization_medium: str = PolymerizationMedium.ANY.value
    status: RunStatus
    cache_key: str | None
    report_version: int
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    
    # Heartbeat / runtime tracking (injected at endpoint)
    stage: str | None = None
    progress: str | None = None
    error: str | None = None

    model_config = {"from_attributes": True}


# ── Summary ─────────────────────────────────────────────────────────────────────

class ResearchRunSummary(BaseModel):
    """
    Lightweight representation used inside paginated list responses.
    Omits large JSON fields (competitors, websites, sources).
    """

    id: uuid.UUID
    compound_name: str
    jurisdictions: list[str]
    status: RunStatus
    cache_key: str | None
    report_version: int
    created_by: uuid.UUID
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── List ────────────────────────────────────────────────────────────────────────

class ResearchRunList(BaseModel):
    """Paginated list envelope returned by GET /api/v1/research-runs."""

    items: list[ResearchRunSummary]
    total: int
    page: int
    page_size: int
    pages: int


# ── Filters ─────────────────────────────────────────────────────────────────────

class ResearchRunFilters(BaseModel):
    """
    Query parameters for GET /api/v1/research-runs.
    Parsed via Depends(parse_filters) in the router.
    """

    page: int = Field(default=1, ge=1, description="1-based page number.")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page.")
    compound: str | None = Field(
        default=None, description="Case-insensitive substring match on compound_name."
    )
    status: RunStatus | None = Field(default=None, description="Filter by run status.")
    date_from: datetime | None = Field(
        default=None, description="Inclusive lower bound on created_at."
    )
    date_to: datetime | None = Field(
        default=None, description="Inclusive upper bound on created_at."
    )
    user_id: uuid.UUID | None = Field(
        default=None,
        description="Admin-only: filter runs belonging to a specific user.",
    )
