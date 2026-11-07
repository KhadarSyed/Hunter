"""Stage gates: a stage opens only when every stage before it is done. The pages, the stage-start routes and the
project list's progress bar all read this one function."""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException

from ...core import store

STAGES = ("brief_scope", "background_research", "search_strategy", "matching_label", "data_set", "deliverables")
LABELS = {"brief_scope": "Brief & Scope", "background_research": "Background Research",
          "search_strategy": "Search Strategy", "matching_label": "Matching label", "data_set": "Data set",
          "deliverables": "Deliverables"}
_RUNNING = ("pending", "running", "queued")
_JOB = {"brief_scope": "spec_generation", "background_research": "background_research",
        "search_strategy": "search_strategy"}
_SHARE = 100 / len(STAGES)
_TTL_S = 4               # live pages refetch on every progress event; a burst reads one computed summary
_CACHE: dict[int, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def _approved(row: dict | None) -> bool:
    return bool(row) and row.get("approval_status") == "approved"


def _latest_job(jobs: list[dict], stage: str) -> dict | None:
    return next((j for j in jobs if j.get("job_type") == _JOB.get(stage)), None)


def _has_approved_rq(project_id: int) -> bool:
    try:
        from ..deliverable import rows
        return bool(rows.approved_rqs(project_id))
    except Exception:
        return False


def _dataset_facts(project_id: int) -> dict:
    try:
        from ..dataset import repository as repo, tagging_job
        from ..deliverable import rows
        counts, st = repo.tagging_counts(project_id), tagging_job.tagging_state(project_id)
        rq_ids = [q.id for q in rows.approved_rqs(project_id)]
        return {"tagging": bool(st.get("running")), "total": counts["total"],
                "user_approved": bool(repo.dataset_approval(project_id)),
                "pending": int(counts["tags"].get("pending", 0)), "approved": repo.approved_count(project_id, rq_ids),
                "done": int(st.get("done") or 0), "of": int(st.get("total") or 0)}
    except Exception:
        return {"tagging": False, "total": 0, "pending": 0, "approved": 0, "done": 0, "of": 0, "user_approved": False}


def _autorun(project_id: int) -> dict:
    try:
        from ..agent import autorun
        return autorun.status(project_id) or {}
    except Exception:
        return {}


def _facts(project_id: int) -> dict:
    jobs = store.list_jobs(project_id)
    auto = _autorun(project_id)
    auto_step = auto.get("step") if auto.get("status") == "running" else None
    research_job = _latest_job(jobs, "background_research")
    research_done = bool(store.get_latest_research(project_id)) and (
        research_job is None or research_job.get("status") == "completed")
    run = store.get_latest_deliverable_run(project_id)
    data = _dataset_facts(project_id)

    def running(stage: str) -> bool:
        job = _latest_job(jobs, stage)
        return bool(job) and job.get("status") in _RUNNING

    return {
        "pid": project_id, "jobs": jobs, "data": data,
        "done": {
            "brief_scope": _approved(store.get_latest_spec(project_id)),
            "background_research": research_done and _approved(store.get_latest_brief(project_id)),
            "search_strategy": _approved(store.get_latest_strategy(project_id)),
            "matching_label": _has_approved_rq(project_id),
            # tagged, and approved by the analyst (an auto-approved row is not the analyst's sign-off)
            "data_set": (not data["tagging"] and data["total"] > 0 and data["pending"] == 0 and data["approved"] > 0
                         and data.get("user_approved", False)),
            "deliverables": bool(run) and run.get("status") == "completed" and bool(run.get("studio_pptx_path")),
        },
        "running": {
            "brief_scope": running("brief_scope"),
            "background_research": running("background_research") or auto_step in ("research", "brief"),
            "search_strategy": running("search_strategy") or auto_step == "strategy",
            "matching_label": False,
            "data_set": data["tagging"],
            "deliverables": bool(run) and run.get("status") in _RUNNING,
        },
    }


def _gates_from(f: dict) -> dict[str, str]:
    out, blocked = {}, False
    for stage in STAGES:
        if f["done"][stage]:
            out[stage] = "done"
        elif f["running"][stage]:
            out[stage] = "running"        # data already moving wins over the lock
        else:
            out[stage] = "locked" if blocked else "open"
        blocked = blocked or out[stage] != "done"
    return out


def stage_gates(project_id: int) -> dict[str, str]:
    return _gates_from(_facts(project_id))


def _fraction(f: dict, stage: str) -> float:
    if stage == "data_set":
        d = f["data"]
        return d["done"] / d["of"] if d["tagging"] and d["of"] else 0.0
    if stage == "deliverables" and f["running"]["deliverables"]:
        from ..deliverable.engine import LIVE_PCT
        return min(1.0, LIVE_PCT.get(f.get("pid", 0), 0) / 100)
    job = _latest_job(f["jobs"], stage)
    if job and job.get("status") in _RUNNING:
        return max(0.0, min(1.0, (job.get("progress_pct") or 0) / 100))
    return 0.0


def _progress_from(f: dict, g: dict) -> tuple[float, str]:
    current = next((s for s in STAGES if g[s] != "done"), None)
    if current is None:
        return 100.0, "deliverables"
    done = sum(1 for s in STAGES if g[s] == "done")
    return round(done * _SHARE + _fraction(f, current) * _SHARE, 2), current


def progress(project_id: int) -> tuple[float, str]:
    f = _facts(project_id)
    return _progress_from(f, _gates_from(f))


def summary(project_id: int) -> dict:
    """Gates plus progress, for the /gates route and the project list; never raises. Cached for a few seconds
    (display only: require() always reads fresh)."""
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(project_id)
    if hit and now - hit[0] < _TTL_S:
        return hit[1]
    out = _summary(project_id)
    with _CACHE_LOCK:
        _CACHE[project_id] = (now, out)
    return out


def _summary(project_id: int) -> dict:
    try:
        f = _facts(project_id)
        g = _gates_from(f)
        pct, current = _progress_from(f, g)
        return {"gates": g, "progress_pct": pct, "current_stage": current}
    except Exception:
        return {"gates": {s: "open" for s in STAGES}, "progress_pct": 0.0, "current_stage": "brief_scope"}


def require(project_id: int, stage: str) -> None:
    """409 when a stage before `stage` is not done."""
    g = stage_gates(project_id)
    for earlier in STAGES[:STAGES.index(stage)]:
        if g[earlier] != "done":
            raise HTTPException(409, f"Finish {LABELS[earlier]} first")
