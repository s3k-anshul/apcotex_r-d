"""
Generic example-section boundary detection for patent text.

Compound-agnostic / jurisdiction-agnostic: matches common heading *structures*
(US-style "Example N", EP-style "Inventive Examples and Comparative Examples",
standalone "Examples", German "Beispiele", etc.) without hardcoding any
material, patent number, or jurisdiction branch.
"""
from __future__ import annotations

import re

# Starts a scientific/examples block within a full description (fetcher).
# Never matches bare mid-sentence "example" / "for example".
EXAMPLE_BLOCK_START_PATTERN = (
    r"(?:"
    r"examples?[ \t]+\d+[a-zA-Z]?"  # Example 1 (same line)
    r"|inventive[ \t]+examples?"
    r"|comparative[ \t]+examples?"
    r"|working[ \t]+examples?"
    r"|preparation[ \t]+examples?"
    r"|experimental[ \t]+examples?"
    r"|synthesis[ \t]+examples?"
    r"|manufacturing[ \t]+examples?"
    r"|polymerization[ \t]+examples?"
    r"|polymerisation[ \t]+examples?"
    r"|reference[ \t]+examples?"
    r"|examples?[ \t]+materials(?:[ \t]+used)?"
    r"|^[ \t]*examples?[ \t]*$"  # lone 'Examples' heading line
    r"|^[ \t]*beispiele[ \t]*$"
    r"|erfindungsgemäße?[ \t]+beispiele"
    r"|vergleichsbeispiele"
    r"|detailed[ \t]+description"
    r"|best[ \t]+mode"
    r"|mode[ \t]+for[ \t]+carrying[ \t]+out"
    r"|embodiment"
    r"|experimental[ \t]+procedure"
    r"|general[ \t]+procedure"
    r"|reaction[ \t]+procedure"
    r"|synthesis[ \t]+procedure"
    r"|polymer[ \t]+preparation"
    r"|production[ \t]+example"
    r")"
)

# Splits an examples block into individual sections (extractor).
EXAMPLE_SECTION_SPLIT_PATTERN = (
    r"(?:(?<=\n)|(?<=\r\n)|^)"
    r"("
    r"(?:\(\s*)?"
    r"(?:"
    r"(?:Comparative|Preparation|Experimental|Synthesis|Working|Inventive|"
    r"Reference|Manufacturing|Polymerization|Polymerisation)[ \t]+"
    r"Examples?"
    r"(?:[ \t]+and[ \t]+Comparative[ \t]+Examples?)?"
    r"(?:[ \t]+sowie[ \t]+Vergleichsbeispiele)?"
    r"(?:[ \t]+\d+[a-zA-Z]?)?"
    r"|"
    # Classic numbered / lettered Example on the SAME line (no newline in gap)
    r"Examples?[ \t]+(?:\d+[a-zA-Z]?|[A-Z])\b"
    r"|"
    r"Examples?[ \t]+Materials(?:[ \t]+used)?"
    r"|"
    r"Examples?(?=[ \t]*(?:[\.\:]?[ \t]*)?(?:\n|$))"
    r"|"
    r"Beispiele(?=[ \t]*(?:[\.\:]?[ \t]*)?(?:\n|$))"
    r"|"
    r"Erfindungsgemäße?[ \t]+Beispiele(?:[ \t]+sowie[ \t]+Vergleichsbeispiele)?"
    r"|"
    r"Vergleichsbeispiele"
    r")"
    r"(?:\s*\))?"
    r"[\.\:]?"
    r")"
)

EXAMPLE_BLOCK_START_RE = re.compile(EXAMPLE_BLOCK_START_PATTERN, re.IGNORECASE | re.MULTILINE)
EXAMPLE_SECTION_SPLIT_RE = re.compile(EXAMPLE_SECTION_SPLIT_PATTERN, re.IGNORECASE | re.MULTILINE)

_PROSE_EXAMPLE_PREFIXES = (
    "examples of ",
    "example of ",
    "example,",
    "example;",
    "for example",
    "by way of example",
    "as an example",
)


def is_prose_example_mention(heading: str) -> bool:
    """True if a matched 'example' span is mid-sentence prose, not a section heading."""
    h = (heading or "").strip().lower()
    if not h:
        return True
    for prefix in _PROSE_EXAMPLE_PREFIXES:
        if h.startswith(prefix):
            return True
    if re.match(r"^examples?\s+of\b", h):
        return True
    return False


def _line_at(text: str, index: int) -> str:
    end = text.find("\n", index)
    if end < 0:
        end = len(text)
    return text[index:end]


def _is_plausible_heading_line(line: str, matched: str) -> bool:
    """Reject long prose lines that merely contain heading-like phrases."""
    line_s = (line or "").strip()
    matched_s = (matched or "").strip()
    if not line_s:
        return False
    if is_prose_example_mention(line_s):
        return False
    # Essentially the heading alone
    if len(line_s) <= max(len(matched_s) + 8, 48):
        return True
    # Short compound headings (Inventive Examples and Comparative Examples)
    if re.match(
        r"^(inventive|comparative|working|preparation|experimental|synthesis|"
        r"reference|manufacturing|polymerization|polymerisation).{0,90}$",
        line_s,
        re.I,
    ):
        low = line_s.lower()
        if any(tok in low for tok in (" again ", " only ", " were used", " is ", " are ")):
            return False
        return True
    if re.match(r"^examples?\s+\d+", line_s, re.I):
        return True
    if re.match(r"^examples?\s+materials", line_s, re.I):
        return True
    if re.match(r"^(examples?|beispiele)\s*$", line_s, re.I):
        return True
    return False


def find_examples_block_start(desc_text: str) -> int | None:
    """Return start index of the first real examples/procedure block, or None."""
    if not desc_text:
        return None

    def _match_line_start(m: re.Match) -> tuple[bool, int, str]:
        """Return (at_line_start, content_index, line_text)."""
        idx = m.start()
        if idx > 0 and desc_text[idx] in "\n\r":
            idx += 1
        at_line = m.start() == 0 or desc_text[m.start()] in "\n\r" or (
            m.start() > 0 and desc_text[m.start() - 1] in "\n\r"
        )
        return at_line, idx, _line_at(desc_text, idx)

    strong: int | None = None
    weak: int | None = None
    for m in EXAMPLE_BLOCK_START_RE.finditer(desc_text):
        at_line, content_idx, line = _match_line_start(m)
        if not at_line:
            continue
        matched = m.group(0).lstrip("\n\r")
        if not _is_plausible_heading_line(line, matched):
            continue
        low = matched.lower()
        is_strong = bool(
            "inventive" in low
            or "comparative" in low
            or "beispiele" in low
            or re.search(r"examples?\s+\d+", low)
            or re.search(r"examples?\s+materials", low)
            or re.match(r"^\s*examples?\s*$", matched, re.I)
        )
        if is_strong:
            strong = content_idx
            break
        if weak is None and "detailed description" not in low:
            weak = content_idx
        elif weak is None:
            weak = content_idx
    return strong if strong is not None else weak


def split_example_sections(text: str) -> list[tuple[str, str]]:
    """
    Split patent examples text into (header, body) pairs.
    Returns [] when no structured section headings are found.
    """
    if not text or not text.strip():
        return []

    blocks = EXAMPLE_SECTION_SPLIT_RE.split(text)
    if len(blocks) <= 1:
        return []

    sections: list[tuple[str, str]] = []
    for i in range(1, len(blocks), 2):
        header = (blocks[i] or "").strip()
        body = (blocks[i + 1] if i + 1 < len(blocks) else "") or ""
        if not header or is_prose_example_mention(header):
            continue
        if "\n" in header:
            header = header.split("\n", 1)[0].strip()
        if not _is_plausible_heading_line(header, header):
            continue
        # Keep list/range headings intact: "Examples 2-25", "Examples 1, 1a, 1b".
        # The section pattern matches only the first number, so the rest of a
        # heading line would otherwise be treated as body text or a new section.
        first_line, sep, remainder = body.partition("\n")
        continuation = first_line.strip()
        if (
            continuation
            and len(continuation) <= 80
            and len(continuation.split()) <= 8
            and re.match(r"^(?:and\b|[,&/\-–—]|\d)", continuation)
        ):
            glue = "" if continuation[:1] in ",-/–—" else " "
            header = f"{header}{glue}{continuation}".strip()
            body = remainder if sep else ""
        sections.append((header, body.strip()))
    return sections
