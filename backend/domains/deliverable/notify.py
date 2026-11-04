"""Email the project's owner when a deliverable run finishes: once per run, in the background, never failing the run."""
from __future__ import annotations

import base64
import io
import logging
import re
import threading
import time
from pathlib import Path

import requests
from PIL import Image

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ...core import config, mailer, store
from ..deckstudio import data_tables
from ..research import logo_files
from ..research.web_research import _COUNTRY_ISO_CODES
from . import visuals

logger = logging.getLogger(__name__)

SECTION_ID = "email"
LOGO_CID = "brandlogo"
FLAG_DIR = config.DATA_DIR / "flags"
LOGO_PX = 64                # logos are stored at 2x the tallest display size (client logo, 32px chip logos)
FLAG_PX = 36                # flags show at 18px
FLAG_FALLBACK = "https://flagcdn.com/w40/{code}.png"     # rectangular, used only when the circle flag cannot render
_ENV = Environment(loader=FileSystemLoader(config.BACKEND_DIR / "core" / "templates"),
                   autoescape=select_autoescape(["html", "j2"]))


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
    return f"{config.get_app_settings().app_url.rstrip('/')}/{project_id}/{page}"


def build_context(project: dict, run: dict, sections: list[dict]) -> dict:
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
    return {**_project_context(project), "stats": stats, "files": _files(run),
            "link": _link(project["id"], "deliverables")}


def _project_context(project: dict) -> dict:
    """Name, client, brief summary, scope and questions: the part every email to the owner shows."""
    spec = project.get("spec") or {}
    scope = spec.get("included_scope") or {}
    client = (project.get("brand") or spec.get("client") or "").strip()
    competitors = scope.get("competitors") or []
    scope_rows = [("Competitors", ", ".join(map(str, competitors))) if competitors else None,
                  ("Geography", spec.get("geography") or scope.get("geography") or ""),
                  ("Time period", spec.get("time_period") or scope.get("time_period") or "")]
    geography = spec.get("geography") or scope.get("geography") or ""
    return {
        "competitors": [str(c) for c in competitors],
        "countries": [c for c in re.split(r"\s*(?:[,;/&]|\band\b)\s*", geography) if c.strip()]
                     if isinstance(geography, str) else [],
        "project_name": project.get("project_name") or f"Project {project['id']}",
        "client": client,
        "summary": spec.get("executive_interpretation") or spec.get("research_objective") or "",
        "questions": [q.get("question") for q in spec.get("research_questions") or []
                      if isinstance(q, dict) and q.get("question")],
        "scope": [r for r in scope_rows if r and isinstance(r[1], str) and r[1].strip()],
    }


def _png(data: bytes, height: int) -> tuple[str, int, int]:
    """(base64 PNG, width, height): transparent margins cropped, scaled to `height` px tall (at most 3x as wide)."""
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    img = img.crop(img.getchannel("A").getbbox() or (0, 0, *img.size))
    img.thumbnail((height * 3, height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), img.width, img.height


def _logo(name: str) -> dict | None:
    """{b64, w, h, light} for a brand's cached logo, else None (the email then shows the name only)."""
    if not name:
        return None
    try:
        found = logo_files.logo_file(name)
        if not found:
            return None
        b64, w, h = _png(found[0].read_bytes(), LOGO_PX)
        return {"b64": b64, "w": w, "h": h, "light": found[1]}
    except Exception as e:      # a logo is decoration: never stops the email
        logger.info("No logo for %s in the ready email: %s", name, type(e).__name__)
        return None


def _flag(country: str) -> dict | None:
    """{b64, w, h} circle flag (Iconify circle-flags, rendered to PNG once and cached), else None."""
    code = _COUNTRY_ISO_CODES.get(country.strip().lower(), "").lower()
    if not code:
        return None
    try:
        path = visuals.icon_png(f"circle-flags:{code}", FLAG_DIR)
        if path:
            data = path.read_bytes()
        else:
            r = requests.get(FLAG_FALLBACK.format(code=code), timeout=10)
            r.raise_for_status()
            data = r.content
        b64, w, h = _png(data, FLAG_PX)
        return {"b64": b64, "w": w, "h": h}
    except Exception as e:      # a flag is decoration: never stops the email
        logger.info("No flag for %s in the ready email: %s", country, type(e).__name__)
        return None


READY_COPY = {"heading": "Your deliverable is ready", "button": "Open deliverables",
              "preheader": "your deck, brief and data tables are ready.", "stats_title": "Deliverable summary",
              "footer": "Sent by Hunter because a deliverable you own finished building."}


def _text(ctx: dict) -> str:
    lines = [f"Hunter: {ctx['heading']}", "", ctx["project_name"]]
    if ctx["client"]:
        lines.append(f"Client: {ctx['client']}")
    lines += ["", f"{ctx['button']}: {ctx['link']}", ""]
    if ctx["stats"]:
        lines += [ctx["stats_title"].upper()] + [f"- {k}: {v}" for k, v in ctx["stats"]]
    if ctx["files"]:
        lines.append(f"- Files available: {', '.join(ctx['files'])}")
    lines += ["", "BRIEF & SCOPE"]
    if ctx["summary"]:
        lines += [ctx["summary"], ""]
    lines += [f"{k}: {v}" for k, v in ctx["scope"]]
    if ctx["questions"]:
        lines += ["", "Research questions:"] + [f"{i}. {q}" for i, q in enumerate(ctx["questions"], 1)]
    return "\n".join(lines) + "\n"


def render(project: dict, run: dict, sections: list[dict], *, inline_logo: bool = True) -> dict:
    """{subject, html, text, inline_images}. inline_logo=False puts the images in as data URIs (browser preview)."""
    ctx = {**build_context(project, run, sections), **READY_COPY}
    return _compose(ctx, f"Your Hunter deliverable is ready — {ctx['project_name']}", inline_logo)


def _compose(ctx: dict, subject: str, inline_logo: bool = True) -> dict:
    images: list[dict] = []

    def embed(cid: str, img: dict | None) -> dict | None:
        """The image with its `src` (cid: when sending, data URI in preview); Outlook needs real width/height."""
        if not img:
            return None
        if inline_logo:
            images.append({"cid": cid, "mime_type": "image/png", "content": img["b64"]})
        return {**img, "src": f"cid:{cid}" if inline_logo else f"data:image/png;base64,{img['b64']}"}

    client_logo = embed(LOGO_CID, _logo(ctx["client"]))
    competitors = [{"name": n, "logo": embed(f"logo{i}", _logo(n))} for i, n in enumerate(ctx["competitors"], 1)]
    countries = [{"name": c, "flag": embed(f"flag{i}", _flag(c))} for i, c in enumerate(ctx["countries"], 1)]
    html = _ENV.get_template("deliverable_ready.html.j2").render(
        **{**ctx, "competitors": competitors, "countries": countries}, subject=subject, logo=client_logo)
    return {"subject": subject, "html": html, "text": _text(ctx), "inline_images": images}


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
    return sum(mailer.send_email(u["email"], u.get("display_name") or "", mail["subject"], mail["html"],
                                 mail["text"], mail["inline_images"]) for u in to)


def notify_ready(project_id: int, run_id: int) -> None:
    """Fire and forget: the run is already complete, so the email can neither fail nor slow it."""
    def _go() -> None:
        try:
            send_ready_email(project_id, run_id)
        except Exception:
            logger.exception("[deliverable:%s] ready email failed", run_id)
    threading.Thread(target=_go, name=f"ready-email-{run_id}", daemon=True).start()


# job type -> (stage name, page the button opens, what the owner does there). Each of these stages waits for a person
# to approve it in the web app; the deliverable has its own ready email above.
STAGE_GATES = {
    "spec_generation": ("Brief & Scope", "brief-scope-review", "Review and approve the brief and scope"),
    "background_research": ("Background research", "background-research", "Review the research and approve it"),
    "search_strategy": ("Search strategy", "search-strategy", "Review and approve the search queries"),
    "dataset_enrichment": ("Dataset tagging", "data-sources", "Review the tagged datasets and approve them"),
}
_SENT: set[tuple] = set()     # shortcut: per process, so a restart mid-stage can send one repeat; fine on one server
_SENT_LOCK = threading.Lock()


def _stage_key(job: dict) -> tuple | None:
    """What one email covers, or None while it should wait: a project uploads several datasets at once, so its
    enrichment jobs are one email, sent when the last of them finishes."""
    if job["job_type"] != "dataset_enrichment" or job["status"] == "failed":
        return (job["id"], job["status"])
    siblings = store.list_jobs(job["project_id"], "dataset_enrichment")
    if any(j["status"] in ("pending", "running") for j in siblings):
        return None
    return (job["project_id"], "dataset_enrichment", tuple(sorted(j["id"] for j in siblings)))


def stage_email(project: dict, job: dict, *, inline_logo: bool = True) -> dict:
    name, page, action = STAGE_GATES[job["job_type"]]
    failed = job["status"] == "failed"
    result = (job.get("error") or "Unknown error") if failed else (job.get("progress_message") or "Complete")
    ctx = {**_project_context(project), "files": [], "link": _link(project["id"], page),
           "stats": [("Stage", name), ("Error" if failed else "Result", str(result)[:300]),
                     ("Next step", f"Open {name} in Hunter and run it again" if failed else action)],
           "heading": f"{name} needs your attention" if failed else f"{name} is ready for your approval",
           "button": f"Open {name}", "stats_title": "Needs your attention" if failed else "Waiting for you",
           "preheader": f"{name} failed: open Hunter to retry it." if failed else f"{action}.",
           "footer": f"Sent by Hunter because a stage of a project you own "
                     f"{'failed' if failed else 'is waiting for your approval'}."}
    subject = f"{'Action needed' if failed else 'Approval needed'}: {name} — {ctx['project_name']}"
    return _compose(ctx, subject, inline_logo)


def send_stage_email(job_id: str) -> bool:
    job = store.get_job(job_id)
    if not job or job.get("job_type") not in STAGE_GATES or job.get("status") not in ("completed", "failed"):
        return False
    project = store.get_project(job["project_id"])
    if not project:
        return False
    with _SENT_LOCK:            # two enrichment jobs finishing together must not both send
        key = _stage_key(job)
        if key is None or key in _SENT:
            return False
        _SENT.add(key)
    return bool(_send(project, stage_email(project, job), f"stage:{job_id}"))


def notify_stage(job_id: str) -> None:
    """Fire and forget from a job's final status: the email never fails or slows the stage."""
    if not mailer.is_configured():
        return

    def _go() -> None:
        try:
            send_stage_email(job_id)
        except Exception:
            logger.exception("[stage:%s] approval email failed", job_id)
    threading.Thread(target=_go, name=f"stage-email-{job_id}", daemon=True).start()
