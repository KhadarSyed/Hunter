"""Project emails to the project's owner, in the one AlphaMetricx layout (core/email_layout.py): Matching label ready,
data set tagged, a stage that stopped, and the deliverable ready. Sent in the background, never failing the work."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from ...core import config, email_layout as layout, mailer, store
from ..deckstudio import data_tables

logger = logging.getLogger(__name__)

SECTION_ID = "email"


def recipients(project: dict) -> list[dict]:
    """The project's owner -- the user who created it -- or nobody (a project with no known creator is not mailed)."""
    owner = store.get_user_by_id(project["owner_user_id"]) if project.get("owner_user_id") else None
    return [owner] if owner and owner.get("email") and not owner.get("archived_at") else []


def _files(run: dict) -> list[str]:
    def has(key: str) -> bool:
        return bool(run.get(key)) and Path(run[key]).exists()
    deck_dir = Path(run["deck_dir"]) if run.get("deck_dir") else None
    tables = bool(deck_dir and next(deck_dir.glob(f"*{data_tables.FILE_SUFFIX}"), None))
    named = [("PowerPoint deck", has("studio_pptx_path") or has("pptx_path")), ("PDF", has("pdf_path")),
             ("HTML deck", has("html_path")), ("Word brief", has("docx_path")), ("Data tables", tables)]
    return [name for name, ok in named if ok]


def _link(project_id: int, page: str) -> str:
    return layout.app_link(f"{project_id}/{page}")


def _name(project: dict) -> str:
    return project.get("project_name") or f"Project {project['id']}"


def _hello(project: dict) -> str:
    owner = recipients(project)
    first = ((owner[0].get("display_name") or "").split() or [""])[0] if owner else ""
    return f"Hello {first}," if first else "Hello,"


def build_context(project: dict, run: dict, sections: list[dict]) -> dict:
    """The deliverable's facts: slide counts, checks, brief coverage, articles, files."""
    by_id = {s.get("id"): s for s in sections}
    studio, qc = by_id.get("studio") or {}, (by_id.get("qc") or {}).get("report") or {}
    stats = []
    if studio.get("slides"):
        stats.append(("Studio deck", f"{len(studio['slides'])} slides"))
    if qc.get("pngs"):
        stats.append(("Classic deck", f"{len(qc['pngs'])} slides"))
    checks = studio.get("validation") or []
    if checks:
        stats.append(("Deck checks passed", f"{sum(c.get('status') == 'pass' for c in checks)} of {len(checks)}"))
    card = studio.get("scorecard") or {}
    if card:
        stats.append(("Brief coverage", f"{card.get('covered', 0)} covered · {card.get('partial', 0)} partial · "
                                         f"{card.get('missing', 0)} missing"))
    articles = ((by_id.get("data-collection") or {}).get("data") or {}).get("unique_urls")
    if articles:
        stats.append(("Articles analysed", f"{articles:,}"))
    files = _files(run)
    if files:
        stats.append(("Files", " · ".join(files)))
    return {"stats": stats, "link": _link(project["id"], "deliverables")}


def render(project: dict, run: dict, sections: list[dict], *, inline_logo: bool = True) -> dict:
    """The deliverable-ready email: {subject, html, text, inline_images}."""
    ctx = build_context(project, run, sections)
    name = _name(project)
    row = layout.project_row(project, "Deliverables · deck ready", "Ready", layout.STATE_GOOD)
    client = f" ({row['client']})" if row["client"] else ""
    return layout.render(f"Your deliverable is ready: {name}", {
        "org": layout.org_panel(project.get("org_id")),
        "pill": {"text": "Deliverable ready", **layout.PILL_GREEN}, "heading": "Your deliverable is ready",
        "preheader": f"{name}: your deck, brief and data tables are ready.",
        "intro": [_hello(project), layout.rich("<b>{}</b>{} finished building.", name, client)],
        "facts": ctx["stats"], "projects_title": "Project", "projects": [row],
        "button": {"text": "Open deliverables", "href": ctx["link"]},
        "footer": "Sent because a deliverable you own finished building."}, inline=inline_logo)


def owner_email(project: dict, name: str, page: str, action: str, *, error: str = "",
                inline_logo: bool = True) -> dict:
    """'<stage> stopped' with the problem and a button to the stage (error), or '<stage> is ready for you'."""
    pname = _name(project)
    if error:
        row = layout.project_row(project, f"{name} · stopped", "Stopped", layout.STATE_BAD)
        return layout.render(f"Action needed: {name} stopped on {pname}", {
            "org": layout.org_panel(project.get("org_id")),
            "pill": {"text": "Needs your attention", **layout.PILL_RED}, "heading": f"{name} stopped",
            "preheader": f"{name} stopped on {pname}. {action}.",
            "intro": [_hello(project), layout.rich("<b>{}</b> on <b>{}</b> stopped before it finished, so the "
                                                   "pipeline is waiting.", name, pname)],
            "callout": {"title": "What went wrong", "lines": [error[:300]], **layout.CALLOUT_RED},
            "facts": [("Stage", name), ("Next step", action)], "projects_title": "Project", "projects": [row],
            "button": {"text": f"Open {name}", "href": _link(project["id"], page)},
            "footer": "Sent because a stage stopped on a project you own."}, inline=inline_logo)
    row = layout.project_row(project, name, name, layout.STATE_TURN)
    return layout.render(f"Your turn: {name} on {pname}", {
        "org": layout.org_panel(project.get("org_id")),
        "pill": {"text": f"Your turn · {name}", **layout.PILL_VIOLET}, "heading": f"{name} is ready for you",
        "preheader": f"{action}.", "intro": [_hello(project), layout.rich("<b>{}</b> is waiting for you on <b>{}</b>.",
                                                                          pname, name)],
        "callout": {"title": "What to do", "lines": [action], **layout.CALLOUT_VIOLET},
        "projects_title": "Project", "projects": [row],
        "button": {"text": f"Open {name}", "href": _link(project["id"], page)},
        "footer": "Sent because a project you own is waiting for you."}, inline=inline_logo)


def _rq_count(project_id: int) -> int:
    strategy = store.get_latest_strategy(project_id) or {}
    return len((strategy.get("strategy") or {}).get("research_question_queries") or [])


def matching_label_email(project: dict, *, inline_logo: bool = True) -> dict:
    """Background Research and Search Strategy are done: approve the research questions on Matching label."""
    pname, n = _name(project), _rq_count(project["id"])
    row = layout.project_row(project, f"Matching label · {n} research questions", "Matching label", layout.STATE_TURN)
    return layout.render(f"{pname} is ready for Matching label", {
        "org": layout.org_panel(project.get("org_id")),
        "pill": {"text": "Your turn · Matching label", **layout.PILL_VIOLET},
        "heading": "Approve the research questions",
        "preheader": "Background Research and Search Strategy are done. Approve the research questions to open the "
                     "Data set.",
        "intro": [_hello(project), layout.rich(
            "<b>{}</b> finished Background Research and Search Strategy. Its research questions and their Boolean "
            "queries are ready for you on <b>Matching label</b>.", pname)],
        "callout": {"title": "What to do", "lines": [
            "1. Open Matching label and read each research question with its query.",
            "2. Approve the ones you want (at least one). Approving opens the Data set stage, where you upload your "
            "articles."], **layout.CALLOUT_VIOLET},
        "facts": [("Research questions", f"{n} ready to review"), ("Search strategy", "Approved automatically"),
                  ("Next stage", "Data set: upload and tag your articles")],
        "projects_title": "Project", "projects": [row],
        "button": {"text": "Open Matching label", "href": _link(project["id"], "matching-label")},
        "footer": "Sent because a project you own is waiting for you."}, inline=inline_logo)


def dataset_tagged_email(project: dict, counts: dict, cost_usd: float, *, inline_logo: bool = True) -> dict:
    """Tagging finished: the counts, then review and approve the data set (approving starts the deck)."""
    pname = _name(project)
    matched, irrelevant = counts.get("matched", 0), counts.get("irrelevant", 0)
    tagged = int((counts.get("tags") or {}).get("tagged", 0))
    uploaded = matched + irrelevant + counts.get("unmatched", 0)
    row = layout.project_row(project, f"Data set · {tagged} tagged, waiting for approval", "Data set",
                             layout.STATE_TURN)
    return layout.render(f"{pname}: data set tagged, review and approve", {
        "org": layout.org_panel(project.get("org_id")),
        "pill": {"text": "Your turn · Data set", **layout.PILL_VIOLET}, "heading": "Your data set is tagged",
        "preheader": f"{uploaded} articles: {matched} matched and tagged, {irrelevant} irrelevant. Review and approve "
                     f"to build the deck.",
        "intro": [_hello(project), layout.rich("Tagging finished for <b>{}</b>. Review the tagged articles on "
                                               "<b>Data set</b> and approve it: approving starts the deck.", pname)],
        "facts": [("Articles uploaded", f"{uploaded:,}"), ("Matched a research question", f"{matched:,} ({tagged:,} tagged)"),
                  ("Irrelevant", f"{irrelevant:,} (not tagged)"), ("Tagging cost", f"${cost_usd:,.2f}")],
        "callout": {"title": "What to do", "lines": [layout.rich(
            "Open Data set, check the tags per research question, then click <b>Approve data set</b>. Deliverables "
            "starts straight away.")], **layout.CALLOUT_VIOLET},
        "projects_title": "Project", "projects": [row],
        "button": {"text": "Review the data set", "href": _link(project["id"], "data-set")},
        "footer": "Sent because tagging finished on a project you own."}, inline=inline_logo)


def send_ready_email(project_id: int, run_id: int) -> bool:
    """Send once per run; the 'email' section records it so a repair or re-render does not send again."""
    sections = store.list_deliverable_sections(run_id)
    if any(s.get("id") == SECTION_ID for s in sections):
        return False
    project, run = store.get_project(project_id), store.get_deliverable_run(run_id)
    if not project or not run or run.get("status") != "completed":
        return False
    sent = _send(project, render(project, run, sections), f"deliverable:{run_id}")
    if sent:
        store.replace_deliverable_section(run_id, {"id": SECTION_ID, "rq_id": None, "module": SECTION_ID,
                                                   "title": "Ready email", "sent_at": time.time(),
                                                   "recipients": sent})
    return bool(sent)


def _send(project: dict, mail: dict, tag: str) -> int:
    """How many of the project's recipients the mail server accepted the email for."""
    to = recipients(project)
    if not to:
        logger.info("[%s] email skipped: project %s has no user with an email", tag, project["id"])
        return 0
    settings = config.get_app_settings()
    if settings.is_production and "localhost" in settings.app_url:
        logger.warning("[%s] APP_URL is %s in production: the email's link will not open", tag, settings.app_url)
    return sum(layout.send(u, mail) for u in to)


def notify_ready(project_id: int, run_id: int) -> None:
    _background(f"deliverable:{run_id}", lambda: send_ready_email(project_id, run_id))


# job type -> (stage name, page the button opens, what the owner does there). A failed job of these types emails the
# owner. Brief & Scope sends nothing: the user is on the page; research and strategy approve themselves
# (agent/autorun.py), which then sends the Matching label email.
STAGE_GATES = {
    "background_research": ("Background Research", "background-research", "Open it and run it again"),
    "search_strategy": ("Search Strategy", "search-strategy", "Open it and run it again"),
}
_SENT: set[tuple] = set()     # shortcut: per process, so a restart mid-stage can send one repeat; fine on one server
_SENT_LOCK = threading.Lock()


def _stage_key(job: dict) -> tuple | None:
    """What one email covers: a failed job, once. A completed job sends nothing (no stage waits on a person here)."""
    return (job["id"], "failed") if job["status"] == "failed" else None


def stage_email(project: dict, job: dict, *, inline_logo: bool = True) -> dict:
    name, page, action = STAGE_GATES[job["job_type"]]
    error = (job.get("error") or "Unknown error") if job["status"] == "failed" else ""
    return owner_email(project, name, page, action, error=error, inline_logo=inline_logo)


def send_stage_email(job_id: str) -> bool:
    job = store.get_job(job_id)
    if not job or job.get("job_type") not in STAGE_GATES or job.get("status") not in ("completed", "failed"):
        return False
    project = store.get_project(job["project_id"])
    if not project:
        return False
    with _SENT_LOCK:            # two failures landing together must not both send
        key = _stage_key(job)
        if key is None or key in _SENT:
            return False
        _SENT.add(key)
    return bool(_send(project, stage_email(project, job), f"stage:{job_id}"))


def _background(tag: str, fn) -> None:
    """Fire and forget: an email never fails or slows the stage that sends it."""
    if not mailer.is_configured():
        return

    def _go() -> None:
        try:
            fn()
        except Exception:
            logger.exception("[%s] email failed", tag)
    threading.Thread(target=_go, name=f"email-{tag}", daemon=True).start()


def notify_stage(job_id: str) -> None:
    _background(f"stage:{job_id}", lambda: send_stage_email(job_id))


def notify_owner(project_id: int, name: str, page: str, action: str, *, error: str = "") -> None:
    def send() -> None:
        project = store.get_project(project_id)
        if project:
            _send(project, owner_email(project, name, page, action, error=error), f"owner:{project_id}")
    _background(f"owner:{project_id}", send)


def notify_matching_label(project_id: int) -> None:
    """Autorun finished research and strategy: the owner approves the research questions next."""
    def send() -> None:
        project = store.get_project(project_id)
        if project:
            _send(project, matching_label_email(project), f"matching-label:{project_id}")
    _background(f"matching-label:{project_id}", send)


def notify_dataset_tagged(project_id: int, since: float) -> None:
    """A full tagging job finished: counts and the tagging cost since it started."""
    def send() -> None:
        from ..dataset import repository as dataset_repo     # lazy: dataset imports this module
        from ..usage import repository as usage_repo
        project = store.get_project(project_id)
        if project:
            mail = dataset_tagged_email(project, dataset_repo.tagging_counts(project_id),
                                        usage_repo.stage_cost_since(project_id, "dataset_tagging", since))
            _send(project, mail, f"dataset-tagged:{project_id}")
    _background(f"dataset-tagged:{project_id}", send)
