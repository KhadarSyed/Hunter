"""Turns engine findings and the brief into a slide spec: sequence, full questions, A/C treatment by chart
density, the closest reference layout per slide (from any deck), scorecard and checklist."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...core import store
from ..deliverable.engine_types import RQ, Section
from .indexer import FAMILY_WORDS
from .spec import SPEC_VERSION, DeckSpec, SlideSpec

LIGHT_MAX_BARS = 6
CHECKLIST_ROWS_PER_SLIDE = 9
CITES_PER_SLIDE = 14
VERBATIM_TITLE = "{topic} (Verbatims)"
COMPETITOR_VERBATIM_TITLE = "{topic}: competitors (Verbatims)"
WALL_CELLS = 8                    # a 4 x 2 wall of whole posts
BRAND_KEY = "BRAND"                       # sections_by_rq key of the brand vs competitors chapter
BRAND_KICKER = "Brand vs competitors"
DENSE_KINDS = {"line_peaks", "column", "treemap"}
_CODE_PREFIX = re.compile(r"\bRQ\d+\s*:\s*")
_CODE = re.compile(r"\bRQ(\d+)\b")
TYPE_FOR_CHART = {"kpi": "kpi_dashboard", "doughnut": "sentiment_split", "gauge": "kpi_dashboard",
                  "line_peaks": "trend_with_peaks", "column": "trend_with_peaks", "bar": "bar_with_cards",
                  "treemap": "theme_cards"}


@dataclass
class PlanInput:
    title: str
    subtitle: str
    period: str
    base_n: int
    rqs: list[RQ]
    rq_titles: dict[str, str]
    sections_by_rq: dict[str, list[Section]]
    insights_by_rq: dict[str, list[dict]]
    answers: list[dict]
    takeaways: list[dict]
    overview: Section
    methodology: list[str]
    citations: list[dict]
    scope_text: str
    brands: list[str]
    geography: str
    sources: str
    checklist: list[dict] = field(default_factory=list)
    verbatims_by_rq: dict[str, list[dict]] = field(default_factory=dict)
    section_summaries: dict[str, list[dict]] = field(default_factory=dict)   # section id -> its cited summary
    brand_products: list[str] = field(default_factory=list)                  # the client's products, from the brief
    citation_brands: dict[str, list[str]] = field(default_factory=dict)      # citation n -> brands it names literally
    is_category: bool = False                                                # the client is a category, not a brand
    products: list[str] = field(default_factory=list)
    category: str = ""


def treatment(slide_type: str, charts: list[dict], tables: list[dict]) -> str:
    if slide_type in ("cover", "divider", "closing"):
        return "full"
    if tables or any(c["kind"] in DENSE_KINDS or len(c.get("categories", [])) > LIGHT_MAX_BARS for c in charts):
        return "C"
    return "A"


def choose_family(scope_text: str) -> tuple[str, str]:
    low = scope_text.lower()
    for family in ("audit", "travel", "brand_social"):
        hits = [w for w in FAMILY_WORDS[family] if w in low]
        if hits:
            return family, f"the brief mentions {', '.join(hits)}, which matches the {family.replace('_', ' ')} family"
    return "topic_map", "a category/editorial brief, which matches the topic map family"


def pick_reference(slide_type: str, family: str) -> dict:
    candidates = store.list_library_slides(slide_type)
    if not candidates:
        return {}
    same = [c for c in candidates if c["family"] == family]
    best = (same or candidates)[0]
    why = "same family" if same else f"closest {slide_type.replace('_', ' ')} layout in any deck"
    return {"deck": best["deck_path"], "slide": best["n"], "why": why}


def _facts(sections: list[Section]) -> list[str]:
    return [f for s in sections for f in s.facts]


def _evidence(rq: RQ, kicker: str, sections: list[Section], insights: list[dict], family: str,
              summaries: dict[str, list[dict]] | None = None) -> list[SlideSpec]:
    out = []
    drawn = [s for s in sections if not s.skipped and (s.chart or s.table) and (s.chart or {}).get("kind") != "kpi"]
    for i, sec in enumerate(drawn):
        charts = [sec.chart] if sec.chart else []
        tables = [sec.table] if sec.table else []
        slide_type = TYPE_FOR_CHART.get((sec.chart or {}).get("kind", ""), "comparison_table")
        own = (summaries or {}).get(sec.id, [])[:1]          # every chart slide says what its chart shows
        cards = ((insights[:2] if own else insights[:3]) if i == 0 else []) + own
        out.append(SlideSpec(
            id=f"{sec.id}-{i}", type=slide_type, treatment=treatment("evidence", charts, tables), kicker=kicker,
            title=sec.title, question=rq.question, so_what=sec.facts[0].split(": ", 1)[-1] if sec.facts else "",
            charts=charts, tables=tables, cards=cards, facts_allowed=_facts(sections),
            citations=[n for c in cards for n in c.get("citations", [])],
            image={"query": f"{kicker} {sec.title}", "role": "panel"}, reference=pick_reference(slide_type, family)))
    return out


def build_deck_spec(inp: PlanInput) -> DeckSpec:
    family, why = choose_family(inp.scope_text)
    all_facts = _facts([inp.overview] + [s for secs in inp.sections_by_rq.values() for s in secs]) + inp.methodology
    slides = [
        SlideSpec(id="cover", type="cover", treatment="full", title=inp.title, so_what=inp.subtitle, notes=inp.period,
                  image={"query": f"{inp.title} {inp.subtitle}", "role": "background"}, reference=pick_reference("cover", family)),
        SlideSpec(id="objectives", type="objectives", treatment="A", title="Objectives & scope",
                  cards=[{"headline": q.question, "text": ""} for q in inp.rqs],
                  notes=f"Brands: {', '.join(inp.brands)} · Sources: {inp.sources} · Geography: {inp.geography} · Period: {inp.period}",
                  image={"query": f"{inp.title} research", "role": "background"}, facts_allowed=all_facts,
                  reference=pick_reference("objectives", family)),
        SlideSpec(id="executive-summary", type="executive_summary", treatment="A", title="What the coverage says",
                  so_what=f"Base: {inp.base_n} unique articles across {len(inp.rqs)} questions",
                  cards=[{"headline": a["value"], "text": a["question"], "note": a["answer"],
                          "citations": (next(iter(inp.insights_by_rq.get(a["rq_id"]) or []), {}) or {}).get("citations", [])}
                         for a in inp.answers],
                  facts_allowed=all_facts + [str(len(inp.rqs))], image={"query": f"{inp.title} overview", "role": "background"},
                  reference=pick_reference("kpi_dashboard", family))]
    brand_sections = inp.sections_by_rq.get(BRAND_KEY) or []
    if brand_sections:                    # the client against its competitors, before the question chapters
        brand_rq = RQ(BRAND_KEY, f"How does {inp.title} compare with its competitors?")
        slides += _evidence(brand_rq, BRAND_KICKER, brand_sections, [], family, inp.section_summaries)
    for k, rq in enumerate(inp.rqs, start=1):
        kicker = inp.rq_titles.get(rq.id) or f"Question {k}"
        answer = next((a for a in inp.answers if a["rq_id"] == rq.id), {})
        sections = inp.sections_by_rq.get(rq.id, [])
        slides.append(SlideSpec(id=f"{rq.id.lower()}-divider", type="divider", treatment="full",
                                kicker=f"Question {k} of {len(inp.rqs)}", question=rq.question,
                                so_what=answer.get("answer", ""), facts_allowed=_facts(sections) + [str(k), str(len(inp.rqs))],
                                image={"query": kicker, "role": "background"}, reference=pick_reference("divider", family)))
        slides += _evidence(rq, kicker, sections, inp.insights_by_rq.get(rq.id, []), family, inp.section_summaries)
        items = inp.verbatims_by_rq.get(rq.id) or []
        if items:
            slides.append(SlideSpec(
                id=f"{rq.id.lower()}-verbatims", type="verbatim_wall", treatment="plain", kicker=kicker,
                title=VERBATIM_TITLE.format(topic=kicker), question=rq.question,
                cards=[{"headline": v["outlet"], "text": v["date"], "url": v["url"], "image": v.get("image")}
                       for v in items[:WALL_CELLS]],
                facts_allowed=_facts(sections) + [v["date"] for v in items], notes="\n".join(v["url"] for v in items)))
        rivals = inp.verbatims_by_rq.get(f"{rq.id}-COMPETITORS") or []
        if rivals:                    # competitors' voices on their own slide, never mixed with the brand's
            slides.append(SlideSpec(
                id=f"{rq.id.lower()}-competitors-verbatims", type="verbatim_wall", treatment="plain", kicker=kicker,
                title=COMPETITOR_VERBATIM_TITLE.format(topic=kicker), question=rq.question,
                cards=[{"headline": v["outlet"], "text": v["date"], "url": v["url"], "image": v.get("image")}
                       for v in rivals[:WALL_CELLS]],
                facts_allowed=_facts(sections) + [v["date"] for v in rivals], notes="\n".join(v["url"] for v in rivals)))
    slides.append(SlideSpec(id="takeaways", type="takeaways", treatment="A", title="Key takeaways", cards=inp.takeaways[:6],
                            facts_allowed=all_facts, citations=[n for c in inp.takeaways for n in c.get("citations", [])],
                            image={"query": f"{inp.title} takeaways", "role": "background"},
                            reference=pick_reference("takeaways", family)))
    counts = {s: sum(1 for r in inp.checklist if r["status"] == s) for s in ("covered", "partial", "missing")}
    gaps = [r for r in inp.checklist if r["status"] != "covered"]
    slides.append(SlideSpec(id="scorecard", type="scorecard", treatment="A", title="Did we answer the brief?",
                            cards=[{"headline": str(counts[s]), "text": s} for s in ("covered", "partial", "missing")],
                            tables=[{"header": ["Brief asked", "Status", "Why"], "rows": [[g["ask"], g["status"], g["note"]] for g in gaps]}],
                            facts_allowed=all_facts + [str(v) for v in counts.values()],
                            image={"query": f"{inp.title} brief", "role": "background"}))
    for p in range(0, max(1, len(inp.checklist)), CHECKLIST_ROWS_PER_SLIDE):
        rows = inp.checklist[p:p + CHECKLIST_ROWS_PER_SLIDE]
        slides.append(SlideSpec(id=f"checklist-{p // CHECKLIST_ROWS_PER_SLIDE + 1}", type="checklist", treatment="plain",
                                title="Brief checklist", facts_allowed=list(all_facts),
                                tables=[{"header": ["Brief asked", "Status", "Where", "Note"],
                                         "rows": [[r["ask"], r["status"], "—", r["note"]] for r in rows]}]))
    slides.append(SlideSpec(id="methodology", type="methodology", treatment="plain", title="Definitions & methodology",
                            cards=[{"headline": "", "text": m} for m in inp.methodology], facts_allowed=all_facts))
    for p in range(0, max(1, len(inp.citations)), CITES_PER_SLIDE):
        page = inp.citations[p:p + CITES_PER_SLIDE]
        slides.append(SlideSpec(id=f"citations-{p // CITES_PER_SLIDE + 1}", type="citations", treatment="plain", title="Sources",
                                tables=[{"header": ["#", "Source", "Headline", "Date"],
                                         "rows": [[str(c["n"]), c.get("outlet") or c.get("domain", ""), c["title"], c["date"]] for c in page]}],
                                facts_allowed=all_facts + [str(c["n"]) for c in page] + [c["date"] for c in page],
                                notes="\n".join(c["url"] for c in page),
                                logos={(c.get("outlet") or c.get("domain", "")): c["icon"] for c in page if c.get("icon")}))
    slides.append(SlideSpec(id="closing", type="closing", treatment="full", title="Thank you", so_what=inp.title,
                            image={"query": f"{inp.title} thank you", "role": "background"}, reference=pick_reference("closing", family)))
    for s in slides:
        _without_codes(s)
    return DeckSpec(version=SPEC_VERSION, title=inp.title, subtitle=inp.subtitle, period=inp.period, base_n=inp.base_n,
                    family=family, family_reason=why, tokens=None, slides=slides,
                    citation_meta={str(c["n"]): {"outlet": c.get("outlet") or c.get("domain", ""), "icon": c.get("icon") or ""}
                                   for c in inp.citations})


def _plain(text: str) -> str:
    """Slides speak in questions, not codes: 'RQ1: 227 of 778' -> '227 of 778', other 'RQ3' -> 'Question 3'."""
    return _CODE.sub(lambda m: f"Question {m.group(1)}", _CODE_PREFIX.sub("", str(text)))


def _without_codes(s: SlideSpec) -> None:
    s.kicker, s.title, s.so_what = _plain(s.kicker), _plain(s.title), _plain(s.so_what)
    s.cards = [{k: (_plain(v) if isinstance(v, str) else v) for k, v in c.items()} for c in s.cards]
    s.tables = [{**t, "rows": [[_plain(cell) for cell in row] for row in t.get("rows", [])]} for t in s.tables]
