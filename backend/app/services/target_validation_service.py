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
    constraint_type: str = "range"  # "range" | "min" | "max" | "exact"
    tolerance: float = 0.5          # absolute tolerance for exact target
    source: str = "target_polymer"
    raw_dict: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Returns True if at least one constraint boundary is populated."""
        return (
            self.min_value is not None
            or self.max_value is not None
            or self.target_value is not None
        )

    def display_target(self) -> str:
        u = f" {self.unit}".rstrip() if self.unit else ""
        if self.constraint_type == "range":
            return f"{self.min_value}–{self.max_value}{u}"
        elif self.constraint_type == "min":
            return f"≥ {self.min_value}{u}"
        elif self.constraint_type == "max":
            return f"≤ {self.max_value}{u}"
        elif self.constraint_type == "exact":
            return f"{self.target_value}{u}"
        return "N/A"


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

            # If min and max were not explicitly provided as distinct numeric values, parse target string
            if min_v is None and max_v is None and raw_target_str is not None:
                p_min, p_max, p_tgt, p_type, p_unit = parse_target_value_string(raw_target_str)
                if p_min is not None or p_max is not None or p_tgt is not None:
                    min_v = p_min
                    max_v = p_max
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
            elif target_v is not None and min_v is None and max_v is None:
                constraint_type = "exact"
            elif min_v is not None and max_v is not None:
                constraint_type = "range"

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
                raw_dict=d,
            )

            if prop.is_active:
                normalized.append(prop)

        return normalized

    @classmethod
    def match_prediction_for_target(
        cls,
        target: NormalizedTargetProperty | str | dict,
        predicted_properties: list[dict[str, Any]],
        recipe_params: list[dict[str, Any]] | None = None,
        rationale: str = "",
    ) -> Optional[dict[str, Any]]:
        """
        Find the predicted property item matching a given target property.
        Matches by normalized token overlap and synonyms (e.g. Mooney, ACN, Solids).
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

        for p in predicted_properties:
            if not isinstance(p, dict):
                continue
            p_name = str(p.get("property") or p.get("name") or "").strip()
            p_clean = re.sub(r"[^a-zA-Z0-9]", " ", p_name.lower()).strip()
            p_tokens = set(p_clean.split())

            if not p_tokens or not target_tokens:
                continue

            # Exact string match
            if target_name_clean == p_clean:
                return p

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
            return best_match

        # Fallback: check if recipe parameters disclose a value for this target
        if recipe_params:
            for param in recipe_params:
                pname = str(param.get("name", "")).lower()
                if any(t in pname for t in target_tokens if len(t) >= 3):
                    val = extract_float(param.get("value"))
                    if val is not None:
                        return {
                            "property": target.name,
                            "predicted_value": val,
                            "unit": param.get("unit") or target.unit,
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
                "predicted_display": "Not predicted",
                "status": "NOT_MET",
                "passed": False,
                "margin_score": 0.0,
                "violation_distance": 1.0,
                "reasoning": "Model did not provide a predicted outcome for this target property.",
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
                    target_center = (t_min + t_max) / 2.0
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
                    target_center = (t_min + t_max) / 2.0
                    center_offset = abs(effective_val - target_center) / (span / 2.0)
                    margin_score = max(0.3, min(1.0, 1.0 - (center_offset * 0.6)))
                else:
                    if effective_val < t_min:
                        violation_distance = t_min - effective_val
                    else:
                        violation_distance = effective_val - t_max

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

        status_str = "MEETS_TARGET" if passed else "NOT_MET"

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
            "passed": passed,
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
        evaluated_properties = []
        targets_met = 0
        total_targets = len(normalized_targets)

        for target in normalized_targets:
            matched_pred = cls.match_prediction_for_target(
                target=target,
                predicted_properties=raw_predictions,
                recipe_params=params,
                rationale=rationale,
            )
            eval_result = cls.evaluate_property_prediction(target, matched_pred)
            evaluated_properties.append(eval_result)
            if eval_result["passed"]:
                targets_met += 1

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
            confidence_score = max(50, min(94, int(round(raw_confidence))))
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
            conf = c_analysis.get("score") or cand.get("confidence_score") or 0
            evid = c_analysis.get("evidence_support") or 0

            return (
                1 if all_met else 0,
                targets_met,
                fit,
                conf,
                evid,
            )

        ranked = sorted(candidates, key=sort_key, reverse=True)
        # Update rank numbers
        for idx, c in enumerate(ranked):
            c["rank"] = idx + 1
            if not c.get("name") or c.get("name").startswith("Recipe "):
                dim = c.get("variation_dimension", "").split(".")[0].strip()
                if dim:
                    c["name"] = f"Recipe {idx + 1} - {dim[:35]}"
                else:
                    c["name"] = f"Recipe {idx + 1}"

        return ranked
