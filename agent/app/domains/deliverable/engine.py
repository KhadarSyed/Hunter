"""Deliverable engine: ten persisted stages, each broadcast on /ws; a failed stage stops the run visibly."""
from __future__ import annotations

import logging
import threading
import time
from datetime import date
from pathlib import Path

from pptx import Presentation

from ...core import config, store
from ...core.events import broadcast
from . import (analytics, brand_kit, catalog, engine_insights, extract, factcheck, generic_deck, templates_index,
               visuals, word_brief)
from . import rows as R
from .citations import CitationRegistry, domain_of
from .engine_types import Section
from ..deckstudio import verbatims
from ..deckstudio.pipeline import run_studio
from ..deckstudio.planner import PlanInput

logger = logging.getLogger(__name__)
STAGES = ("gate", "ingest", "routing", "plan", "classify", "compute", "insights", "template", "render", "qc",
          "index", "design", "assets", "compose", "export")
MAX_LOGOS = 24
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


_STAGE_LABELS = {"gate": "Checking approvals", "ingest": "Ingesting approved datasets",
                 "routing": "Routing articles to questions", "plan": "Planning analyses",
                 "classify": "Classifying entities", "compute": "Computing charts and tables",
                 "insights": "Drafting cited insights", "template": "Choosing a template",
                 "render": "Building slides", "qc": "Fact check and layout QC",
                 "index": "Reading reference decks", "design": "Designing the deck",
                 "assets": "Finding photos & logos", "compose": "Composing slides", "export": "Exporting PPTX & PDF"}


# Share of a typical run's time spent in each stage: the overall % moves with the work, not the stage count
STAGE_WEIGHTS = {"gate": 1, "ingest": 3, "routing": 2, "plan": 5, "classify": 28, "compute": 3, "insights": 14,
                 "template": 2, "render": 8, "qc": 4, "index": 4, "design": 3, "assets": 8, "compose": 10, "export": 5}


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

    def progress(self, pct: float, label: str) -> None:
        """Overall % (never goes back) and what is happening right now; kept with the run for page reloads."""
        self.pct = max(self.pct, min(100, int(round(pct))))
        state = {"pct": self.pct, "stage": self.current, "label": label, "started_at": self.started_at}
        store.replace_deliverable_section(self.run_id, {"id": "progress", "rq_id": None, "module": "progress",
                                                        "title": "Progress", **state})
        broadcast({"type": "deliverable_progress", "project_id": self.project_id, "run_id": self.run_id, **state})

    def within(self, stage: str, fraction: float, label: str) -> None:
        start, end = _stage_span(stage)
        self.progress(start + (end - start) * max(0.0, min(1.0, fraction)), label)

    def log(self, message: str) -> None:
        """A progress line, streamed live and kept with the run. Step names and counts only, never article
        content, because /ws is unauthenticated."""
        line = {"ts": time.time(), "message": message}
        self.lines.append(line)
        store.replace_deliverable_section(self.run_id, {"id": "log", "rq_id": None, "module": "log",
                                                        "title": "Run log", "lines": self.lines})
        broadcast({"type": "deliverable_log", "project_id": self.project_id, "run_id": self.run_id, **line})

    def stage(self, name: str, status: str, detail: str = "") -> None:
        self.stages[name] = status
        store.update_deliverable_run(self.run_id, stage=name, stages_json=self.stages)
        broadcast({"type": "deliverable_stage", "project_id": self.project_id, "run_id": self.run_id,
                   "stage": name, "status": status, "detail": detail})
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
    total = sum(len(rows_by_rq[q.id]) for q, _ in jobs) or 1
    finished = 0
    for q, kind in jobs:
        n = len(rows_by_rq[q.id])

        def report(done, _of, q=q, kind=kind, n=n, base=finished):
            if run:
                run.within("classify", (base + done) / total,
                           f"Classifying {kind} in {q.id}: {done} of {n} articles")
        if run:
            run.log(f"{q.id}: classifying {kind} in {n} articles")
        try:
            extraction[(q.id, kind)] = extract.extract(llm, rows_by_rq[q.id], kind, progress=report)
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


def _logo_urls(names: list[str]) -> dict[str, str]:
    """Brand logo URLs for the web page (the deck embeds downloaded PNGs instead)."""
    from ..research.brandfetch import resolve_logo
    from .cli import logo_png_url
    out = {}
    for name in names:
        url = logo_png_url(resolve_logo(name))
        if url:
            out[name] = url
    return out


def _hero_info(query: str) -> dict:
    from ..research.pexels import resolve_background_image
    return resolve_background_image(query) or {}


def _citation_icons(entries: list[dict], folder: Path) -> dict[int, Path]:
    icons = {}
    for e in entries:
        icon = visuals.favicon_png(domain_of(e["url"]), folder)
        if icon:
            icons[e["n"]] = icon
    return icons


def _page_visuals(project: dict, sections_by_rq, kit_logo_url: str | None) -> dict:
    spec = project.get("spec") or {}
    brand = (spec.get("commissioning_brand") or {}).get("name") or project.get("brand") or ""
    industry = (spec.get("industry") or {}).get("name") or ""
    competitors = [e["name"] for e in spec.get("validated_entities") or [] if e.get("type") == "competitor"]
    named = [c for secs in sections_by_rq.values() for s in secs
             if s.module in ("brand_sov", "entities") and s.chart and s.id.endswith(("brand_sov", "brands"))
             for c in s.chart["categories"]]
    logos = _logo_urls(list(dict.fromkeys(competitors + named))[:MAX_LOGOS])
    if kit_logo_url:
        logos[brand] = kit_logo_url
    hero = _hero_info(f"{brand} {industry}".strip())
    photographer = hero.get("photographer") or "Pexels"
    country = (spec.get("included_scope") or {}).get("geography") or spec.get("geography") or ""
    return {"id": "visuals", "rq_id": None, "module": "visuals", "title": "Visuals",
            "hero": {"url": hero.get("image_url"), "credit": f"Photo: {photographer} / Pexels"},
            "logos": logos, "country": visuals.country_code(country), "brand": brand}


def _deck_input(project: dict, rows, rqs, overview, sections_by_rq, insights_by_rq, answers, takeaways,
                methodology, registry, base, out_dir: Path, rq_titles: dict[str, str]) -> generic_deck.DeckInput:
    spec = project.get("spec") or {}
    brand = (spec.get("commissioning_brand") or {}).get("name") or project.get("brand") or "Research"
    industry = (spec.get("industry") or {}).get("name") or ""
    country = (spec.get("included_scope") or {}).get("geography") or spec.get("geography") or ""
    kit = brand_kit.fetch_kit(brand, out_dir / "brand")
    competitors = [e["name"] for e in spec.get("validated_entities") or [] if e.get("type") == "competitor"]
    # every brand or retailer drawn in a chart gets its logo looked up, not only the share-of-voice chart
    sov_brands = [c for secs in sections_by_rq.values() for s in secs if s.chart and not s.skipped
                  and (s.module == "brand_sov" or s.id.endswith(("-brands", "-retailers"))) for c in s.chart["categories"]]
    logo_map = visuals.logos(list(dict.fromkeys(competitors + sov_brands))[:MAX_LOGOS], out_dir / "logos")
    if kit.logo:
        logo_map[brand] = kit.logo
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
        title=brand, subtitle=_subtitle(brand, project.get("project_name") or ""), date_label=f"{date.today():%B %Y}",
        period_label=period, rqs=rqs, overview=overview, sections_by_rq=sections_by_rq,
        insights_by_rq=insights_by_rq, answers=answers, takeaways=takeaways, methodology=methodology,
        citations=_deck_citations(registry.entries()), base_n=base, palette=palette, accent=kit.accent, title_font=kit.title_font,
        logos=logo_map, icons=icons, hero=hero, hero_credit=credit, brand_image=kit.banner,
        flag=visuals.country_flag_png(country, out_dir / "icons"), rq_titles=rq_titles,
        citation_icons=_citation_icons(registry.entries(), out_dir / "favicons"), brand_colors=list(kit.colors))


def _plan_input(project: dict, inp, rqs, overview, sections_by_rq, insights_by_rq, answers, takeaways, methodology,
                base: int, rq_titles: dict[str, str], verbatims_by_rq: dict | None = None) -> PlanInput:
    spec = project.get("spec") or {}
    geography = (spec.get("included_scope") or {}).get("geography") or spec.get("geography") or ""
    return PlanInput(title=inp.title, subtitle=inp.subtitle, period=inp.period_label, base_n=base, rqs=rqs,
                     rq_titles=rq_titles, sections_by_rq=sections_by_rq, insights_by_rq=insights_by_rq,
                     answers=answers, takeaways=takeaways, overview=overview, methodology=methodology,
                     citations=inp.citations, scope_text=_scope_text(project), brands=list(inp.logos),
                     geography=str(geography), sources="Meltwater", verbatims_by_rq=verbatims_by_rq or {})


def _verbatims_by_rq(rqs, rows_by_rq, insights_by_rq, registry) -> dict[str, list[dict]]:
    """The articles behind each question's verbatim slide: its insights' citations first, then the widest reach."""
    cited = {c["n"]: c["url"] for c in registry.entries()}
    return {q.id: verbatims.pick(rows_by_rq[q.id], [cited[n] for i in insights_by_rq[q.id]
                                                    for n in i.get("citations", []) if n in cited])
            for q in rqs}


def run_engine(run_id: int, project_id: int, llm) -> None:
    run = _Run(run_id, project_id)
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
        run.log(f"{len(rqs)} research questions: " + ", ".join(q.id for q in rqs))
        rows = R.load_rows(project_id, rqs)
        if not rows:
            raise StageFailed("ingest", "The approved datasets have no usable rows")
        run.stage("ingest", "done", f"{len(rows)} unique articles")

        current = "routing"
        run.stage("routing", "running")
        rows = R.assign_stories(R.route(rows, rqs))
        base = R.base_n(rows)
        rows_by_rq = {q.id: R.rq_rows(rows, q.id) for q in rqs}
        summary = R.ingest_summary(project_id, rows)
        run.section({"id": "data-collection", "rq_id": None, "module": "data_collection", "title": "Data collection",
                     "data": summary, "facts": [f"Base: {base} unique articles across all questions"]})
        for q in rqs:
            run.log(f"{q.id}: {len(rows_by_rq[q.id])} articles")
        run.stage("routing", "done", f"base N = {base}")

        current = "plan"
        run.stage("plan", "running")
        plans = {q.id: catalog.plan_rq(llm, q, rows_by_rq[q.id])[0] for q in rqs}
        for q in rqs:
            run.log(f"{q.id}: " + ", ".join(m["module"] for m in plans[q.id]["modules"]))
        counts = [f"{q.id}: {len(plans[q.id]['modules'])}" for q in rqs]
        run.stage("plan", "done", ", ".join(counts))

        current = "classify"
        run.stage("classify", "running")
        extraction, skipped_kinds = _extract_all(llm, rqs, plans, rows_by_rq, run)
        run.stage("classify", "done", ("skipped: " + ", ".join(sorted(skipped_kinds))) if skipped_kinds else "")

        current = "compute"
        run.stage("compute", "running")
        overview = analytics.overview_section(rqs, rows_by_rq, base)
        run.section(overview.to_dict())
        sections_by_rq: dict[str, list[Section]] = {}
        for q in rqs:
            sections_by_rq[q.id] = [analytics.compute_module(m, q, rows_by_rq[q.id], base,
                                                             extraction.get((q.id, m.get("entity_kind"))))
                                    for m in plans[q.id]["modules"]]
            for s in sections_by_rq[q.id]:
                run.section(s.to_dict())
            drawn = [s for s in sections_by_rq[q.id] if not s.skipped]
            run.log(f"{q.id}: {len(drawn)} of {len(sections_by_rq[q.id])} analyses ready")
        run.stage("compute", "done")

        current = "insights"
        run.stage("insights", "running")
        registry = CitationRegistry()
        insights_by_rq = {}
        for k, q in enumerate(rqs):
            run.within("insights", k / len(rqs), f"Drafting cited insights for {q.id}")
            insights_by_rq[q.id] = engine_insights.rq_insights(q, sections_by_rq[q.id], rows_by_rq[q.id], registry, llm)
            run.section({"id": f"{q.id.lower()}-insights", "rq_id": q.id, "module": "insights", "title": "Insights",
                         "insights": insights_by_rq[q.id]})
            run.log(f"{q.id}: {len(insights_by_rq[q.id])} insights drafted")
        answers = engine_insights.executive_answers(rqs, sections_by_rq, base)
        takeaways = [i for q in rqs for i in insights_by_rq[q.id][:1]]
        run.section({"id": "executive-summary", "rq_id": None, "module": "executive_summary",
                     "title": "Executive summary", "answers": answers, "takeaways": takeaways})
        run.stage("insights", "done")

        current = "template"
        run.stage("template", "running")
        project = store.get_project(project_id) or {}
        template, why = templates_index.choose_template_explained(_scope_text(project), llm)
        run.log(f"Template: {template.stem} - {why}")
        run.stage("template", "done", template.stem)

        current = "render"
        run.stage("render", "running")
        out_dir = config.DELIVERABLE_DIR / f"project_{project_id}" / f"run_{run_id}"
        methodology = _methodology(summary, rqs)
        inp = _deck_input(project, rows, rqs, overview, sections_by_rq, insights_by_rq, answers, takeaways,
                          methodology, registry, base, out_dir, {q.id: plans[q.id]["title"] for q in rqs})
        safe = "".join(ch for ch in inp.title if ch.isalnum() or ch in " -_").strip() or "Deliverable"
        pptx_path, appendix = generic_deck.build_generic_deck(inp, template, out_dir / "work",
                                                              out_dir / f"{safe} - Deliverable.pptx")
        run.section({"id": "citations", "rq_id": None, "module": "citations", "title": "Citations",
                     "citations": _deck_citations(registry.entries())})
        run.section(_page_visuals(project, sections_by_rq, None))
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
            studio = run_studio(run, project_id, llm,
                                _plan_input(project, inp, rqs, overview, sections_by_rq, insights_by_rq, answers,
                                            takeaways, methodology, base, {q.id: plans[q.id]["title"] for q in rqs},
                                            _verbatims_by_rq(rqs, rows_by_rq, insights_by_rq, registry)),
                                inp.brand_colors, inp.brand_image, inp.logos, out_dir)
            run.section({"id": "studio", "rq_id": None, "module": "studio", "title": "Deck",
                         "family": studio["family"], "family_reason": studio["family_reason"],
                         "checklist": studio["checklist"], "scorecard": studio["scorecard"],
                         "slides": [{"id": s.id, "type": s.type, "treatment": s.treatment, "reference": s.reference,
                                     "source": next((r["source"] for r in studio["report"] if r["slide_id"] == s.id), "template"),
                                     "qc": next((r.get("qc", []) for r in studio["report"] if r["slide_id"] == s.id), [])}
                                    for s in studio["spec"].slides]})
            studio_paths = {"html_path": str(studio["html"]), "pdf_path": str(studio["pdf"]),
                            "studio_pptx_path": str(studio["pptx"]), "deck_dir": str(studio["deck_dir"])}
        except Exception as e:      # e.g. no Chromium: the classic deliverable still ships
            logger.error("[deliverable:%s] studio stage %s failed: %s", run_id, run.current, e, exc_info=True)
            run.stages[run.current] = "failed"
            store.update_deliverable_run(run_id, stage=run.current, stages_json=run.stages)
            run.log(f"Presentation studio failed at {run.current}: {e} - the classic deck and brief are still available")
        store.update_deliverable_run(run_id, status="completed", finished_at=time.time(), **studio_paths)
        run.progress(100, "Deliverable ready")
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
                   "error": str(e)})


def run_payload(run_id: int) -> dict:
    return {"run": store.get_deliverable_run(run_id), "sections": store.list_deliverable_sections(run_id)}
