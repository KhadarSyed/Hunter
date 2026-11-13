"""The one AlphaMetricx email layout: every email the app sends (accounts, stages, outages, deliverables) is a context
for core/templates/email.html.j2, rendered here with its pictures attached inline (cid), so Outlook shows them without
"download pictures". Rich text goes through rich(): the markup is trusted, every value put into it is escaped.

Context keys: org (org_panel), pill, heading, preheader, intro [lines], callout {title, lines, bg, bar, fg}, code,
code_note, facts [(label, value)], button {text, href, note}, models_title, models [model_row], projects_title,
projects [project_row], footer.
"""
from __future__ import annotations

import base64
import functools
import io
import logging
import re
import time
from html import unescape

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from PIL import Image

from . import config

logger = logging.getLogger(__name__)
WORDMARK_KEY = "HunterAgent/assets/house/alphametricx-logo.png"
_ENV = Environment(loader=FileSystemLoader(config.BACKEND_DIR / "core" / "templates"),
                   autoescape=select_autoescape(["html", "j2"]))

# pills, callouts and model badges
PILL_VIOLET = {"bg": "#EDE7F8", "fg": "#5B2C9D"}
PILL_AMBER = {"bg": "#FFF7E6", "fg": "#92400E"}
PILL_RED = {"bg": "#FEF2F2", "fg": "#991B1B"}
PILL_GREEN = {"bg": "#ECFDF5", "fg": "#065F46"}
CALLOUT_VIOLET = {"bg": "#F6F3FB", "bar": "#5B2C9D", "fg": "#5B2C9D"}
CALLOUT_AMBER = {"bg": "#FFF7E6", "bar": "#F59E0B", "fg": "#92400E"}
CALLOUT_RED = {"bg": "#FEF2F2", "bar": "#EF4444", "fg": "#991B1B"}
CALLOUT_GREEN = {"bg": "#ECFDF5", "bar": "#10B981", "fg": "#065F46"}
BADGE_DOWN = {"bg": "#FEE2E2", "fg": "#991B1B"}
BADGE_UP = {"bg": "#D1FAE5", "fg": "#065F46"}
BADGE_IN_USE = {"bg": "#EDE7F8", "fg": "#5B2C9D"}
STATE_GOOD, STATE_BAD, STATE_TURN = "#047857", "#B91C1C", "#5B2C9D"


def rich(fmt: str, *args, **kwargs) -> Markup:
    """Trusted markup with escaped values: rich("<b>{}</b> is ready", project_name)."""
    return Markup(fmt).format(*args, **kwargs)


def app_link(path: str) -> str:
    return f"{config.get_app_settings().app_url.rstrip('/')}/{path.lstrip('/')}"


def _png(data: bytes, height: int) -> dict:
    """{b64, w, h}: transparent margins cropped, kept at up to 3x `height` (sharp on high-density screens), shown at
    `height` px."""
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    img = img.crop(img.getchannel("A").getbbox() or (0, 0, *img.size))
    img.thumbnail((height * 60, height * 3), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return {"b64": base64.b64encode(buf.getvalue()).decode("ascii"), "w": max(1, round(img.width * height / img.height)),
            "h": height}


@functools.lru_cache(maxsize=1)
def _wordmark() -> dict | None:
    """The AlphaMetricx wordmark: the S3 copy, else the one the web app ships."""
    from . import object_store
    data = None
    try:
        data = object_store.get_bytes(WORDMARK_KEY)
    except Exception as e:      # a logo is decoration: never stops an email
        logger.info("Wordmark not read from S3: %s", type(e).__name__)
    for path in (config.REPO_ROOT / "frontend" / "public" / "alphametricx.png",
                 config.BACKEND_DIR / "static" / "alphametricx.png"):
        if data is None and path.exists():
            data = path.read_bytes()
    return _png(data, 26) if data else None


def client_logo(name: str) -> dict | None:
    """The client's cached brand logo (the one project cards use), {b64, w, h, light}, else None."""
    if not name:
        return None
    try:
        from ..domains.research import logo_files      # lazy: domains import core
        found = logo_files.logo_file(name)
        return {**_png(found[0].read_bytes(), 32), "light": found[1]} if found else None
    except Exception as e:
        logger.info("No logo for %s in an email: %s", name, type(e).__name__)
        return None


_PROVIDER_ICONS = {"azure_openai": "logos:microsoft-azure", "anthropic": "logos:anthropic-icon",
                   "gemini": "logos:google-gemini"}


@functools.lru_cache(maxsize=32)
def provider_logo(provider_type: str, base_url: str = "") -> dict | None:
    """The provider's logo, by type and, for an OpenAI-compatible server, by host (NVIDIA, OpenAI); else a neutral
    API mark (no other brand's logo is guessed)."""
    host = base_url.lower()
    icon = _PROVIDER_ICONS.get(provider_type) or ("logos:nvidia" if "nvidia" in host else
                                                  "simple-icons:openai" if "openai.com" in host else "mdi:api")
    try:
        from ..domains.deliverable import visuals       # lazy: domains import core
        path = visuals.icon_png(icon, config.ASSET_CACHE_DIR / "email_icons", "#000000")
        return _png(path.read_bytes(), 22) if path else None
    except Exception as e:
        logger.info("No provider logo %s in an email: %s", icon, type(e).__name__)
        return None


def org_panel(org_id: int | None) -> dict:
    """{name, rows}: the organization, each Admin's name and email, its active projects."""
    from . import store
    org = store.get_organization_by_id(org_id) if org_id else None
    if not org:
        return {"name": "AlphaMetricx", "rows": []}
    projects = [p for p in store.list_projects(org_id=org_id) if not p.get("archived_at")]
    rows = [("Organization", org["name"])]
    rows += [("Admin", f"{u.get('display_name') or u['email']} · {u['email']}") for u in org_admins(org_id)]
    rows.append(("Projects", f"{len(projects)} active"))
    return {"name": org["name"], "rows": rows}


def org_admins(org_id: int) -> list[dict]:
    """Who gets an organization's alerts: its active Admins; an org with none (a test org run by a Super Admin) has
    its Super Admin members instead."""
    from . import store
    users = [u for u in store.list_users(org_id=org_id) if not u.get("archived_at") and u.get("email")]
    admins = [u for u in users if u.get("role") == "admin" and u.get("org_id") == org_id]
    return admins or [u for u in users if u.get("role") == "super_admin"]


def project_row(project: dict, stage: str, state: str, state_color: str) -> dict:
    client = (project.get("brand") or (project.get("spec") or {}).get("client") or "").strip()
    return {"name": project.get("project_name") or f"Project {project['id']}", "client": client, "stage": stage,
            "state": state, "state_color": state_color, "logo": client_logo(client)}


def model_row(provider: dict, detail: str, state: str, badge: dict) -> dict:
    """provider: an org_llm_providers row (name, provider_type, base_url)."""
    labels = {"azure_openai": "Azure OpenAI", "anthropic": "Anthropic", "gemini": "Google Gemini",
              "openai_compatible": "OpenAI-compatible"}
    return {"name": provider["name"], "provider": labels.get(provider["provider_type"], provider["provider_type"]),
            "detail": detail, "state": state, **badge,
            "logo": provider_logo(provider["provider_type"], provider.get("base_url") or "")}


def _text(ctx: dict) -> str:
    """The plain-text part: the same content, no markup."""
    def plain(v) -> str:
        return unescape(re.sub(r"<[^>]+>", "", str(v)))
    lines = [plain(ctx["heading"]), ""] + [plain(p) for p in ctx.get("intro") or []]
    if ctx.get("callout"):
        lines += ["", plain(ctx["callout"]["title"])] + [plain(x) for x in ctx["callout"].get("lines") or []]
    if ctx.get("code"):
        lines += ["", f"Code: {ctx['code']}" + (f" ({ctx['code_note']})" if ctx.get("code_note") else "")]
    if ctx.get("models"):
        lines += ["", str(ctx.get("models_title", "")).upper()]
        lines += [f"- {m['name']} ({m['provider']}): {m['state']} {m.get('detail') or ''}".rstrip() for m in ctx["models"]]
    if ctx.get("projects"):
        lines += ["", str(ctx.get("projects_title", "")).upper()]
        lines += [f"- {p['name']} · {p['stage']}: {p['state']}" for p in ctx["projects"]]
    if ctx.get("facts"):
        lines += [""] + [f"{k}: {plain(v)}" for k, v in ctx["facts"]]
    if ctx.get("button"):
        lines += ["", f"{ctx['button']['text']}: {ctx['button']['href']}"]
    if ctx["org"].get("rows"):
        lines += ["", "ORGANIZATION"] + [f"{k}: {v}" for k, v in ctx["org"]["rows"]]
    lines += ["", plain(ctx.get("footer", "")), "", f"Questions? {config.get_app_settings().support_email}",
              f"AlphaMetricx © {time.localtime().tm_year} · Never share your password or codes."]
    return "\n".join(lines) + "\n"


def render(subject: str, ctx: dict, *, inline: bool = True) -> dict:
    """{subject, html, text, inline_images}. inline=False puts the pictures in as data URIs (a browser preview)."""
    images: list[dict] = []

    def attach(cid: str, img: dict | None) -> dict | None:
        if not img:
            return None
        if inline:
            images.append({"cid": cid, "mime_type": "image/png", "content": img["b64"]})
        return {**img, "src": f"cid:{cid}" if inline else f"data:image/png;base64,{img['b64']}"}

    ctx = {**ctx, "org": ctx.get("org") or {"name": "AlphaMetricx", "rows": []}}
    ctx["models"] = [{**m, "logo": attach(f"model{i}", m.get("logo"))} for i, m in enumerate(ctx.get("models") or [])]
    ctx["projects"] = [{**p, "logo": attach(f"project{i}", p.get("logo"))} for i, p in enumerate(ctx.get("projects") or [])]
    html = _ENV.get_template("email.html.j2").render(
        **ctx, subject=subject, wordmark=attach("wordmark", _wordmark()), support=config.get_app_settings().support_email,
        year=time.localtime().tm_year)
    return {"subject": subject, "html": html, "text": _text(ctx), "inline_images": images}


def send(to: dict, mail: dict) -> bool:
    """One rendered email to one user {email, display_name}. Never raises."""
    from . import mailer
    return mailer.send_email(to["email"], to.get("display_name") or "", mail["subject"], mail["html"], mail["text"],
                             inline_images=mail["inline_images"])
