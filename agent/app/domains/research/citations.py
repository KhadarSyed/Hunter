"""Ground Background Research citations in the source register.

Every section's [S#] tags are checked against the register: unknown tags are removed, the valid ones are
recorded on the section as `sources`, and a section left with none is flagged `unsourced` (never given
made-up sources). Methodology and the Source Register itself are exempt.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

EXEMPT_SECTIONS = frozenset({"methodology", "source_register"})
_TAG = re.compile(r"\[\s*([Ss]\d+(?:\s*,\s*[Ss]\d+)*)\s*\]")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?])")


def _norm_url(url: str) -> str:
    return str(url or "").strip().rstrip("/").lower()


def _rewrite(content: str, valid: set[str], used: list[str]) -> str:
    def repl(m: re.Match) -> str:
        refs = [r.strip().upper() for r in m.group(1).split(",")]
        kept = [r for r in refs if r in valid]
        for r in kept:
            if r not in used:
                used.append(r)
        return "".join(f"[{r}]" for r in kept)
    out = _TAG.sub(repl, content)
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)          # "fell [S9]." → "fell ." → "fell."
    return re.sub(r"[ \t]{2,}", " ", out)


def enforce_citations(sections: dict, register: list[dict]) -> dict:
    """Return new sections with invalid tags stripped and `sources` / `unsourced` set (input untouched)."""
    valid = {e["ref"].upper() for e in register if e.get("ref")}
    out = {}
    for key, section in sections.items():
        if key in EXEMPT_SECTIONS or not isinstance(section, dict):
            out[key] = section
            continue
        used: list[str] = []
        content = _rewrite(str(section.get("content", "")), valid, used)
        out[key] = {**section, "content": content, "sources": sorted(used, key=lambda r: int(r[1:])),
                    "unsourced": not used}
    return out


def research_item_sources(items: list[dict], existing_urls: set[str]) -> list[dict]:
    """Stored research items the register doesn't have yet, shaped like register inputs, so everything the
    summarizer reads can be cited."""
    seen = {_norm_url(u) for u in existing_urls}
    out = []
    for item in items:
        url = item.get("url") or ""
        if not url or _norm_url(url) in seen:
            continue
        seen.add(_norm_url(url))
        ts = item.get("published_date")
        date = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else ""
        out.append({"url": url, "headline": item.get("title") or "Untitled",
                    "publisher": item.get("publication") or "", "date": date})
    return out
