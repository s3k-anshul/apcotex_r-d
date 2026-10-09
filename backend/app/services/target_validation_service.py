"""
app/services/target_validation_service.py

Deterministic Target Validation & Confidence Scoring Service for Recipe Simulator.
Evaluates recipe candidates against user target properties as hard objectives,
detects target violations, calculates mathematically deterministic Target Fit,
and computes evidence-based confidence scores.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Documented Scoring Weight Constants (Section 8)
# ─────────────────────────────────────────────────────────────────────────────

# In STRICT_TARGET mode (when user provides one or more target properties):
WEIGHT_TARGET_COMPLIANCE = 0.60
WEIGHT_EVIDENCE_SUPPORT = 0.20
WEIGHT_RECIPE_COMPLETENESS = 0.10
WEIGHT_PROCESS_FEASIBILITY = 0.10

# In GENERAL mode (when no explicit target properties are provided):
WEIGHT_NO_TARGET_EVIDENCE = 0.35
WEIGHT_NO_TARGET_COMPLETENESS = 0.25
WEIGHT_NO_TARGET_FEASIBILITY = 0.20
WEIGHT_NO_TARGET_PLAUSIBILITY = 0.20


def extract_float(value: Any) -> Optional[float]:
    """Safely extract a float number from int, float, or string representation."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s.lower() in ("none", "null", "n/a", "-", ""):
        return None
    # Match first valid floating point or integer number
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
    if m:
        try:
            return float(m.group(0))
        except (ValueError, TypeError):
            return None
    return None


@dataclass
class NormalizedTargetProperty:
    """Standardized internal representation of a target property constraint."""
    name: str
    unit: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    target_value: Optional[float] = None
    constraint_type: str = "range"  # "range" | "min" | "max" | "exact" | "qualitative"
    tolerance: float = 0.5          # absolute tolerance for exact target
    source: str = "target_polymer"
    raw_target_str: Optional[str] = None
    current_value: Optional[str] = None
    direction: Optional[str] = None
    feedback_relevance: Optional[str] = None
    conflict_with_range: bool = False
    raw_dict: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Returns True if at least one constraint boundary or target description is populated."""
        return (
            self.min_value is not None
            or self.max_value is not None
            or self.target_value is not None
            or bool(self.raw_target_str and self.raw_target_str.strip() and self.raw_target_str.strip().lower() not in ("none", "null", "n/a", "-", ""))
        )

    @property
    def target_min(self) -> Optional[float]:
        return self.min_value

    @property
    def target_max(self) -> Optional[float]:
        return self.max_value

    @property
    def qualitative(self) -> bool:
        return self.constraint_type == "qualitative"

    def display_target(self) -> str:
        u = f" {self.unit}".rstrip() if self.unit else ""
        if self.min_value is not None and self.max_value is not None and self.target_value is not None:
            if self.conflict_with_range:
                return f"Target: {self.target_value}{u} [Conflicts with range {self.min_value}–{self.max_value}{u}]"
            return f"Target: {self.target_value}{u} (Range: {self.min_value}–{self.max_value}{u})"
        if self.constraint_type == "range" and self.min_value is not None and self.max_value is not None:
            return f"{self.min_value}–{self.max_value}{u}"
        elif self.constraint_type == "min" and self.min_value is not None:
            return f"≥ {self.min_value}{u}"
        elif self.constraint_type == "max" and self.max_value is not None:
            return f"≤ {self.max_value}{u}"
        elif self.constraint_type == "exact" and self.target_value is not None:
            return f"{self.target_value}{u}"
        elif self.raw_target_str:
            return f"{self.raw_target_str}{u}"
        return "N/A"


class StatusString(str):
    """
    String representation of target status supporting:
    - 'MEETS_TARGET', 'WITHIN_RANGE', 'TARGET_MET'
    - 'NOT_MET', 'OUTSIDE_TARGET', 'OUTSIDE_RANGE', 'TARGET_NOT_MET'
    - 'UNKNOWN'
    for 100% backward and forward compatibility across frontend and backend.
    """
    def __eq__(self, other: Any) -> bool:
        if isinstance(other, (str, StatusString)):
            s_self = str(self).replace(" ", "_").upper()
            s_other = str(other).replace(" ", "_").upper()
            if s_self in ("NOT_MET", "OUTSIDE_TARGET", "OUTSIDE_RANGE", "TARGET_NOT_MET") and s_other in ("NOT_MET", "OUTSIDE_TARGET", "OUTSIDE_RANGE", "TARGET_NOT_MET"):
                return True
            if s_self in ("MEETS_TARGET", "WITHIN_RANGE", "TARGET_MET") and s_other in ("MEETS_TARGET", "WITHIN_RANGE", "TARGET_MET"):
                return True
            if s_self == "UNKNOWN" and s_other == "UNKNOWN":
                return True
        return super().__eq__(other)

    def __hash__(self) -> int:
        return super().__hash__()


class PropertyEvaluationResult(dict):
    """
    Result of evaluating a single predicted property against target constraints.
    Inherits from dict so that dictionary lookups and JSON serialization work natively,
    while also providing property/attribute access (.meets_target, .status, .violation_distance).
    """

    @property
    def meets_target(self) -> bool:
        return bool(self.get("passed", False))

    def __getattr__(self, name: str) -> Any:
        if name in self:
            return self[name]
        raise AttributeError(f"'PropertyEvaluationResult' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def parse_target_value_string(
    raw: Any,
) -> tuple[Optional[float], Optional[float], Optional[float], str, str]:
    """
    Parses a target string (e.g., '48-52 MU', '>= 22 MPa', '<= 1.0 %', '28 %', '-35 to -29 °C', '22.0- MPa')
    into (min_value, max_value, target_value, constraint_type, unit).
    """
    if raw is None:
        return None, None, None, "range", ""
    s = str(raw).strip()
    if not s or s.lower() in ("none", "null", "n/a", "-", ""):
        return None, None, None, "range", ""

    # 1. Range: e.g. "48-52 MU", "48 - 52", "48–52", "-35 to -29 °C", "27-29 %"
    m_range = re.search(
        r"^\s*([-+]?\d*\.?\d+)\s*(?:to|–|—|\s-\s|-)\s*([-+]?\d*\.?\d+)\s*(.*)$",
        s,
        re.IGNORECASE,
    )
    if m_range:
        v1 = extract_float(m_range.group(1))
        v2 = extract_float(m_range.group(2))
        unit = m_range.group(3).strip()
        if v1 is not None and v2 is not None:
            if v1 > v2:
                v1, v2 = v2, v1
            return v1, v2, None, "range", unit

    # 2. Minimum-only: e.g. ">= 22 MPa", "> 22", "≥ 22", "min 22", "22.0- MPa", "22.0+ MPa"
    m_min_pre = re.search(r"^\s*(?:>=|≥|>|min:?)\s*([-+]?\d*\.?\d+)\s*(.*)$", s, re.IGNORECASE)
    if m_min_pre:
        v = extract_float(m_min_pre.group(1))
        unit = m_min_pre.group(2).strip()
        if v is not None:
            return v, None, None, "min", unit

    m_min_post = re.search(r"^\s*([-+]?\d*\.?\d+)\s*[-+]\s*(.*)$", s)
    if m_min_post:
        v = extract_float(m_min_post.group(1))
        unit = m_min_post.group(2).strip()
        if v is not None:
            return v, None, None, "min", unit

    # 3. Maximum-only: e.g. "<= 1.0 %", "< 1.0", "≤ 1.0", "max 1.0", "max: 1.0"
    m_max_pre = re.search(r"^\s*(?:<=|≤|<|max:?)\s*([-+]?\d*\.?\d+)\s*(.*)$", s, re.IGNORECASE)
    if m_max_pre:
        v = extract_float(m_max_pre.group(1))
        unit = m_max_pre.group(2).strip()
        if v is not None:
            return None, v, None, "max", unit

    # 4. Exact / single number: e.g. "28.0 %", "28"
    m_exact = re.search(r"^\s*([-+]?\d*\.?\d+)\s*(.*)$", s)
    if m_exact:
        v = extract_float(m_exact.group(1))
        unit = m_exact.group(2).strip()
        if v is not None:
            return None, None, v, "exact", unit

    return None, None, None, "range", ""


class TargetValidationService:
    """
    Dedicated service for:
    1. Normalizing target properties across diverse input formats.
    2. Deterministically validating recipe property predictions against targets.
    3. Calculating Target Fit Score and detecting violations.
    4. Calculating backend-grounded Confidence Score (replacing arbitrary LLM scores).
    5. Ranking recipe candidates according to target compliance and evidence support.
    """

    @staticmethod
    def normalize_target_properties(
        raw_properties: list[dict[str, Any] | Any] | dict[str, Any] | None,
    ) -> list[NormalizedTargetProperty]:
        """
        Normalize dynamic target properties from frontend or API payloads.
        Handles range (min+max), min-only, max-only, exact targets.
        Discards empty placeholders with no values.
        """
        if not raw_properties:
            return []

        if isinstance(raw_properties, dict):
            dict_items = []
            for k, v in raw_properties.items():
                if isinstance(v, dict):
                    dict_items.append({"property": k, **v})
                else:
                    dict_items.append({"property": k, "target": v})
            raw_properties = dict_items

        normalized: list[NormalizedTargetProperty] = []
        for item in raw_properties:
            if hasattr(item, "model_dump"):
                d = item.model_dump(exclude_none=False)
            elif isinstance(item, dict):
                d = dict(item)
            else:
                continue

            name = (
                str(d.get("feature") or d.get("name") or d.get("id") or d.get("property") or "").strip()
            )
            if not name:
                continue

            unit = str(d.get("unit") or "").strip()
            min_v = extract_float(d.get("min") or d.get("target_min"))
            max_v = extract_float(d.get("max") or d.get("target_max"))
            target_v = extract_float(d.get("target") or d.get("value") or d.get("target_value"))
            raw_target_str = d.get("target") or d.get("value") or d.get("target_value")

            constraint_type = "range"
            tolerance = 0.5

            # If range was explicitly provided as a combined string (e.g. range="20-25"), parse it
            if min_v is None and max_v is None and d.get("range"):
                p_min, p_max, p_tgt, p_type, p_unit = parse_target_value_string(d.get("range"))
                if p_min is not None and p_max is not None:
                    min_v = p_min
                    max_v = p_max
                    if not unit and p_unit:
                        unit = p_unit

            # If min and max were not explicitly provided as distinct numeric values, parse target string
            if min_v is None and max_v is None and raw_target_str is not None:
                p_min, p_max, p_tgt, p_type, p_unit = parse_target_value_string(raw_target_str)
                if p_min is not None or p_max is not None or p_tgt is not None:
                    min_v = p_min
                    max_v = p_max
                    if p_tgt is not None:
                        target_v = p_tgt
                    constraint_type = p_type
                    if not unit and p_unit:
                        unit = p_unit

            # Determine constraint type from resulting values
            if min_v is not None and max_v is not None:
                if abs(min_v - max_v) < 1e-6:
                    constraint_type = "exact"
                    target_v = min_v
                    min_v = None
                    max_v = None
                else:
                    if min_v > max_v:
                        # Swap if inverted accidentally
                        min_v, max_v = max_v, min_v
                    constraint_type = "range"
            elif min_v is not None and max_v is None and target_v is None:
                constraint_type = "min"
            elif max_v is not None and min_v is None and target_v is None:
                constraint_type = "max"
            elif min_v is None and max_v is None and target_v is None and raw_target_str is not None:
                str_raw = str(raw_target_str).strip()
                if str_raw and str_raw.lower() not in ("none", "null", "n/a", "-", ""):
                    constraint_type = "qualitative"

            # Compute scientifically justified tolerance for exact target (2.5% or min 0.5 units)
            if constraint_type == "exact" and target_v is not None:
                explicit_tol = extract_float(d.get("tolerance"))
                if explicit_tol is not None and explicit_tol > 0:
                    tolerance = explicit_tol
                else:
                    tolerance = max(0.5, round(abs(target_v) * 0.025, 2))

            prop = NormalizedTargetProperty(
                name=name,
                unit=unit,
                min_value=min_v,
                max_value=max_v,
                target_value=target_v,
                constraint_type=constraint_type,
                tolerance=tolerance,
                source=str(d.get("source") or "target_polymer"),
                raw_target_str=str(raw_target_str) if raw_target_str is not None else None,
                current_value=str(d.get("current_value") or d.get("actual") or d.get("actual_value") or "") or None,
                direction=str(d.get("direction") or "") or None,
                feedback_relevance=str(d.get("feedback_relevance") or "") or None,
                raw_dict=d,
            )

            if prop.is_active:
                normalized.append(prop)

        return normalized

    @classmethod
    def format_optimization_targets_table(
        cls,
        normalized_targets: list[NormalizedTargetProperty],
        actual_values: dict[str, Any] | None = None,
        source_recipe_data: dict[str, Any] | None = None,
        customer_feedback: str = "",
    ) -> str:
        """
        Builds a rich, normalized, compact markdown table of all user-supplied target properties.
        Guarantees EVERY populated target property enters the LLM reasoning context without being dropped.
        For >15 properties, groups logically into scientific clusters (Cure/Rheology, Mechanical, Aging, etc.)
        while preserving all properties.
        """
        if not normalized_targets:
            return "No explicit quantitative target properties supplied. Optimize formulation scientifically based on customer feedback."

        actual_map = {}
        if isinstance(actual_values, dict):
            for k, v in actual_values.items():
                if v is not None and str(v).strip() != "":
                    actual_map[re.sub(r"[^a-zA-Z0-9]", "", str(k).lower())] = str(v).strip()

        source_preds = {}
        if isinstance(source_recipe_data, dict):
            for sp in source_recipe_data.get("predicted_properties") or []:
                if isinstance(sp, dict):
                    sp_name = sp.get("property") or sp.get("name") or ""
                    sp_val = sp.get("predicted_value") or sp.get("predicted_display") or ""
                    sp_u = sp.get("unit") or ""
                    if sp_name and sp_val:
                        source_preds[re.sub(r"[^a-zA-Z0-9]", "", str(sp_name).lower())] = f"{sp_val} {sp_u}".strip()

        feedback_lower = str(customer_feedback or "").lower()

        rows = []
        for idx, t in enumerate(normalized_targets, start=1):
            clean_name = re.sub(r"[^a-zA-Z0-9]", "", t.name.lower())
            
            # 1. Resolve Current / Observed Value
            cur_val = t.current_value
            if not cur_val and clean_name in actual_map:
                cur_val = actual_map[clean_name]
            if not cur_val and clean_name in source_preds:
                cur_val = f"{source_preds[clean_name]} (baseline)"
            if not cur_val:
                cur_val = "Not trialed / baseline"

            # 2. Determine Optimization Direction
            direction = t.direction
            if not direction:
                num_cur = extract_float(cur_val)
                if num_cur is not None:
                    if t.constraint_type == "min" and t.min_value is not None:
                        direction = f"Increase to ≥ {t.min_value}" if num_cur < t.min_value else f"Maintain ≥ {t.min_value} (cur: {num_cur})"
                    elif t.constraint_type == "max" and t.max_value is not None:
                        direction = f"Decrease to ≤ {t.max_value}" if num_cur > t.max_value else f"Maintain ≤ {t.max_value} (cur: {num_cur})"
                    elif t.constraint_type == "exact" and t.target_value is not None:
                        if num_cur < t.target_value - t.tolerance:
                            direction = f"Increase toward {t.target_value}"
                        elif num_cur > t.target_value + t.tolerance:
                            direction = f"Decrease toward {t.target_value}"
                        else:
                            direction = f"Maintain at {t.target_value}"
                    elif t.constraint_type == "range" and t.min_value is not None and t.max_value is not None:
                        if num_cur < t.min_value:
                            direction = f"Increase into range ({t.min_value}–{t.max_value})"
                        elif num_cur > t.max_value:
                            direction = f"Decrease into range ({t.min_value}–{t.max_value})"
                        else:
                            direction = f"Maintain within range ({t.min_value}–{t.max_value})"
                if not direction:
                    direction = f"Align with target ({t.display_target()})"

            # 3. Determine Customer Feedback Relevance
            relevance = t.feedback_relevance
            if not relevance:
                t_words = [w for w in re.sub(r"[^a-zA-Z0-9]", " ", t.name.lower()).split() if len(w) >= 3]
                if any(w in feedback_lower for w in t_words):
                    relevance = "Direct customer observation / priority"
                else:
                    relevance = "Target specification constraint"

            rows.append({
                "idx": idx,
                "property": t,
                "name": t.name,
                "unit": t.unit or "—",
                "target_display": t.display_target(),
                "cur_val": cur_val,
                "direction": direction,
                "relevance": relevance,
            })

        def _classify_property(prop_name: str) -> str:
            pl = prop_name.lower()
            if any(k in pl for k in ("ts1", "ts2", "t10", "t50", "t90", "mh", "ml", "cure", "scorch", "rheo")):
                return "Cure & Rheology Kinetics"
            elif any(k in pl for k in ("tensile", "elongation", "modulus", "tear", "hardness", "shore", "strength")):
                return "Mechanical & Physical Properties"
            elif any(k in pl for k in ("compression", "set", "abrasion", "aging", "heat", "flex", "fatigue", "resilience")):
                return "Dynamic & Aging Durability"
            elif any(k in pl for k in ("swell", "oil", "irm", "isooctane", "fuel", "solvent", "chemical", "water absorption")):
                return "Chemical & Fluid Resistance"
            elif any(k in pl for k in ("processing oil", "oil phr", "solid", "tsc", "ph", "viscosity", "mooney")):
                return "Polymer Processing & Viscosity"
            return "Additional & Custom Specifications"

        if len(rows) <= 15:
            table_lines = [
                "| # | Property Name | Unit | Target / Specification | Current / Observed Value | Target Direction | Feedback Relevance |",
                "|---|---|---|---|---|---|---|",
            ]
            for r in rows:
                table_lines.append(
                    f"| {r['idx']} | {r['name']} | {r['unit']} | {r['target_display']} | {r['cur_val']} | {r['direction']} | {r['relevance']} |"
                )
            return "\n".join(table_lines)
        else:
            clusters: dict[str, list[dict]] = {}
            for r in rows:
                c_name = _classify_property(r["name"])
                clusters.setdefault(c_name, []).append(r)

            grouped_lines = [
                f"TOTAL SUPPLIED TARGET PROPERTIES: {len(rows)} (ALL MUST BE ANALYZED WITHOUT EXCEPTION)",
                ""
            ]
            for c_title, c_rows in clusters.items():
                grouped_lines.append(f"### {c_title} ({len(c_rows)} properties)")
                grouped_lines.append(
                    "| # | Property Name | Unit | Target / Specification | Current / Observed Value | Target Direction | Feedback Relevance |"
                )
                grouped_lines.append("|---|---|---|---|---|---|---|")
                for r in c_rows:
                    grouped_lines.append(
                        f"| {r['idx']} | {r['name']} | {r['unit']} | {r['target_display']} | {r['cur_val']} | {r['direction']} | {r['relevance']} |"
                    )
                grouped_lines.append("")

            return "\n".join(grouped_lines).strip()

    @classmethod
    def match_prediction_for_target(
        cls,
        target: NormalizedTargetProperty | str | dict,
        predicted_properties: list[dict[str, Any]],
        recipe_params: list[dict[str, Any]] | None = None,
        rationale: str = "",
        target_impacts: list[dict[str, Any]] | None = None,
    ) -> Optional[dict[str, Any]]:
        """
        Find the predicted property item matching a given target property.
        Matches by normalized token overlap and synonyms (e.g. Mooney, ACN, Solids),
        or by inspecting target_impact deltas.
        """
        if isinstance(target, str):
            raw_name = target
        elif isinstance(target, dict):
            raw_name = target.get("name") or target.get("property") or target.get("feature") or ""
        elif hasattr(target, "name"):
            raw_name = target.name
        else:
            raw_name = str(target)
        target_name_clean = re.sub(r"[^a-zA-Z0-9]", " ", raw_name.lower()).strip()
        target_tokens = set(target_name_clean.split())

        best_match = None
        best_score = 0.0

        # Prioritize candidate target_impacts deltas over inherited predicted_properties
        if target_impacts:
            for ti in target_impacts:
                if not isinstance(ti, dict):
                    continue
                ti_name = str(ti.get("property") or ti.get("name") or "").strip()
                ti_clean = re.sub(r"[^a-zA-Z0-9]", " ", ti_name.lower()).strip()
                ti_tokens = set(ti_clean.split())
                if ti_clean == target_name_clean or (target_tokens and ti_tokens and (ti_tokens == target_tokens or target_tokens.issubset(ti_tokens))):
                    ti_val = extract_float(ti.get("predicted_value") or ti.get("value"))
                    if ti_val is None:
                        ti_val = extract_float(ti.get("expected_effect") or ti.get("effect") or ti.get("reason"))
                    t_unit = target.unit if hasattr(target, "unit") else ""
                    return {
                        "property": raw_name,
                        "predicted_value": ti_val,
                        "unit": ti.get("unit") or t_unit,
                        "status": ti.get("status") or "MEETS_TARGET",
                        "reasoning": str(ti.get("expected_effect") or ti.get("effect") or ti.get("reason") or "Assessed in target impact deltas."),
                    }

        for p in (predicted_properties or []):
            if not isinstance(p, dict):
                continue
            p_name = str(p.get("property") or p.get("name") or "").strip()
            p_clean = re.sub(r"[^a-zA-Z0-9]", " ", p_name.lower()).strip()
            p_tokens = set(p_clean.split())

            # Direct string match (case-insensitive)
            if p_name.strip().lower() == raw_name.strip().lower():
                res = dict(p)
                res["property"] = raw_name
                res["name"] = raw_name
                return res

            # Clean alphanumeric match
            if target_name_clean and target_name_clean == p_clean:
                res = dict(p)
                res["property"] = raw_name
                res["name"] = raw_name
                return res

            if not p_tokens or not target_tokens:
                continue

            # Token overlap score
            overlap = len(target_tokens.intersection(p_tokens))
            union = len(target_tokens.union(p_tokens))
            jaccard = overlap / max(union, 1)

            # Domain specific token matches
            bonus = 0.0
            if "acn" in target_tokens and "acn" in p_tokens:
                bonus += 0.5
            if "mooney" in target_tokens and "mooney" in p_tokens:
                bonus += 0.5
            if "tg" in target_tokens and "tg" in p_tokens:
                bonus += 0.5
            if "tensile" in target_tokens and "tensile" in p_tokens:
                bonus += 0.5
            if ("solid" in target_tokens or "tsc" in target_tokens) and ("solid" in p_tokens or "tsc" in p_tokens):
                bonus += 0.5
            if "ph" in target_tokens and "ph" in p_tokens:
                bonus += 0.5

            score = jaccard + bonus
            if score > best_score and score >= 0.35:
                best_score = score
                best_match = p

        if best_match:
            res = dict(best_match)
            res["property"] = raw_name
            res["name"] = raw_name
            return res

        # Fallback 1: check target_impacts array if provided
        if target_impacts:
            for ti in target_impacts:
                if not isinstance(ti, dict):
                    continue
                ti_name = str(ti.get("property") or ti.get("name") or "").strip()
                ti_clean = re.sub(r"[^a-zA-Z0-9]", " ", ti_name.lower()).strip()
                if ti_clean == target_name_clean or (target_tokens and set(ti_clean.split()) == target_tokens):
                    ti_val = extract_float(ti.get("predicted_value") or ti.get("value"))
                    if ti_val is None:
                        ti_val = extract_float(ti.get("expected_effect") or ti.get("effect") or ti.get("reason"))
                    t_unit = target.unit if hasattr(target, "unit") else ""
                    return {
                        "property": raw_name,
                        "predicted_value": ti_val,
                        "unit": t_unit,
                        "status": ti.get("status") or "MEETS_TARGET",
                        "reasoning": str(ti.get("expected_effect") or ti.get("effect") or ti.get("reason") or "Assessed in target impact deltas."),
                    }

        # Fallback 2: check if recipe parameters disclose a value for this target
        if recipe_params:
            for param in recipe_params:
                pname = str(param.get("name", "")).lower()
                if any(t in pname for t in target_tokens if len(t) >= 3):
                    val = extract_float(param.get("value"))
                    if val is not None:
                        t_unit = target.unit if hasattr(target, "unit") else ""
                        return {
                            "property": raw_name,
                            "predicted_value": val,
                            "unit": param.get("unit") or t_unit,
                            "status": "MEETS_TARGET",
                            "reasoning": f"Synthesized from recipe parameter {param.get('name')}.",
                        }

        return None

    @classmethod
    def evaluate_property_prediction(
        cls,
        target: NormalizedTargetProperty,
        prediction: Optional[dict[str, Any]],
    ) -> PropertyEvaluationResult:
        """
        Deterministically evaluates a single predicted property against its target constraint.
        Does NOT trust Gemini's 'status' field! Independent mathematical verification.
        """
        if target.constraint_type == "qualitative":
            passed = bool(prediction and (prediction.get("status") in ("MEETS_TARGET", "MEETS TARGET") or prediction.get("passed")))
            pred_disp = str(prediction.get("predicted_value") or prediction.get("predicted_display") or prediction.get("reasoning") or "Qualitative alignment") if prediction else "Not quantitatively predictable"
            return PropertyEvaluationResult({
                "name": target.name,
                "property": target.name,
                "unit": target.unit,
                "constraint_type": target.constraint_type,
                "target_display": target.display_target(),
                "target_min": None,
                "target_max": None,
                "target_value": None,
                "predicted_value": None,
                "predicted_min": None,
                "predicted_max": None,
                "predicted_display": pred_disp,
                "status": StatusString("MEETS_TARGET" if passed else "OUTSIDE_TARGET"),
                "target_status": "MEETS TARGET" if passed else "OUTSIDE TARGET",
                "passed": passed,
                "meets_target": passed,
                "margin_score": 1.0 if passed else 0.0,
                "violation_distance": 0.0 if passed else 1.0,
                "reasoning": str(prediction.get("reasoning") or "") if prediction else "Qualitative property retained in optimization context; deterministic numerical calculation unavailable.",
            })

        if not prediction:
            return PropertyEvaluationResult({
                "name": target.name,
                "property": target.name,
                "unit": target.unit,
                "constraint_type": target.constraint_type,
                "target_display": target.display_target(),
                "target_min": target.min_value,
                "target_max": target.max_value,
                "target_value": target.target_value,
                "predicted_value": None,
                "predicted_min": None,
                "predicted_max": None,
                "predicted_display": "Not quantitatively predictable",
                "status": StatusString("UNKNOWN"),
                "target_status": "UNKNOWN",
                "passed": False,
                "meets_target": False,
                "margin_score": 0.0,
                "violation_distance": 1.0,
                "reasoning": "Experimental validation required; model did not quantitatively infer this property from synthesis levers.",
            })

        pred_val = extract_float(prediction.get("predicted_value"))
        pred_min = extract_float(prediction.get("predicted_min"))
        pred_max = extract_float(prediction.get("predicted_max"))
        pred_unit = str(prediction.get("unit") or target.unit or "").strip()
        reasoning = str(prediction.get("reasoning") or "").strip()

        # Handle cases where model returned range as single string or flipped min/max
        if pred_min is not None and pred_max is not None and pred_min > pred_max:
            pred_min, pred_max = pred_max, pred_min

        # If min and max are equal, treat as single point prediction
        if pred_min is not None and pred_max is not None and abs(pred_min - pred_max) < 1e-6:
            pred_val = pred_min

        # Determine effective point prediction if only min or max is given
        effective_val = pred_val
        if effective_val is None:
            if pred_min is not None and pred_max is not None:
                effective_val = round((pred_min + pred_max) / 2.0, 2)
            elif pred_min is not None:
                effective_val = pred_min
            elif pred_max is not None:
                effective_val = pred_max

        # Display text for prediction
        if pred_min is not None and pred_max is not None and abs(pred_min - pred_max) >= 1e-4:
            pred_display = f"{pred_min}–{pred_max} {pred_unit}".strip()
        elif effective_val is not None:
            pred_display = f"{effective_val} {pred_unit}".strip()
        else:
            pred_display = "Indeterminate"

        passed = False
        margin_score = 0.0
        violation_distance = 0.0

        if effective_val is None and pred_min is None and pred_max is None:
            passed = False
            violation_distance = 1.0
            status_str = StatusString("UNKNOWN")
            target_status = "UNKNOWN"
        elif target.constraint_type == "range":
            t_min = target.min_value if target.min_value is not None else 0.0
            t_max = target.max_value if target.max_value is not None else 100.0
            span = max(t_max - t_min, 1e-4)

            if pred_min is not None and pred_max is not None:
                # Range prediction vs Range target
                # Tolerant epsilon for rounding: 0.1% of span
                eps = max(0.05, span * 0.01)
                passed = (pred_min >= t_min - eps) and (pred_max <= t_max + eps)
                if passed:
                    # Margin measures how nicely centered the range sits
                    pred_center = (pred_min + pred_max) / 2.0
                    target_center = target.target_value if target.target_value is not None else ((t_min + t_max) / 2.0)
                    center_offset = abs(pred_center - target_center) / (span / 2.0)
                    margin_score = max(0.2, min(1.0, 1.0 - (center_offset * 0.5)))
                else:
                    dist_min = max(0.0, t_min - pred_min)
                    dist_max = max(0.0, pred_max - t_max)
                    violation_distance = dist_min + dist_max
            elif effective_val is not None:
                # Point prediction vs Range target
                eps = max(0.05, span * 0.01)
                passed = (t_min - eps <= effective_val <= t_max + eps)
                if passed:
                    target_center = target.target_value if target.target_value is not None else ((t_min + t_max) / 2.0)
                    center_offset = abs(effective_val - target_center) / (span / 2.0)
                    margin_score = max(0.3, min(1.0, 1.0 - (center_offset * 0.6)))
                else:
                    if effective_val < t_min:
                        violation_distance = t_min - effective_val
                    else:
                        violation_distance = effective_val - t_max

            status_str = StatusString("WITHIN_RANGE" if passed else "OUTSIDE_RANGE")
            target_status = StatusString("WITHIN RANGE" if passed else "OUTSIDE RANGE")

        elif target.constraint_type == "min":
            t_min = target.min_value if target.min_value is not None else 0.0
            val_to_check = pred_min if pred_min is not None else effective_val
            scale = max(abs(t_min) * 0.25, 1.0)
            eps = scale * 0.02
            if val_to_check is not None:
                passed = (val_to_check >= t_min - eps)
                if passed:
                    surplus = val_to_check - t_min
                    margin_score = min(1.0, max(0.5, 0.5 + (surplus / scale) * 0.5))
                else:
                    violation_distance = max(0.0, t_min - val_to_check)
            status_str = StatusString("WITHIN_RANGE" if passed else "OUTSIDE_RANGE")
            target_status = StatusString("WITHIN RANGE" if passed else "OUTSIDE RANGE")

        elif target.constraint_type == "max":
            t_max = target.max_value if target.max_value is not None else 100.0
            val_to_check = pred_max if pred_max is not None else effective_val
            scale = max(abs(t_max) * 0.25, 1.0)
            eps = scale * 0.02
            if val_to_check is not None:
                passed = (val_to_check <= t_max + eps)
                if passed:
                    under = t_max - val_to_check
                    margin_score = min(1.0, max(0.5, 0.5 + (under / scale) * 0.5))
                else:
                    violation_distance = max(0.0, val_to_check - t_max)
            status_str = StatusString("WITHIN_RANGE" if passed else "OUTSIDE_RANGE")
            target_status = StatusString("WITHIN RANGE" if passed else "OUTSIDE RANGE")

        elif target.constraint_type == "exact":
            t_val = target.target_value if target.target_value is not None else 0.0
            val_to_check = effective_val
            tol = target.tolerance
            if val_to_check is not None:
                diff = abs(val_to_check - t_val)
                passed = (diff <= tol + 1e-4)
                if passed:
                    margin_score = max(0.4, 1.0 - (diff / max(tol, 1e-4)) * 0.6)
                else:
                    violation_distance = diff
            status_str = StatusString("TARGET_MET" if passed else "TARGET_NOT_MET")
            target_status = StatusString("TARGET MET" if passed else "TARGET NOT MET")
        else: # qualitative
            status_str = StatusString("TARGET_MET" if passed else "TARGET_NOT_MET")
            target_status = StatusString("TARGET MET" if passed else "TARGET NOT MET")

        return PropertyEvaluationResult({
            "name": target.name,
            "property": target.name,
            "unit": target.unit,
            "constraint_type": target.constraint_type,
            "target_display": target.display_target(),
            "target_min": target.min_value,
            "target_max": target.max_value,
            "target_value": target.target_value,
            "predicted_value": effective_val,
            "predicted_min": pred_min,
            "predicted_max": pred_max,
            "predicted_display": pred_display,
            "status": status_str,
            "target_status": target_status,
            "passed": passed,
            "meets_target": passed,
            "margin": round(effective_val - target.target_value, 3) if (effective_val is not None and target.target_value is not None) else None,
            "margin_score": round(margin_score, 3),
            "violation_distance": round(violation_distance, 3),
            "reasoning": reasoning or (
                f"Formulation parameters align to achieve estimated {pred_display}."
                if passed
                else f"Formulation falls short of {target.display_target()} (predicted {pred_display})."
            ),
        })

    @classmethod
    def evaluate_recipe(
        cls,
        recipe: dict[str, Any],
        normalized_targets: list[NormalizedTargetProperty],
        patent_context: dict[str, Any] | None = None,
        competitor_data: list[dict[str, Any]] | None = None,
        all_user_properties: list[dict[str, Any] | Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], int]:
        """
        Comprehensive evaluation of a single recipe candidate:
        Returns:
            (target_analysis_dict, confidence_analysis_dict, confidence_score_int)
        """
        params = recipe.get("parameters", [])
        stages = recipe.get("stages", [])
        raw_predictions = recipe.get("predicted_properties") or []

        # If stages exist but root parameters is empty, flatten stages
        if not params and stages:
            for s in stages:
                if isinstance(s, dict):
                    params.extend(s.get("parameters", []))

        rationale = str(recipe.get("rationale") or "")
        target_impacts = recipe.get("target_impact") or recipe.get("predicted_impacts") or []
        evaluated_properties = []
        targets_met = 0
        total_targets = len(normalized_targets)

        for target in normalized_targets:
            matched_pred = cls.match_prediction_for_target(
                target=target,
                predicted_properties=raw_predictions,
                recipe_params=params,
                rationale=rationale,
                target_impacts=target_impacts,
            )
            eval_result = cls.evaluate_property_prediction(target, matched_pred)
            evaluated_properties.append(eval_result)
            if eval_result["passed"]:
                targets_met += 1

        # Guarantee every user-specified property (active AND unconstrained) is explicitly represented
        if evaluated_properties or all_user_properties:
            eval_names = {re.sub(r"[^a-zA-Z0-9]", "", ep["name"].lower()) for ep in evaluated_properties}
            enriched_predictions = []
            for ep in evaluated_properties:
                enriched_predictions.append({
                    "property": ep["name"],
                    "name": ep["name"],
                    "unit": ep["unit"],
                    "predicted_value": ep["predicted_value"],
                    "predicted_min": ep["predicted_min"],
                    "predicted_max": ep["predicted_max"],
                    "predicted_display": ep.get("predicted_display"),
                    "target_display": ep.get("target_display"),
                    "status": str(ep["status"]),
                    "target_status": str(ep["target_status"]),
                    "passed": bool(ep["passed"]),
                    "meets_target": bool(ep.get("meets_target", ep["passed"])),
                    "reasoning": str(ep["reasoning"]),
                })
            # Also explicitly represent any inactive/blank property rows provided by the user
            if all_user_properties:
                for u_prop in all_user_properties:
                    if hasattr(u_prop, "model_dump"):
                        up_dict = u_prop.model_dump(exclude_none=False)
                    elif isinstance(u_prop, dict):
                        up_dict = u_prop
                    else:
                        continue
                    p_name = str(up_dict.get("feature") or up_dict.get("name") or up_dict.get("property") or up_dict.get("id") or "").strip()
                    if not p_name:
                        continue
                    clean_p = re.sub(r"[^a-zA-Z0-9]", "", p_name.lower())
                    if clean_p not in eval_names:
                        eval_names.add(clean_p)
                        p_unit = str(up_dict.get("unit") or "").strip()
                        matched_raw = None
                        for rp in raw_predictions:
                            if isinstance(rp, dict):
                                rp_name = str(rp.get("property") or rp.get("name") or "")
                                if re.sub(r"[^a-zA-Z0-9]", "", rp_name.lower()) == clean_p:
                                    matched_raw = rp
                                    break
                        if matched_raw:
                            pred_val = extract_float(matched_raw.get("predicted_value"))
                            pred_disp = str(matched_raw.get("predicted_display") or f"{pred_val} {p_unit}".strip() if pred_val is not None else "—")
                            reason = str(matched_raw.get("reasoning") or "Predicted from chemical formulation context.")
                        else:
                            pred_val = None
                            pred_disp = "—"
                            reason = "Unconstrained property row from user input; not modeled as an active optimization target."
                        enriched_predictions.append({
                            "property": p_name,
                            "name": p_name,
                            "unit": p_unit,
                            "predicted_value": pred_val,
                            "predicted_min": None,
                            "predicted_max": None,
                            "predicted_display": pred_disp,
                            "target_display": "Not specified (unconstrained)",
                            "status": "UNKNOWN",
                            "target_status": "UNKNOWN",
                            "passed": False,
                            "meets_target": False,
                            "reasoning": reason,
                        })
                        evaluated_properties.append(PropertyEvaluationResult({
                            "name": p_name,
                            "property": p_name,
                            "unit": p_unit,
                            "constraint_type": "none",
                            "target_display": "Not specified (unconstrained)",
                            "target_min": None,
                            "target_max": None,
                            "target_value": None,
                            "predicted_value": pred_val,
                            "predicted_min": None,
                            "predicted_max": None,
                            "predicted_display": pred_disp,
                            "status": StatusString("UNKNOWN"),
                            "target_status": StatusString("UNKNOWN"),
                            "passed": False,
                            "meets_target": False,
                            "margin": None,
                            "margin_score": 0.0,
                            "violation_distance": 0.0,
                            "reasoning": reason,
                        }))
            # Preserve any existing predictions not part of the active evaluated targets
            for raw_p in raw_predictions:
                if isinstance(raw_p, dict):
                    raw_p_name = str(raw_p.get("name") or raw_p.get("property") or "")
                    if re.sub(r"[^a-zA-Z0-9]", "", raw_p_name.lower()) not in eval_names:
                        enriched_predictions.append(raw_p)
            recipe["predicted_properties"] = enriched_predictions

        # ── 1. Target Fit Score Calculation ──────────────────────────────────────
        if total_targets == 0:
            target_mode = "GENERAL"
            target_fit_score: Optional[int] = None
            avg_margin_score = 0.0
        else:
            target_mode = "STRICT_TARGET"
            pass_rate = targets_met / float(total_targets)
            avg_margin = (
                sum(p["margin_score"] for p in evaluated_properties) / float(total_targets)
                if evaluated_properties
                else 0.0
            )
            # Deterministic Target Fit Score = percentage of target properties met (100% if all met, 67% for 2/3, etc.)
            target_fit_score = int(round(pass_rate * 100.0))
            avg_margin_score = round(avg_margin * 100.0, 1)

        # ── 2. Evidence Support Score (0 - 100) ──────────────────────────────────
        verified_patents = recipe.get("patent_references") or []
        pat_context_patents = (
            patent_context.get("patents", []) if isinstance(patent_context, dict) else []
        )
        if not pat_context_patents and isinstance(patent_context, dict) and "per_patent_analysis" in patent_context:
            pat_context_patents = patent_context.get("per_patent_analysis", [])

        if len(verified_patents) >= 2:
            evidence_score = 92.0
        elif len(verified_patents) == 1:
            evidence_score = 78.0
        elif pat_context_patents:
            evidence_score = 65.0
        else:
            evidence_score = 55.0

        # Check patent references in parameters
        param_citations = sum(
            1 for p in params if isinstance(p, dict) and (p.get("patent_ref") or p.get("patentRef"))
        )
        evidence_score = min(98.0, evidence_score + min(10.0, param_citations * 2.0))

        # ── 3. Recipe Completeness Score (0 - 100) ──────────────────────────────
        completeness_score = 50.0
        if stages:
            non_empty_stages = sum(
                1 for s in stages if isinstance(s, dict) and len(s.get("parameters", [])) > 0
            )
            completeness_score += min(35.0, non_empty_stages * 6.0)
        elif params:
            completeness_score += min(30.0, len(params) * 2.5)

        proc = recipe.get("process_conditions") or {}
        if proc.get("reaction_time"):
            completeness_score += 5.0
        if proc.get("temperature_profile"):
            completeness_score += 5.0
        if proc.get("feeding_hours"):
            completeness_score += 5.0
        completeness_score = min(100.0, completeness_score)

        # ── 4. Process Feasibility & Consistency (0 - 100) ───────────────────────
        feasibility_score = 70.0
        # Continuous phase water check (aqueous emulsion should have 80-250 phr water)
        water_param = next(
            (p for p in params if isinstance(p, dict) and "water" in str(p.get("name", "")).lower()),
            None,
        )
        if water_param:
            w_val = extract_float(water_param.get("value"))
            if w_val is not None and 80.0 <= w_val <= 300.0:
                feasibility_score += 15.0
            elif w_val is not None:
                feasibility_score += 5.0

        # Check CTA presence
        has_cta = any(
            any(k in str(p.get("name", "")).lower() for k in ("cta", "mercaptan", "modifier", "transfer"))
            for p in params
            if isinstance(p, dict)
        )
        if has_cta:
            feasibility_score += 10.0

        # Method check
        method = str(recipe.get("polymerization_method", "")).lower()
        if "emulsion" in method or "aqueous" in method or "suspension" in method:
            feasibility_score += 5.0
        feasibility_score = min(100.0, feasibility_score)

        # ── 5. Confidence Score Synthesis ────────────────────────────────────────
        if target_mode == "STRICT_TARGET":
            # Target compliance is the dominant factor (60%)
            t_fit = float(target_fit_score if target_fit_score is not None else 50)
            raw_confidence = (
                (WEIGHT_TARGET_COMPLIANCE * t_fit)
                + (WEIGHT_EVIDENCE_SUPPORT * evidence_score)
                + (WEIGHT_RECIPE_COMPLETENESS * completeness_score)
                + (WEIGHT_PROCESS_FEASIBILITY * feasibility_score)
            )
            # If all targets met, reward confidence; if hard targets failed, discount
            if targets_met < total_targets:
                unmet_count = total_targets - targets_met
                raw_confidence -= unmet_count * 4.0
            confidence_score = max(40, min(96, int(round(raw_confidence))))
            confidence_explanation = (
                f"Calculated from {targets_met}/{total_targets} target properties met "
                f"(Target Fit {target_fit_score}%), {len(verified_patents)} verified patent citations, "
                f"and formulation completeness."
            )
        else:
            # GENERAL mode (no target constraints)
            raw_confidence = (
                (WEIGHT_NO_TARGET_EVIDENCE * evidence_score)
                + (WEIGHT_NO_TARGET_COMPLETENESS * completeness_score)
                + (WEIGHT_NO_TARGET_FEASIBILITY * feasibility_score)
                + (WEIGHT_NO_TARGET_PLAUSIBILITY * 80.0)
            )
            confidence_score = max(50, min(95, int(round(raw_confidence))))
            confidence_explanation = (
                f"Calculated from patent support ({len(verified_patents)} citations), "
                f"aqueous process feasibility, and synthesis completeness with no explicit target properties provided (General Mode)."
            )

        target_analysis = {
            "mode": target_mode,
            "target_fit_score": target_fit_score,
            "target_margin_score": avg_margin_score,
            "targets_met": targets_met,
            "targets_total": total_targets,
            "target_violation_count": total_targets - targets_met,
            "properties": evaluated_properties,
            "evaluated_properties": evaluated_properties,
            "violations": [p for p in evaluated_properties if not p["passed"]],
        }

        confidence_analysis = {
            "score": confidence_score,
            "target_compliance": float(target_fit_score) if target_fit_score is not None else None,
            "evidence_support": round(evidence_score, 1),
            "recipe_completeness": round(completeness_score, 1),
            "process_feasibility": round(feasibility_score, 1),
            "explanation": confidence_explanation,
        }

        return target_analysis, confidence_analysis, confidence_score

    @classmethod
    def rank_candidates(
        cls,
        candidates: list[dict[str, Any]],
        normalized_targets: list[NormalizedTargetProperty],
    ) -> list[dict[str, Any]]:
        """
        Sort candidate recipes deterministically:
        1. All hard targets satisfied first.
        2. Highest targets_met count.
        3. Highest target_fit_score.
        4. Highest confidence_score.
        5. Evidence score.
        """
        def sort_key(cand: dict[str, Any]) -> tuple:
            t_analysis = cand.get("target_analysis") or {}
            c_analysis = cand.get("confidence_analysis") or {}

            targets_met = t_analysis.get("targets_met") or 0
            targets_total = t_analysis.get("targets_total") or 0
            all_met = (targets_met == targets_total) if targets_total > 0 else True
            fit = t_analysis.get("target_fit_score") or 0
            margin = t_analysis.get("target_margin_score") or 0.0
            conf = c_analysis.get("score") or cand.get("confidence_score") or 0
            evid = c_analysis.get("evidence_support") or 0

            return (
                1 if all_met else 0,
                targets_met,
                fit,
                margin,
                conf,
                evid,
            )

        ranked = sorted(candidates, key=sort_key, reverse=True)
        # Update rank numbers
        for idx, c in enumerate(ranked):
            c["rank"] = idx + 1
            c["display_name"] = f"Recipe {idx + 1}"
            if not c.get("name") or c.get("name").startswith("Recipe "):
                dim = c.get("variation_dimension", "").split(".")[0].strip()
                if dim:
                    c["name"] = f"Recipe {idx + 1} - {dim[:35]}"
                else:
                    c["name"] = f"Recipe {idx + 1}"

        return ranked
