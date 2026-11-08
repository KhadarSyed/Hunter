"""An organisation's model outage: its state (org_llm_state, mirrored in memory so a healthy call costs nothing) and
the emails to its admins, once per event: switched to a backup model, paused (every model down), recovered."""
from __future__ import annotations

import logging
import threading
import time

from ...core import email_layout as layout, mailer, store
from . import repository as repo

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_state: dict[int, dict | None] = {}     # org id -> its outage row, None when healthy (loaded once from the table)


def _get(org_id: int) -> dict | None:
    with _lock:
        if org_id in _state:
            st = _state[org_id]
            return dict(st) if st else None
    st = repo.get_outage(org_id)
    with _lock:
        _state[org_id] = st
    return dict(st) if st else None


def _put(org_id: int, st: dict | None) -> None:
    with _lock:
        _state[org_id] = st
    if st is None:
        repo.clear_outage(org_id)
    else:
        repo.save_outage(org_id, st)


def snapshot(org_id: int) -> dict | None:
    """The org's outage as the LLM Providers page shows it, or None when healthy."""
    st = _get(org_id)
    return None if st is None else {k: st.get(k) for k in ("acting_provider_id", "down_since", "paused", "last_error",
                                                             "failed_calls")}


def is_paused(org_id: int | None) -> bool:
    return bool(org_id) and bool((_get(org_id) or {}).get("paused"))


def _new() -> dict:
    return {"acting_provider_id": None, "down_since": time.time(), "failed_calls": 0, "notified": "", "paused": 0,
            "last_error": ""}


def on_failure(org_id: int, row: dict, kind: str, reason: str) -> None:
    st = _get(org_id) or _new()
    st["failed_calls"] += 1
    st["last_error"] = f"{row['name']}: {reason}"[:300]
    _put(org_id, st)


def on_success(org_id: int, rows: list[dict], row: dict) -> None:
    st = _get(org_id)
    if st is None:
        return                          # healthy: the common case, no I/O
    if row["id"] == rows[0]["id"]:      # the saved default answers again: the outage is over
        _put(org_id, None)
        if st["notified"]:
            _email(org_id, "recovered", rows, row, st)
        return
    if st["acting_provider_id"] != row["id"] or st["paused"]:
        was_paused = st["paused"]
        st.update(acting_provider_id=row["id"], paused=0)
        send = st["notified"] != "switched" or bool(was_paused)
        if send:
            st["notified"] = "switched"
        _put(org_id, st)
        if send:
            _email(org_id, "switched", rows, row, st)


def on_all_down(org_id: int, rows: list[dict]) -> None:
    st = _get(org_id) or _new()
    if st["paused"] and st["notified"] == "paused":
        return
    st.update(paused=1, acting_provider_id=None, notified="paused")
    _put(org_id, st)
    _email(org_id, "paused", rows, None, st)


# ─── the emails ──────────────────────────────────────────────────────────────────────────────────────────────────

def _is_down(row: dict) -> bool:
    from .service import down_info
    return down_info(row["id"]) is not None


def _models(rows: list[dict], acting: dict | None) -> list[dict]:
    from .service import down_info
    out = []
    for r in rows:
        d = down_info(r["id"])
        if acting and r["id"] == acting["id"]:
            out.append(layout.model_row(r, "answering", "Now in use", layout.BADGE_IN_USE))
        elif d:
            hint = "check the key or model in LLM Providers" if d["kind"] == "config" else ""
            out.append(layout.model_row(r, " · ".join(x for x in (d["reason"][:110], hint) if x), "Down",
                                        layout.BADGE_DOWN))
        else:
            out.append(layout.model_row(r, "standby", "Ready", layout.BADGE_UP))
    return out


def _running_projects(org_id: int) -> list[tuple[dict, str]]:
    """(project, what it is doing) for the org's projects with a stage running now."""
    from ..projects import gates
    out = []
    for p in store.list_projects(org_id=org_id):
        detail = gates.summary(p["id"]).get("detail") or {}
        running = next(((s, d) for s, d in detail.items() if d.get("state") == "running"), None)
        if running:
            stage = gates.LABELS[running[0]] + (f" · {running[1]['sub']}" if running[1].get("sub") else "")
            out.append((store.get_project(p["id"]) or p, stage))
    return out


def _since(ts: float) -> str:
    return time.strftime("%d %b %Y, %H:%M %Z", time.localtime(ts))


def _listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def build(org_id: int, kind: str, rows: list[dict], acting: dict | None, st: dict) -> dict:
    """The switched / paused / recovered email for the org's admins: {subject, html, text, inline_images}."""
    org = layout.org_panel(org_id)
    name = org["name"]
    projects = _running_projects(org_id)
    common = {"org": org, "models_title": "Your models", "models": _models(rows, acting)}
    if kind == "switched":
        names = [r["name"] for r in rows if r["id"] != acting["id"] and _is_down(r)] or [rows[0]["name"]]
        down, verb = _listed(names), "is" if len(names) == 1 else "are"
        return layout.render(f"{name}: {down} {verb} down, work moved to {acting['name']}", {**common,
            "pill": {"text": "Model outage · switched", **layout.PILL_AMBER},
            "heading": f"{down} {verb} down, work continues on {acting['name']}",
            "preheader": f"{down} stopped answering. Work moved to {acting['name']}.",
            "intro": ["Hello,", "The AI model your organization uses stopped answering, so its work moved to the next "
                                "model you have set up. Nothing was sent to the platform model."],
            "callout": {"title": f"Since {_since(st['down_since'])} · {st['failed_calls']} failed calls",
                        "lines": [st.get("last_error") or ""], **layout.CALLOUT_AMBER},
            "projects_title": f"Projects now running on {acting['name']}",
            "projects": [layout.project_row(p, s, "Continuing", layout.STATE_GOOD) for p, s in projects],
            "button": {"text": "Open LLM Providers", "href": layout.app_link("settings?tab=providers"),
                       "note": f"We'll email you again when {rows[0]['name']} answers."},
            "footer": f"Sent to the admins of {name} because its AI model stopped answering."})
    if kind == "paused":
        names = [r["name"] for r in rows]
        verb = "is" if len(names) == 1 else "are"
        paused = [layout.project_row(p, s, "Paused", layout.STATE_BAD) for p, s in projects]
        return layout.render(f"{name}: {_listed(names)} {verb} down, {len(paused)} "
                             f"project{'' if len(paused) == 1 else 's'} paused", {**common,
            "pill": {"text": "Model outage · paused", **layout.PILL_RED},
            "heading": f"{_listed(names)} {verb} down",
            "preheader": f"None of {name}'s models is answering. Its projects are paused and resume on their own.",
            "intro": ["Hello,", "None of your organization's AI models is answering, so its running projects are "
                                "paused. We recheck every 5 minutes and resume each project where it stopped as soon "
                                "as any model answers. Nothing is lost and nothing was sent to the platform model."],
            "projects_title": "Paused projects", "projects": paused,
            "button": {"text": "Fix in LLM Providers", "href": layout.app_link("settings?tab=providers"),
                       "note": "Adding or fixing a model resumes the projects within 5 minutes."},
            "footer": f"Sent to the admins of {name} because its projects could not reach any AI model."})
    minutes = max(1, round((time.time() - st["down_since"]) / 60))
    return layout.render(f"{name}: {acting['name']} is back", {**common,
        "pill": {"text": "Recovered", **layout.PILL_GREEN}, "heading": f"{acting['name']} is answering again",
        "preheader": f"{acting['name']} is back after {minutes} minutes.",
        "intro": ["Hello,", layout.rich("<b>{}</b> is answering again and every paused project resumed where it "
                                        "stopped.", acting["name"])],
        "facts": [("Outage", f"{_since(st['down_since'])} · {minutes} min"),
                  ("Failed calls", f"{st['failed_calls']} (not charged)")],
        "projects_title": "Resumed projects",
        "projects": [layout.project_row(p, s, "Resumed", layout.STATE_GOOD) for p, s in projects],
        "button": {"text": "Open projects", "href": layout.app_link("projects")},
        "footer": f"Sent to the admins of {name} after its AI model recovered."})


def _email(org_id: int, kind: str, rows: list[dict], acting: dict | None, st: dict) -> None:
    """In the background: the email never slows or fails the call that noticed the outage."""
    if not mailer.is_configured():
        return

    def go() -> None:
        try:
            mail = build(org_id, kind, rows, acting, st)
            sent = sum(layout.send(u, mail) for u in layout.org_admins(org_id))
            logger.info("Outage email '%s' for org %s sent to %s admin(s)", kind, org_id, sent)
        except Exception:
            logger.exception("Outage email '%s' for org %s failed", kind, org_id)
    threading.Thread(target=go, name=f"outage-email-{org_id}", daemon=True).start()
