"""
app/services/pipeline/report_service.py

Aggregates extracted patent data, generates a Markdown report via Gemini,
and exports the final report to PDF and DOCX formats.
"""
import html
import logging
import os
import re
import uuid
from typing import List, Tuple, Dict, Optional

from docx import Document
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xhtml2pdf import pisa

from app.services.llm.llm_client import llm_client
from app.services.pipeline.schemas import (
    ReportPatentEvidence, PatentResearchReport, LLMPatentResearchReport,
    LLMPatentAnalysis,
    ReportPatent, ReportPatentDetails, ReportPatentMethodology, PatentExtraction,
    MediumAndWaterRoleEvidence, DynamicTargetAttributeEvidence,
    ReportComparisonDimension,
)
from app.services.prompts.patent_prompts import (
    REPORT_GENERATION_SYSTEM_PROMPT,
    REPORT_GENERATION_USER_TEMPLATE
)

logger = logging.getLogger(__name__)

_PDF_FONT_FAMILY = "Helvetica"
_PDF_FONT_READY = False
_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def _ensure_pdf_font() -> str:
    """Register a Unicode face for PDF text. Helvetica cannot draw Greek letters."""
    global _PDF_FONT_FAMILY, _PDF_FONT_READY
    if _PDF_FONT_READY:
        return _PDF_FONT_FAMILY
    regular_candidates = (
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    )
    bold_candidates = (
        r"C:\Windows\Fonts\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    )
    regular = next((path for path in regular_candidates if os.path.isfile(path)), "")
    bold = next((path for path in bold_candidates if os.path.isfile(path)), "")
    if regular:
        try:
            pdfmetrics.registerFont(TTFont("ApcotexSans", regular))
            if bold:
                pdfmetrics.registerFont(TTFont("ApcotexSans-Bold", bold))
            else:
                pdfmetrics.registerFont(TTFont("ApcotexSans-Bold", regular))
            pdfmetrics.registerFontFamily(
                "ApcotexSans",
                normal="ApcotexSans",
                bold="ApcotexSans-Bold",
                italic="ApcotexSans",
                boldItalic="ApcotexSans-Bold",
            )
            _PDF_FONT_FAMILY = "ApcotexSans"
        except Exception:
            logger.exception("PDF Unicode font registration failed; using Helvetica")
            _PDF_FONT_FAMILY = "Helvetica"
    _PDF_FONT_READY = True
    return _PDF_FONT_FAMILY


def _pdf_text(text: str, break_long: bool = False, limit: int = 16) -> str:
    """Escape report text for XHTML. Optionally break tokens that cannot wrap."""
    if text is None:
        return ""
    raw = str(text)
    if not break_long:
        return html.escape(raw)
    pieces = []
    for token in raw.split(" "):
        escaped = html.escape(token)
        if len(token) <= limit:
            pieces.append(escaped)
            continue
        chunks = [
            html.escape(token[index:index + limit])
            for index in range(0, len(token), limit)
        ]
        pieces.append("<br/>".join(chunks))
    return " ".join(pieces)


def _is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    cells = [cell for cell in cells if cell]
    return bool(cells) and all(_SEPARATOR_CELL.match(cell) for cell in cells)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _comparison_widths(headers: list[str]) -> list[int]:
    weights = []
    for header in headers:
        key = header.strip().lower()
        if key == "patent":
            weights.append(14)
        elif key in {"applicant", "assignee"}:
            weights.append(16)
        elif key == "title":
            weights.append(22)
        elif key in {"year", "jurisdiction"}:
            weights.append(8)
        elif "method" in key or "synthesis" in key:
            weights.append(20)
        elif key in {"priority", "date"}:
            weights.append(10)
        elif key in {"key findings", "key finding"}:
            weights.append(20)
        else:
            weights.append(16)
    total = sum(weights) or 1
    widths = [max(1, int(round(100 * weight / total))) for weight in weights]
    widths[-1] = max(1, widths[-1] + (100 - sum(widths)))
    return widths


def _comparison_table_html(table_lines: list[str], is_wide: bool = False) -> str:
    rows = []
    for line in table_lines:
        if _is_table_separator(line):
            continue
        rows.append(_split_table_row(line))
    if not rows:
        return ""
    header = rows[0]
    width_count = max(len(row) for row in rows)
    if len(header) < width_count:
        header = header + [""] * (width_count - len(header))
    widths = _comparison_widths(header)

    def break_limit(header: str) -> int:
        key = header.strip().lower()
        if key in {"priority", "date", "year", "jurisdiction"}:
            return 12
        if key == "patent":
            return 18
        if key in {"applicant", "assignee", "key findings", "key finding"}:
            return 20
        return 22

    def cell(tag: str, value: str, width: int, header: str) -> str:
        return (
            f'<{tag} width="{width}%">'
            f"{_pdf_text(value, break_long=True, limit=break_limit(header))}</{tag}>"
        )

    head = "<tr>" + "".join(
        cell("th", header[index], widths[index], header[index]) for index in range(width_count)
    ) + "</tr>"
    body_rows = []
    for row in rows[1:]:
        padded = row + [""] * (width_count - len(row))
        body_rows.append(
            "<tr>" + "".join(
                cell("td", padded[index], widths[index], header[index])
                for index in range(width_count)
            ) + "</tr>"
        )
    table_cls = "compare compare-wide" if (is_wide or width_count > 6) else "compare"
    return (
        f'<table class="{table_cls}" repeat="1">'
        f"<thead>{head}</thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def _metadata_table_html(items: list[tuple[str, str]]) -> str:
    rows = []
    for label, value in items:
        rows.append(
            "<tr>"
            f'<td class="meta-label" width="28%">{_pdf_text(label)}</td>'
            f'<td width="72%">{_pdf_text(value, break_long=True, limit=48)}</td>'
            "</tr>"
        )
    return f'<table class="meta">{"".join(rows)}</table>'


def _bullet_list_html(items: list[str]) -> str:
    if not items:
        return ""
    import re
    formatted = []
    for item in items:
        escaped = _pdf_text(item, break_long=True, limit=60)
        bold_formatted = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        formatted.append(f"<li>{bold_formatted}</li>")
    return f"<ul>{''.join(formatted)}</ul>"


def _looks_like_label(item: str) -> bool:
    label, separator, _value = item.partition(": ")
    return bool(separator) and label and len(label) <= 80 and "\n" not in label


def pdf_html_from_markdown(markdown_text: str) -> str:
    """
    PDF-only structure for the existing report Markdown.

    Does not alter the Markdown stored for the web view or the DOCX exporter.
    """
    lines = (markdown_text or "").splitlines()
    body: list[str] = []
    index = 0
    landscape = False

    def skip_blank(position: int) -> int:
        while position < len(lines) and not lines[position].strip():
            position += 1
        return position

    def close_landscape() -> None:
        nonlocal landscape
        if landscape:
            body.append('<pdf:nexttemplate name="body"/>')
            body.append("<pdf:nextpage/>")
            landscape = False

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue

        if landscape and stripped.startswith("## "):
            close_landscape()

        if stripped.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            first_row_cells = _split_table_row(table_lines[0]) if table_lines else []
            is_wide_table = len(first_row_cells) > 6
            table_needs_landscape = is_wide_table and not landscape
            if table_needs_landscape:
                title_item = None
                if body and (body[-1].startswith("<h4>Table") or body[-1].startswith("<h4>") or "COMPARISON TABLE" in body[-1].upper()):
                    title_item = body.pop()
                body.append('<pdf:nexttemplate name="landscape"/>')
                body.append("<pdf:nextpage/>")
                if title_item:
                    body.append(title_item)
            body.append(_comparison_table_html(table_lines, is_wide=is_wide_table))
            if table_needs_landscape:
                body.append('<pdf:nexttemplate name="body"/>')
                body.append("<pdf:nextpage/>")
            continue

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            if level == 1:
                body.append(f"<h1>{_pdf_text(title)}</h1>")
                index += 1
                continue
            if level == 2:
                body.append(f"<h2>{_pdf_text(title)}</h2>")
                index += 1
                continue
            if level >= 4:
                index += 1
                meta: list[tuple[str, str]] = []
                while True:
                    index = skip_blank(index)
                    if index >= len(lines) or not lines[index].strip().startswith("- "):
                        break
                    item = lines[index].strip()[2:].strip()
                    if not _looks_like_label(item):
                        break
                    label, _, value = item.partition(": ")
                    meta.append((label, value))
                    index += 1
                number = next((value for label, value in meta if label == "Patent Number"), "")
                patent_title = next((value for label, value in meta if label == "Patent Title"), "")
                heading = title
                if number and number not in heading:
                    heading = f"{title}: {number}"
                if patent_title and patent_title not in heading:
                    heading = f"{heading} — {patent_title}"
                body.append(f'<h3 class="patent">{_pdf_text(heading)}</h3>')
                if meta:
                    body.append(_metadata_table_html(meta))
                continue
            body.append(f"<h3>{_pdf_text(title)}</h3>")
            index += 1
            continue

        if stripped.startswith("**") and stripped.endswith("**") and stripped.count("**") == 2:
            body.append(f"<h4>{_pdf_text(stripped.strip('*').strip())}</h4>")
            index += 1
            continue

        if stripped.startswith("- "):
            items = []
            while index < len(lines):
                current = lines[index].strip()
                if not current:
                    nxt = skip_blank(index)
                    if nxt < len(lines) and lines[nxt].strip().startswith("- "):
                        index = nxt
                        continue
                    break
                if not current.startswith("- "):
                    break
                item_content = current[2:].strip()
                if item_content.startswith("|") and item_content.endswith("|"):
                    break
                items.append(item_content)
                index += 1
            if items:
                body.append(_bullet_list_html(items))
            continue

        paragraph = [stripped]
        index += 1
        while index < len(lines):
            nxt = lines[index].strip()
            if not nxt:
                index += 1
                break
            if nxt.startswith(("#", "-", "|", "**")):
                break
            paragraph.append(nxt)
            index += 1
        body.append(f"<p>{_pdf_text(' '.join(paragraph))}</p>")

    close_landscape()
    font = _ensure_pdf_font()
    content = "\n".join(body)
    return f"""<html>
<head>
<style>
@page landscape {{
    size: a4 landscape;
    margin: 1.1cm;
}}
@page body {{
    size: a4 portrait;
    margin: 1.5cm;
}}
body {{
    font-family: {font};
    font-size: 10.5pt;
    line-height: 1.35;
    color: #1c1c1c;
}}
h1 {{
    font-family: {font};
    color: #003366;
    font-size: 16pt;
    margin: 0 0 8pt 0;
    padding-bottom: 4pt;
    border-bottom: 1.5pt solid #003366;
}}
h2 {{
    font-family: {font};
    color: #003366;
    font-size: 13pt;
    margin: 12pt 0 4pt 0;
    page-break-after: avoid;
}}
h3 {{
    font-family: {font};
    color: #0b3d6e;
    font-size: 11.5pt;
    margin: 10pt 0 3pt 0;
    page-break-after: avoid;
}}
h3.patent {{
    font-size: 12pt;
    margin-top: 12pt;
    page-break-after: avoid;
}}
h4 {{
    font-family: {font};
    color: #16324f;
    font-size: 10.5pt;
    margin: 8pt 0 2pt 0;
    page-break-after: avoid;
}}
p {{
    margin: 1pt 0 6pt 0;
}}
ul {{
    margin: 1pt 0 6pt 14pt;
    padding-left: 8pt;
}}
li {{
    margin: 0 0 2pt 0;
}}
table.meta {{
    width: 100%;
    border-collapse: collapse;
    margin: 2pt 0 6pt 0;
    page-break-before: avoid;
}}
table.meta td {{
    border: 0.4pt solid #c5d0dc;
    padding: 2pt 4pt;
    vertical-align: top;
    font-size: 9.5pt;
}}
td.meta-label {{
    font-weight: bold;
    background-color: #f3f6fa;
}}
table.compare {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 4pt;
    margin-bottom: 6pt;
}}
table.compare tr {{
    page-break-inside: avoid;
}}
table.compare th, table.compare td {{
    border: 0.6pt solid #8aa0b8;
    padding: 3pt 3.5pt;
    vertical-align: top;
    font-size: 8pt;
    line-height: 1.25;
    word-wrap: break-word;
}}
table.compare th {{
    background-color: #e6eef6;
    font-weight: bold;
    color: #0b3d6e;
}}
table.compare.compare-wide th, table.compare.compare-wide td {{
    font-size: 7.2pt;
    padding: 2.2pt 3pt;
    line-height: 1.2;
}}
</style>
</head>
<body>
{content}
</body>
</html>"""

_NO_WATER_SUMMARY = (
    "No water-related process step disclosed in the extracted evidence."
)
_NOT_DISCLOSED_VALUE = "Not disclosed in extracted evidence"
_DEFAULT_TARGET_LABEL = "Target Attribute"

_REPORT_REPAIR_SUFFIX = """
REPAIR / RETRY INSTRUCTION (MANDATORY):
The previous response was invalid JSON or failed schema validation.
Return ONLY a valid compact JSON object matching LLMPatentResearchReport.
Rules:
- JSON only — no markdown fences, no commentary
- Do not omit required fields (per_patent_analysis, cross_patent_comparison, references)
- One per_patent_analysis entry per patent in the REQUIRED PATENT MANIFEST
- Do NOT paste full patent text; summarize with short strings
- disclosed_parameters Up to 35; example_highlights Up to 6; evidence arrays MAX 2 snippets (<=120 chars)
- abstract 120-180 words MAX; conclusion <=120 words
- Properly escape and terminate every JSON string
- Do not invent missing technical values — use "Not disclosed in extracted evidence" when absent
"""


def strip_report_json_fences(text: str) -> str:
    """Remove optional markdown code fences around JSON. Does not alter scientific values."""
    import re

    t = (text or "").strip()
    if not t.startswith("```"):
        return t
    t = re.sub(r"^```(?:json|JSON)?\s*\n?", "", t)
    t = re.sub(r"\n?```\s*$", "", t)
    return t.strip()


def extract_outer_json_object(text: str) -> str | None:
    """
    If the response has leading/trailing noise, isolate the outermost {...} span.
    Does NOT attempt to repair truncated/unterminated strings (unsafe for science data).
    """
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    return text[start : end + 1]


def try_parse_llm_report(
    raw_text: str | None,
    *,
    expected_patent_count: int = 0,
) -> LLMPatentResearchReport | None:
    """
    Safely parse a Gemini report response into LLMPatentResearchReport.
    Supports: plain JSON, markdown-fenced JSON, JSON with minor preamble/trailer.
    Refuses dangerous reconstruction of unterminated scientific strings.
    Rejects structurally empty reports when patents were expected.
    """
    import json

    if not raw_text or not str(raw_text).strip():
        return None

    candidates = []
    stripped = strip_report_json_fences(str(raw_text))
    candidates.append(stripped)
    outer = extract_outer_json_object(stripped)
    if outer and outer not in candidates:
        candidates.append(outer)

    last_err = None
    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError as e:
            last_err = e
            continue
        try:
            parsed = LLMPatentResearchReport.model_validate(data)
        except Exception as e:
            last_err = e
            continue
        analyses = parsed.per_patent_analysis or []
        if expected_patent_count > 0 and len(analyses) == 0:
            logger.warning(
                "[REPORT] Parsed JSON but per_patent_analysis empty (expected %d) — treating as incomplete",
                expected_patent_count,
            )
            return None
        return parsed

    if last_err:
        logger.warning(
            "[REPORT] Safe JSON parse failed (no value-guessing repair): %s",
            str(last_err)[:300],
        )
    return None


def _compact_extractions_for_retry(extractions: List[ReportPatentEvidence]) -> List[ReportPatentEvidence]:
    """Reduce evidence payload on report retry without dropping patents."""
    compacted: List[ReportPatentEvidence] = []
    for ev in extractions:
        clone = ev.model_copy(deep=True)
        if clone.source_text and len(clone.source_text) > 1500:
            clone.source_text = clone.source_text[:1500] + "...[truncated for report retry]"
        for param in clone.overall_patent_parameters or []:
            if param.source_sentence and len(param.source_sentence) > 80:
                param.source_sentence = param.source_sentence[:80] + "..."
        for ex in clone.examples or []:
            if ex.raw_text and len(ex.raw_text) > 800:
                ex.raw_text = ex.raw_text[:800] + "...[truncated for report retry]"
            for param in ex.extracted_parameters or []:
                if param.source_sentence and len(param.source_sentence) > 80:
                    param.source_sentence = param.source_sentence[:80] + "..."
        for sec in clone.synthesis_sections or []:
            if sec.raw_text and len(sec.raw_text) > 600:
                sec.raw_text = sec.raw_text[:600] + "...[truncated for report retry]"
        compacted.append(clone)
    return compacted


_SECTION_SYSTEM = """You are an expert polymer scientist.
Return ONLY valid JSON matching the LLMPatentAnalysis schema for ONE patent.
Rules:
- JSON only — no markdown, no commentary
- Summarize; do NOT paste full patent text or long procedures
- disclosed_parameters Up to 35 short lines; example_highlights Up to 6
- evidence arrays MAX 2 snippets (<=120 chars)
- Do not invent values; use "Not disclosed in extracted evidence" when absent
- Properly escape and terminate every JSON string
"""


async def generate_report_via_patent_sections(
    *,
    compound_name: str,
    original_input: str,
    research_profile: str,
    extractions: List[ReportPatentEvidence],
    target_attribute_label: str,
) -> LLMPatentResearchReport:
    """
    Fallback: one structured LLMPatentAnalysis call per patent, then assemble
    LLMPatentResearchReport locally. Used when single-shot report hits MAX_TOKENS
    / malformed JSON. Same canonical schema — no second report service.
    """
    compact = _compact_extractions_for_retry(extractions)
    from app.services.pipeline.report_evidence_service import ReportEvidenceService
    svc = ReportEvidenceService()
    analyses: list[LLMPatentAnalysis] = []
    total_in = 0
    total_out = 0

    for ev in compact:
        one_json = svc.serialize_evidence([ev])
        prompt = (
            f"Compound: {compound_name}\n"
            f"Original input: {original_input}\n"
            f"Research profile: {research_profile[:1500]}\n"
            f"TARGET ATTRIBUTE LABEL: {target_attribute_label}\n"
            f"Analyze ONLY this patent: {ev.patent_number}\n"
            f"EVIDENCE:\n{one_json}\n"
            "Return one LLMPatentAnalysis object. Keep all strings concise."
        )
        obj, _provider, usage = await llm_client.generate_structured(
            prompt=prompt,
            system_prompt=_SECTION_SYSTEM,
            schema=LLMPatentAnalysis,
            temperature=0.1,
            metadata={"stage": "REPORT_GENERATION"},
        )
        total_in += int((usage or {}).get("input_tokens") or 0)
        total_out += int((usage or {}).get("output_tokens") or 0)

        if obj is None:
            raw = (usage or {}).get("raw_response_text")
            # Try wrapping as full report then extract, or parse analysis object
            import json
            salvaged_report = try_parse_llm_report(raw, expected_patent_count=0)
            if salvaged_report and salvaged_report.per_patent_analysis:
                obj = salvaged_report.per_patent_analysis[0]
            else:
                for cand in (
                    strip_report_json_fences(raw or ""),
                    extract_outer_json_object(strip_report_json_fences(raw or "")) or "",
                ):
                    if not cand:
                        continue
                    try:
                        obj = LLMPatentAnalysis.model_validate(json.loads(cand))
                        break
                    except Exception:
                        continue

        if obj is None:
            logger.error(
                "[REPORT] Sectional analysis failed for %s | finish_reason=%s",
                ev.patent_number,
                (usage or {}).get("finish_reason"),
            )
            raise ValueError(
                f"REPORT_GENERATION_FAILED: sectional analysis failed for {ev.patent_number}"
            )

        if not (obj.patent_number or "").strip():
            obj.patent_number = ev.patent_number
        obj.synthesis_method = _usable_narrative(getattr(obj, "synthesis_method", ""))
        obj.technical_relevance = _usable_narrative(getattr(obj, "technical_relevance", ""))
        obj.disclosed_parameters = [
            cleaned for cleaned in (
                _usable_narrative(item) for item in (obj.disclosed_parameters or [])
            ) if cleaned
        ]
        obj.example_highlights = [
            cleaned for cleaned in (
                _usable_narrative(item) for item in (obj.example_highlights or [])
            ) if cleaned
        ]
        analyses.append(obj)
        logger.info("[REPORT] Sectional analysis OK for %s", obj.patent_number)

    if not analyses:
        raise ValueError("REPORT_GENERATION_FAILED: sectional path produced zero analyses")

    pn_list = [a.patent_number for a in analyses]
    cross: list[str] = []
    if len(analyses) >= 2:
        cross = [
            f"Compared {len(analyses)} primary patents ({', '.join(pn_list)}) on disclosed "
            f"polymerization parameters and {target_attribute_label}."
        ]
        for a in analyses:
            if a.synthesis_method:
                cross.append(f"{a.patent_number}: {a.synthesis_method[:200]}")

    refs = []
    for ev in extractions:
        refs.append(
            f"{ev.patent_number} | {ev.title} | {ev.assignee} | {ev.jurisdiction} | "
            f"{ev.publication_year} | {ev.url}"
        )

    report = LLMPatentResearchReport(
        title=f"Patent Research Report: {compound_name}",
        abstract=(
            f"This report synthesizes extracted evidence from {len(analyses)} selected "
            f"primary patent(s) for {compound_name} (input: {original_input}). "
            f"Patents: {', '.join(pn_list)}. Focus: polymerization/synthesis parameters "
            f"and {target_attribute_label}. Values are evidence-backed only."
        ),
        per_patent_analysis=analyses,
        cross_patent_comparison=cross,
        conclusion=(
            f"Analysis of {len(analyses)} primary patent(s) for {compound_name} is complete. "
            "See per-patent disclosed parameters; undisclosed values are marked explicitly."
        ),
        references=refs,
    )
    conclusion, conclusion_ok = salvage_narrative(report.conclusion)
    if not conclusion_ok:
        raise ValueError(
            "REPORT_GENERATION_FAILED: sectional conclusion failed the repetition check"
        )
    report.conclusion = conclusion
    logger.info(
        "[REPORT] Assembled sectional report | patents=%d | in_tokens≈%d out_tokens≈%d",
        len(analyses),
        total_in,
        total_out,
    )
    return report


def resolve_target_attribute_label(
    attribute_constraint: Optional[str] = None,
    research_profile: Optional[object] = None,
) -> str:
    """
    Derive the dynamic target-attribute label from the research strategy.
    Priority: explicit attribute_constraint → strategy target_attributes → generic fallback.
    Compound-agnostic: no material-specific branching.
    """
    constraint = (attribute_constraint or "").strip()
    if constraint and constraint.lower() not in ("none", "null", "n/a"):
        return constraint

    attrs: list = []
    if research_profile is None:
        pass
    elif isinstance(research_profile, dict):
        attrs = research_profile.get("target_attributes") or []
    elif isinstance(research_profile, str):
        text = research_profile.strip()
        if text:
            try:
                import json as _json
                parsed = _json.loads(text)
                if isinstance(parsed, dict):
                    attrs = parsed.get("target_attributes") or []
            except Exception:
                attrs = []
    else:
        attrs = list(getattr(research_profile, "target_attributes", None) or [])

    for item in attrs:
        if isinstance(item, str) and item.strip():
            return item.strip()
        label = getattr(item, "label", None) or getattr(item, "name", None)
        if label and str(label).strip():
            return str(label).strip()

    return _DEFAULT_TARGET_LABEL


def _normalize_medium_and_water_role(
    raw: Optional[MediumAndWaterRoleEvidence],
) -> MediumAndWaterRoleEvidence:
    if raw is None:
        return MediumAndWaterRoleEvidence(summary=_NO_WATER_SUMMARY, water_present=False)
    summary = (raw.summary or "").strip()
    if not summary or summary.lower() in ("unknown", "null", "n/a", "none"):
        summary = _NO_WATER_SUMMARY
    return MediumAndWaterRoleEvidence(
        core_reaction_medium=(raw.core_reaction_medium or "").strip(),
        water_present=bool(raw.water_present),
        water_roles=list(raw.water_roles or []),
        summary=summary,
        evidence=list(raw.evidence or []),
    )


def _usable_narrative(text: str) -> str:
    cleaned, ok = salvage_narrative(text or "")
    return cleaned if ok else ""


def salvage_narrative(text: str) -> tuple[str, bool]:
    """
    Drop a low-diversity repeated tail from generated prose.

    A short phrase repeated many times in a row is a generation failure.
    The varied text before that loop is kept. If the whole field is the loop,
    the narrative is unusable and the caller must retry generation.
    """
    raw = (text or "").strip()
    if not raw:
        return "", True
    words = list(re.finditer(r"\S+", raw))
    tokens = [match.group(0).lower() for match in words]
    cut_at = None
    if len(tokens) >= 16:
        for size in range(2, 9):
            index = 0
            while index + size * 8 <= len(tokens):
                phrase = tokens[index:index + size]
                repeats = 1
                cursor = index + size
                while cursor + size <= len(tokens) and tokens[cursor:cursor + size] == phrase:
                    repeats += 1
                    cursor += size
                if repeats >= 8:
                    cut_at = words[index].start()
                    break
                index += 1
            if cut_at is not None:
                break
    if cut_at is None and len(tokens) >= 40:
        for index in range(0, len(tokens) - 39):
            if len(set(tokens[index:])) <= 6:
                cut_at = words[index].start()
                break
    if cut_at is None:
        return raw, True
    prefix = raw[:cut_at].strip()
    prefix_tokens = re.findall(r"\S+", prefix.lower())
    varied = len(set(prefix_tokens)) >= 12 and len(prefix_tokens) >= 20
    if varied:
        logger.warning(
            "[REPORT] Removed a repeated-token tail from generated narrative (%d chars kept)",
            len(prefix),
        )
        return prefix, True
    return "", False


def _label_tokens(label: str) -> list[str]:
    stop = {
        "content", "value", "level", "amount", "property", "target",
        "ratio", "index", "with", "from", "that", "this", "unit",
        "example", "examples", "table", "comparative", "measured",
    }
    return [
        token for token in re.findall(r"[a-z0-9]{4,}", (label or "").lower())
        if token not in stop
    ]


def _alias_tokens(label: str, context_text: str) -> set[str]:
    """Map parenthetical abbreviations defined in the report text onto the target label."""
    tokens = set(_label_tokens(label))
    aliases = set()
    for long_name, short_name in re.findall(
        r"([A-Za-z][A-Za-z\-]{3,})\s*\(([A-Z][A-Z0-9]{1,8})\)",
        context_text or "",
    ):
        if long_name.lower() in tokens or any(tok in long_name.lower() for tok in tokens):
            aliases.add(short_name.lower())
    return tokens | aliases


def _line_mentions_property(line: str, needles: set[str]) -> bool:
    low = (line or "").lower()
    return any(re.search(rf"\b{re.escape(needle)}\b", low) for needle in needles)


def reconcile_target_attribute(
    attr: DynamicTargetAttributeEvidence,
    evidence_lines: list[str],
    parameter_lines: list[str],
    context_text: str = "",
) -> DynamicTargetAttributeEvidence:
    """
    If the summary says a property is undisclosed, but example or table lines
    state measured values for that property, keep those values.
    Feed or charge amounts are not treated as measured content.
    Claim-only ranges are labeled as claims.
    """
    if (attr.value or "").strip() != _NOT_DISCLOSED_VALUE:
        return attr
    needles = _alias_tokens(attr.label or "", context_text)
    if not needles:
        return attr
    measured: list[str] = []
    claimed: list[str] = []
    for line in list(evidence_lines or []) + list(parameter_lines or []):
        text = (line or "").strip()
        if not text or not _line_mentions_property(text, needles) or not re.search(r"\d", text):
            continue
        low = text.lower()
        is_input = bool(re.search(r"\b(charge|feed|phr|parts by)\b", low)) and not re.search(
            r"\b(bound|measured|content)\b", low
        )
        if is_input:
            continue
        is_claim = bool(re.search(r"\bclaim\b", low)) and not re.search(
            r"\b(example|table|preparation)\b", low
        )
        if is_claim:
            claimed.append(text)
        else:
            measured.append(text)
    if measured:
        shown = []
        for line in measured[:4]:
            example = ""
            match = re.match(
                r"((?:comparative\s+)?example\s+\S+|table\s+\d+|preparation\s+of\s+\S+)",
                line,
                re.I,
            )
            if match:
                example = match.group(1).rstrip(":")
            number = re.search(
                r"\d+(?:\.\d+)?(?:\s*(?:to|–|-)\s*\d+(?:\.\d+)?)?\s*(?:wt\s*%|%|phr)",
                line,
                re.I,
            )
            bit = number.group(0).strip() if number else line[:80]
            shown.append(f"{bit} ({example})" if example else bit)
        attr.value = "; ".join(shown)
        attr.status = "direct"
        attr.belongs_to_target = True
        return attr
    if claimed:
        attr.value = "Disclosed as a claim range; no worked-example measurement was extracted"
        attr.status = "indirect"
        attr.belongs_to_target = False
        return attr
    return attr


def _date_cell(details) -> str:
    priority = (getattr(details, "priority_date", None) or "").strip()
    published = (getattr(details, "publication_year", None) or "").strip()
    if priority and priority.lower() not in {"unknown", "not disclosed", "none"}:
        return f"Priority {priority}"
    if published:
        return f"Published {published}"
    return ""


def _normalize_target_attribute(
    raw: Optional[DynamicTargetAttributeEvidence],
    label: str,
) -> DynamicTargetAttributeEvidence:
    if raw is None:
        return DynamicTargetAttributeEvidence(
            label=label,
            value=_NOT_DISCLOSED_VALUE,
            status="not_found",
            material_context="",
            belongs_to_target=False,
            evidence=[],
        )
    belongs = bool(getattr(raw, "belongs_to_target", False))
    value = (raw.value or "").strip()
    status = (raw.status or "").strip().lower() or "not_found"
    material_context = (getattr(raw, "material_context", None) or "").strip()
    # Ownership invariant: values that do not belong to the requested target are not reported as target properties.
    if not belongs:
        value = _NOT_DISCLOSED_VALUE
        status = "not_found"
    elif not value or value.lower() in ("unknown", "null", "n/a", "none", ""):
        value = _NOT_DISCLOSED_VALUE
        status = "not_found"
        belongs = False
    attr_label = (raw.label or "").strip() or label
    return DynamicTargetAttributeEvidence(
        label=attr_label,
        value=value,
        status=status,
        material_context=material_context,
        belongs_to_target=belongs and value != _NOT_DISCLOSED_VALUE,
        evidence=list(raw.evidence or []) if belongs else [],
    )


def _normalize_dynamic_parameter_name(raw_name: str) -> str:
    """Safely normalizes parameter names without material-specific hardcoding."""
    cleaned = raw_name.strip().strip("-:*•").strip()
    low = cleaned.lower()

    if any(k in low for k in ("polymerization temp", "reaction temp", "synthesis temp")):
        return "Polymerization Temperature"
    if low in ("temp", "temperature"):
        return "Temperature"
    if any(k in low for k in ("monomer conversion", "polymerization conversion", "conversion")):
        return "Conversion"
    if any(k in low for k in ("polymerization time", "reaction time", "synthesis time")):
        return "Reaction Time"
    if any(k in low for k in ("chain transfer agent", "molecular weight modifier", "cta")):
        return "Chain Transfer Agent"
    if any(k in low for k in ("initiator system", "catalyst system", "initiator", "catalyst")):
        return "Initiator / Catalyst"
    if any(k in low for k in ("emulsifier", "surfactant", "emulsifying agent", "soap")):
        return "Emulsifier / Surfactant"
    if any(k in low for k in ("monomer ratio", "monomer composition", "comonomer ratio", "feed ratio")):
        return "Monomer Ratio / Composition"
    if any(k in low for k in ("reaction pressure", "hydrogen pressure", "pressure")):
        return "Pressure"
    if any(k in low for k in ("solids content", "solid content", "total solids")):
        return "Solids Content"
    if any(k in low for k in ("mooney viscosity", "mooney")):
        return "Mooney Viscosity"
    if any(k in low for k in ("coagulant", "coagulating agent")):
        return "Coagulant"
    if any(k in low for k in ("glass transition", " tg", "tg ")):
        return "Glass Transition Temperature (Tg)"
    if any(k in low for k in ("molecular weight", " mw", "number average")):
        return "Molecular Weight"

    return cleaned.title() if len(cleaned) <= 40 else cleaned[:37] + "..."


def _build_concise_patent_methodology_summary(patent: ReportPatent) -> list[str]:
    """
    Builds a compact 4-5 bullet synthesis summary for a single patent.
    Material-agnostic: uses generic chemical concepts (method, conditions, feed, catalyst, finding).
    """
    pd = patent.patent_details
    method = patent.polymerization_method
    dynamic_params = list(getattr(method, "dynamic_parameters", []) or [])
    medium = getattr(patent, "medium_and_water_role", None)
    target_attr = getattr(patent, "target_attribute", None)
    evidence = list(getattr(patent, "experimental_evidence", []) or [])

    bullets = []

    # 1. Synthesis Route & Method
    route = ""
    for p in dynamic_params:
        low = p.lower()
        if any(k in low for k in ("synthesis method", "polymerization method", "process type", "method:")):
            route = p.split(":", 1)[1].strip() if ":" in p else p.strip()
            break
    if not route:
        if medium and getattr(medium, "core_reaction_medium", None):
            route = f"{medium.core_reaction_medium} polymerization"
        elif getattr(pd, "polymer_type", None):
            route = f"Polymerization process for {pd.polymer_type}"
        elif getattr(pd, "relevance_to_target", None):
            route = pd.relevance_to_target
        else:
            route = "Polymerization process disclosed in source"
    bullets.append(f"- **Synthesis Route**: {route}")

    # 2. Reaction Conditions (Temperature, time, conversion, pressure, Mooney)
    conditions = []
    for p in dynamic_params:
        low = p.lower()
        if any(k in low for k in ("temperature", "temp", "conversion", "reaction time", "pressure", "mooney")):
            parts = p.split(":", 1)
            if len(parts) == 2:
                conditions.append(f"{parts[0].strip()}: {parts[1].strip()}")
            else:
                conditions.append(p.strip())
    if conditions:
        bullets.append(f"- **Reaction Conditions**: {' | '.join(conditions[:4])}")
    elif getattr(pd, "relevance_to_target", None):
        bullets.append(f"- **Reaction Conditions**: {pd.relevance_to_target}")

    # 3. Composition & Target Property (Monomer ratio, feed, target attribute)
    composition_parts = []
    for p in dynamic_params:
        low = p.lower()
        if any(k in low for k in ("monomer", "ratio", "composition", "feed", "solids")):
            parts = p.split(":", 1)
            if len(parts) == 2:
                composition_parts.append(f"{parts[0].strip()}: {parts[1].strip()}")
            else:
                composition_parts.append(p.strip())
    if target_attr and target_attr.value and target_attr.value.lower() not in (
        "not disclosed", "none", "unknown", "not disclosed in extracted evidence"
    ):
        composition_parts.append(f"{target_attr.label}: {target_attr.value}")
    if composition_parts:
        bullets.append(f"- **Composition & Target**: {' | '.join(composition_parts[:3])}")

    # 4. Catalyst, Initiator & Modifiers (Initiator, CTA, surfactant, coagulant)
    catalyst_parts = []
    for p in dynamic_params:
        low = p.lower()
        if any(k in low for k in ("initiator", "catalyst", "chain transfer", "cta", "emulsifier", "surfactant", "coagulant", "modifier")):
            parts = p.split(":", 1)
            if len(parts) == 2:
                catalyst_parts.append(f"{parts[0].strip()}: {parts[1].strip()}")
            else:
                catalyst_parts.append(p.strip())
    if catalyst_parts:
        bullets.append(f"- **Catalyst & Modifiers**: {' | '.join(catalyst_parts[:3])}")

    # If few or none of the above matched, provide raw dynamic parameters up to 4
    if len(bullets) <= 2 and dynamic_params:
        for p in dynamic_params[:4]:
            if not any(p.strip() in b for b in bullets):
                bullets.append(f"- {p.strip()}")

    # 5. Key Technical Finding (from evidence or technical relevance)
    finding = ""
    for ev in evidence:
        s = ev.strip()
        if not s or s.startswith("|") or ("Table" in s and "|" in s):
            continue
        if "not detected by parser" in s.lower() or "evidence coverage:" in s.lower():
            continue
        finding = s
        break
    if not finding and getattr(patent, "technical_relevance", None):
        finding = patent.technical_relevance
    if finding:
        if len(finding) > 160:
            finding = finding[:157] + "..."
        bullets.append(f"- **Key Technical Finding**: {finding}")

    return bullets


def _build_dynamic_comparison_dimensions(
    methodology_patents: list[ReportPatent],
    resolved_label: str,
    medium_values: dict[str, str],
    attribute_values: dict[str, str],
) -> list[ReportComparisonDimension]:
    """
    Dynamically collects and normalizes technical properties discovered across
    all primary patents to build a compact cross-patent comparison (5-7 columns max).
    Works dynamically for ANY chemical/polymer system with zero material hardcoding.
    """
    dimensions = [
        ReportComparisonDimension(
            parameter_name="Medium & Water Role",
            values=medium_values,
        ),
        ReportComparisonDimension(
            parameter_name=resolved_label,
            values=attribute_values,
        ),
    ]

    pat_count = len(methodology_patents)
    if pat_count < 2:
        return dimensions

    all_pns = [mp.patent_details.patent_number for mp in methodology_patents]
    discovered: dict[str, dict[str, str]] = {}

    for mp in methodology_patents:
        pn = mp.patent_details.patent_number
        params = getattr(mp.polymerization_method, "dynamic_parameters", []) or []
        for p_str in params:
            if not p_str or ":" not in p_str:
                continue
            raw_key, _, raw_val = p_str.partition(":")
            raw_key = raw_key.strip()
            raw_val = raw_val.strip()
            if not raw_key or not raw_val:
                continue
            if raw_key.lower().startswith("synthesis method"):
                continue
            norm_name = _normalize_dynamic_parameter_name(raw_key)
            if norm_name in ("Medium & Water Role", resolved_label):
                continue
            if norm_name not in discovered:
                discovered[norm_name] = {}
            if pn not in discovered[norm_name]:
                discovered[norm_name][pn] = raw_val[:50]

    # Rank discovered properties by patent coverage
    ranked_props = sorted(
        discovered.keys(),
        key=lambda k: len(discovered[k]),
        reverse=True,
    )

    # Add top 2 dynamic properties discovered across evidence
    # (Total table cols = Patent + Applicant + Medium + resolved_label + 2 dynamic props + Key Finding = 7 cols max)
    for prop_name in ranked_props[:2]:
        vals = {}
        for pn in all_pns:
            vals[pn] = discovered[prop_name].get(pn, _NOT_DISCLOSED_VALUE)
        dimensions.append(ReportComparisonDimension(
            parameter_name=prop_name,
            values=vals,
        ))

    return dimensions


class ReportService:
    def __init__(self):
        # Ensure export directory exists
        self.export_dir = os.path.join(os.getcwd(), "exports")
        os.makedirs(self.export_dir, exist_ok=True)

    async def generate_structured_report(
        self, compound_name: str, extractions: List[ReportPatentEvidence],
        patent_manifest: List[str] = None,
        secondary_candidates: list = None,
        original_input: str = "",
        research_profile: str = "",
        attribute_constraint: Optional[str] = None,
        target_attribute_label: Optional[str] = None,
    ) -> tuple:
        """Generate the structured report via LLM using the aggregated extractions."""
        import time
        from app.core.config import settings

        logger.info("Generating final structured report for %d patents...", len(extractions))

        from app.services.pipeline.report_evidence_service import ReportEvidenceService
        svc = ReportEvidenceService()

        resolved_label = (target_attribute_label or "").strip() or resolve_target_attribute_label(
            attribute_constraint=attribute_constraint,
            research_profile=research_profile,
        )
        constraint_for_prompt = (attribute_constraint or "").strip() or "None"

        effective_provider_limit = getattr(settings, 'REPORT_PROVIDER_SAFE_LIMIT', 100000)
        overhead = getattr(settings, 'REPORT_EVIDENCE_OVERHEAD_TOKENS', 4000)
        evidence_budget = max(1000, effective_provider_limit - overhead)

        sys_prompt = REPORT_GENERATION_SYSTEM_PROMPT.format(compound_name=compound_name)
        sys_tokens = svc.estimate_tokens(sys_prompt)
        # Estimate base overhead using dummy values for all template placeholders
        base_tokens = svc.estimate_tokens(
            REPORT_GENERATION_USER_TEMPLATE.format(
                compound_name=compound_name,
                original_input="dummy",
                research_profile="dummy",
                extractions_data="",
                patent_manifest="",
                primary_count=0,
                patent_count=0,
                target_attribute_label=resolved_label,
                attribute_constraint=constraint_for_prompt,
            )
        )
        overhead_total = sys_tokens + base_tokens


        # ── Safety: trim evidence per-patent proportionally if still oversized ────
        extractions_data = svc.serialize_evidence(extractions)
        est_tokens = svc.estimate_tokens(extractions_data)
        total_prompt_tokens = est_tokens + overhead_total

        if total_prompt_tokens > effective_provider_limit:
            deficit = total_prompt_tokens - effective_provider_limit
            logger.warning(
                "[REPORT] Evidence still oversized after upstream compaction: "
                "%d tokens (limit %d, deficit %d). Applying per-patent proportional trim.",
                total_prompt_tokens, effective_provider_limit, deficit
            )
            # Trim source sentences proportionally across all patents (never drop a patent)
            for ev in extractions:
                for param in ev.overall_patent_parameters:
                    if param.source_sentence and len(param.source_sentence) > 60:
                        param.source_sentence = param.source_sentence[:60] + "..."
                for ex in ev.examples:
                    for param in ex.extracted_parameters:
                        if param.source_sentence and len(param.source_sentence) > 60:
                            param.source_sentence = param.source_sentence[:60] + "..."
            extractions_data = svc.serialize_evidence(extractions)
            est_tokens = svc.estimate_tokens(extractions_data)
            total_prompt_tokens = est_tokens + overhead_total
            logger.info(
                "[REPORT] After proportional trim: %d tokens (limit %d)",
                total_prompt_tokens, effective_provider_limit
            )

        # Build patent manifest for injection into user prompt
        if patent_manifest is None:
            patent_manifest = [ev.patent_number for ev in extractions]
        manifest_lines = [f"{i+1}. {pn}" for i, pn in enumerate(patent_manifest)]
        manifest_str = "\n".join(manifest_lines)
        patent_count = len(patent_manifest)
        primary_count = patent_count

        prompt = REPORT_GENERATION_USER_TEMPLATE.format(
            compound_name=compound_name,
            original_input=original_input,
            research_profile=research_profile,
            extractions_data=extractions_data,
            patent_manifest=manifest_str,
            primary_count=primary_count,
            patent_count=patent_count,
            target_attribute_label=resolved_label,
            attribute_constraint=constraint_for_prompt,
        )

        logger.info(
            "[REPORT GENERATION]\n"
            "Patents in manifest: %d\n"
            "Structured evidence tokens: %d\n"
            "System/template overhead tokens: %d\n"
            "Total LLM input tokens: %d\n"
            "PROVIDER CONTEXT CAPABILITY: %d (not an evidence retention limit)\n"
            "Target attribute label: %s",
            len(extractions), est_tokens, overhead_total, total_prompt_tokens, effective_provider_limit, resolved_label
        )

        t0 = time.time()
        first_error = None
        first_raw_len = 0
        first_finish_reason = None
        try:
            report_obj, provider_id, _usage = await llm_client.generate_structured(
                prompt=prompt,
                system_prompt=sys_prompt,
                schema=LLMPatentResearchReport,
                temperature=0.2,
                metadata={"stage": "REPORT_GENERATION"},
            )
            latency = time.time() - t0
            in_tokens = (_usage or {}).get("input_tokens", est_tokens)
            out_tokens = (_usage or {}).get("output_tokens", 0)

            def _report_complete(obj) -> bool:
                if obj is None:
                    return False
                if patent_count > 0 and not (getattr(obj, "per_patent_analysis", None) or []):
                    return False
                conclusion, ok = salvage_narrative(getattr(obj, "conclusion", "") or "")
                if not ok:
                    logger.error("[REPORT] Conclusion failed the repetition check")
                    return False
                obj.conclusion = conclusion
                abstract, abstract_ok = salvage_narrative(getattr(obj, "abstract", "") or "")
                if abstract_ok and abstract:
                    obj.abstract = abstract
                kept = []
                for point in getattr(obj, "cross_patent_comparison", None) or []:
                    cleaned, point_ok = salvage_narrative(point)
                    if point_ok and cleaned:
                        kept.append(cleaned)
                obj.cross_patent_comparison = kept
                return True

            if not _report_complete(report_obj):
                raw_text = (_usage or {}).get("raw_response_text")
                first_error = (
                    (_usage or {}).get("invalid_response_error")
                    or (_usage or {}).get("validation_error")
                    or (
                        "empty per_patent_analysis"
                        if report_obj is not None
                        else "LLM returned None"
                    )
                )
                first_raw_len = int((_usage or {}).get("response_length") or (len(raw_text) if raw_text else 0))
                first_finish_reason = (_usage or {}).get("finish_reason")
                logger.error(
                    "[REPORT] Schema/JSON failure on first attempt | Latency: %.1fs | "
                    "Provider: %s | error=%s | response_length=%d | finish_reason=%s",
                    latency,
                    provider_id,
                    str(first_error)[:400],
                    first_raw_len,
                    first_finish_reason,
                )

                # Attempt safe parse of raw response (fences / outer object only)
                salvaged = try_parse_llm_report(
                    raw_text, expected_patent_count=patent_count
                )
                if salvaged is not None and _report_complete(salvaged):
                    logger.info("[REPORT] Recovered valid report via safe JSON parse of raw response")
                    report_obj = salvaged
                else:
                    report_obj = None
                    # Compact evidence + repair retry (one attempt)
                    logger.warning(
                        "[REPORT] Retrying structured report with compact evidence + repair instructions"
                    )
                    compact_extractions = _compact_extractions_for_retry(extractions)
                    compact_data = svc.serialize_evidence(compact_extractions)
                    repair_prompt = REPORT_GENERATION_USER_TEMPLATE.format(
                        compound_name=compound_name,
                        original_input=original_input,
                        research_profile=research_profile,
                        extractions_data=compact_data,
                        patent_manifest=manifest_str,
                        primary_count=primary_count,
                        patent_count=patent_count,
                        target_attribute_label=resolved_label,
                        attribute_constraint=constraint_for_prompt,
                    ) + _REPORT_REPAIR_SUFFIX

                    report_obj, provider_id, _usage2 = await llm_client.generate_structured(
                        prompt=repair_prompt,
                        system_prompt=sys_prompt + "\n\nOUTPUT MUST BE COMPACT VALID JSON ONLY.",
                        schema=LLMPatentResearchReport,
                        temperature=0.1,
                        metadata={"stage": "REPORT_GENERATION"},
                    )
                    latency = time.time() - t0
                    in_tokens = (_usage2 or {}).get("input_tokens", in_tokens)
                    out_tokens = (_usage2 or {}).get("output_tokens", 0)

                    if not _report_complete(report_obj):
                        raw2 = (_usage2 or {}).get("raw_response_text")
                        err2 = (
                            (_usage2 or {}).get("invalid_response_error")
                            or (_usage2 or {}).get("validation_error")
                            or "retry returned None/incomplete"
                        )
                        salvaged2 = try_parse_llm_report(
                            raw2, expected_patent_count=patent_count
                        )
                        if salvaged2 is not None and _report_complete(salvaged2):
                            logger.info("[REPORT] Recovered valid report via safe parse after retry")
                            report_obj = salvaged2
                        else:
                            logger.warning(
                                "[REPORT] Single-shot + compact retry failed "
                                "(finish_reason=%s). Falling back to per-patent sectional generation.",
                                (_usage2 or {}).get("finish_reason") or first_finish_reason,
                            )
                            try:
                                report_obj = await generate_report_via_patent_sections(
                                    compound_name=compound_name,
                                    original_input=original_input or compound_name,
                                    research_profile=research_profile or "",
                                    extractions=extractions,
                                    target_attribute_label=resolved_label,
                                )
                                provider_id = provider_id or "gemini"
                                latency = time.time() - t0
                            except Exception as section_err:
                                logger.error(
                                    "[REPORT] RESPONSE_EMPTY after retry+sectional | Latency: %.1fs | "
                                    "Provider: %s | First error: %s | Retry error: %s | "
                                    "Sectional error: %s | first_response_length=%d | "
                                    "retry_response_length=%d | finish_reason=%s",
                                    latency,
                                    provider_id,
                                    str(first_error)[:300],
                                    str(err2)[:300],
                                    str(section_err)[:300],
                                    first_raw_len,
                                    len(raw2) if raw2 else 0,
                                    (_usage2 or {}).get("finish_reason") or first_finish_reason,
                                )
                                raise ValueError(
                                    "REPORT_GENERATION_FAILED: LLM structured JSON invalid after retry "
                                    "and sectional fallback. "
                                    f"first_error={str(first_error)[:400]!r}; "
                                    f"retry_error={str(err2)[:400]!r}; "
                                    f"sectional_error={str(section_err)[:400]!r}; "
                                    f"first_response_length={first_raw_len}; "
                                    f"finish_reason={first_finish_reason!r}. "
                                    "Search/selection/extraction were not the failure point."
                                ) from section_err

            # Map LLM per-patent analysis to methodology section.
            # per_patent_analysis is keyed by patent_number.
            llm_analysis_by_pn = {}
            for pa in getattr(report_obj, 'per_patent_analysis', []):
                pn = getattr(pa, 'patent_number', '')
                if pn:
                    llm_analysis_by_pn[pn] = pa

            methodology_patents = []
            medium_values: Dict[str, str] = {}
            attribute_values: Dict[str, str] = {}

            for ext in extractions:
                legal_status = (getattr(ext, "legal_status", None) or "").strip()
                if legal_status.lower() in {"", "unknown", "not disclosed", "none", "patent"}:
                    legal_status = None
                priority_date = (getattr(ext, "priority_date", None) or "").strip() or None
                details = ReportPatentDetails(
                    patent_number=ext.patent_number,
                    patent_title=ext.title,
                    assignee=ext.assignee,
                    publication_year=ext.publication_year,
                    jurisdiction=ext.jurisdiction,
                    priority_date=priority_date,
                    legal_status=legal_status,
                    polymer_type=None,
                    relevance_to_target="Automatically extracted candidate",
                    relevance_tier="PRIMARY"
                )

                llm_pa = llm_analysis_by_pn.get(ext.patent_number)

                # OPTION A: use LLM's per-patent analysis when available
                params = []
                if llm_pa:
                    # synthesis_method as first bullet
                    if getattr(llm_pa, 'synthesis_method', ''):
                        params.append(f"Synthesis method: {llm_pa.synthesis_method}")
                    # disclosed parameters from LLM evidence reading
                    for dp in getattr(llm_pa, 'disclosed_parameters', []):
                        if dp:
                            params.append(dp)
                else:
                    # Fallback: use deterministic overall_patent_parameters if LLM produced nothing
                    for p in ext.overall_patent_parameters:
                        s = f"{p.name}: {p.value} {p.unit}".strip()
                        if p.context:
                            s += f" ({p.context})"
                        params.append(s)

                medium_role = _normalize_medium_and_water_role(
                    getattr(llm_pa, "medium_and_water_role", None) if llm_pa else None
                )
                target_attr = _normalize_target_attribute(
                    getattr(llm_pa, "target_attribute", None) if llm_pa else None,
                    resolved_label,
                )
                # Force strategy label (prevent model drift / cross-run bleed)
                target_attr.label = resolved_label

                medium_values[ext.patent_number] = medium_role.summary
                attribute_values[ext.patent_number] = target_attr.value

                # Experimental evidence: use LLM example_highlights, fall back to deterministic examples
                evidence = []
                if llm_pa and getattr(llm_pa, 'example_highlights', []):
                    # Drop unhelpful parser-placeholder bullets the model sometimes invents
                    for h in llm_pa.example_highlights:
                        hl = (h or "").strip()
                        if not hl:
                            continue
                        low = hl.lower()
                        if "not detected by parser" in low or "not structurally extracted" in low:
                            continue
                        evidence.append(hl)
                if not evidence:
                    for findings in ext.technical_findings:
                        evidence.append(findings)
                    for ex in ext.examples:
                        param_strs = ", ".join(
                            f"{p.name}: {p.value} {p.unit}" for p in ex.extracted_parameters
                        )
                        if param_strs:
                            evidence.append(f"{ex.example_id}: {param_strs}")
                        elif getattr(ex, "raw_text", None):
                            snippet = (ex.raw_text or "").strip().split("\n", 1)[0][:240]
                            evidence.append(f"{ex.example_id}: {snippet}")
                    for sec in ext.synthesis_sections[:3]:
                        title = getattr(sec, "section_title", "Process section") or "Process section"
                        snippet = (getattr(sec, "raw_text", "") or "").strip().replace("\n", " ")[:240]
                        if snippet:
                            evidence.append(f"{title}: {snippet}")
                    for note in ext.limitations_or_missing_data:
                        if note and note not in evidence:
                            evidence.append(note)

                context_bits = " ".join(
                    [
                        report_obj.abstract or "",
                        getattr(llm_pa, "synthesis_method", "") if llm_pa else "",
                        " ".join(evidence),
                        " ".join(params),
                    ]
                )
                target_attr = reconcile_target_attribute(
                    target_attr, evidence, params, context_bits
                )
                attribute_values[ext.patent_number] = target_attr.value
                example_count = len(getattr(ext, "examples", None) or [])
                table_count = sum(
                    1
                    for sec in (getattr(ext, "synthesis_sections", None) or [])
                    if str(getattr(sec, "section_title", "") or "").lower().startswith("table")
                )
                coverage = f"Evidence coverage: {example_count} example section(s) stored"
                if table_count:
                    coverage += f"; {table_count} table section(s) stored outside example text"
                coverage += f"; {len(evidence)} finding(s) shown above."
                for note in getattr(ext, "limitations_or_missing_data", None) or []:
                    if note and note not in evidence:
                        evidence.append(note)
                if coverage not in evidence:
                    evidence.append(coverage)
                methodology = ReportPatentMethodology(dynamic_parameters=params)

                methodology_patents.append(ReportPatent(
                    patent_details=details,
                    polymerization_method=methodology,
                    experimental_evidence=evidence if evidence else [
                        "No segmented worked-example sections were available; "
                        "see methodology parameters and source evidence for process details."
                    ],
                    technical_relevance=getattr(llm_pa, 'technical_relevance', '') or "Selected via deterministic pipeline scoring.",
                    medium_and_water_role=medium_role,
                    target_attribute=target_attr,
                    tables=getattr(ext, "tables", []),
                ))
            
            comparison_dimensions = _build_dynamic_comparison_dimensions(
                methodology_patents=methodology_patents,
                resolved_label=resolved_label,
                medium_values=medium_values,
                attribute_values=attribute_values,
            )

            final_report = PatentResearchReport(
                title=report_obj.title or "PATENT RESEARCH REPORT",
                abstract=report_obj.abstract or "No abstract provided.",
                methodology_patents=methodology_patents,
                secondary_patents=[],
                cross_patent_comparison=report_obj.cross_patent_comparison,
                conclusion=report_obj.conclusion,
                references=report_obj.references,
                dynamic_target_attribute_label=resolved_label,
                comparison_dimensions=comparison_dimensions,
            )

            # Authoritative manifest: drop phantom patents from LLM references
            allowed = {ev.patent_number for ev in extractions}
            if patent_manifest:
                allowed |= set(patent_manifest)
            titles_by_pn = {
                ev.patent_number: (ev.title or "").strip()
                for ev in extractions
                if (ev.title or "").strip()
            }
            cleaned_refs = []
            for ref in final_report.references or []:
                ref_pn = ref.split("|")[0].strip() if "|" in ref else str(ref).strip()
                if ref_pn in allowed:
                    stored_title = titles_by_pn.get(ref_pn, "")
                    if "|" in ref and stored_title:
                        parts = [part.strip() for part in ref.split("|")]
                        shown = parts[1] if len(parts) > 1 else ""
                        if shown.endswith("...") or shown.endswith("…") or len(stored_title) > len(shown):
                            parts[1] = stored_title
                            ref = " | ".join(parts)
                    cleaned_refs.append(ref)
                else:
                    logger.warning(
                        "[REPORT] Dropping phantom reference not in selected manifest: %s",
                        ref_pn,
                    )
            final_report.references = cleaned_refs or sorted(allowed)

            # Methodology patents are built only from extractions — assert no extras
            for mp in final_report.methodology_patents:
                pn = getattr(mp.patent_details, "patent_number", "")
                if pn and pn not in allowed:
                    logger.error(
                        "[REPORT] Unexpected methodology patent %s not in manifest", pn
                    )

            logger.info(
                "[REPORT] RESPONSE_RECEIVED | Latency: %.1fs | Provider: %s | "
                "Input tokens: %d | Output tokens: %d | Patents mapped: %d | Status: SUCCESS",
                latency, provider_id, in_tokens, out_tokens,
                len(final_report.methodology_patents)
            )

            return final_report, _usage

        except Exception as e:
            latency = time.time() - t0
            logger.error(
                "[REPORT] REPORT_FAILED | Type: %s | Message: %s | "
                "Latency: %.1fs | Provider limit: %d | Input tokens estimated: %d",
                type(e).__name__, str(e)[:300], latency, effective_provider_limit, total_prompt_tokens
            )
            raise


    def report_to_markdown(self, report: 'PatentResearchReport') -> str:
        """Converts the structured report to concise markdown for PDF export (canonical 5 sections)."""
        lines = []

        title = report.title or "PATENT RESEARCH REPORT"
        lines.append(f"# {title.upper()}")

        abstract = report.abstract or "No abstract provided."
        lines.append("\n## 1. ABSTRACT")
        lines.append(abstract)

        lines.append("\n## 2. METHODOLOGY")
        primary_patents = getattr(report, 'methodology_patents', []) or []

        if not primary_patents:
            lines.append(
                "No patents from the authoritative selected primary manifest were available. "
                "This reflects selection criteria outcomes (identity / qualifier / centrality), "
                "not a claim that no related patents exist in the literature."
            )
        else:
            # 1. Compact Patent Methodology Overview Table
            lines.append("| Patent | Title | Assignee | Year | Jurisdiction | Synthesis Method |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for patent in primary_patents:
                pd = patent.patent_details
                method_str = ""
                for p in getattr(patent.polymerization_method, "dynamic_parameters", []) or []:
                    low = p.lower()
                    if any(k in low for k in ("synthesis method", "polymerization method", "process type", "method:")):
                        method_str = p.split(":", 1)[1].strip() if ":" in p else p.strip()
                        break
                if not method_str:
                    method_str = getattr(pd, "polymer_type", "") or getattr(pd, "relevance_to_target", "") or "Disclosed in source"
                if len(method_str) > 50:
                    method_str = method_str[:47] + "..."
                raw_title = pd.patent_title or "Not available from source"
                short_title = raw_title[:65] + "..." if len(raw_title) > 65 else raw_title
                lines.append(
                    f"| {pd.patent_number or 'N/A'} | {short_title} | {pd.assignee or 'Not disclosed'} | "
                    f"{pd.publication_year or 'N/A'} | {pd.jurisdiction or 'N/A'} | {method_str} |"
                )

            # 2. Concise Methodology Summaries per selected patent
            for patent in primary_patents:
                pd = patent.patent_details
                pub_yr = f", {pd.publication_year}" if pd.publication_year else ""
                lines.append(f"\n**{pd.patent_number} — {pd.assignee or 'Unknown Assignee'}{pub_yr}**")
                bullets = _build_concise_patent_methodology_summary(patent)
                for b in bullets:
                    lines.append(b)

        # 3. Cross-Patent Comparison & Synthesis Trends
        lines.append("\n## 3. CROSS-PATENT COMPARISON & SYNTHESIS TRENDS")
        comparison_dims = getattr(report, "comparison_dimensions", None) or []
        if primary_patents and comparison_dims:
            headers = ["Patent", "Applicant"]
            for dim in comparison_dims:
                headers.append(getattr(dim, "parameter_name", None) or dim.get("parameter_name", ""))
            headers.append("Key Finding")
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for patent in primary_patents:
                pd = patent.patent_details
                row = [
                    pd.patent_number or "",
                    pd.assignee or "",
                ]
                for dim in comparison_dims:
                    values = getattr(dim, "values", None) or (dim.get("values") if isinstance(dim, dict) else {}) or {}
                    val = values.get(pd.patent_number, _NOT_DISCLOSED_VALUE)
                    if len(val) > 75:
                        val = val[:72] + "..."
                    row.append(val)
                finding = ""
                if patent.experimental_evidence:
                    for ev in patent.experimental_evidence:
                        s = ev.strip()
                        if not s.startswith("|") and not ("Table" in s and "|" in s):
                            finding = s
                            break
                if not finding and patent.technical_relevance:
                    finding = patent.technical_relevance
                if len(finding) > 75:
                    finding = finding[:72] + "..."
                row.append(finding)
                lines.append("| " + " | ".join(row) + " |")

        if len(primary_patents) >= 2 and report.cross_patent_comparison:
            lines.append("\n**Synthesis Trends & Observations**")
            for point in report.cross_patent_comparison:
                lines.append(f"- {point}")
        elif len(primary_patents) == 0:
            lines.append(
                "- No patents from the authoritative selected primary manifest were "
                "available for comparison. This reflects selection criteria outcomes "
                "(identity / qualifier / centrality), not a claim that no related "
                "patents exist in the literature."
            )
        elif len(primary_patents) < 2:
            lines.append(
                "- Fewer than two selected primary patents were available, so "
                "cross-patent quantitative trends were not generated."
            )
        else:
            lines.append("- No cross-patent comparison data provided.")

        # 4. Conclusion
        lines.append("\n## 4. CONCLUSION")
        if report.conclusion:
            lines.append(report.conclusion)
        else:
            lines.append("No conclusion provided.")

        # 5. References
        lines.append("\n## 5. REFERENCES")
        if report.references:
            for ref in report.references:
                lines.append(f"- {ref}")
        else:
            lines.append("- No references provided.")

        return "\n".join(lines)

    async def export_to_pdf(self, markdown_text: str, file_name: str) -> str:
        """Render the concise report Markdown to PDF. Layout changes stay in this path."""
        logger.info("Exporting report to PDF: %s", file_name)
        styled_html = pdf_html_from_markdown(markdown_text)
        pdf_path = os.path.join(self.export_dir, file_name)
        
        try:
            with open(pdf_path, "w+b") as result_file:
                pisa_status = pisa.CreatePDF(styled_html, dest=result_file)
                
            if pisa_status.err:
                logger.error("Error creating PDF via xhtml2pdf")
                raise Exception("PDF generation failed.")
                
            # Report-level validation: page count check (target: ~5 pages)
            try:
                reader = PdfReader(pdf_path)
                page_count = len(reader.pages)
                logger.info(
                    "[REPORT VALIDATION] Generated PDF %s page count: %d (target: ~5 pages)",
                    file_name,
                    page_count,
                )
                if page_count > 8 or page_count < 3:
                    logger.warning(
                        "[REPORT VALIDATION WARNING] PDF %s page count %d deviates from target of ~5 pages",
                        file_name,
                        page_count,
                    )
            except Exception as pe:
                logger.debug("Page count validation inspection failed: %s", pe)

            return pdf_path
        except Exception as e:
            logger.error("Export to PDF failed: %s", e)
            return ""

    def _sanitize_text_for_xml(self, text: str) -> str:
        """Remove control characters and NULL bytes that are incompatible with XML."""
        if not text:
            return text
        import re
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        return text

    async def export_to_docx(self, report: 'PatentResearchReport', file_name: str) -> str:
        """
        Export DOCX directly from canonical PatentResearchReport matching the concise 5 sections.
        Ensures zero data loss between web report, PDF, and DOCX without dumping raw evidence.
        """
        logger.info("Exporting report to DOCX (concise 5-section): %s", file_name)

        doc = Document()

        def _safe(text) -> str:
            if text is None:
                return "Not available from source"
            s = str(text).strip()
            if not s or s.lower() in ("not disclosed", "none"):
                return "Not available from source"
            import re as _re
            return _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)

        # Title
        doc.add_heading(_safe(report.title or 'PATENT RESEARCH REPORT'), level=1)

        # 1. ABSTRACT
        doc.add_heading('1. ABSTRACT', level=2)
        doc.add_paragraph(_safe(report.abstract or 'No abstract provided.'))

        # 2. METHODOLOGY
        primary_patents = getattr(report, 'methodology_patents', []) or []
        doc.add_heading('2. METHODOLOGY', level=2)

        if not primary_patents:
            doc.add_paragraph(
                'No patents from the authoritative selected primary manifest were available.'
            )
        else:
            # Methodology Overview Table
            table = doc.add_table(rows=1, cols=6)
            table.style = 'Table Grid'
            hdr_cells = table.rows[0].cells
            for i, h in enumerate(['Patent', 'Title', 'Assignee', 'Year', 'Jurisdiction', 'Synthesis Method']):
                hdr_cells[i].text = h
                for p_elem in hdr_cells[i].paragraphs:
                    for r_elem in p_elem.runs:
                        r_elem.bold = True

            for patent in primary_patents:
                pd = patent.patent_details
                method_str = ""
                for p in getattr(patent.polymerization_method, "dynamic_parameters", []) or []:
                    low = p.lower()
                    if any(k in low for k in ("synthesis method", "polymerization method", "process type", "method:")):
                        method_str = p.split(":", 1)[1].strip() if ":" in p else p.strip()
                        break
                if not method_str:
                    method_str = getattr(pd, "polymer_type", "") or getattr(pd, "relevance_to_target", "") or "Disclosed in source"
                if len(method_str) > 50:
                    method_str = method_str[:47] + "..."
                raw_title = pd.patent_title or "Not available from source"
                short_title = raw_title[:65] + "..." if len(raw_title) > 65 else raw_title

                row_cells = table.add_row().cells
                row_cells[0].text = _safe(pd.patent_number or 'N/A')
                row_cells[1].text = _safe(short_title)
                row_cells[2].text = _safe(pd.assignee or 'Not disclosed')
                row_cells[3].text = _safe(pd.publication_year or 'N/A')
                row_cells[4].text = _safe(pd.jurisdiction or 'N/A')
                row_cells[5].text = _safe(method_str)

            # Concise Methodology Summaries per patent
            for patent in primary_patents:
                pd = patent.patent_details
                pub_yr = f", {pd.publication_year}" if pd.publication_year else ""
                doc.add_heading(f"{_safe(pd.patent_number)} — {_safe(pd.assignee or 'Unknown Assignee')}{pub_yr}", level=3)
                bullets = _build_concise_patent_methodology_summary(patent)
                for b in bullets:
                    b_clean = b[2:].strip() if b.startswith("- ") else b.strip()
                    doc.add_paragraph(_safe(b_clean), style='List Bullet')

        # 3. CROSS-PATENT COMPARISON & SYNTHESIS TRENDS
        doc.add_heading('3. CROSS-PATENT COMPARISON & SYNTHESIS TRENDS', level=2)
        comparison_dims = getattr(report, "comparison_dimensions", None) or []
        if primary_patents and comparison_dims:
            headers = ["Patent", "Applicant"]
            for dim in comparison_dims:
                headers.append(getattr(dim, "parameter_name", None) or dim.get("parameter_name", ""))
            headers.append("Key Finding")

            comp_table = doc.add_table(rows=1, cols=len(headers))
            comp_table.style = 'Table Grid'
            for i, h in enumerate(headers):
                cell = comp_table.rows[0].cells[i]
                cell.text = _safe(h)
                for p_elem in cell.paragraphs:
                    for r_elem in p_elem.runs:
                        r_elem.bold = True

            for patent in primary_patents:
                pd = patent.patent_details
                row_cells = comp_table.add_row().cells
                row_cells[0].text = _safe(pd.patent_number or "")
                row_cells[1].text = _safe(pd.assignee or "")
                for i, dim in enumerate(comparison_dims):
                    values = getattr(dim, "values", None) or (dim.get("values") if isinstance(dim, dict) else {}) or {}
                    val = values.get(pd.patent_number, _NOT_DISCLOSED_VALUE)
                    if len(val) > 75:
                        val = val[:72] + "..."
                    row_cells[i + 2].text = _safe(val)
                finding = ""
                if patent.experimental_evidence:
                    for ev in patent.experimental_evidence:
                        s = ev.strip()
                        if not s.startswith("|") and not ("Table" in s and "|" in s):
                            finding = s
                            break
                if not finding and patent.technical_relevance:
                    finding = patent.technical_relevance
                if len(finding) > 75:
                    finding = finding[:72] + "..."
                row_cells[-1].text = _safe(finding)

        if len(primary_patents) >= 2 and report.cross_patent_comparison:
            p_trends = doc.add_paragraph()
            p_trends.add_run("Synthesis Trends & Observations").bold = True
            for point in report.cross_patent_comparison:
                doc.add_paragraph(_safe(point), style='List Bullet')
        elif len(primary_patents) < 2:
            doc.add_paragraph("Fewer than two selected primary patents were available for quantitative comparison.")

        # 4. CONCLUSION
        doc.add_heading('4. CONCLUSION', level=2)
        doc.add_paragraph(_safe(report.conclusion or 'No conclusion provided.'))

        # 5. REFERENCES
        doc.add_heading('5. REFERENCES', level=2)
        if report.references:
            for ref in report.references:
                doc.add_paragraph(_safe(ref), style='List Bullet')
        else:
            doc.add_paragraph('No references provided.')

        docx_path = os.path.join(self.export_dir, file_name)
        try:
            doc.save(docx_path)
            return docx_path
        except Exception as e:
            logger.error("Export to DOCX failed: %s", e)
            return ""

    def validate_report_consistency(
        self,
        report: 'PatentResearchReport',
        primary_manifest: list[str],
        secondary_manifest: list[str] = None
    ) -> tuple[bool, list[str]]:
        """
        Run deterministic consistency checks before saving a report run.

        Returns:
            (ok, errors) where ok=True means all checks passed.
        """
        errors = []
        # Secondary patents are not part of the report contract; ignore any leftover list.
        _ = secondary_manifest
        all_manifest = set(primary_manifest)

        primary_patents = getattr(report, 'methodology_patents', []) or []
        secondary_patents = getattr(report, 'secondary_patents', None) or []

        # Check 0: Report must not contain supporting/related/secondary patents
        if secondary_patents:
            errors.append(
                f"CHECK FAIL: Report contains {len(secondary_patents)} secondary/related "
                "patent(s); only the selected primary manifest is allowed."
            )

        # Check 1: Every primary patent has a publication_number
        for p in primary_patents:
            pn = getattr(p.patent_details, 'patent_number', None)
            if not pn:
                errors.append(f"CHECK FAIL: Primary patent missing patent_number: {p}")

        # Check 2: Abstract exists
        if not report.abstract:
            errors.append("CHECK FAIL: Report abstract is empty.")

        # Check 3: If 0 primary patents, cross_patent_comparison must be empty
        if len(primary_patents) == 0 and report.cross_patent_comparison:
            errors.append(
                "CHECK FAIL: 0 primary patents but cross_patent_comparison is non-empty."
            )

        # Check 4: If < 2 primary patents, cross_patent_comparison must be empty
        if len(primary_patents) < 2 and report.cross_patent_comparison:
            errors.append(
                f"CHECK FAIL: {len(primary_patents)} primary patent(s) but "
                "cross_patent_comparison is non-empty (requires >= 2)."
            )

        # Check 5: Every reference must be from the primary manifest
        for ref in report.references:
            # References format: 'PatentNumber | ...'
            ref_pn = ref.split('|')[0].strip() if '|' in ref else ref.strip()
            if ref_pn and all_manifest and ref_pn not in all_manifest:
                errors.append(f"CHECK FAIL: Reference '{ref_pn}' not in evidence manifest.")

        # Check 6: Primary patent numbers match manifest exactly (no extras, no missing)
        report_primary_pns = {
            getattr(p.patent_details, 'patent_number', '') for p in primary_patents
        }
        manifest_set = set(primary_manifest)
        missing = manifest_set - report_primary_pns
        if missing:
            errors.append(f"CHECK FAIL: Missing patents in report: {sorted(missing)}")
        extras = report_primary_pns - manifest_set
        if extras:
            errors.append(f"CHECK FAIL: Extra patents not in selected manifest: {sorted(extras)}")

        ok = len(errors) == 0
        if ok:
            logger.info("[REPORT CONSISTENCY] All checks PASSED.")
        else:
            for err in errors:
                logger.error("[REPORT CONSISTENCY] %s", err)
        return ok, errors
