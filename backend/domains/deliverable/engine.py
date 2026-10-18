"""Deliverable engine: ten persisted stages, each broadcast on /ws; a failed stage stops the run visibly."""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from pptx import Presentation

from ...core import config, store, writing_locale
from ...core.events import broadcast
from . import (analytics, brand_kit, catalog, engine_insights, extract, factcheck, generic_deck, templates_index,
               visuals, word_brief)
from . import brand_analytics, chart_choice, entity_relevance, evidence, repair_context, tag_insights
from ...agents import question_tag_schema
from . import rows as R
from .citations import CitationRegistry, domain_of
from .ingest import normalize_url
from .engine_types import RQ, Section
from ..agent import memory as agent_memory
from ..agent.repair import issues
from ..deckstudio import verbatims, vision
from ..deckstudio.pipeline import run_studio
from ..deckstudio.checklist import brief_asks
from ..deckstudio.planner import BRAND_KEY, PlanInput
from ..strategy.dimensions import project_dimensions as question_dimensions

logger = logging.getLogger(__name__)
STAGES = ("gate", "ingest", "routing", "plan", "classify", "compute", "insights", "template", "render", "qc",
          "index", "design", "assets", "compose", "export", "repair")
MAX_LOGOS = 40
RETAIL_CATEGORY = "retail: stores, supermarkets and online marketplaces"
CITE_POOL = 12          # brand / competitor articles offered to the brand chapter's summaries
INSIGHT_WORKERS = 4     # questions drafting insights at once (each makes several chat calls)
_lock = threading.Lock()


class RunBusy(RuntimeError):
    pass


class StageFailed(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def _gate_reasons(project_id: int) -> list[str]:
    reasons = []
    if (store.get_latest_spec(project_id) or {}).get("approval_status") != "approved":
        reasons.append("Scope is not approved")
    if (store.get_latest_strategy(project_id) or {}).get("approval_status") != "approved":
        reasons.append("Search strategy is not approved")
    if not [d for d in store.get_datasets_by_project(project_id) if d.get("approval_status") == "approved"]:
        reasons.append("No approved dataset")
    return reasons


def _rq_label(q: RQ, limit: int = 90) -> str:
    """The question itself next to its id: analyst-authored text, never article content."""
    text = " ".join((q.question or "").split())
    if not text:
        return q.id
    return f'{q.id} "{text[:limit - 1]}…"' if len(text) > limit else f'{q.id} "{text}"'


_STAGE_LABELS = {"gate": "Checking approvals", "ingest": "Ingesting approved datasets",
                 "routing": "Routing articles to questions", "plan": "Planning analyses",
                 "classify": "Classifying entities", "compute": "Computing charts and tables",
                 "insights": "Drafting cited insights", "template": "Choosing a template",
                 "render": "Building slides", "qc": "Fact check and layout QC",
                 "index": "Reading reference decks", "design": "Designing the deck",
                 "assets": "Finding photos & logos", "compose": "Composing slides", "export": "Exporting PPTX & PDF",
                 "repair": "Repairing open deck checks"}


# Share of a typical run's time spent in each stage: the overall % moves with the work, not the stage count
# Percent of a run per stage (sums to 100), measured on run 45 (2026-10-13): photo search and article screenshots
# (assets) dominate now that the creative restyle is off, so compose is short. The repair agent's 4 is an estimate
# (a re-render and export when checks are open), taken from assets until runs are measured again
STAGE_WEIGHTS = {"gate": 0, "ingest": 0, "routing": 0.3, "plan": 1.2, "classify": 0.2, "compute": 0, "insights": 7.6,
                 "template": 0.1, "render": 17.8, "qc": 2.9, "index": 7.7, "design": 0.6, "assets": 51.6, "compose": 1.5,
                 "export": 4.5, "repair": 4}
TYPICAL_RUNS = 5


def _typical_seconds() -> float | None:
    durations = sorted(store.recent_run_durations(TYPICAL_RUNS))
    return durations[len(durations) // 2] if durations else None


_QUOTED = re.compile(r'\s*"[^"]*"')


def _wire(text: str) -> str:
    """What /ws may carry: ids and counts. Quoted text (a research question, a headline) stays in the stored
    log, which the page reads through the access-checked REST route."""
    return _QUOTED.sub("", text)


def _stage_span(name: str) -> tuple[float, float]:
    before = 0
    for stage in STAGES:
        if stage == name:
            return before, before + STAGE_WEIGHTS.get(stage, 0)
        before += STAGE_WEIGHTS.get(stage, 0)
    return before, before


class _Run:
    def __init__(self, run_id: int, project_id: int):
        self.run_id, self.project_id, self.stages, self.lines = run_id, project_id, {}, []
        self.started_at, self.pct, self.current = time.time(), 0, "gate"
        self.timings: dict[str, list[float]] = {}
        self.typical = _typical_seconds()

    def progress(self, pct: float, label: str) -> None:
        """Overall % (never goes back) and what is happening right now; kept with the run for page reloads."""
        self.pct = max(self.pct, min(100, int(round(pct))))
        state = {"pct": self.pct, "stage": self.current, "label": label, "started_at": self.started_at,
                 "typical_seconds": self.typical}
        store.replace_deliverable_section(self.run_id, {"id": "progress", "rq_id": None, "module": "progress",
                                                        "title": "Progress", **state})
        broadcast({"type": "deliverable_progress", "project_id": self.project_id, "run_id": self.run_id,
                   **state, "label": _wire(label)})

    def within(self, stage: str, fraction: float, label: str) -> None:
        start, end = _stage_span(stage)
        self.progress(start + (end - start) * max(0.0, min(1.0, fraction)), label)

    def log(self, message: str) -> None:
        """A progress line, kept with the run in full and streamed live without its quoted text (see _wire),
        because /ws is unauthenticated."""
        line = {"ts": time.time(), "message": message}
        self.lines.append(line)
        store.replace_deliverable_section(self.run_id, {"id": "log", "rq_id": None, "module": "log",
                                                        "title": "Run log", "lines": self.lines})
        broadcast({"type": "deliverable_log", "project_id": self.project_id, "run_id": self.run_id,
                   **line, "message": _wire(message)})

    def stage(self, name: str, status: str, detail: str = "") -> None:
        self.stages[name] = status
        now = time.time()
        if status == "running":
            self.timings[name] = [now, now]
        elif name in self.timings:
            self.timings[name][1] = now
            store.replace_deliverable_section(self.run_id, {"id": "timings", "rq_id": None, "module": "timings",
                                                            "title": "Timings", "stages": self.timings})
        store.update_deliverable_run(self.run_id, stage=name, stages_json=self.stages)
        broadcast({"type": "deliverable_stage", "project_id": self.project_id, "run_id": self.run_id,
                   "stage": name, "status": status, "detail": _wire(detail)})
        if status == "running":
            self.current = name
            self.log(f"{_STAGE_LABELS.get(name, name)} ({name})…")
            self.within(name, 0, _STAGE_LABELS.get(name, name))
        elif status == "done":
            self.log(f"Done: {name}" + (f" - {detail}" if detail else ""))
            self.within(name, 1, f"Done: {_STAGE_LABELS.get(name, name)}")

    def section(self, payload: dict) -> None:
        store.save_deliverable_section(self.run_id, payload)
        # Ids only: /ws is unauthenticated, so the page fetches content through the access-checked REST route
        broadcast({"type": "deliverable_section", "project_id": self.project_id, "run_id": self.run_id,
                   "section_id": payload["id"]})


def start_run(project_id: int, *, llm=None, threaded: bool = True) -> int:
    with _lock:
        if store.get_active_deliverable_run(project_id):
            raise RunBusy("A deliverable run is already in progress")
        run_id = store.create_deliverable_run(project_id)
    if threaded:
        if llm is None:
            try:
                from ...core.anthropic_client import get_llm_client
                llm = get_llm_client()
            except Exception as e:      # never leave a 'running' row behind: it would block Generate for good
                logger.error("[deliverable:%s] LLM client unavailable: %s", run_id, e)
                store.update_deliverable_run(run_id, status="failed", stage="gate", error=str(e),
                                             finished_at=time.time())
                return run_id
        threading.Thread(target=run_engine, args=(run_id, project_id, llm), daemon=True).start()
    else:
        run_engine(run_id, project_id, llm)
    return run_id


def _scope_text(project: dict) -> str:
    spec = project.get("spec") or {}
    return " ".join(filter(None, [(spec.get("commissioning_brand") or {}).get("name"),
                                  (spec.get("industry") or {}).get("name"),
                                  (spec.get("research_subject") or {}).get("description"),
                                  str(spec.get("raw_brief") or "")[:600]]))


def _subtitle(title: str, project_name: str) -> str:
    """The project name without the repeated title ("Baby Skincare Category - Earned Editorial" -> "Earned Editorial")."""
    name = (project_name or "").strip()
    if name.lower().startswith(title.lower()):
        name = name[len(title):].lstrip(" -–—:|")
    return name or "Media Analysis"


_THEME_PROMPT = ("Write the subtitle for the cover of a research deck, from the client brief below. Name the theme of the "
                 "study the way the brief frames it (what is being analysed and why), in 4 to 10 words, title case. Do "
                 "not repeat the brand name \"{brand}\", and write no dates or numbers. Reply with the subtitle only.\n\n"
                 "Research objective: {objective}\n\nBrief:\n{brief}")


def _theme_subtitle(brand: str, project: dict, llm) -> str:
    """The cover subtitle from the brief's theme ("Media & Reputation Analysis: Who Is Winning the Conversation"),
    not the project name with the brand cut off ("Brand & Competitors"); the project-name form when no LLM answers."""
    fallback = _subtitle(brand, project.get("project_name") or "")
    spec = project.get("spec") or {}
    brief = str(spec.get("raw_brief") or "").strip()
    if llm is None or not brief:
        return fallback
    objective = spec.get("research_objective") or spec.get("deliverable_objective") or ""
    if isinstance(objective, dict):
        objective = objective.get("description") or objective.get("text") or ""
    try:
        reply = llm.chat([{"role": "user", "content": _THEME_PROMPT.format(
            brand=brand, objective=str(objective)[:400], brief=brief[:1500])}])
    except Exception as e:        # the cover still opens on the project-name subtitle
        logger.warning("cover subtitle from the brief failed (%s); using the project name", type(e).__name__)
        return fallback
    text = " ".join(str(reply or "").strip().strip('"').split())
    words = text.split()
    if not 3 <= len(words) <= 12 or any(ch.isdigit() for ch in text) or brand.lower() in text.lower():
        return fallback
    return text


def _methodology(summary: dict, rqs) -> list[str]:
    files, urls, stories, base = summary["files"], summary["unique_urls"], summary["stories"], summary["base_n"]
    return ([f"{files} approved files; {urls} unique article URLs; {stories} unique stories; "
             f"base {base} unique articles.",
             "Articles are counted once per URL; syndicated copies (same headline) are grouped into stories.",
             "Shares are of the base unless a chart says otherwise."]
            + [f"{q.id} query: {q.query}" for q in rqs if q.query])


def _extract_all(llm, rqs, plans, rows_by_rq, run: "_Run | None" = None) -> tuple[dict, set[str]]:
    extraction: dict[tuple[str, str], dict | None] = {}
    skipped: set[str] = set()
    jobs = [(q, m["entity_kind"]) for q in rqs for m in plans[q.id]["modules"] if m["module"] == "entities"]
    total = sum(min(len(rows_by_rq[q.id]), extract.EXTRACT_SAMPLE) for q, _ in jobs) or 1
    finished = 0
    for q, kind in jobs:
        n = min(len(rows_by_rq[q.id]), extract.EXTRACT_SAMPLE)

        def report(done, _of, q=q, kind=kind, n=n, base=finished):
            if run:
                run.within("classify", (base + done) / total,
                           f"Classifying {kind} in {_rq_label(q, 50)}: {done} of {n} articles")
        if run:
            run.log(f"{_rq_label(q, 50)}: classifying {kind} in the {n} most-read articles")
        try:
            extraction[(q.id, kind)] = extract.extract(llm, extract.most_read(rows_by_rq[q.id]), kind, progress=report)
        except extract.ExtractionUnavailable as e:
            extraction[(q.id, kind)] = None
            skipped.add(kind)
            logger.warning("extraction skipped for %s/%s: %s", q.id, kind, e)
        finished += n
    return extraction, skipped


def _deck_citations(entries: list[dict]) -> list[dict]:
    """One-line headlines, the source domain, and the domain standing in for a missing outlet name."""
    out = []
    for e in entries:
        domain = domain_of(e["url"])
        out.append({**e, "title": " ".join((e.get("title") or "").split()), "outlet": e.get("outlet") or domain,
                    "domain": domain})
    return out


def _hero_info(query: str) -> dict:
    from ..research.pexels import resolve_background_image
    return resolve_background_image(query) or {}


def _citation_icons(entries: list[dict], folder: Path) -> dict[int, Path]:
    icons = {}
    for e in entries:
        icon = (visuals.favicon_png(domain_of(e["url"]), folder)
                or visuals.letter_badge_png(e.get("outlet") or domain_of(e["url"]), folder))
        if icon:
            icons[e["n"]] = icon
    return icons


def _page_visuals(project: dict, sections_by_rq, verified: dict[str, Path]) -> dict:
    """The page's banner and logo strips: the deck's own verified logos (the ones the vision check approved), so the
    page never shows a namesake's logo the deck refused. Letter-badge stand-ins are left out."""
    spec = project.get("spec") or {}
    brand = (spec.get("commissioning_brand") or {}).get("name") or project.get("brand") or ""
    industry = (spec.get("industry") or {}).get("name") or ""
    competitors = [e["name"] for e in spec.get("validated_entities") or [] if e.get("type") == "competitor"]
    named = [c for secs in sections_by_rq.values() for s in secs
             if s.module in ("brand_sov", "entities") and s.chart and s.id.endswith(("brand_sov", "brands"))
             for c in s.chart["categories"]]
    logos, shown = {}, set()
    for n in dict.fromkeys([brand] + competitors + named):
        path = visuals.find_logo(n, verified)
        # one mark per logo: "BYD Dolphin" and "BYD" share BYD's logo, which the banner shows once
        if not path or visuals.is_badge(path) or Path(path).resolve() in shown:
            continue
        if (uri := visuals.logo_data_uri(path)):
            logos[n] = uri
            shown.add(Path(path).resolve())
    hero = _hero_info(f"{brand} {industry}".strip())
    photographer = hero.get("photographer") or "Pexels"
    country = (spec.get("included_scope") or {}).get("geography") or spec.get("geography") or ""
    return {"id": "visuals", "rq_id": None, "module": "visuals", "title": "Visuals",
            "hero": {"url": hero.get("image_url"), "credit": f"Photo: {photographer} / Pexels"},
            "logos": logos, "country": visuals.country_code(country), "brand": brand}


_OUTLET_MODULES = ("outlet_ranking", "reach")


OUTLET_COLUMNS = ("outlet", "source")


def _table_outlets(s: Section) -> list[str]:
    header = [str(h).strip().lower() for h in (s.table or {}).get("header") or []]
    col = next((i for i, h in enumerate(header) if h in OUTLET_COLUMNS), None)
    return [str(r[col]) for r in (s.table or {}).get("rows") or [] if col is not None and len(r) > col and r[col]]


def _label_icons(sections_by_rq, rows, folder: Path, color: str) -> dict[str, Path]:
    """An icon beside every chart label that has one: a sport's or an injury's symbol, an outlet's site icon."""
    domain_by_outlet: dict[str, str] = {}
    for r in rows:
        if r.article.outlet and r.article.outlet not in domain_by_outlet:
            domain_by_outlet[r.article.outlet] = domain_of(r.article.url)
    out: dict[str, Path] = {}
    for secs in sections_by_rq.values():
        for s in secs:
            for outlet in _table_outlets(s):         # a table's outlet column shows each site's icon too
                if outlet not in out and (icon := visuals.favicon_png(domain_by_outlet.get(outlet, ""), folder / "favicons")
                                          or visuals.letter_badge_png(outlet, folder / "favicons", color)):
                    out[outlet] = icon
            for label in (s.chart or {}).get("categories") or []:
                if label in out:
                    continue
                if s.module in _OUTLET_MODULES:      # an outlet without a site icon still gets its initial
                    icon = (visuals.favicon_png(domain_by_outlet.get(label, ""), folder / "favicons")
                            or visuals.letter_badge_png(label, folder / "favicons", color))
                else:
                    icon_id = visuals.value_icon(label)
                    icon = visuals.icon_png(icon_id, folder / "icons", color) if icon_id else None
                if icon:
                    out[label] = icon
    return out


def _logo_judge(llm, category: str):
    """A vision check that a logo is the brand's own -- the one in this project's category, not a namesake."""
    return lambda data, name, domain="": vision.is_logo_of(llm, data, name, category=category, domain=domain)


def _makers(llm, names: list[str], brands: list[str]) -> dict[str, str]:
    """{product name: the study brand that makes it} for chart labels with no logo of their own, so a product carries
    its maker's verified logo instead of a letter badge. Names no study brand makes, or no LLM, stay unmapped."""
    if llm is None or not names or not brands:
        return {}
    prompt = ("For each name, say which one of these brands makes or owns it, or null if none of them does or you "
              f"are not sure. BRANDS: {json.dumps(brands)}\nNAMES: {json.dumps(names)}\n"
              'Return JSON {"makers": {"<name>": "<brand or null>"}}')
    try:
        reply = json.loads(llm.chat([{"role": "user", "content": prompt}], format_json=True))
    except Exception as e:      # no mapping: the labels keep their letter badges
        logger.warning("product makers not resolved: %s", type(e).__name__)
        return {}
    makers = (reply or {}).get("makers") or {}
    return {n: makers[n] for n in names if makers.get(n) in brands}


def _fit_chart(section: Section, question: str) -> Section:
    """The section drawn as the chart its data and question call for (see chart_choice)."""
    if section.skipped or not section.chart:
        return section
    return dataclasses.replace(section, chart=chart_choice.choose(section.chart, question))


def _deck_input(project: dict, rows, rqs, overview, sections_by_rq, insights_by_rq, answers, takeaways,
                methodology, registry, base, out_dir: Path, rq_titles: dict[str, str],
                llm=None) -> generic_deck.DeckInput:
    spec = project.get("spec") or {}
    brand = (spec.get("commissioning_brand") or {}).get("name") or project.get("brand") or "Research"
    industry = (spec.get("industry") or {}).get("name") or ""
    country = (spec.get("included_scope") or {}).get("geography") or spec.get("geography") or ""
    judge = _logo_judge(llm, _category(project, brand)) if llm is not None else None
    kit = brand_kit.fetch_kit(brand, out_dir / "brand", judge=judge)
    competitors = [e["name"] for e in spec.get("validated_entities") or [] if e.get("type") == "competitor"]
    # every brand or retailer drawn in a chart gets its logo looked up, not only the share-of-voice chart
    sov_brands = [c for secs in sections_by_rq.values() for s in secs if s.chart and not s.skipped
                  and (s.module == "brand_sov" or s.id.endswith(("-brands", "-retailers"))) for c in s.chart["categories"]]
    retailers = {visuals.plain_name(c) for secs in sections_by_rq.values() for s in secs
                 if s.chart and not s.skipped and s.id.endswith("-retailers") for c in s.chart["categories"]}
    names = list(dict.fromkeys(visuals.plain_name(n) for n in competitors + sov_brands if n))[:MAX_LOGOS]
    category = _category(project, brand)
    # brands are judged against the project's category (a namesake from another industry is refused); retailers
    # (Amazon, Walmart) sell into the category without belonging to it, so they are judged as retailers
    shop_judge = _logo_judge(llm, RETAIL_CATEGORY) if llm is not None else None
    logo_map = {**visuals.logos([n for n in names if n not in retailers], out_dir / "logos", judge=judge, hint=category),
                **visuals.logos([n for n in names if n in retailers], out_dir / "logos", judge=shop_judge, hint="store")}
    logo_map = {**_label_icons(sections_by_rq, rows, out_dir, kit.accent), **logo_map}   # brand logos win
    # the client's own products (Model Y, Cybertruck) named in a brand chart carry the client's verified logo
    own_products = {visuals.plain_name(e["name"]).casefold() for e in spec.get("validated_entities") or []
                    if isinstance(e, dict) and e.get("type") == "product" and e.get("name")}
    unplaced = [n for n in dict.fromkeys(sov_brands) if not visuals.find_logo(n, logo_map)
                and visuals.plain_name(n).casefold() not in own_products]
    makers = _makers(llm, unplaced, [brand] + competitors)      # "Model 3" -> Tesla, "Mustang Mach-E" -> Ford
    for name in dict.fromkeys(sov_brands):     # every brand drawn in a chart shows a mark beside its label
        key = visuals.plain_name(name).casefold()
        is_own = key in own_products or key.removeprefix(brand.casefold() + " ") in own_products
        maker = makers.get(name)
        mark = (visuals.find_logo(name, logo_map) or (kit.logo if (is_own or maker == brand) and kit.logo else None)
                or (visuals.find_logo(maker, logo_map) if maker else None)
                or visuals.letter_badge_png(name, out_dir / "logos", kit.accent))
        if mark:
            logo_map[name] = mark
    if kit.logo:
        logo_map[brand] = kit.logo
    elif (mark := visuals.wordmark_png(brand, _category(project, brand), out_dir / "brand", kit.accent)):
        logo_map[brand] = mark                # a category client (no brand logo) still opens on its own mark
    icons = {}
    for key, icon_id in visuals.ICONS.items():
        png = visuals.icon_png(icon_id, out_dir / "icons", kit.accent)
        if png:
            icons[key] = png
    hero, credit = visuals.hero_image(f"{brand} {industry}".strip(), out_dir)
    dates = sorted(r.article.date for r in rows if r.article.date)
    period = f"{dates[0]:%b %Y} - {dates[-1]:%b %Y}" if dates else str(spec.get("time_period") or "")
    palette = kit.palette if kit.colors else visuals.palette_from_logo(kit.logo)
    return generic_deck.DeckInput(
        title=brand, subtitle=_theme_subtitle(brand, project, llm), date_label=f"{date.today():%B %Y}",
        period_label=period, rqs=rqs, overview=overview, sections_by_rq=sections_by_rq,
        insights_by_rq=insights_by_rq, answers=answers, takeaways=takeaways, methodology=methodology,
        citations=_deck_citations(registry.entries()), base_n=base, palette=palette, accent=kit.accent, title_font=kit.title_font,
        logos=logo_map, icons=icons, hero=hero, hero_credit=credit, brand_image=kit.banner,
        flag=visuals.country_flag_png(country, out_dir / "icons"), rq_titles=rq_titles,
        citation_icons=_citation_icons(registry.entries(), out_dir / "favicons"), brand_colors=list(kit.colors))


def _plan_input(project: dict, inp, rqs, overview, sections_by_rq, insights_by_rq, answers, takeaways, methodology,
                base: int, rq_titles: dict[str, str], verbatims_by_rq: dict | None = None,
                section_summaries: dict | None = None) -> PlanInput:
    spec = project.get("spec") or {}
    geography = (spec.get("included_scope") or {}).get("geography") or spec.get("geography") or ""
    return PlanInput(title=inp.title, subtitle=inp.subtitle, period=inp.period_label, base_n=base, rqs=rqs,
                     rq_titles=rq_titles, sections_by_rq=sections_by_rq, insights_by_rq=insights_by_rq,
                     answers=answers, takeaways=takeaways, overview=overview, methodology=methodology,
                     citations=[{**c, "icon": str(inp.citation_icons.get(c["n"]) or "")} for c in inp.citations],
                     scope_text=_scope_text(project), brands=[b.name for b in _brands(project, rqs)],
                     geography=str(geography), sources="Meltwater", verbatims_by_rq=verbatims_by_rq or {},
                     products=_products(project), category=_category(project, inp.title),
                     section_summaries=section_summaries or {},
                     is_category="category" in str(spec.get("research_type") or "").lower(),
                     objective=str(spec.get("research_objective") or ""), media=_media(spec),
                     time_period=str(spec.get("time_period") or ""),
                     brand_products=[e["name"] for e in (spec.get("validated_entities") or [])
                                     if isinstance(e, dict) and e.get("type") == "product" and e.get("name")])


_MEDIA_WORDS = (("social", "Social media"), ("editorial", "Earned editorial"), ("broadcast", "Broadcast"),
                ("podcast", "Podcasts"))


def _media(spec: dict) -> str:
    """The scope slide's 'Media' line, from the brief's research type and subject; empty when the brief doesn't say."""
    text = f"{spec.get('research_type') or ''} {(spec.get('research_subject') or {}).get('description') or ''}".lower()
    return ", ".join(label for word, label in _MEDIA_WORDS if word in text)


MAX_PRODUCT_HINTS = 6
_TITLE_NOISE = re.compile(r"\b(category|analysis|media|earned|editorial|coverage|research|report)\b", re.I)


def _products(project: dict) -> list[str]:
    """What photos should show besides brands: the scope's topics (e.g. soccer, running) and the commissioning
    brand's product keywords (e.g. wound care, colloidal oatmeal)."""
    entities = [e for e in (project.get("spec") or {}).get("validated_entities") or [] if isinstance(e, dict)]
    topics = [e["name"] for e in entities if e.get("type") == "topic" and e.get("name")]
    brand = next((e for e in entities if e.get("type") == "brand"), {})
    return list(dict.fromkeys(topics + list(brand.get("keywords") or [])))[:MAX_PRODUCT_HINTS]


def _category(project: dict, title: str) -> str:
    """The category photos must show: the industry's most specific part ("Personal Care / Baby Skincare" ->
    "baby skincare"), else the title without report words."""
    industry = ((project.get("spec") or {}).get("industry") or {}).get("name") or ""
    named = industry.split("/")[-1].strip()
    return (named or " ".join(_TITLE_NOISE.sub(" ", title).split())).lower()


def _citation_brands(registry, rows, brands) -> dict[str, list[str]]:
    """Each citation's literally named brands (the deck validator fails a source that names none); every row, since
    the brand chapter cites articles that sit under no question."""
    by_url = {r.article.norm_url: r for r in rows}
    out = {}
    for c in registry.entries():
        row = by_url.get(normalize_url(c["url"]))
        out[str(c["n"])] = evidence.row_brands(row, brands) if row else evidence.mentions(c.get("title") or "", brands)
    return out


def _relevant_urls(rows, answer_tag: str, brands) -> set[str]:
    """The articles that answer a question: tagged yes on its answer tag, or naming a brand of the set. Keyword
    matches in another sense (a 'cut' in a video game) carry neither, so they are never a card's example."""
    return {r.article.norm_url for r in rows
            if (answer_tag and evidence.affirmative((r.dynamic_tags or {}).get(answer_tag))) or evidence.row_brands(r, brands)}


def _verbatims_by_rq(rqs, rows_by_rq, insights_by_rq, registry, brands, dims_by_rq,
                     answer_tags: dict[str, str] | None = None) -> dict[str, list[dict]]:
    """Each question's verbatim wall: articles that name the brand and carry the question's intent (its
    insights' citations first); competitors' on a wall of their own, keyed "<RQ>-COMPETITORS"."""
    cited = {c["n"]: c["url"] for c in registry.entries()}
    out: dict[str, list[dict]] = {}
    for q in rqs:
        dims = dims_by_rq.get(q.id, [])
        answer = (answer_tags or {}).get(q.id, "")
        primary = evidence.for_question(rows_by_rq[q.id], brands, dims, answer)
        quoted = {cited[n] for i in insights_by_rq[q.id] for n in i.get("citations", []) if n in cited}
        # articles that answer the question (tagged yes) lead the wall, then the insights' sources, in rank order
        first = [r.article.url for r in primary if answer and evidence.affirmative((r.dynamic_tags or {}).get(answer))]
        first += [r.article.url for r in primary if r.article.url in quoted]
        out[q.id] = verbatims.pick(primary, list(dict.fromkeys(first)), ordered=True)
        competitors = evidence.rank(rows_by_rq[q.id], brands, dims, "competitor")
        if competitors:                    # their articles that answer the question lead their wall too
            answering = [r.article.url for r in competitors
                         if answer and evidence.affirmative((r.dynamic_tags or {}).get(answer))]
            out[f"{q.id}-COMPETITORS"] = verbatims.pick(competitors, answering, ordered=True)
    return out


def _brands(project: dict, rqs) -> list:
    """The primary brand (its spellings and products) and its competitors, from the brief and the queries."""
    spec = project.get("spec") or {}
    entities = [e for e in spec.get("validated_entities") or [] if isinstance(e, dict) and e.get("name")]
    primary = (spec.get("commissioning_brand") or {}).get("name") or project.get("brand") or project.get("name") or ""
    return evidence.brand_set(primary, [e["name"] for e in entities if e.get("type") == "competitor"],
                              [q.query for q in rqs], [e["name"] for e in entities if e.get("type") == "product"])


def run_engine(run_id: int, project_id: int, llm) -> None:
    run = _Run(run_id, project_id)
    # every drafting call writes in the project's country/region language (Global: US English)
    llm = writing_locale.with_locale(llm, writing_locale.project_geography(store.get_project(project_id)))
    current = "gate"
    try:
        run.stage("gate", "running")
        reasons = _gate_reasons(project_id)
        if reasons:
            raise StageFailed("gate", "; ".join(reasons))
        run.stage("gate", "done")

        current = "ingest"
        run.stage("ingest", "running")
        rqs = R.load_rqs(project_id)
        if not rqs:
            raise StageFailed("ingest", "The search strategy has no research questions")
        run.log(f"{len(rqs)} research questions: " + "; ".join(_rq_label(q, 60) for q in rqs))
        rows = R.load_rows(project_id, rqs)
        if not rows:
            raise StageFailed("ingest", "The approved datasets have no usable rows")
        note = R.country_note(project_id)
        run.stage("ingest", "done", f"{len(rows)} unique articles" + (f" ({note})" if note else ""))

        current = "routing"
        run.stage("routing", "running")
        rows = R.assign_stories(R.route(rows, rqs))
        base = R.base_n(rows)
        rows_by_rq = {q.id: R.rq_rows(rows, q.id) for q in rqs}
        summary = R.ingest_summary(project_id, rows)
        run.section({"id": "data-collection", "rq_id": None, "module": "data_collection", "title": "Data collection",
                     "data": summary, "facts": [f"Base: {base} unique articles across all questions"]})
        for q in rqs:
            run.log(f"{_rq_label(q)}: {len(rows_by_rq[q.id])} articles")
        run.stage("routing", "done", f"base N = {base}")

        current = "plan"
        run.stage("plan", "running")
        # Each question's own dimensions (sport, injury type, ...) answer it first: a "which sport" question gets
        # a by-sport chart, not only brand volume
        dims_by_rq = question_dimensions(project_id, llm)
        project = store.get_project(project_id) or {}
        brands = _brands(project, rqs)
        tag_schemas = {rq: question_tag_schema.from_json(row["schema"])          # stored copy: no LLM here
                       for rq, row in store.get_question_tag_schemas(project_id).items()}
        answer_tags = {q.id: tag_insights.lead_tag(tag_schemas.get(q.id), q.question) for q in rqs}
        evidence_by_rq = {q.id: evidence.for_question(rows_by_rq[q.id], brands, dims_by_rq.get(q.id, []),
                                                      answer_tags[q.id])
                          for q in rqs}
        for q in rqs:
            run.log(f"{q.id}: {len(evidence_by_rq[q.id])} articles name the brand and can be cited")
        # the brief's own words count too: "look at both social and editorial" asks for the split even when the
        # brief analysis did not list it as an expected analysis
        asks = [text for _, text in brief_asks(project_id)] + [(project.get("spec") or {}).get("raw_brief") or ""]
        plans = {q.id: catalog.with_brief_asks(
                     catalog.with_breakdowns(catalog.plan_rq(llm, q, rows_by_rq[q.id])[0], q, dims_by_rq.get(q.id, [])), asks)
                 for q in rqs}
        for q in rqs:
            run.log(f"{_rq_label(q)}: " + ", ".join(m["module"] for m in plans[q.id]["modules"]))
        counts = [f"{_rq_label(q, 40)}: {len(plans[q.id]['modules'])}" for q in rqs]
        run.stage("plan", "done", ", ".join(counts))

        current = "classify"
        run.stage("classify", "running")
        extraction, skipped_kinds = _extract_all(llm, rqs, plans, rows_by_rq, run)
        run.stage("classify", "done", ("skipped: " + ", ".join(sorted(skipped_kinds))) if skipped_kinds else "")

        current = "compute"
        run.stage("compute", "running")
        overview = _fit_chart(analytics.overview_section(rqs, rows_by_rq, base), "")
        run.section(overview.to_dict())
        # client vs competitors, all questions: the chapter's own title is the comparison it answers
        brand_secs = [_fit_chart(s, s.title) for s in brand_analytics.brand_sections(rows, brands)]
        for s in brand_secs:
            run.section(s.to_dict())
        sections_by_rq: dict[str, list[Section]] = {}
        for q in rqs:
            sections_by_rq[q.id] = [analytics.compute_module(m, q, rows_by_rq[q.id], base,
                                                             extraction.get((q.id, m.get("entity_kind"))), brands)
                                    for m in plans[q.id]["modules"]]
            tagged = tag_insights.tag_section(q, rows_by_rq[q.id], tag_schemas.get(q.id))
            if tagged:               # the question answered from its own tags leads its chapter
                sections_by_rq[q.id].insert(0, tagged)
            # names a keyword pulled in from another world never reach a brand/product chart (remembered per category)
            sections_by_rq[q.id] = entity_relevance.prune(sections_by_rq[q.id], llm,
                                                          _category(project, (project.get("brand") or "")),
                                                          q.question, run.log)
            sections_by_rq[q.id] = [_fit_chart(s, q.question) for s in sections_by_rq[q.id]]
            for s in sections_by_rq[q.id]:
                run.section(s.to_dict())
            drawn = [s for s in sections_by_rq[q.id] if not s.skipped]
            run.log(f"{_rq_label(q)} charts: " + "; ".join(f"{s.title} - {s.chart['kind']} ({s.chart['choice']})"
                                                           for s in drawn if s.chart and s.chart.get("choice")))
            run.log(f"{_rq_label(q)}: {len(drawn)} of {len(sections_by_rq[q.id])} analyses ready")
        run.stage("compute", "done")

        current = "insights"
        run.stage("insights", "running")
        registry = CitationRegistry()
        insights_by_rq = {}
        summaries_by_section: dict[str, list[dict]] = {}

        def draft_question(q):
            # a question's chart and theme summaries follow its insights (each is told what was already said);
            # questions are independent, so they draft side by side
            found = engine_insights.rq_insights(q, sections_by_rq[q.id], rows_by_rq[q.id], registry, llm,
                                                evidence=evidence_by_rq[q.id])
            summaries = engine_insights.section_summaries(q, sections_by_rq[q.id], rows_by_rq[q.id], registry, llm,
                                                          evidence=evidence_by_rq[q.id], avoid=found,
                                                          relevant=_relevant_urls(rows_by_rq[q.id], answer_tags[q.id],
                                                                                  brands))
            return found, summaries

        with ThreadPoolExecutor(max_workers=INSIGHT_WORKERS) as pool:
            futures = {pool.submit(draft_question, q): q for q in rqs}
            for k, done in enumerate(as_completed(futures), start=1):
                q = futures[done]
                insights_by_rq[q.id], summaries = done.result()
                summaries_by_section.update(summaries)
                run.within("insights", k / len(rqs), f"Drafted cited insights for {k} of {len(rqs)} questions")
                run.section({"id": f"{q.id.lower()}-insights", "rq_id": q.id, "module": "insights",
                             "title": "Insights", "insights": insights_by_rq[q.id]})
                run.log(f"{_rq_label(q)}: {len(insights_by_rq[q.id])} insights drafted")
        brand_evidence = (evidence.rank(rows, brands, [], "primary")[:CITE_POOL]
                          + evidence.rank(rows, brands, [], "competitor")[:CITE_POOL])
        summaries_by_section.update(engine_insights.section_summaries(
            RQ(BRAND_KEY, f"How does {brands[0].name if brands else 'the brand'} compare with its competitors?"),
            brand_secs, rows, registry, llm, evidence=brand_evidence))
        answers = engine_insights.executive_answers(rqs, sections_by_rq, base)
        takeaways = [i for q in rqs for i in insights_by_rq[q.id][:1]]
        run.section({"id": "executive-summary", "rq_id": None, "module": "executive_summary",
                     "title": "Executive summary", "answers": answers, "takeaways": takeaways})
        run.stage("insights", "done")

        current = "template"
        run.stage("template", "running")
        template, why = templates_index.choose_template_explained(_scope_text(project), llm)
        run.log(f"Template: {template.stem} - {why}")
        run.stage("template", "done", template.stem)

        current = "render"
        run.stage("render", "running")
        out_dir = config.DELIVERABLE_DIR / f"project_{project_id}" / f"run_{run_id}"
        methodology = _methodology(summary, rqs)
        inp = _deck_input(project, rows, rqs, overview, sections_by_rq, insights_by_rq, answers, takeaways,
                          methodology, registry, base, out_dir, {q.id: plans[q.id]["title"] for q in rqs}, llm=llm)
        safe = "".join(ch for ch in inp.title if ch.isalnum() or ch in " -_").strip() or "Deliverable"
        pptx_path, appendix = generic_deck.build_generic_deck(inp, template, out_dir / "work",
                                                              out_dir / f"{safe} - Deliverable.pptx")
        run.section({"id": "citations", "rq_id": None, "module": "citations", "title": "Citations",
                     "citations": _deck_citations(registry.entries())})
        run.section(_page_visuals(project, sections_by_rq, inp.logos))
        run.log(f"Deck saved with {len(Presentation(str(pptx_path)).slides)} slides; "
                f"{len(registry.entries())} sources cited")
        run.stage("render", "done", pptx_path.name)

        current = "qc"
        run.stage("qc", "running")
        facts = overview.facts + [f for secs in sections_by_rq.values() for s in secs for f in s.facts] + methodology
        report = factcheck.run_qc(pptx_path, facts, set(appendix), out_dir / "thumbs")
        pngs = [Path(p) for p in report["pngs"]]
        first = generic_deck.rq_first_slides(pptx_path, [q.id for q in rqs])
        rq_pngs = [pngs[first[q.id] - 1] if q.id in first and first[q.id] <= len(pngs) else None for q in rqs]
        docx_path = word_brief.build_word_brief(inp, out_dir / f"{safe} - Brief.docx", rq_pngs)
        run.log(f"Fact check: {len(report['facts'])} issues; layout: {len(report['layout'])} issues; "
                f"{report['fixed']} auto-fixed; {len(pngs)} thumbnails")
        run.log("Word brief saved")
        run.section({"id": "qc", "rq_id": None, "module": "qc", "title": "Quality check", "report": report})
        n_facts, n_layout = len(report["facts"]), len(report["layout"])
        run.stage("qc", "done", "ready" if report["ready"] else f"{n_facts} fact / {n_layout} layout issues")

        # The classic deck and brief are kept first; the studio deck is added on top and cannot fail the run
        store.update_deliverable_run(run_id, pptx_path=str(pptx_path), docx_path=str(docx_path),
                                     thumbs_dir=str(out_dir / "thumbs"))
        studio_paths = {}
        try:
            plan_input = _plan_input(project, inp, rqs, overview, {**sections_by_rq, BRAND_KEY: brand_secs},
                                     insights_by_rq, answers,
                                     takeaways, methodology, base, {q.id: plans[q.id]["title"] for q in rqs},
                                     _verbatims_by_rq(rqs, rows_by_rq, insights_by_rq, registry, brands,
                                                      dims_by_rq, answer_tags), summaries_by_section)
            plan_input.citation_brands = _citation_brands(registry, rows, brands)
            plan_input.brand_share = sum(1 for r in rows if evidence.row_brands(r, brands)) / max(1, len(rows))
            plan_input.mixed_media = len({analytics._channel(r) for r in rows} - {""}) > 1
            plan_input.repair_context = repair_context.build(
                rqs, {**sections_by_rq, BRAND_KEY: brand_secs}, rows_by_rq, rows, brands,
                {**{q.id: _relevant_urls(rows_by_rq[q.id], answer_tags[q.id], brands) for q in rqs},
                 BRAND_KEY: {r.article.norm_url for r in brand_evidence}})
            studio = run_studio(run, project_id, llm, plan_input,
                                inp.brand_colors, inp.brand_image, inp.logos, out_dir,
                                on_fix=lambda sid, action, kind: agent_memory.remember(
                                    project_id, "fix", f"run{run_id}_{sid}", {"action": action, "flag": kind}),
                                on_issue=lambda sid, qc: issues.file_issue(
                                    "deck_qc", "layout", f"Slide layout problem survives repair: {qc[0].split(':')[0]}",
                                    {"run_id": run_id, "slide_id": sid, "qc": qc}, project_id))
            run.section({"id": "studio", "rq_id": None, "module": "studio", "title": "Deck",
                         "family": studio["family"], "family_reason": studio["family_reason"],
                         "design_system": studio["design_system"], "design_reason": studio["design_reason"],
                         "checklist": studio["checklist"], "scorecard": studio["scorecard"],
                         "validation": studio.get("validation", []),
                         "slides": [{"id": s.id, "type": s.type, "treatment": s.treatment, "reference": s.reference,
                                     "source": next((r["source"] for r in studio["report"] if r["slide_id"] == s.id), "template"),
                                     "qc": next((r.get("qc", []) for r in studio["report"] if r["slide_id"] == s.id), [])}
                                    for s in studio["spec"].slides]})
            for c in studio.get("validation", []):
                if c["status"] == "fail":       # a person decides: missing content is not a code defect
                    issues.file_issue("deck_validation", "missing", f"Deck check failed: {c['check'][:80]}",
                                      {"run_id": run_id, "detail": c["detail"]}, project_id)
            studio_paths = {"html_path": str(studio["html"]), "pdf_path": str(studio["pdf"]),
                            "studio_pptx_path": str(studio["pptx"]), "deck_dir": str(studio["deck_dir"])}
        except Exception as e:      # e.g. no Chromium: the classic deliverable still ships
            logger.error("[deliverable:%s] studio stage %s failed: %s", run_id, run.current, e, exc_info=True)
            run.stages[run.current] = "failed"
            store.update_deliverable_run(run_id, stage=run.current, stages_json=run.stages)
            run.log(f"Presentation studio failed at {run.current}: {e} - the classic deck and brief are still available")
        store.update_deliverable_run(run_id, status="completed", finished_at=time.time(), **studio_paths)
        run.progress(100, "Deliverable ready")
        try:
            issues.check_progress_calibration(run_id)
        except Exception:
            logger.exception("[deliverable:%s] progress calibration check failed", run_id)
        broadcast({"type": "deliverable_completed", "project_id": project_id, "run_id": run_id,
                   "ready": report["ready"]})
    except Exception as e:
        stage = e.stage if isinstance(e, StageFailed) else current
        logger.error("[deliverable:%s] stage %s failed: %s", run_id, stage, e, exc_info=not isinstance(e, StageFailed))
        run.stages[stage] = "failed"
        try:
            run.log(f"Failed at {stage}: {e}")
        except Exception:       # recording the line must never mask the original failure
            logger.exception("[deliverable:%s] could not record the failure line", run_id)
        store.update_deliverable_run(run_id, status="failed", stage=stage, stages_json=run.stages, error=str(e),
                                     finished_at=time.time())
        broadcast({"type": "deliverable_failed", "project_id": project_id, "run_id": run_id, "stage": stage,
                   "error": _wire(str(e))})
        try:
            issues.from_exception(stage, e, project_id)
        except Exception:       # filing an issue must never mask the run's own failure
            logger.exception("[deliverable:%s] could not file the failure as an issue", run_id)


def run_payload(run_id: int) -> dict:
    return {"run": store.get_deliverable_run(run_id), "sections": store.list_deliverable_sections(run_id)}
