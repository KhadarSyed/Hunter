"""Autorun: once Brief & Scope is approved, background research and search strategy run and approve themselves, and
the next step for a person is Data Sources. It goes through the app's own routes like the autopilot, so it gets the
UI's checks: research with blocking reasons or a strategy that fails validation is left unapproved and the owner is
emailed instead."""
from __future__ import annotations

import contextvars
import logging
import threading

from ..deliverable import notify
from .api_client import ApiClient

logger = logging.getLogger(__name__)

JOB_TIMEOUT = 3 * 3600
# step -> (stage name, page): where the chain is, and where a stopped chain sends the owner
STEPS = {"research": ("Background research", "background-research"),
         "brief": ("Background research", "background-research"),
         "strategy": ("Search strategy", "search-strategy")}
_STATE: dict[int, dict] = {}    # shortcut: per process; a restart stops the chain as it stops any running job
_LOCK = threading.Lock()


class JobFailed(RuntimeError):
    """The stage's job failed: its own failure email has already gone out."""


def status(project_id: int) -> dict:
    return _STATE.get(project_id) or {"status": "idle"}


def start(project_id: int, user_id: int) -> dict:
    with _LOCK:
        if status(project_id)["status"] == "running":
            return _STATE[project_id]
        _STATE[project_id] = {"status": "running", "step": "research", "job_id": None, "error": None}
    threading.Thread(target=contextvars.copy_context().run, args=(_run, project_id, user_id), daemon=True, name=f"autorun-{project_id}").start()
    return _STATE[project_id]


def _set(project_id: int, **changes) -> None:
    _STATE[project_id] = {**_STATE[project_id], **changes}


def _job(api: ApiClient, project_id: int, started: dict) -> dict:
    _set(project_id, job_id=started["job_id"])
    job = api.wait_job(started["job_id"], JOB_TIMEOUT)
    if job["status"] != "completed":
        raise JobFailed(job.get("error") or f"job {job['status']}")
    return job.get("result") or {}


def _approved(answer: dict) -> None:
    if not answer.get("approved"):
        raise RuntimeError("; ".join(answer.get("blocking_reasons") or []) or "not approved")


def _steps(api: ApiClient, project_id: int, reviewer: str) -> None:
    project = api.call("GET", f"/projects/{project_id}")
    done = _job(api, project_id, api.call("POST", "/research/start",
                                           json={"spec": project["spec"], "project_id": project_id}))
    _set(project_id, step="brief", job_id=None)
    _approved(api.call("POST", f"/research/{done['research_id']}/approve", json={"reviewer": reviewer}))
    brief = api.call("POST", "/brief/generate", json={"project_id": project_id})
    api.call("POST", f"/brief/{brief['brief_id']}/approve", json={"reviewer": reviewer})
    _set(project_id, step="strategy")
    _job(api, project_id, api.call("POST", "/strategy/generate", json={"project_id": project_id}))
    _approved(api.call("POST", f"/strategy/{project_id}/final-approve",
                       json={"reviewer": reviewer, "acknowledge_meltwater_validation": True}))


def _run(project_id: int, user_id: int) -> None:
    from ..usage.service import scope as usage_scope
    with usage_scope(project_id=project_id, stage="agent", user_id=user_id):
        _drive(project_id, user_id)


def _drive(project_id: int, user_id: int) -> None:
    api = None
    try:
        api = ApiClient(user_id)
        _steps(api, project_id, f"autorun:{user_id}")
        _set(project_id, status="done", step="data-sources", job_id=None)
        notify.notify_owner(project_id, "Data set", "data-set",
                            "Review the research questions, upload your datasets and approve them")
    except Exception as e:
        logger.warning("[autorun:%s] stopped at %s: %s", project_id, status(project_id).get("step"), e)
        _set(project_id, status="blocked", error=str(e)[:500])
        if not isinstance(e, JobFailed):
            name, page = STEPS[status(project_id)["step"]]
            notify.notify_owner(project_id, name, page, "Open it, check what is flagged and approve it", error=str(e))
    finally:
        if api:
            api.close()
