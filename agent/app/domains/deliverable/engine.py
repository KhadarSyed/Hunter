"""Deliverable engine: ten persisted stages, each broadcast on /ws; a failed stage stops the run visibly."""
from __future__ import annotations

import logging
import threading
import time
from datetime import date
from pathlib import Path

from ...core import config, store
from ...core.events import broadcast
from . import (analytics, brand_kit, catalog, engine_insights, extract, factcheck, generic_deck, templates_index,
               visuals, word_brief)
from . import rows as R
from .citations import CitationRegistry
from .engine_types import Section

logger = logging.getLogger(__name__)
STAGES = ("gate", "ingest", "routing", "plan", "classify", "compute", "insights", "template", "render", "qc")
MAX_LOGOS = 10
RQ_SLIDE_PNG_OFFSET = 3     # cover, executive summary, overview come before the first RQ slide
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


class _Run:
    def __init__(self, run_id: int, project_id: int):
        self.run_id, self.project_id, self.stages = run_id, project_id, {}

    def stage(self, name: str, status: str, detail: str = "") -> None:
        self.stages[name] = status
        store.update_deliverable_run(self.run_id, stage=name, stages_json=self.stages)
        broadcast({"type": "deliverable_stage", "project_id": self.project_id, "run_id": self.run_id,
                   "stage": name, "status": status, "detail": detail})

    def section(self, payload: dict) -> None:
        store.save_deliverable_section(self.run_id, payload)
        broadcast({"type": "deliverable_section", "project_id": self.project_id, "run_id": self.run_id,
                   "section": payload})


def start_run(project_id: int, *, llm=None, threaded: bool = True) -> int:
    with _lock:
        if store.get_active_deliverable_run(project_id):
            raise RunBusy("A deliverable run is already in progress")
        run_id = store.create_deliverable_run(project_id)
    if threaded:
        if llm is None:
            from ...core.anthropic_client import get_llm_client
            llm = get_llm_client()
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


def _extract_all(llm, rqs, plans, rows_by_rq) -> tuple[dict, set[str]]:
    extraction: dict[tuple[str, str], dict | None] = {}
    skipped: set[str] = set()
    for q in rqs:
        for m in plans[q.id]["modules"]:
            if m["module"] != "entities":
                continue
            kind = m["entity_kind"]
            try:
                extraction[(q.id, kind)] = extract.extract(llm, rows_by_rq[q.id], kind)
            except extract.ExtractionUnavailable as e:
                extraction[(q.id, kind)] = None
                skipped.add(kind)
                logger.warning("extraction skipped for %s/%s: %s", q.id, kind, e)
    return extraction, skipped


def _deck_input(project: dict, rows, rqs, overview, sections_by_rq, insights_by_rq, answers, takeaways,
                methodology, registry, base, out_dir: Path, rq_titles: dict[str, str]) -> generic_deck.DeckInput:
    spec = project.get("spec") or {}
    brand = (spec.get("commissioning_brand") or {}).get("name") or project.get("brand") or "Research"
    industry = (spec.get("industry") or {}).get("name") or ""
    country = (spec.get("included_scope") or {}).get("geography") or spec.get("geography") or ""
    kit = brand_kit.fetch_kit(brand, out_dir / "brand")
    competitors = [e["name"] for e in spec.get("validated_entities") or [] if e.get("type") == "competitor"]
    sov_brands = [c for secs in sections_by_rq.values() for s in secs
                  if s.module == "brand_sov" and s.chart for c in s.chart["categories"]]
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
        citations=registry.entries(), base_n=base, palette=palette, accent=kit.accent, title_font=kit.title_font,
        logos=logo_map, icons=icons, hero=hero, hero_credit=credit, brand_image=kit.banner,
        flag=visuals.country_flag_png(country, out_dir / "icons"), rq_titles=rq_titles)


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
        run.stage("routing", "done", f"base N = {base}")

        current = "plan"
        run.stage("plan", "running")
        plans = {q.id: catalog.plan_rq(llm, q, rows_by_rq[q.id])[0] for q in rqs}
        counts = [f"{q.id}: {len(plans[q.id]['modules'])}" for q in rqs]
        run.stage("plan", "done", ", ".join(counts))

        current = "classify"
        run.stage("classify", "running")
        extraction, skipped_kinds = _extract_all(llm, rqs, plans, rows_by_rq)
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
        run.stage("compute", "done")

        current = "insights"
        run.stage("insights", "running")
        registry = CitationRegistry()
        insights_by_rq = {}
        for q in rqs:
            insights_by_rq[q.id] = engine_insights.rq_insights(q, sections_by_rq[q.id], rows_by_rq[q.id], registry, llm)
            run.section({"id": f"{q.id.lower()}-insights", "rq_id": q.id, "module": "insights", "title": "Insights",
                         "insights": insights_by_rq[q.id]})
        answers = engine_insights.executive_answers(rqs, sections_by_rq, base)
        takeaways = [i for q in rqs for i in insights_by_rq[q.id][:1]]
        run.section({"id": "executive-summary", "rq_id": None, "module": "executive_summary",
                     "title": "Executive summary", "answers": answers, "takeaways": takeaways})
        run.stage("insights", "done")

        current = "template"
        run.stage("template", "running")
        project = store.get_project(project_id) or {}
        template = templates_index.choose_template(_scope_text(project), llm)
        run.stage("template", "done", template.name)

        current = "render"
        run.stage("render", "running")
        out_dir = config.DELIVERABLE_DIR / f"project_{project_id}" / f"run_{run_id}"
        methodology = _methodology(summary, rqs)
        inp = _deck_input(project, rows, rqs, overview, sections_by_rq, insights_by_rq, answers, takeaways,
                          methodology, registry, base, out_dir, {q.id: plans[q.id]["title"] for q in rqs})
        safe = "".join(ch for ch in inp.title if ch.isalnum() or ch in " -_").strip() or "Deliverable"
        pptx_path, appendix = generic_deck.build_generic_deck(inp, template, out_dir / "work",
                                                              out_dir / f"{safe} - Deliverable.pptx")
        run.stage("render", "done", pptx_path.name)

        current = "qc"
        run.stage("qc", "running")
        facts = overview.facts + [f for secs in sections_by_rq.values() for s in secs for f in s.facts] + methodology
        report = factcheck.run_qc(pptx_path, facts, set(appendix), out_dir / "thumbs")
        pngs = [Path(p) for p in report["pngs"]]
        rq_pngs = pngs[RQ_SLIDE_PNG_OFFSET:RQ_SLIDE_PNG_OFFSET + len(rqs)]
        docx_path = word_brief.build_word_brief(inp, out_dir / f"{safe} - Brief.docx", rq_pngs)
        run.section({"id": "qc", "rq_id": None, "module": "qc", "title": "Quality check", "report": report})
        n_facts, n_layout = len(report["facts"]), len(report["layout"])
        run.stage("qc", "done", "ready" if report["ready"] else f"{n_facts} fact / {n_layout} layout issues")

        store.update_deliverable_run(run_id, status="completed", pptx_path=str(pptx_path), docx_path=str(docx_path),
                                     thumbs_dir=str(out_dir / "thumbs"), finished_at=time.time())
        broadcast({"type": "deliverable_completed", "project_id": project_id, "run_id": run_id,
                   "ready": report["ready"]})
    except Exception as e:
        stage = e.stage if isinstance(e, StageFailed) else current
        logger.error("[deliverable:%s] stage %s failed: %s", run_id, stage, e, exc_info=not isinstance(e, StageFailed))
        run.stages[stage] = "failed"
        store.update_deliverable_run(run_id, status="failed", stage=stage, stages_json=run.stages, error=str(e),
                                     finished_at=time.time())
        broadcast({"type": "deliverable_failed", "project_id": project_id, "run_id": run_id, "stage": stage,
                   "error": str(e)})


def run_payload(run_id: int) -> dict:
    return {"run": store.get_deliverable_run(run_id), "sections": store.list_deliverable_sections(run_id)}
