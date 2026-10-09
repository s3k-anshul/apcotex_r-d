"""
app/schemas/recipe.py

Pydantic schemas for the Recipe Simulator workflow, including LLM structured output schemas.
"""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import uuid


# ---------------------------------------------------------------------------
# Core Request & Response Schemas
# ---------------------------------------------------------------------------

class RecipePropertyDef(BaseModel):
    id: str
    feature: str
    unit: str
    min: Optional[str] = None
    max: Optional[str] = None
    target: Optional[str] = None
    range: Optional[str] = None
    value: Optional[str] = None
    tolerance: Optional[float] = None
    constraint_type: Optional[str] = None
    category: Optional[str] = None
    dataType: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class CompetitorData(BaseModel):
    name: str
    values: dict[str, str]


class RecipeCycleCreate(BaseModel):
    # research_run_id is optional: user may arrive via SelectPatentReportModal
    # without an active research session.
    research_run_id: Optional[uuid.UUID] = None
    patent_report_id: Optional[uuid.UUID] = None
    report_metadata_id: Optional[uuid.UUID] = None
    # target_product overrides compound_name derived from the research run.
    target_product: Optional[str] = None
    target_properties: list[RecipePropertyDef] = Field(default_factory=list)
    competitor_data: list[CompetitorData] = Field(default_factory=list)
    process_type: Optional[str] = None  # "Batch" | "Continuous" | "No Preference"
    temperature_range: Optional[dict[str, Any] | str] = None
    model_config = ConfigDict(extra="allow")


class RecipeCycleUpdate(BaseModel):
    target_properties: Optional[list[RecipePropertyDef]] = None
    competitor_data: Optional[list[CompetitorData]] = None
    process_type: Optional[str] = None
    temperature_range: Optional[dict[str, Any] | str] = None
    model_config = ConfigDict(extra="allow")


class RecipeCandidateResponse(BaseModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    rank: int
    name: str
    display_name: str = ""
    recipe_data: dict[str, Any]
    patent_references: list[str]
    evidence_coverage_score: int
    confidence_score: Optional[int] = None
    target_fit_score: Optional[int] = None
    targets_met: Optional[int] = None
    targets_total: Optional[int] = None
    target_analysis: Optional[dict[str, Any]] = None
    confidence_analysis: Optional[dict[str, Any]] = None
    predicted_properties: list[dict[str, Any]] = Field(default_factory=list)
    is_selected: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def populate_target_and_confidence(self) -> "RecipeCandidateResponse":
        if not self.display_name:
            disp = self.recipe_data.get("display_name") if isinstance(self.recipe_data, dict) else None
            self.display_name = str(disp or f"Recipe {self.rank}")
        if isinstance(self.recipe_data, dict):
            if not self.predicted_properties:
                self.predicted_properties = list(self.recipe_data.get("predicted_properties") or [])
            if self.target_analysis is None:
                self.target_analysis = self.recipe_data.get("target_analysis")
            if self.confidence_analysis is None:
                self.confidence_analysis = self.recipe_data.get("confidence_analysis")
            if self.target_fit_score is None and self.target_analysis:
                self.target_fit_score = self.target_analysis.get("target_fit_score")
            if self.targets_met is None and self.target_analysis:
                self.targets_met = self.target_analysis.get("targets_met")
            if self.targets_total is None and self.target_analysis:
                self.targets_total = self.target_analysis.get("targets_total")
            if self.confidence_score is None:
                cs = self.recipe_data.get("confidence_score")
                if cs is None and self.confidence_analysis:
                    cs = self.confidence_analysis.get("score")
                if cs is not None:
                    try:
                        self.confidence_score = int(cs)
                    except (ValueError, TypeError):
                        pass
        return self


class RecipeCycleResponse(BaseModel):
    id: uuid.UUID
    research_run_id: Optional[uuid.UUID] = None
    report_metadata_id: Optional[uuid.UUID] = None
    compound_name: str
    status: str
    target_properties: list[dict[str, Any]]
    competitor_data: list[dict[str, Any]]
    process_type: Optional[str] = None
    temperature_range: Optional[dict[str, Any] | str] = None
    selected_candidate_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def populate_user_constraints(cls, data: Any) -> Any:
        if hasattr(data, "patent_context_summary") and isinstance(data.patent_context_summary, dict):
            u_c = data.patent_context_summary.get("user_constraints") or {}
            if hasattr(data, "__dict__"):
                # Ensure fields are set if not explicitly present on model
                if not getattr(data, "process_type", None) and u_c.get("process_type"):
                    setattr(data, "process_type", u_c.get("process_type"))
                if not getattr(data, "temperature_range", None) and u_c.get("temperature_range"):
                    setattr(data, "temperature_range", u_c.get("temperature_range"))
        elif isinstance(data, dict):
            pcs = data.get("patent_context_summary") or {}
            if isinstance(pcs, dict):
                u_c = pcs.get("user_constraints") or {}
                if not data.get("process_type") and u_c.get("process_type"):
                    data["process_type"] = u_c.get("process_type")
                if not data.get("temperature_range") and u_c.get("temperature_range"):
                    data["temperature_range"] = u_c.get("temperature_range")
        return data


class RecipeCycleDetailResponse(RecipeCycleResponse):
    candidates: list[RecipeCandidateResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class CustomerTrialCreate(BaseModel):
    selected_candidate_id: Optional[uuid.UUID] = None
    saved_recipe_id: Optional[uuid.UUID] = None
    feedback_text: Optional[str] = None
    actual_values: dict[str, Any] = Field(default_factory=dict)
    target_values: dict[str, Any] = Field(default_factory=dict)
    target_properties: Optional[list[dict[str, Any]]] = None
    competitor_properties: Optional[list[dict[str, Any]]] = None
    target_compound: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class CustomerTrialUpdate(BaseModel):
    feedback_text: Optional[str] = None
    actual_values: Optional[dict[str, Any]] = None
    target_values: Optional[dict[str, Any]] = None
    target_properties: Optional[list[dict[str, Any]]] = None
    competitor_properties: Optional[list[dict[str, Any]]] = None
    target_compound: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class OptimizedCandidateUpdate(BaseModel):
    recipe_data: dict[str, Any]
    name: Optional[str] = None


class OptimizedRecipeCandidateResponse(BaseModel):
    id: uuid.UUID
    trial_id: uuid.UUID
    revision_label: str
    name: str
    recipe_data: dict[str, Any]
    changed_parameters: list[dict[str, Any]]
    predicted_impacts: list[dict[str, Any]]
    confidence_score: Optional[int] = None
    target_fit_score: Optional[int] = None
    targets_met: Optional[int] = None
    targets_total: Optional[int] = None
    target_analysis: Optional[dict[str, Any]] = None
    confidence_analysis: Optional[dict[str, Any]] = None
    optimization_strategy: Optional[str] = None
    expected_outcome: Optional[str] = None
    expected_impact: Optional[str] = None
    tradeoffs: Optional[str] = None
    is_selected: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def populate_optimization_metadata(self) -> "OptimizedRecipeCandidateResponse":
        if isinstance(self.recipe_data, dict):
            if self.target_analysis is None:
                self.target_analysis = self.recipe_data.get("target_analysis")
            if self.confidence_analysis is None:
                self.confidence_analysis = self.recipe_data.get("confidence_analysis")
            if self.target_fit_score is None and self.target_analysis:
                self.target_fit_score = self.target_analysis.get("target_fit_score")
            if self.targets_met is None and self.target_analysis:
                self.targets_met = self.target_analysis.get("targets_met")
            if self.targets_total is None and self.target_analysis:
                self.targets_total = self.target_analysis.get("targets_total")
            if self.confidence_score is None:
                cs = self.recipe_data.get("confidence_score")
                if cs is not None:
                    try:
                        self.confidence_score = int(cs)
                    except (ValueError, TypeError):
                        pass
            if not self.optimization_strategy:
                self.optimization_strategy = self.recipe_data.get("optimization_strategy")
            if not self.expected_outcome:
                self.expected_outcome = self.recipe_data.get("expected_outcome")
            if not self.expected_impact:
                self.expected_impact = self.recipe_data.get("expected_impact")
            if not self.tradeoffs:
                self.tradeoffs = self.recipe_data.get("tradeoffs")
        return self


class CustomerTrialResponse(BaseModel):
    id: uuid.UUID
    cycle_id: Optional[uuid.UUID] = None
    selected_candidate_id: Optional[uuid.UUID] = None
    saved_recipe_id: Optional[uuid.UUID] = None
    recipe_snapshot: Optional[dict[str, Any]] = None
    status: str
    feedback_text: Optional[str] = None
    actual_values: dict[str, Any] = Field(default_factory=dict)
    target_values: dict[str, Any] = Field(default_factory=dict)
    selected_optimized_id: Optional[uuid.UUID] = None
    optimized_candidates: list[OptimizedRecipeCandidateResponse] = Field(default_factory=list)
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


def _as_str_dict(value: dict | None) -> dict[str, str]:
    if not value:
        return {}
    return {str(k): "" if v is None else str(v) for k, v in value.items()}


def to_customer_trial_response(trial: Any) -> CustomerTrialResponse:
    """Serialize a trial including optimized_candidates safely for AsyncSession."""
    status = trial.status.value if hasattr(trial.status, "value") else str(trial.status)
    opts = []

    # Safe relationship access that never triggers implicit lazy I/O in AsyncSession
    raw_candidates = []
    from sqlalchemy.inspection import inspect as sa_inspect
    insp = sa_inspect(trial, raiseerr=False)
    if insp is not None:
        if "optimized_candidates" in insp.dict:
            raw_candidates = insp.dict["optimized_candidates"]
        elif not insp.unloaded or "optimized_candidates" not in insp.unloaded:
            raw_candidates = getattr(trial, "optimized_candidates", [])
    else:
        raw_candidates = getattr(trial, "optimized_candidates", [])

    if raw_candidates and isinstance(raw_candidates, (list, tuple)):
        for cand in raw_candidates:
            try:
                rdata = getattr(cand, "recipe_data", {}) or {}
                cs = rdata.get("confidence_score") if isinstance(rdata, dict) else None
                opts.append(
                    OptimizedRecipeCandidateResponse(
                        id=cand.id,
                        trial_id=cand.trial_id,
                        revision_label=cand.revision_label,
                        name=cand.name,
                        recipe_data=cand.recipe_data,
                        changed_parameters=cand.changed_parameters or [],
                        predicted_impacts=cand.predicted_impacts or [],
                        is_selected=cand.is_selected,
                        created_at=cand.created_at,
                        confidence_score=int(cs) if cs is not None else None,
                        optimization_strategy=rdata.get("optimization_strategy") if isinstance(rdata, dict) else None,
                        expected_outcome=rdata.get("expected_outcome") if isinstance(rdata, dict) else None,
                        expected_impact=rdata.get("expected_impact") if isinstance(rdata, dict) else None,
                        tradeoffs=rdata.get("tradeoffs") if isinstance(rdata, dict) else None,
                    )
                )
            except Exception:
                pass

    return CustomerTrialResponse(
        id=trial.id,
        cycle_id=trial.cycle_id,
        selected_candidate_id=trial.selected_candidate_id,
        saved_recipe_id=trial.saved_recipe_id,
        recipe_snapshot=trial.recipe_snapshot,
        status=status,
        feedback_text=trial.feedback_text,
        actual_values=_as_str_dict(getattr(trial, "actual_values", None)),
        target_values=_as_str_dict(getattr(trial, "target_values", None)),
        selected_optimized_id=trial.selected_optimized_id,
        optimized_candidates=opts,
        created_by=trial.created_by,
        created_at=trial.created_at,
    )


# ---------------------------------------------------------------------------
# Saved Recipe
# ---------------------------------------------------------------------------

class SavedRecipeCreate(BaseModel):
    """Persist the user-edited recipe payload (not the original LLM snapshot)."""
    recipe_name: str = Field(..., min_length=1, max_length=255)
    recipe_data: dict[str, Any]
    target_properties: list[dict[str, Any]] = Field(default_factory=list)
    competitor_properties: list[dict[str, Any]] = Field(default_factory=list)
    source_cycle_id: Optional[uuid.UUID] = None
    source_candidate_id: Optional[uuid.UUID] = None
    parent_recipe_id: Optional[uuid.UUID] = None
    source_trial_id: Optional[uuid.UUID] = None
    source_optimized_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    # NORMAL (default) or OPTIMIZED. Inferred as OPTIMIZED when parent + trial are set.
    recipe_kind: Optional[str] = None


class SavedRecipeUpdate(BaseModel):
    recipe_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    recipe_data: Optional[dict[str, Any]] = None
    target_properties: Optional[list[dict[str, Any]]] = None
    competitor_properties: Optional[list[dict[str, Any]]] = None
    notes: Optional[str] = None


class SavedRecipeResponse(BaseModel):
    id: uuid.UUID
    recipe_name: str
    recipe_data: dict[str, Any]
    target_properties: list[dict[str, Any]]
    competitor_properties: list[dict[str, Any]]
    created_by: uuid.UUID
    created_by_name: Optional[str] = None
    updated_by: Optional[uuid.UUID] = None
    updated_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    parent_recipe_id: Optional[uuid.UUID] = None
    parent_recipe_name: Optional[str] = None
    revision_number: int
    recipe_kind: str = "NORMAL"
    optimization_number: int = 0
    status: str
    source_feedback_text: Optional[str] = None
    source_cycle_id: Optional[uuid.UUID] = None
    source_candidate_id: Optional[uuid.UUID] = None
    source_trial_id: Optional[uuid.UUID] = None
    source_optimized_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    is_revision: bool = False
    model_config = ConfigDict(from_attributes=True)


class CandidateRecipeDataUpdate(BaseModel):
    """Patch transient generated candidate with user edits before/at save."""
    recipe_data: dict[str, Any]
    name: Optional[str] = None


class OptimizedCandidateUpdate(BaseModel):
    """Patch transient generated customer trial optimized candidate with user edits."""
    recipe_data: dict[str, Any]
    name: Optional[str] = None



class SavedRecipeBatchCreate(BaseModel):
    recipes: list[SavedRecipeCreate] = Field(..., min_length=1)


class SavedRecipeBatchItemResult(BaseModel):
    recipe_name: str
    success: bool
    saved_recipe: Optional[SavedRecipeResponse] = None
    error: Optional[str] = None


class SavedRecipeBatchResponse(BaseModel):
    results: list[SavedRecipeBatchItemResult]
    total_requested: int
    total_saved: int
    total_failed: int


# ---------------------------------------------------------------------------
# LLM Structured Output Schemas - DYNAMIC (no hardcoded compound fields)
# ---------------------------------------------------------------------------

def sanitize_unit_string(unit: Any) -> str:
    """Sanitize and normalize unit string, collapsing duplicate % and %25 URL artifacts."""
    import re
    raw_u = str(unit or "").strip()
    if "%" in raw_u:
        raw_u = re.sub(r"%\s*25", "%", raw_u)
        raw_u = re.sub(r"%(?:25)+", "%", raw_u)
        raw_u = re.sub(r"(?:%\s*)+", "%", raw_u).strip()
    return raw_u[:25].strip()


_sanitize_unit_string = sanitize_unit_string


class LLMRecipeParameter(BaseModel):
    """One synthesis ingredient or process parameter - fully dynamic."""
    name: str = Field(
        max_length=120,
        description=(
            "Full descriptive parameter name derived from the compound and patent context. "
            "For monomers: include chemical name and role, e.g. 'Butadiene (Monomer 1)', "
            "'Acrylonitrile (Monomer 2)', 'Styrene (Monomer)'. "
            "For auxiliaries: e.g. 'Potassium persulfate (Initiator)', "
            "'t-Dodecyl mercaptan (CTA)', 'Sodium oleate (Emulsifier)', 'Water'. "
            "For process: 'Reaction Temperature', 'Polymerization Time', 'Target Conversion'. "
            "NEVER hardcode names - always derive from the target compound and patent evidence."
        )
    )
    value: str = Field(
        max_length=60,
        description=(
            "The numeric or descriptive candidate value. Must be scientifically plausible. "
            "NOT a placeholder like 'X', 'TBD', or '0'. "
            "For numeric quantities: include only the number (unit goes in unit field)."
        )
    )
    unit: str = Field(
        default="",
        max_length=25,
        description=(
            "Unit of measurement (e.g. 'phr', '%', '°C', 'h', 'g/mol'). "
            "Use empty string when there is no unit. Never output repeated characters or '%25'."
        )
    )
    source: str = Field(
        default="inferred",
        max_length=40,
        description=(
            "One of 'patent' (when explicitly disclosed in the patent report), "
            "'ai_generated' (when synthesized from chemical principles/process requirement not in patent), "
            "or 'inferred' (when estimated from patent context and scientific reasoning). "
            "NEVER fabricate patent references."
        )
    )
    patent_ref: Optional[str] = Field(
        default=None,
        max_length=60,
        description=(
            "If source='patent', the specific patent number (e.g. 'US20250075019A1'). "
            "Leave null for inferred values."
        )
    )

    @model_validator(mode="before")
    @classmethod
    def sanitize_parameter(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "name" in data and len(str(data["name"])) > 120:
                data["name"] = str(data["name"])[:120].strip()
            if "value" in data and len(str(data["value"])) > 60:
                data["value"] = str(data["value"])[:60].strip()
            if "unit" in data:
                data["unit"] = sanitize_unit_string(data.get("unit"))
            if "patent_ref" in data and data["patent_ref"] and len(str(data["patent_ref"])) > 60:
                data["patent_ref"] = str(data["patent_ref"])[:60].strip()
        return data


class LLMRecipeStage(BaseModel):
    """A synthesis stage grouping related parameters."""
    stage_name: str = Field(
        max_length=80,
        description=(
            "Synthesis stage name according to the canonical client Excel template. "
            "Canonical stages in order: 'Reactor Charge', 'Emulsifier Solution', 'Catalyst Solution', "
            "'Monomer Mix', 'Chemical Stripping', 'Post Addition'."
        )
    )
    parameters: list[LLMRecipeParameter] = Field(
        default_factory=list,
        description="All ingredients and parameters for this stage. Empty list if not applicable to this chemistry."
    )
    omission_reason: Optional[str] = Field(
        default=None,
        max_length=250,
        description=(
            "If this stage is omitted or has no ingredients, a concise scientific AI reason explaining "
            "why it is not required for this synthesis route. Leave null if stage has parameters."
        )
    )


class LLMReactionTime(BaseModel):
    value: str = Field(max_length=40, description="Total reaction / polymerization time, e.g. '8' or '6-8'")
    unit: str = Field(default="h", max_length=20, description="Unit of time, e.g. 'h'")


class LLMFeedingHours(BaseModel):
    monomer: Optional[str] = Field(default="N/A", max_length=50, description="Monomer feed duration, e.g. '4 h' or 'N/A' if batch")
    emulsifier: Optional[str] = Field(default="N/A", max_length=50, description="Emulsifier feed duration, e.g. '4 h' or 'N/A'")
    catalyst: Optional[str] = Field(default="N/A", max_length=50, description="Catalyst feed duration, e.g. 'Continuous 6 h' or 'N/A'")


class LLMTemperatureStep(BaseModel):
    stage: str = Field(max_length=80, description="Stage or phase, e.g. 'Initial Charge', 'Feeding / Polymerization', 'Peak / Stripping'")
    value: str = Field(max_length=40, description="Temperature value or range, e.g. '10', '10-12', '75'")
    unit: str = Field(default="°C", max_length=20, description="Temperature unit, e.g. '°C'")


class LLMCatalystAlternative(BaseModel):
    name: str = Field(default="", max_length=120, description="Alternative catalyst or initiator chemical name")
    catalyst: Optional[str] = Field(default=None, max_length=120, description="Alias for catalyst name")
    dosage: str = Field(default="", max_length=50, description="Dosage and unit, e.g. '0.15 phr' or 'N/A'")
    dosage_phr: Optional[float | str] = Field(default=None, description="Dosage in phr")
    notes: Optional[str] = Field(default=None, max_length=200, description="Technical rationale or comparative notes")

    @model_validator(mode="before")
    @classmethod
    def populate_catalyst_alt_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("name") and data.get("catalyst"):
                data["name"] = data["catalyst"]
            elif not data.get("catalyst") and data.get("name"):
                data["catalyst"] = data["name"]
            if data.get("dosage_phr") is not None and not data.get("dosage"):
                data["dosage"] = f"{data['dosage_phr']} phr"
            elif data.get("dosage") and data.get("dosage_phr") is None:
                try:
                    import re
                    m = re.search(r"[-+]?\d*\.?\d+", str(data["dosage"]))
                    if m:
                        data["dosage_phr"] = float(m.group(0))
                except Exception:
                    pass
        return data


class LLMCatalystSystem(BaseModel):
    primary_catalyst: str = Field(default="", max_length=120, description="Primary catalyst / initiator chemical name")
    primary_dosage: str = Field(default="", max_length=50, description="Dosage and unit for primary catalyst, e.g. '0.25 phr'")
    primary_dosage_phr: Optional[float | str] = Field(default=None, description="Primary dosage in phr")
    alternatives: list[LLMCatalystAlternative] = Field(
        default_factory=list,
        description="Up to 2 chemically sound alternative catalysts with dosages, or empty list if none validated"
    )

    @model_validator(mode="before")
    @classmethod
    def populate_catalyst_sys_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("primary_dosage_phr") is not None and not data.get("primary_dosage"):
                data["primary_dosage"] = f"{data['primary_dosage_phr']} phr"
            elif data.get("primary_dosage") and data.get("primary_dosage_phr") is None:
                try:
                    import re
                    m = re.search(r"[-+]?\d*\.?\d+", str(data["primary_dosage"]))
                    if m:
                        data["primary_dosage_phr"] = float(m.group(0))
                except Exception:
                    pass
        return data


class LLMActivatorAlternative(BaseModel):
    name: str = Field(default="", max_length=120, description="Alternative activator chemical name")
    activator: Optional[str] = Field(default=None, max_length=120, description="Alias for activator name")
    dosage: str = Field(default="", max_length=50, description="Dosage and unit, e.g. '0.05 phr'")
    dosage_phr: Optional[float | str] = Field(default=None, description="Dosage in phr")
    notes: Optional[str] = Field(default=None, max_length=200, description="Technical rationale or comparative notes")

    @model_validator(mode="before")
    @classmethod
    def populate_activator_alt_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("name") and data.get("activator"):
                data["name"] = data["activator"]
            elif not data.get("activator") and data.get("name"):
                data["activator"] = data["name"]
            if data.get("dosage_phr") is not None and not data.get("dosage"):
                data["dosage"] = f"{data['dosage_phr']} phr"
            elif data.get("dosage") and data.get("dosage_phr") is None:
                try:
                    import re
                    m = re.search(r"[-+]?\d*\.?\d+", str(data["dosage"]))
                    if m:
                        data["dosage_phr"] = float(m.group(0))
                except Exception:
                    pass
        return data


class LLMActivatorSystem(BaseModel):
    applicable: bool = Field(default=False, description="True if redox activator is required, False if not applicable / not required")
    name: Optional[str] = Field(default="Not applicable", max_length=120, description="Activator chemical name, or 'Not applicable'")
    activator_name: Optional[str] = Field(default=None, max_length=120, description="Alias for activator chemical name")
    dosage: Optional[str] = Field(default="", max_length=50, description="Dosage and unit, e.g. '0.05 phr'")
    dosage_phr: Optional[float | str] = Field(default=None, description="Dosage in phr")
    stage_or_role: Optional[str] = Field(default="", max_length=100, description="Addition stage or redox role")
    stage: Optional[str] = Field(default=None, max_length=100, description="Alias for addition stage")
    alternatives: list[LLMActivatorAlternative] = Field(
        default_factory=list,
        description="Alternative activators with dosages where applicable"
    )
    notes: Optional[str] = Field(default=None, max_length=200, description="Notes")

    @model_validator(mode="before")
    @classmethod
    def populate_activator_sys_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("activator_name") and not data.get("name"):
                data["name"] = data["activator_name"]
            elif data.get("name") and not data.get("activator_name"):
                data["activator_name"] = data["name"]
            if data.get("stage") and not data.get("stage_or_role"):
                data["stage_or_role"] = data["stage"]
            elif data.get("stage_or_role") and not data.get("stage"):
                data["stage"] = data["stage_or_role"]
            if data.get("dosage_phr") is not None and not data.get("dosage"):
                data["dosage"] = f"{data['dosage_phr']} phr"
            elif data.get("dosage") and data.get("dosage_phr") is None:
                try:
                    import re
                    m = re.search(r"[-+]?\d*\.?\d+", str(data["dosage"]))
                    if m:
                        data["dosage_phr"] = float(m.group(0))
                except Exception:
                    pass
        return data


class LLMCoagulationSystem(BaseModel):
    applicable: bool = Field(default=False, description="True if latex/polymer isolation requires coagulation, False if not applicable")
    coagulant: Optional[str] = Field(default="Not applicable", max_length=120, description="Coagulant chemical name, or 'Not applicable'")
    dosage: Optional[str] = Field(default="", max_length=50, description="Dosage and unit, e.g. '2.0 phr'")
    dosage_phr: Optional[float | str] = Field(default=None, description="Dosage in phr")
    process_conditions: Optional[str] = Field(default="", max_length=200, description="Coagulation temperature, pH, or procedure")
    notes: Optional[str] = Field(default=None, max_length=200, description="Notes")

    @model_validator(mode="before")
    @classmethod
    def populate_coag_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("dosage_phr") is not None and not data.get("dosage"):
                data["dosage"] = f"{data['dosage_phr']} phr"
            elif data.get("dosage") and data.get("dosage_phr") is None:
                try:
                    import re
                    m = re.search(r"[-+]?\d*\.?\d+", str(data["dosage"]))
                    if m:
                        data["dosage_phr"] = float(m.group(0))
                except Exception:
                    pass
        return data


class LLMProcessConditions(BaseModel):
    reaction_time: Optional[LLMReactionTime] = Field(default=None, description="Total reaction time")
    feeding_hours: Optional[LLMFeedingHours] = Field(default=None, description="Feeding hours for monomer, emulsifier, catalyst")
    temperature_profile: list[LLMTemperatureStep] = Field(default_factory=list, description="Temperature profile across reaction stages")
    temperature_range: Optional[str] = Field(default=None, max_length=60, description="Target/operating reaction temperature range, e.g. '5–7 °C'")
    process_type: Optional[str] = Field(default=None, max_length=50, description="Process type: 'Batch' or 'Continuous'")


class LLMPredictedProperty(BaseModel):
    property: str = Field(max_length=120, description="Exact target property name (e.g. 'Mooney Viscosity', 'BACN', 'Tensile Strength')")
    predicted_value: Optional[float] = Field(default=None, description="Point predicted numerical value")
    predicted_min: Optional[float] = Field(default=None, description="Minimum predicted numerical value (if range prediction)")
    predicted_max: Optional[float] = Field(default=None, description="Maximum predicted numerical value (if range prediction)")
    unit: str = Field(default="", max_length=25, description="Clean unit symbol (e.g. %, MU, MPa, sec). Max 20 chars. Never output repeated characters or '%25'.")
    status: Optional[str] = Field(default="UNKNOWN", max_length=40, description="Model status claim: 'WITHIN_RANGE', 'OUTSIDE_RANGE', 'TARGET_MET', 'TARGET_NOT_MET', or 'UNKNOWN'")
    reasoning: str = Field(default="", max_length=300, description="Concise chemical and process basis for prediction (max 20 words)")

    @model_validator(mode="before")
    @classmethod
    def coerce_predictions(cls, data: Any) -> Any:
        import re
        if isinstance(data, dict):
            for f in ("predicted_value", "predicted_min", "predicted_max"):
                if f in data and data[f] is not None:
                    if isinstance(data[f], (int, float)):
                        data[f] = float(data[f])
                    else:
                        m = re.search(r"[-+]?\d*\.?\d+", str(data[f]))
                        data[f] = float(m.group(0)) if m else None
            if "name" in data and "property" not in data:
                data["property"] = str(data["name"])
            if "property" in data and not isinstance(data["property"], str):
                data["property"] = str(data["property"])
            if "property" in data and len(str(data["property"])) > 120:
                data["property"] = str(data["property"])[:120].strip()

            data["unit"] = sanitize_unit_string(data.get("unit"))

            if "reasoning" in data and not isinstance(data["reasoning"], str):
                data["reasoning"] = str(data["reasoning"]) if data["reasoning"] is not None else ""
            if "reasoning" in data and len(str(data["reasoning"])) > 300:
                data["reasoning"] = str(data["reasoning"])[:300].strip()

            if "status" in data and not isinstance(data["status"], str):
                data["status"] = str(data["status"]) if data["status"] is not None else "UNKNOWN"
            if "status" in data and len(str(data["status"])) > 40:
                data["status"] = str(data["status"])[:40].strip()
        return data


class LLMRecipeCandidate(BaseModel):
    """
    A complete candidate polymerization recipe. ALL ingredient names, monomers,
    initiators, emulsifiers etc. are DYNAMIC - derived from the target compound
    and patent report context, not hardcoded for any specific polymer family.
    """
    name: str = Field(
        max_length=120,
        description=(
            "Short descriptive recipe candidate name that identifies the variation "
            "dimension, e.g. 'Recipe 1 - Low CTA Baseline', 'Recipe 2 - High Initiator'."
        )
    )
    compound: str = Field(
        max_length=120,
        description="Target compound/polymer being synthesized, e.g. 'Low ACN NBR', 'SBR', 'XSBR'."
    )
    polymerization_method: str = Field(
        max_length=120,
        description=(
            "Overall polymerization process derived from patent evidence, "
            "e.g. 'Cold Emulsion Polymerization', 'Warm Emulsion', 'Solution Polymerization'."
        )
    )
    process_type: str = Field(
        default="Batch",
        max_length=50,
        description="Process type: 'Batch' or 'Continuous'. Respect user constraint when specified."
    )
    stages: list[LLMRecipeStage] = Field(
        description=(
            "Ordered synthesis stages following the canonical client Excel template order: "
            "1. Reactor Charge, 2. Emulsifier Solution, 3. Catalyst Solution, "
            "4. Monomer Mix, 5. Chemical Stripping, 6. Post Addition. "
            "Ingredient names within stages must be dynamic for the target compound."
        )
    )
    parameters: list[LLMRecipeParameter] = Field(
        default_factory=list,
        description=(
            "Must be left empty ([]) to prevent output duplication. "
            "Backend automatically compiles flat parameters from stages."
        )
    )
    process_conditions: Optional[LLMProcessConditions] = Field(
        default=None,
        description="Process conditions (reaction time, feeding hours, temperature profile) separate from ingredients."
    )
    catalyst_system: Optional[LLMCatalystSystem] = Field(
        default=None,
        description="Catalyst system with primary catalyst + dosage, and up to 2 chemically sound alternatives"
    )
    activator_system: Optional[LLMActivatorSystem] = Field(
        default=None,
        description="Activator / redox reducing agent system where applicable (or applicable=False / 'Not applicable')"
    )
    coagulation_system: Optional[LLMCoagulationSystem] = Field(
        default=None,
        description="Coagulation / latex isolation system where applicable (or applicable=False / 'Not applicable')"
    )
    predicted_properties: list[LLMPredictedProperty] = Field(
        default_factory=list,
        description="Model-predicted outcomes for each target property constraint. Empty list if no targets provided."
    )
    patent_references: list[str] = Field(
        default_factory=list,
        description=(
            "Patent numbers only whose evidence influenced this recipe (e.g. ['EP2316860B1']). "
            "Empty list if no specific patent values are cited."
        )
    )
    rationale: str = Field(
        default="",
        max_length=300,
        description=(
            "1 concise sentence explaining the variation. Maximum 25 words. Strictly no long prose."
        )
    )
    variation_dimension: str = Field(
        max_length=150,
        description=(
            "Primary synthesis dimension varied in this candidate to produce meaningful "
            "differentiation, e.g. 'Monomer ratio', 'Initiator concentration', "
            "'Chain-transfer agent level', 'Polymerization temperature', 'Water/emulsifier ratio'. "
            "Each of the 5 candidates must vary a different primary dimension."
        )
    )

    @model_validator(mode="before")
    @classmethod
    def sanitize_candidate(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for str_field, max_l in [
                ("name", 120),
                ("compound", 120),
                ("polymerization_method", 120),
                ("process_type", 50),
                ("rationale", 300),
                ("variation_dimension", 150),
            ]:
                if str_field in data and data[str_field] is not None:
                    s_val = str(data[str_field]).strip()
                    if len(s_val) > max_l:
                        data[str_field] = s_val[:max_l].strip()
                    else:
                        data[str_field] = s_val
        return data


class LLMRecipePlanCandidate(BaseModel):
    candidate_number: int = Field(ge=1, le=5, description="Candidate rank 1 to 5")
    name: str = Field(max_length=64, description="Concise candidate title, e.g. 'Baseline Cold Emulsion', max 50 chars")
    variation_dimension: str = Field(max_length=100, description="Primary synthesis dimension, e.g. 'Monomer ratio', 'Initiator concentration'")
    key_formulation_changes: list[str] = Field(default_factory=list, description="2-3 specific chemical levers, e.g. ['Increase butadiene to 72 phr']")
    rationale: str = Field(max_length=200, description="1 concise sentence explaining the chemical hypothesis")
    patent_references: list[str] = Field(default_factory=list, description="Patent citations supporting this route")


class LLMRecipePlan(BaseModel):
    compound: str = Field(max_length=120, description="Target compound name")
    candidates: list[LLMRecipePlanCandidate] = Field(description="Exactly 5 distinct recipe formulation strategies")


class LLMSingleRecipe(BaseModel):
    recipe: LLMRecipeCandidate = Field(description="A single complete candidate polymerization recipe")


class LLMRecipeSet(BaseModel):
    recipes: list[LLMRecipeCandidate] = Field(
        description=(
            "Exactly 5 distinct recipe formulations. Each must be a NEW candidate "
            "- not a copy of a patent example. Each must vary a different primary dimension."
        )
    )


class LLMOptimizedParameter(BaseModel):
    name: str = Field(description="Ingredient or parameter name")
    value: str = Field(description="Numerical value or range, e.g. '180' or '0.25'")
    unit: str = Field(default="", description="Unit of measurement, e.g. phr, %, °C, h")
    source: Optional[str] = Field(default="inferred")
    patent_ref: Optional[str] = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def coerce_values(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "value" in data and not isinstance(data["value"], str):
                data["value"] = str(data["value"]) if data["value"] is not None else ""
            if "name" in data and not isinstance(data["name"], str):
                data["name"] = str(data["name"]) if data["name"] is not None else ""
            if "unit" in data and not isinstance(data["unit"], str):
                data["unit"] = str(data["unit"]) if data["unit"] is not None else ""
        return data


class LLMOptimizedStage(BaseModel):
    stage_name: str = Field(description="Dynamic synthesis stage name (e.g. 'Reactor Charge', 'Monomer Mix', etc.)")
    parameters: list[LLMOptimizedParameter] = Field(
        default_factory=list,
        description="Parameters and ingredients for this stage"
    )


class LLMOptimizedChange(BaseModel):
    parameter: str = Field(description="Name of the changed parameter")
    old_value: str = Field(default="", description="Previous value in parent recipe (e.g. '5' or '5 phr')")
    new_value: str = Field(default="", description="New value in this optimized revision (e.g. '3' or '3 phr')")
    unit: Optional[str] = Field(default="", description="Unit of measurement, e.g. phr, °C, h")
    reason: str = Field(default="", max_length=1500, description="Scientific rationale for this parameter change")

    # Backward compatibility with previous/revised fields and robust coercion
    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "previous" in data and "old_value" not in data:
                data["old_value"] = str(data["previous"] or "")
            if "revised" in data and "new_value" not in data:
                data["new_value"] = str(data["revised"] or "")
            if "rationale" in data and "reason" not in data:
                data["reason"] = str(data["rationale"] or "")
            if "old_value" in data and not isinstance(data["old_value"], str):
                data["old_value"] = str(data["old_value"]) if data["old_value"] is not None else ""
            if "new_value" in data and not isinstance(data["new_value"], str):
                data["new_value"] = str(data["new_value"]) if data["new_value"] is not None else ""
            if "parameter" in data and not isinstance(data["parameter"], str):
                data["parameter"] = str(data["parameter"]) if data["parameter"] is not None else ""
            if "unit" in data and not isinstance(data["unit"], str):
                data["unit"] = str(data["unit"]) if data["unit"] is not None else ""
            if "reason" in data and not isinstance(data["reason"], str):
                data["reason"] = str(data["reason"]) if data["reason"] is not None else ""
        return data

    @property
    def previous(self) -> str:
        return self.old_value

    @property
    def revised(self) -> str:
        return self.new_value

    @property
    def rationale(self) -> str:
        return self.reason


# Ergonomic alias for changed parameter schema
LLMChangedParameter = LLMOptimizedChange


class LLMTargetImpact(BaseModel):
    property: str = Field(description="Name of the target property influenced by this revision")
    expected_direction: str = Field(default="increases", description="Direction of change, e.g. 'increases', 'decreases', 'meets target'")
    expected_effect: str = Field(default="", description="Concise statement of impact on this property")
    predicted_value: Optional[str] = Field(default=None, description="Optional predicted numerical value or range")
    status: Optional[str] = Field(default=None, description="MEETS_TARGET or OUTSIDE_TARGET")
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def coerce_impact(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "name" in data and "property" not in data:
                data["property"] = str(data["name"])
            if "direction" in data and "expected_direction" not in data:
                data["expected_direction"] = str(data["direction"])
            if "effect" in data and "expected_effect" not in data:
                data["expected_effect"] = str(data["effect"])
            if "reason" in data and "expected_effect" not in data:
                data["expected_effect"] = str(data["reason"])
            if "predicted_value" in data and data["predicted_value"] is not None:
                data["predicted_value"] = str(data["predicted_value"])
        return data


class LLMOptimizedRecipeCandidate(BaseModel):
    name: str = Field(
        default="Optimized Revision",
        max_length=120,
        description="Descriptive revision name, e.g. 'Revision A - Conservative Oil Reduction'"
    )
    optimization_strategy: str = Field(
        default="Targeted Lever Optimization",
        max_length=2000,
        description="Scientific optimization strategy and chemical rationale"
    )
    confidence_score: int = Field(
        default=75,
        ge=0,
        le=100,
        description="Dynamic AI/design confidence score (0-100)"
    )
    stages: list[LLMOptimizedStage] = Field(
        default_factory=list,
        description="Complete synthesis stages and parameters for this formulation revision. May be empty [] when backend applies changed_parameters deltas onto source recipe."
    )
    process_conditions: Optional[LLMProcessConditions] = Field(
        default=None,
        description="Process conditions (reaction time, feeding hours, temperature profile)"
    )
    changed_parameters: list[LLMOptimizedChange] = Field(
        default_factory=list,
        description="List ONLY parameters that changed vs parent recipe (parameter, old_value, new_value, unit, reason)"
    )
    target_impact: list[LLMTargetImpact] = Field(
        default_factory=list,
        description="Compact target impact assessment for properties influenced by proposed changes"
    )
    expected_outcome: str = Field(
        default="",
        max_length=2000,
        description="Statement of intended outcome addressing customer feedback"
    )
    expected_impact: str = Field(
        default="",
        max_length=2000,
        description="Statement of expected physical/chemical impact and tradeoffs"
    )
    revision_label: Optional[str] = Field(default=None)
    compound: Optional[str] = Field(default="")
    polymerization_method: Optional[str] = Field(default="Cold Emulsion Polymerization")
    process_type: str = Field(
        default="Batch",
        description="Process type: 'Batch' or 'Continuous'. Respect user constraint or source recipe."
    )
    catalyst_system: Optional[LLMCatalystSystem] = Field(
        default=None,
        description="Dynamic catalyst system (primary catalyst + dosage + validated alternatives)"
    )
    activator_system: Optional[LLMActivatorSystem] = Field(
        default=None,
        description="Dynamic activator system (applicability, activator name, dosage, addition stage, alternatives)"
    )
    coagulation_system: Optional[LLMCoagulationSystem] = Field(
        default=None,
        description="Dynamic coagulation system (applicability, coagulation system, coagulant, dosage, conditions)"
    )
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    predicted_properties: list[LLMPredictedProperty] = Field(
        default_factory=list,
        description="Predicted property outcomes addressing target constraints"
    )
    predicted_impacts: list[Any] = Field(default_factory=list)
    tradeoffs: Optional[str] = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def coerce_candidate(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "confidence_score" in data:
                try:
                    data["confidence_score"] = int(round(float(data["confidence_score"])))
                except (ValueError, TypeError):
                    data["confidence_score"] = 75
            if "stages" in data and isinstance(data["stages"], list):
                coerced_stages = []
                for s in data["stages"]:
                    if hasattr(s, "model_dump"):
                        coerced_stages.append(s.model_dump())
                    elif isinstance(s, dict):
                        coerced_stages.append(s)
                    else:
                        coerced_stages.append(s)
                data["stages"] = coerced_stages
            if "tradeoffs" in data and isinstance(data["tradeoffs"], list):
                data["tradeoffs"] = "; ".join(str(x) for x in data["tradeoffs"])
            if "expected_outcome" in data and isinstance(data["expected_outcome"], list):
                data["expected_outcome"] = "; ".join(str(x) for x in data["expected_outcome"])
            if "expected_impact" in data and isinstance(data["expected_impact"], list):
                data["expected_impact"] = "; ".join(str(x) for x in data["expected_impact"])
            if "target_impact" in data and isinstance(data["target_impact"], list):
                if not data.get("predicted_impacts"):
                    data["predicted_impacts"] = [
                        item.model_dump() if hasattr(item, "model_dump") else item
                        for item in data["target_impact"]
                    ]
            if "predicted_impacts" in data and isinstance(data["predicted_impacts"], list):
                data["predicted_impacts"] = [
                    item.model_dump() if hasattr(item, "model_dump") else item
                    for item in data["predicted_impacts"]
                ]
        return data


class LLMOptimizationSet(BaseModel):
    optimized_recipes: list[LLMOptimizedRecipeCandidate] = Field(
        description="Exactly 3 distinct optimized recipe revisions (no more, no less)"
    )

    @field_validator("optimized_recipes")
    @classmethod
    def validate_exactly_three(cls, v: list[LLMOptimizedRecipeCandidate]) -> list[LLMOptimizedRecipeCandidate]:
        if len(v) != 3:
            raise ValueError(f"Expected exactly 3 optimized recipe revisions, got {len(v)}")
        return v


class LLMAdditionalOptimizationCandidates(BaseModel):
    additional_recipes: list[LLMOptimizedRecipeCandidate] = Field(
        default_factory=list,
        description="Additional distinct optimized recipe candidate revisions (no more, no less)"
    )
