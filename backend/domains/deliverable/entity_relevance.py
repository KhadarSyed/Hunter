"""Relevance agent for named-entity charts: keeps the brands, products and retailers that belong to the brief's
category and drops the ones a keyword pulled in from another world ('Slay the Spire 2', 'Grafana' and 'DLSS' in a
first-aid study's social data).

Each name's verdict is remembered in the agent memory per category (project 0 = shared), so a later run, or
another project in the same category, reuses it instead of asking again."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import replace

from ...core import store
from .engine_types import Section
from .labels import canon

logger = logging.getLogger(__name__)

SHARED = 0                      # agent-memory scope shared by every project
MEMORY_KIND = "entity_relevance"
# entity charts, and a question's own breakdown of brands ('Competitor brand': where a keyword can pull in 'Gym')
ENTITY_SECTIONS = re.compile(r"-(brands|products|retailers)$|question_breakdown-\w*(brand|competitor|retailer|product)")
MAX_NAMES = 60                  # names judged in one call
_BRAND_FACT = re.compile(r"^Brand (.+): (\d+) of (\d+) brand mentions")


def _judged(category: str) -> dict[str, bool]:
    rows = store.list_memory(SHARED, MEMORY_KIND)
    return next((r["value"] for r in rows if r["key"] == canon(category)), {}) or {}


def _ask(llm, names: list[str], category: str, question: str) -> dict[str, bool]:
    prompt = ("A media-research deck about the category below charts names that articles mention. Some were pulled in "
              "by a keyword used in another sense (a video game, a software tool, a sports team where the category is "
              "first aid). Mark each name relevant=true only if it is a brand, product or retailer that people "
              f"encounter in this category.\nCATEGORY: {category}\nQUESTION: {question}\nNAMES: {json.dumps(names)}\n"
              'Return JSON {"relevant": [names that belong], "not_relevant": [names that do not]}.')
    try:
        reply = json.loads(llm.chat([{"role": "user", "content": prompt}], format_json=True))
    except Exception as e:      # an unjudged name is kept: no verdict is better than a wrong one
        logger.warning("entity relevance check unavailable: %s", type(e).__name__)
        return {}
    keep = {canon(n) for n in reply.get("relevant") or []}
    drop = {canon(n) for n in reply.get("not_relevant") or []}
    return {canon(n): canon(n) in keep for n in names if canon(n) in keep | drop}


def verdicts(llm, names: list[str], category: str, question: str) -> dict[str, bool]:
    """{canon(name): relevant?}, from memory first; unknown names are asked about once and remembered."""
    known = dict(_judged(category))
    unknown = [n for n in dict.fromkeys(names) if canon(n) not in known]
    if unknown and llm is not None:
        fresh = _ask(llm, unknown[:MAX_NAMES], category, question)
        if fresh:
            known.update(fresh)
            store.set_memory(SHARED, MEMORY_KIND, canon(category), known)
    return known


def _is_entity_chart(s: Section) -> bool:
    return not s.skipped and bool(s.chart) and (s.module == "brand_sov" or bool(ENTITY_SECTIONS.search(s.id)))


def _pruned(s: Section, keep) -> Section:
    chart = s.chart or {}
    pairs = [(c, v) for c, v in zip(chart.get("categories") or [], chart.get("values") or []) if keep(c)]
    if not pairs:
        return replace(s, skipped="No names relevant to the brief's category")
    cats, vals = [c for c, _ in pairs], [v for _, v in pairs]
    facts = [f for f in s.facts if not any(f.startswith(n) or f.startswith(f"Brand {n}:")
                                           for n in chart.get("categories") or [] if not keep(n))]
    if chart.get("unit") == "percent":           # shares are re-based on the names that remain
        counts = {m.group(1): int(m.group(2)) for f in facts if (m := _BRAND_FACT.match(f))}
        total = sum(counts.get(c, 0) for c in cats)
        if total:
            vals = [round(100 * counts.get(c, 0) / total, 1) for c in cats]
            facts = [f"Brand {c}: {counts.get(c, 0)} of {total} brand mentions ({v}%)" for c, v in zip(cats, vals)] + \
                    [f for f in facts if not _BRAND_FACT.match(f)]
    table = s.table
    if table and table.get("rows"):
        table = {**table, "rows": [r for r in table["rows"] if not r or keep(str(r[0]))]}
    return replace(s, chart={**chart, "categories": cats, "values": vals}, facts=facts, table=table,
                   segment_urls={k: v for k, v in s.segment_urls.items() if keep(k)})


def prune(sections: list[Section], llm, category: str, question: str, log=lambda _m: None) -> list[Section]:
    """The sections with off-category names removed from every brand/product/retailer chart."""
    charts = [s for s in sections if _is_entity_chart(s)]
    if not charts or not category:
        return sections
    names = [str(c) for s in charts for c in s.chart.get("categories") or []]
    judged = verdicts(llm, names, category, question)

    def keep(name: str) -> bool:
        return judged.get(canon(name), True)

    dropped = sorted({n for n in names if not keep(n)})
    if dropped:
        log(f"Relevance agent dropped {len(dropped)} name(s) outside '{category}': {', '.join(dropped[:8])}")
    return [_pruned(s, keep) if s in charts else s for s in sections]
