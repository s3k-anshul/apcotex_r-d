"""
backend/app/services/recipe_pdf_service.py

PDF export service for Apcotex Recipe Simulator candidate recipes.
Renders all 5 generated polymerization recipes vertically into a single
high-quality, print-ready PDF matching the Recipe Card UI styling.
"""
import html
import io
import logging
import re
from typing import Any

from xhtml2pdf import pisa
from app.services.pipeline.report_service import _ensure_pdf_font

logger = logging.getLogger(__name__)

CANONICAL_STAGE_NAMES = [
    "Reactor Charge",
    "Emulsifier Solution",
    "Catalyst Solution",
    "Monomer Mix",
    "Chemical Stripping",
    "Post Addition",
]


def _escape(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


def _clean_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    return s if s else ""


def _extract_number(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    m = re.search(r"[-+]?\d*\.?\d+", str(val))
    return float(m.group(0)) if m else None


def get_default_template_properties(compound_name: str = "") -> list[dict[str, str]]:
    """
    Returns the established default recipe property template definitions.
    Compound-agnostic: adapts primary monomer to NBR / SBR / generic copolymers.
    """
    cmp_lower = (compound_name or "").lower()
    if "sbr" in cmp_lower or "styrene butadiene" in cmp_lower:
        primary_monomer = {"name": "Bound Styrene Content", "unit": "%"}
    elif "nbr" in cmp_lower or "acrylonitrile" in cmp_lower or "nitrile" in cmp_lower:
        primary_monomer = {"name": "Bound Acrylonitrile (BACN)", "unit": "%"}
    else:
        primary_monomer = {"name": "Bound Monomer Content (BACN)", "unit": "%"}

    return [
        primary_monomer,
        {"name": "Mooney (ML1+4 @ 100°C)", "unit": "MU"},
        {"name": "Stress Relaxation", "unit": "sec"},
    ]


def filter_relevant_properties_for_display(
    recipe_properties: list[dict[str, Any]],
    user_properties: list[dict[str, Any]] | None = None,
    compound_name: str = "",
) -> list[dict[str, Any]]:
    """
    Deterministically filters properties according to the inclusion rules:
    1. Include each property explicitly supplied by the user (with active target/range).
    2. Include each property in the established default recipe property template.
    3. Deduplicate by normalized identifier, preserving preferred display name and unit.
    4. Do not include unconstrained rows from the global property catalog.
    """
    def _norm(name: str) -> str:
        s = re.sub(r"[^a-zA-Z0-9]", "", (name or "").lower())
        # Map common synonyms
        if any(k in s for k in ("bacn", "boundacrylonitrile", "boundacn", "boundmonomer", "boundstyrene")):
            return "monomer_bound"
        if "mooney" in s:
            return "mooney_viscosity"
        if "stressrelax" in s or s == "sr":
            return "stress_relaxation"
        return s

    # 1. Determine explicitly supplied user targets
    user_supplied_keys: set[str] = set()
    user_prop_map: dict[str, dict[str, Any]] = {}
    if user_properties:
        for up in user_properties:
            p_name = str(up.get("feature") or up.get("name") or up.get("property") or up.get("id") or "").strip()
            if not p_name:
                continue
            has_val = (
                (up.get("min") is not None and str(up.get("min")).strip() != "")
                or (up.get("max") is not None and str(up.get("max")).strip() != "")
                or (up.get("target") is not None and str(up.get("target")).strip() != "")
                or (up.get("value") is not None and str(up.get("value")).strip() != "")
            )
            k = _norm(p_name)
            if has_val:
                user_supplied_keys.add(k)
                user_prop_map[k] = up

    # 2. Determine default template properties
    default_template = get_default_template_properties(compound_name)
    default_keys = {_norm(dt["name"]) for dt in default_template}
    default_map = {_norm(dt["name"]): dt for dt in default_template}

    allowed_keys = user_supplied_keys | default_keys

    # 3. Match against candidate recipe properties
    seen_keys: set[str] = set()
    result: list[dict[str, Any]] = []

    for prop in recipe_properties:
        p_name = str(prop.get("name") or prop.get("property") or "").strip()
        if not p_name:
            continue
        k = _norm(p_name)
        if k in allowed_keys and k not in seen_keys:
            seen_keys.add(k)
            # Ensure name and unit are formatted cleanly
            clean_item = dict(prop)
            if k in default_map and (k not in user_supplied_keys or not clean_item.get("unit")):
                clean_item.setdefault("unit", default_map[k]["unit"])
            result.append(clean_item)

    # 4. If any default template properties are missing from recipe output, include them with UNKNOWN
    for dt in default_template:
        k = _norm(dt["name"])
        if k not in seen_keys:
            seen_keys.add(k)
            u_info = user_prop_map.get(k)
            target_disp = ""
            if u_info:
                u_min = u_info.get("min")
                u_max = u_info.get("max")
                u_tgt = u_info.get("target") or u_info.get("value")
                u_u = u_info.get("unit") or dt["unit"]
                if u_min is not None and u_max is not None and str(u_min).strip() and str(u_max).strip():
                    target_disp = f"{u_min}–{u_max} {u_u}".strip()
                elif u_tgt is not None and str(u_tgt).strip():
                    target_disp = f"Target: {u_tgt} {u_u}".strip()
                elif u_min is not None and str(u_min).strip():
                    target_disp = f"≥ {u_min} {u_u}".strip()
                elif u_max is not None and str(u_max).strip():
                    target_disp = f"≤ {u_max} {u_u}".strip()
            
            result.append({
                "property": dt["name"],
                "name": dt["name"],
                "unit": dt["unit"],
                "predicted_value": None,
                "predicted_display": "—",
                "target_display": target_disp if target_disp else "Not specified",
                "status": "UNKNOWN",
                "target_status": "UNKNOWN",
                "passed": False,
                "meets_target": False,
                "reasoning": "Experimental validation required; model did not quantitatively infer this property from synthesis levers.",
            })

    return result


class RecipePdfService:
    """Service to render all 5 generated recipes into a comprehensive PDF document."""

    @classmethod
    def generate_recipes_pdf(
        cls,
        recipes: list[dict[str, Any]],
        compound_name: str = "Polymer Formulation",
        cycle_info: dict[str, Any] | None = None,
    ) -> bytes:
        """
        Generates binary PDF bytes containing all 5 recipes stacked vertically.
        """
        font_family = _ensure_pdf_font()
        cycle_info = cycle_info or {}
        user_props = cycle_info.get("target_properties") or []

        html_content = cls._build_html_document(
            recipes=recipes,
            compound_name=compound_name,
            cycle_info=cycle_info,
            user_props=user_props,
            font_family=font_family,
        )

        output = io.BytesIO()
        pisa_status = pisa.CreatePDF(
            io.BytesIO(html_content.encode("utf-8")),
            dest=output,
            encoding="utf-8",
        )
        if pisa_status.err:
            logger.error("xhtml2pdf rendering failed for recipes: %s", pisa_status.err)
            raise RuntimeError("Failed to render Recipe PDF")

        return output.getvalue()

    @classmethod
    def _build_html_document(
        cls,
        recipes: list[dict[str, Any]],
        compound_name: str,
        cycle_info: dict[str, Any],
        user_props: list[dict[str, Any]],
        font_family: str,
    ) -> str:
        css = cls._build_css(font_family)
        header_section = cls._build_header(compound_name, recipes, cycle_info)
        cards_html = []

        for idx, recipe in enumerate(recipes, start=1):
            cards_html.append(cls._build_single_recipe_card(idx, recipe, compound_name, user_props, cycle_info))

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>Apcotex Generated Polymerization Recipes - {_escape(compound_name)}</title>
<style>
{css}
</style>
</head>
<body>
{header_section}
<div class="recipes-container">
{"".join(cards_html)}
</div>
</body>
</html>"""

    @classmethod
    def _build_css(cls, font_family: str) -> str:
        return f"""
        @page {{
            size: a4 portrait;
            margin: 1.2cm 1.0cm 1.2cm 1.0cm;
        }}

        body {{
            font-family: "{font_family}", Helvetica, Arial, sans-serif;
            color: #1e293b;
            font-size: 8.5pt;
            line-height: 1.35;
            margin: 0;
            padding: 0;
        }}

        .doc-header {{
            background-color: #1F5FA8;
            color: #ffffff;
            padding: 14px 18px;
            border-radius: 6px;
            margin-bottom: 16px;
        }}

        .doc-header h1 {{
            font-size: 14pt;
            font-weight: bold;
            margin: 0 0 4px 0;
            color: #ffffff;
        }}

        .doc-header p {{
            font-size: 8.5pt;
            margin: 0;
            color: #E0E7FF;
        }}

        .recipe-card {{
            border: 1.5px solid #CBD5E1;
            border-radius: 6px;
            margin-bottom: 22px;
            background: #ffffff;
            page-break-inside: auto;
        }}

        .page-break {{
            page-break-before: always;
        }}

        .card-header {{
            background-color: #F8FAFC;
            border-bottom: 1.5px solid #CBD5E1;
            padding: 10px 14px;
        }}

        .card-header-table {{
            width: 100%;
            border-collapse: collapse;
        }}

        .card-title {{
            font-size: 11pt;
            font-weight: bold;
            color: #1F5FA8;
            margin: 0;
        }}

        .badge {{
            display: inline-block;
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 7.5pt;
            font-weight: bold;
            margin-left: 5px;
        }}

        .badge-fit {{
            background-color: #E0F2FE;
            color: #0369A1;
            border: 1px solid #BAE6FD;
        }}

        .badge-met {{
            background-color: #DCFCE7;
            color: #15803D;
            border: 1px solid #BBF7D0;
        }}

        .badge-conf {{
            background-color: #FEF3C7;
            color: #B45309;
            border: 1px solid #FDE68A;
        }}

        .identity-bar {{
            background-color: #F1F5F9;
            padding: 6px 14px;
            border-bottom: 1px solid #E2E8F0;
            font-size: 8pt;
            color: #334155;
        }}

        .identity-bar strong {{
            color: #0f172a;
        }}

        .card-body {{
            padding: 12px 14px;
        }}

        .section-title {{
            font-size: 9pt;
            font-weight: bold;
            color: #1F5FA8;
            border-bottom: 1.5px solid #1FB7B5;
            padding-bottom: 3px;
            margin-top: 10px;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        table.data-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 10px;
            font-size: 8pt;
        }}

        table.data-table th {{
            background-color: #F1F5F9;
            color: #334155;
            font-weight: bold;
            text-align: left;
            padding: 5px 7px;
            border: 1px solid #CBD5E1;
        }}

        table.data-table td {{
            padding: 5px 7px;
            border: 1px solid #E2E8F0;
            vertical-align: top;
        }}

        .stage-box {{
            background: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 4px;
            padding: 6px 8px;
            margin-bottom: 6px;
        }}

        .stage-title {{
            font-weight: bold;
            color: #1e293b;
            font-size: 8pt;
            margin-bottom: 4px;
        }}

        .tag-pass {{
            background-color: #DCFCE7;
            color: #15803D;
            font-weight: bold;
            padding: 2px 5px;
            border-radius: 3px;
            font-size: 7.5pt;
        }}

        .tag-fail {{
            background-color: #FEE2E2;
            color: #B91C1C;
            font-weight: bold;
            padding: 2px 5px;
            border-radius: 3px;
            font-size: 7.5pt;
        }}

        .tag-unknown {{
            background-color: #F1F5F9;
            color: #64748B;
            font-weight: bold;
            padding: 2px 5px;
            border-radius: 3px;
            font-size: 7.5pt;
        }}

        .patent-box {{
            background-color: #EFF6FF;
            border: 1px solid #BFDBFE;
            border-radius: 4px;
            padding: 6px 10px;
            font-size: 8pt;
            color: #1E40AF;
            margin-top: 6px;
        }}
        """

    @classmethod
    def _build_header(
        cls,
        compound_name: str,
        recipes: list[dict[str, Any]],
        cycle_info: dict[str, Any],
    ) -> str:
        count = len(recipes)
        process_type = cycle_info.get("process_type") or "Batch Emulsion"
        return f"""
        <div class="doc-header">
            <h1>APCOTEX R&amp;D PRODUCT RECIPE SIMULATOR</h1>
            <p><strong>Candidate Polymerization Formulations:</strong> {_escape(compound_name)} &nbsp;|&nbsp; <strong>Total Recipes:</strong> {count} &nbsp;|&nbsp; <strong>Default Process:</strong> {_escape(process_type)}</p>
        </div>
        """

    @classmethod
    def _build_single_recipe_card(
        cls,
        rank: int,
        recipe: dict[str, Any],
        compound_name: str,
        user_props: list[dict[str, Any]],
        cycle_info: dict[str, Any],
    ) -> str:
        raw = recipe.get("recipe_data") if isinstance(recipe.get("recipe_data"), dict) else recipe
        name = recipe.get("display_name") or recipe.get("name") or raw.get("name") or f"Recipe {rank}"
        variation = raw.get("variation_dimension") or ""

        # Extract scores
        ta = raw.get("target_analysis") or recipe.get("target_analysis") or {}
        fit_score = recipe.get("target_fit_score") or ta.get("target_fit_score") or raw.get("target_fit_score")
        met = recipe.get("targets_met") if recipe.get("targets_met") is not None else ta.get("targets_met")
        tot = recipe.get("targets_total") if recipe.get("targets_total") is not None else ta.get("targets_total")
        conf = recipe.get("confidence_score") or raw.get("confidence_score")

        badges_html = []
        if fit_score is not None:
            badges_html.append(f'<span class="badge badge-fit">Target Fit: {fit_score}%</span>')
        if met is not None and tot is not None:
            badges_html.append(f'<span class="badge badge-met">Targets Met: {met}/{tot}</span>')
        if conf is not None:
            badges_html.append(f'<span class="badge badge-conf">Confidence: {conf}%</span>')

        # Reaction temperature and process
        process_type = raw.get("process_type") or cycle_info.get("process_type") or "Batch"
        conds = raw.get("process_conditions") or {}
        temp_prof = conds.get("temperature_profile") or []
        op_temp = None
        if temp_prof and isinstance(temp_prof, list):
            first_step = temp_prof[0]
            if isinstance(first_step, dict):
                op_temp = f"{first_step.get('value', '')} {first_step.get('unit', '°C')}".strip()

        target_tr = cycle_info.get("temperature_range") or raw.get("temperature_range")
        tr_disp = ""
        if isinstance(target_tr, dict) and target_tr.get("min") is not None and target_tr.get("max") is not None:
            tr_disp = f"{target_tr['min']}–{target_tr['max']} {target_tr.get('unit', '°C')}"
        elif target_tr:
            tr_disp = str(target_tr)

        temp_summary = op_temp or tr_disp or "Controlled Reaction Temperature"
        if op_temp and tr_disp and op_temp != tr_disp:
            temp_summary = f"{op_temp} (Target Range: {tr_disp})"

        # Canonical stages
        stages_html = cls._build_stages_section(raw)

        # Process conditions
        conds_html = cls._build_process_conditions_section(conds)

        # Systems (Catalyst, Activator, Coagulation)
        systems_html = cls._build_systems_section(raw)

        # Target properties & model predictions
        preds_html = cls._build_predictions_section(recipe, raw, user_props, compound_name)

        # Patent references
        patents = recipe.get("patent_references") or raw.get("patent_references") or []
        patent_html = ""
        if patents:
            p_str = ", ".join(patents)
            patent_html = f"""
            <div class="patent-box">
                <strong>Patent Support &amp; Citations:</strong> {_escape(p_str)}
            </div>
            """

        page_break_class = "page-break" if rank > 1 else ""

        return f"""
        <div class="recipe-card {page_break_class}">
            <div class="card-header">
                <table class="card-header-table">
                    <tr>
                        <td>
                            <div class="card-title">Candidate {rank}: {_escape(name)}</div>
                            {f'<div style="font-size:7.5pt; color:#64748B; margin-top:2px;">Dimension: {_escape(variation)}</div>' if variation else ''}
                        </td>
                        <td style="text-align: right;">
                            {" ".join(badges_html)}
                        </td>
                    </tr>
                </table>
            </div>

            <div class="identity-bar">
                <strong>Target Polymer:</strong> {_escape(compound_name)} &nbsp;|&nbsp;
                <strong>Process Type:</strong> {_escape(process_type)} &nbsp;|&nbsp;
                <strong>Operating Temperature:</strong> {_escape(temp_summary)}
            </div>

            <div class="card-body">
                <div class="section-title">1. Synthesis Stages (Canonical Order)</div>
                {stages_html}

                <div class="section-title">2. Process Conditions</div>
                {conds_html}

                <div class="section-title">3. Catalyst, Activator &amp; Coagulation Systems</div>
                {systems_html}

                <div class="section-title">4. Target Polymer Properties &amp; Model Predictions</div>
                {preds_html}

                {patent_html}
            </div>
        </div>
        """

    @classmethod
    def _build_stages_section(cls, raw: dict[str, Any]) -> str:
        stages = raw.get("stages") or []
        if not stages:
            return '<p style="color:#64748B; font-style:italic;">No discrete stage formulation provided.</p>'

        rows = []
        for s_idx, stg in enumerate(stages, start=1):
            s_name = stg.get("name") or stg.get("stage_name") or f"Stage {s_idx}"
            applicable = stg.get("applicable", True)
            omission = stg.get("omission_reason") or ""
            params = stg.get("parameters") or []

            if applicable is False or (omission and not params):
                content = f'<span style="color:#64748B; font-style:italic;">Not applicable — {_escape(omission or "Omitted per chemistry")}</span>'
            elif not params:
                content = '<span style="color:#64748B; font-style:italic;">Standard reactor setup</span>'
            else:
                items = []
                for p in params:
                    p_name = p.get("name") or "Chemical"
                    val = p.get("value") or ""
                    unit = p.get("unit") or ""
                    func = p.get("function") or ""
                    func_str = f" ({func})" if func else ""
                    val_str = f"{val} {unit}".strip()
                    items.append(f"<strong>{_escape(p_name)}</strong>: {_escape(val_str)}{_escape(func_str)}")
                content = "; &nbsp; ".join(items)

            rows.append(f"""
            <tr>
                <td style="width: 25%; font-weight:bold; background-color:#F8FAFC;">{_escape(s_name)}</td>
                <td style="width: 75%;">{content}</td>
            </tr>
            """)

        return f"""
        <table class="data-table">
            <thead>
                <tr>
                    <th>Synthesis Stage</th>
                    <th>Ingredients, Dosages &amp; Functions</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
        """

    @classmethod
    def _build_process_conditions_section(cls, conds: dict[str, Any]) -> str:
        rx_time = conds.get("reaction_time")
        feed_hrs = conds.get("feeding_hours") or {}
        temp_prof = conds.get("temperature_profile") or []

        time_str = "Standard cycle"
        if isinstance(rx_time, dict):
            val = rx_time.get("value")
            unit = rx_time.get("unit") or "hrs"
            if val is not None:
                time_str = f"{val} {unit}"
        elif rx_time:
            time_str = str(rx_time)

        feed_items = []
        if isinstance(feed_hrs, dict):
            for k in ("monomer", "emulsifier", "catalyst", "activator"):
                v = feed_hrs.get(k)
                if v is not None and str(v).strip():
                    feed_items.append(f"{k.capitalize()}: {v} hrs")
        feed_str = ", ".join(feed_items) if feed_items else "Batch addition / single charge"

        temp_steps = []
        if isinstance(temp_prof, list):
            for step in temp_prof:
                if isinstance(step, dict):
                    stg = step.get("stage") or "Step"
                    v = step.get("value")
                    u = step.get("unit") or "°C"
                    if v is not None:
                        temp_steps.append(f"{stg}: {v} {u}")
        temp_prof_str = " → ".join(temp_steps) if temp_steps else "Isothermal control"

        return f"""
        <table class="data-table">
            <tbody>
                <tr>
                    <td style="width: 33%;"><strong>Total Reaction Time:</strong><br/>{_escape(time_str)}</td>
                    <td style="width: 33%;"><strong>Feeding Duration:</strong><br/>{_escape(feed_str)}</td>
                    <td style="width: 34%;"><strong>Temperature Profile:</strong><br/>{_escape(temp_prof_str)}</td>
                </tr>
            </tbody>
        </table>
        """

    @classmethod
    def _build_systems_section(cls, raw: dict[str, Any]) -> str:
        cat = raw.get("catalyst_system") or {}
        act = raw.get("activator_system") or {}
        coag = raw.get("coagulation_system") or {}

        # Catalyst
        cat_name = cat.get("primary_catalyst") or cat.get("name") or "Redox initiator system"
        cat_dose = cat.get("dosage") or (f"{cat.get('dosage_phr')} phr" if cat.get("dosage_phr") else "")
        cat_str = f"{cat_name} ({cat_dose})" if cat_dose else cat_name

        # Activator
        act_app = act.get("applicable", True)
        if act_app is False:
            act_str = "Not applicable / Not required"
        else:
            act_name = act.get("activator") or act.get("name") or "Reducing agent (SFS / Fe-EDTA)"
            act_dose = act.get("dosage") or (f"{act.get('dosage_phr')} phr" if act.get("dosage_phr") else "")
            act_str = f"{act_name} ({act_dose})" if act_dose else act_name

        # Coagulation
        coag_app = coag.get("applicable", True)
        if coag_app is False:
            coag_str = "Not applicable (Latex product)"
        else:
            coag_name = coag.get("coagulant") or coag.get("name") or "Calcium chloride / Acid-salt"
            coag_cond = coag.get("process_conditions") or ""
            coag_str = f"{coag_name} ({coag_cond})" if coag_cond else coag_name

        return f"""
        <table class="data-table">
            <tbody>
                <tr>
                    <td style="width: 33%;"><strong>Catalyst System:</strong><br/>{_escape(cat_str)}</td>
                    <td style="width: 33%;"><strong>Activator System:</strong><br/>{_escape(act_str)}</td>
                    <td style="width: 34%;"><strong>Coagulation System:</strong><br/>{_escape(coag_str)}</td>
                </tr>
            </tbody>
        </table>
        """

    @classmethod
    def _build_predictions_section(
        cls,
        recipe: dict[str, Any],
        raw: dict[str, Any],
        user_props: list[dict[str, Any]],
        compound_name: str,
    ) -> str:
        # Gather all candidate properties
        props = list(recipe.get("predicted_properties") or raw.get("predicted_properties") or [])
        if not props and raw.get("target_analysis"):
            props = list(raw["target_analysis"].get("properties") or [])

        # Filter strictly to relevant properties (user targets + default template)
        relevant_props = filter_relevant_properties_for_display(
            recipe_properties=props,
            user_properties=user_props,
            compound_name=compound_name,
        )

        if not relevant_props:
            return '<p style="color:#64748B; font-style:italic;">No target property evaluations modeled.</p>'

        rows = []
        for p in relevant_props:
            name = p.get("property") or p.get("name") or "Property"
            unit = p.get("unit") or ""
            unit_suffix = f" {unit}" if unit else ""

            # Target Objective
            target_str = p.get("target_display") or ""
            if not target_str:
                t_min = p.get("target_min")
                t_max = p.get("target_max")
                t_val = p.get("target_value")
                if t_min is not None and t_max is not None:
                    target_str = f"{t_min}–{t_max}{unit_suffix}"
                elif t_val is not None:
                    target_str = f"Target: {t_val}{unit_suffix}"
                elif t_min is not None:
                    target_str = f"≥ {t_min}{unit_suffix}"
                elif t_max is not None:
                    target_str = f"≤ {t_max}{unit_suffix}"
                else:
                    target_str = "Not specified"

            # Model Prediction (point estimate)
            pred_val = p.get("predicted_value")
            pred_disp = p.get("predicted_display")
            if pred_val is not None:
                pred_str = f"{pred_val}{unit_suffix}"
            elif pred_disp and pred_disp != "—":
                pred_str = pred_disp
            elif p.get("predicted_min") is not None and p.get("predicted_max") is not None:
                pred_str = f"{p['predicted_min']}–{p['predicted_max']}{unit_suffix}"
            else:
                pred_str = "—"

            # Status Badge
            status = str(p.get("status") or p.get("target_status") or "UNKNOWN").upper()
            meets = bool(p.get("passed") or p.get("meets_target"))
            is_unknown = "UNKNOWN" in status or pred_str == "—"

            if is_unknown:
                badge = '<span class="tag-unknown">UNKNOWN</span>'
            elif meets or "WITHIN" in status or "MET" in status:
                badge = '<span class="tag-pass">WITHIN RANGE</span>'
            else:
                badge = '<span class="tag-fail">OUTSIDE RANGE</span>'

            reasoning = p.get("reasoning") or "Model prediction based on synthesis levers and reaction kinetics."

            rows.append(f"""
            <tr>
                <td style="width: 22%; font-weight:bold;">{_escape(name)}</td>
                <td style="width: 20%;">{_escape(target_str)}</td>
                <td style="width: 18%; font-weight:bold; color:#1F5FA8;">{_escape(pred_str)}</td>
                <td style="width: 15%; text-align:center;">{badge}</td>
                <td style="width: 25%; font-size:7.5pt; color:#475569;">{_escape(reasoning)}</td>
            </tr>
            """)

        return f"""
        <table class="data-table">
            <thead>
                <tr>
                    <th>Target Property</th>
                    <th>Target Objective</th>
                    <th>Model Prediction</th>
                    <th style="text-align:center;">Status</th>
                    <th>Chemical Levers &amp; Rationale</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
        """
