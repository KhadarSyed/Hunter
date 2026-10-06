"""LLM-drafted insights, accepted only if every number and citation checks out."""
from __future__ import annotations

import json
import logging
import re

from .citations import CitationRegistry
from .ingest import Article

logger = logging.getLogger(__name__)
_NUM = re.compile(r"\d+(?:\.\d+)?")
_YEARS = {"2024", "2025", "2026"}


def allowed_numbers(facts: list[str]) -> set[str]:
    return {n for f in facts for n in _NUM.findall(f)} | _YEARS


def validate_insight(text: str, cites: list[int], allowed: set[str], candidate_ids: set[int]) -> str | None:
    if not cites or not set(cites) <= candidate_ids:
        return "citation missing or outside candidate set"
    bad = [n for n in _NUM.findall(text) if n not in allowed]
    if bad:
        return f"number(s) not in facts: {bad}"
    return None


def _fallback(facts: list[str], candidates: list[Article], registry: CitationRegistry) -> list[dict]:
    if not facts or not candidates:
        return []
    return [{"headline": "Key finding", "text": facts[0], "citations": [registry.cite(a) for a in candidates[:2]]}]


def draft_section(section: str, facts: list[str], candidates: list[Article], registry: CitationRegistry,
                  llm, n_insights: int = 3) -> list[dict]:
    """Candidates get local ids 1..k in the prompt; only articles an accepted insight actually cites are
    registered, so the appendix lists cited articles only."""
    if llm is None:
        return _fallback(facts, candidates, registry)
    allowed = allowed_numbers(facts)
    local = {i: a for i, a in enumerate(candidates, start=1)}
    arts = [{"id": i, "outlet": a.outlet, "date": a.date.isoformat() if a.date else "", "title": a.title,
             "excerpt": a.text[:400]} for i, a in local.items()]
    messages = [
        {"role": "system", "content": "You write insights for a media-research deck. Use ONLY numbers that appear "
         "in FACTS. Every insight must cite article ids from ARTICLES that support it. Return JSON only."},
        {"role": "user", "content": f"Section: {section}\nFACTS:\n" + "\n".join(f"- {f}" for f in facts) +
         f"\nARTICLES:\n{json.dumps(arts, ensure_ascii=False)}\nWrite {n_insights} insights as "
         '{"insights":[{"headline":"<=8 words","text":"<=45 words","citations":[ids]}]}'},
    ]
    try:
        parsed = json.loads(llm.chat(messages, format_json=True))
    except (json.JSONDecodeError, RuntimeError) as e:
        logger.warning("insight drafting for %s failed (%s); using fallback", section, e)
        return _fallback(facts, candidates, registry)
    kept = []
    for ins in parsed.get("insights", []):
        headline, text = str(ins.get("headline", "")).strip(), str(ins.get("text", "")).strip()
        cites = [int(c) for c in ins.get("citations", []) if str(c).isdigit()]
        reason = validate_insight(f"{headline} {text}", cites, allowed, set(local))
        if reason:
            logger.info("dropped insight in %s: %s", section, reason)
            continue
        kept.append({"headline": headline, "text": text,
                     "citations": sorted({registry.cite(local[c]) for c in cites})})
    return kept or _fallback(facts, candidates, registry)
