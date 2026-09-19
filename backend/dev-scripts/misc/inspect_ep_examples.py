"""Temporary inspection script for EP example formatting."""
import asyncio
import re
from pathlib import Path

from app.services.pipeline.fetcher_service import FetcherService

OUT_DIR = Path("dev-logs")


async def inspect(pn: str) -> None:
    fs = FetcherService()
    url = f"https://patents.google.com/patent/{pn}/en"
    parsed = await fs.fetch_patent(url)
    out = OUT_DIR / f"inspect_{pn}.txt"
    OUT_DIR.mkdir(exist_ok=True)
    lines: list[str] = []
    lines.append(f"pn={pn}")
    lines.append(f"title={parsed.title}")
    ex = parsed.examples or ""
    desc = parsed.detailed_description or ""
    lines.append(f"examples_chars={len(ex)}")
    lines.append(f"desc_chars={len(desc)}")
    lines.append("--- EXAMPLES FIELD HEAD ---")
    lines.append(ex[:4000])
    lines.append("--- EXAMPLE-LIKE LINES IN examples field ---")
    for i, line in enumerate(ex.splitlines()):
        if re.search(r"example", line, re.I):
            lines.append(f"{i}: {line[:180]}")
    lines.append("--- LINE-START EXAMPLE HEADINGS IN examples ---")
    for i, line in enumerate(ex.splitlines()):
        if re.match(
            r"^\s*(Examples?|EXAMPLES?|Example\s+\d|EXAMPLE\s+\d|Working Example|Preparation Example)",
            line,
            re.I,
        ):
            lines.append(f"{i}: {line[:180]}")
    example_pattern = (
        r"(?:(?<=\n)|(?<=\r\n)|^)"
        r"(?:Example|Comparative Example|Preparation Example|Experimental Example|Synthesis Example)"
        r"\s+(?:\d+[a-zA-Z]?|[a-zA-Z])\b[\.\:]?"
    )
    blocks = re.split(f"({example_pattern})", ex, flags=re.IGNORECASE | re.MULTILINE)
    count = sum(1 for b in blocks[1::2] if b.strip())
    lines.append(f"current_regex_split_count={count}")

    # Show unique formats of lines that look like headings
    lines.append("--- UNIQUE HEADING-ISH FORMATS ---")
    seen = set()
    for line in ex.splitlines():
        s = line.strip()
        if re.search(r"^example", s, re.I) or re.search(r"^examples?\b", s, re.I):
            key = re.sub(r"\d+", "N", s[:80])
            if key not in seen:
                seen.add(key)
                lines.append(repr(s[:120]))

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} examples_chars={len(ex)} regex_count={count}")


async def main() -> None:
    for pn in ("EP2316860B1", "EP3827029A1"):
        try:
            await inspect(pn)
        except Exception as e:
            print(f"FAILED {pn}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
