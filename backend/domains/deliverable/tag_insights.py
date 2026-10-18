"""The question answered from its question-driven tags.

The schema's lead classification (deal_sale_led: Yes/No) gives the answer as a share of the tagged articles, and the
articles tagged Yes give what drives it: the outlets, brands and themes they lead with, the month they peak, the
supporting tags (deal type, expert type) and quoted examples. These become facts the insight writer may use -- every
number in an insight still has to come from them -- and the quoted articles are offered as its first citations.
"""
from __future__ import annotations

import re
from collections import Counter

from ...agents.question_tag_schema import TagDef, TagSchema
from .engine_types import RQ, EngineRow, Section
from .labels import unify

TOP = 3
MAX_QUOTES = 3
POSITIVE = ("Yes", "True")


def _pct(n: int, base: int) -> float:
    return round(100 * n / base, 1) if base else 0.0


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2}


def _lead(schema: TagSchema, question: str = "") -> TagDef | None:
    """The tag that answers the question: the Yes/No classification whose name shares the most words with the
    question ('expert_brand_affiliated' for 'what percentage are affiliated with a brand?', not 'expert_cited'),
    else the first classification."""
    classes = [t for t in schema.tags if t.tag_type in ("classification", "multi_classification")]
    yes_no = [t for t in classes if any(v in POSITIVE for v in t.allowed_values)]
    if not yes_no:
        return classes[0] if classes else None
    words = _stems(question)
    return max(yes_no, key=lambda t: (len(_stems(t.tag_name.replace("_", " ")) & words), -yes_no.index(t)))


def lead_tag(schema: TagSchema | None, question: str = "") -> str:
    """The dynamic tag that answers the question ("" when it has none)."""
    lead = _lead(schema, question) if schema else None
    return lead.tag_name if lead else ""


def _values(row: EngineRow, tag: str) -> list[str]:
    v = (row.dynamic_tags or {}).get(tag)
    return [x for x in (v if isinstance(v, list) else [v]) if x]


def _unified(rows: list[EngineRow], tag: TagDef) -> dict[int, list[str]]:
    """{id(row): its values for `tag`}, with spelling, case and plural variants under one label (the schema's own
    allowed value when one matches)."""
    names = unify((str(v) for r in rows for v in _values(r, tag.tag_name)), tag.allowed_values)
    return {id(r): list(dict.fromkeys(names[str(v)] for v in _values(r, tag.tag_name))) for r in rows}


def _top(counter: Counter, unit: str = "articles") -> str:
    return ", ".join(f"{k} ({n} {unit if n != 1 else unit.rstrip('s')})" for k, n in counter.most_common(TOP))


def _driver_facts(rq: RQ, label: str, hits: list[EngineRow], schema: TagSchema, lead: TagDef) -> list[str]:
    facts = []
    outlets = Counter(r.article.outlet for r in hits if r.article.outlet)
    if outlets:
        facts.append(f"{rq.id}: outlets leading {label} coverage: {_top(outlets)}")
    brands = Counter(b for r in hits for b in dict.fromkeys((r.entities or {}).get("brands") or []))
    if brands:
        facts.append(f"{rq.id}: brands most named in {label} coverage: {_top(brands)}")
    themes = Counter(t for r in hits for t in dict.fromkeys(r.themes or []))
    if themes:
        facts.append(f"{rq.id}: leading themes in {label} coverage: {_top(themes)}")
    months = Counter(r.article.date.strftime("%b %Y") for r in hits if r.article.date)
    if months:
        month, n = months.most_common(1)[0]
        facts.append(f"{rq.id}: {label} coverage peaks in {month} ({n} article{'s' if n != 1 else ''})")
    for t in schema.tags:
        if t.tag_name == lead.tag_name or t.tag_type == "entity":
            continue
        counts = Counter(v for r in hits for v in _values(r, t.tag_name) if v not in ("None", "Unknown"))
        for value, n in counts.most_common(TOP):
            facts.append(f"{rq.id}: {_label(t.tag_name)} {value}: {n} of {len(hits)} {label} articles")
    for t in schema.tags:
        if t.tag_type == "entity":
            named = Counter(v for r in hits for v in _values(r, t.tag_name))
            if named:
                facts.append(f"{rq.id}: {_label(t.tag_name)} most named: {_top(named)}")
    return facts


def tag_section(rq: RQ, rows: list[EngineRow], schema: TagSchema | None) -> Section | None:
    lead = _lead(schema, rq.question) if schema else None
    if lead is None:
        return None
    tagged = [r for r in rows if _values(r, lead.tag_name)]
    if not tagged:
        return None
    vals = _unified(tagged, lead)
    counts = Counter(v for r in tagged for v in vals[id(r)])
    order = [v for v in lead.allowed_values if counts.get(v)] + [v for v in counts if v not in lead.allowed_values]
    label = _label(lead.tag_name)
    yes = next((v for v in order if v in POSITIVE), order[0])
    hits = [r for r in tagged if yes in vals[id(r)]]
    facts = [f"{rq.id}: {label}: {yes} in {counts[yes]} of {len(tagged)} tagged articles ({_pct(counts[yes], len(tagged))}%)"]
    facts += [f"{rq.id}: {label}: {v} in {counts[v]} of {len(tagged)} tagged articles ({_pct(counts[v], len(tagged))}%)"
              for v in order if v != yes]
    facts += _driver_facts(rq, label.lower(), hits, schema, lead)
    quoted = [r for r in hits if (r.tag_evidence or {}).get(lead.tag_name)]
    facts += [f'{rq.id}: example of {label.lower()} coverage, {r.article.outlet}: "{r.tag_evidence[lead.tag_name]}"'
              for r in quoted[:MAX_QUOTES]]
    cite_first = [r.article.norm_url for r in quoted] + [r.article.norm_url for r in hits]
    return Section(id=f"{rq.id.lower()}-tag_share-{lead.tag_name}", rq_id=rq.id, module="tag_share",
                   title=f"{label}: share of tagged coverage",
                   chart={"kind": "bar", "categories": order, "values": [counts[v] for v in order], "unit": "count",
                          "peaks": [], "series_label": "Articles", "n": len(tagged)},     # out of the tagged articles
                   facts=facts, candidate_urls=list(dict.fromkeys(cite_first)),
                   notes=[f"Base: {len(tagged)} articles tagged for this question"],
                   segment_urls={v: [r.article.norm_url for r in tagged if v in vals[id(r)]][:8]
                                 for v in order})


def tag_answer(rq: RQ, section: Section) -> dict:
    """The executive-summary answer: the tagged share and what leads it."""
    cats, vals = section.chart["categories"], section.chart["values"]
    total = sum(vals)
    yes = next((c for c in cats if c in POSITIVE), cats[0])
    n = vals[cats.index(yes)]
    pct = _pct(n, total)
    label = section.title.split(":")[0].lower()
    lead = next((f.split(": ", 2)[2] for f in section.facts if " outlets leading " in f), "")
    text = f"{n} of {total} tagged articles ({pct}%) are {label}" + (f"; led by {lead}" if lead else "")
    return {"rq_id": rq.id, "question": rq.question, "value": f"{pct}%", "answer": text}
