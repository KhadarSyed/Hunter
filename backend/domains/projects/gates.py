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
JOB_DONE_FRACTION = 0.9  # a stage whose job finished but which is not yet done (approval or a follow-up step left)
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
                "phase": st.get("phase"), "rq_count": len(rq_ids), "matched": counts.get("matched", 0),
                "irrelevant": counts.get("irrelevant", 0), "unmatched": counts.get("unmatched", 0),
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
        "pid": project_id, "jobs": jobs, "data": data, "run": run, "auto_step": auto_step,
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
    if job and job.get("status") == "completed":
        return JOB_DONE_FRACTION    # job finished, its approval / analyst brief still to come: never fall back to 0
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


_AUTO_STEP = {"research": "Researching the web", "brief": "Writing and approving the analyst brief",
              "strategy": "Generating and approving the Boolean strategy"}


def _sub(f: dict, stage: str, state: str) -> str:
    """What the stage is doing right now (its sub-stage), or what it is waiting for."""
    job, d, run = _latest_job(f["jobs"], stage), f["data"], f.get("run") or {}
    if state == "locked":
        return "Opens when the stage before it is done"
    if stage in _JOB and state == "running":
        if f.get("auto_step") and stage != "brief_scope" and (job is None or job.get("status") not in _RUNNING):
            return _AUTO_STEP.get(f["auto_step"], "Running")
        return (job or {}).get("progress_message") or "Running"
    if stage == "brief_scope":
        return "Approved" if state == "done" else "Waiting for your approval" if job else "Generate the scope"
    if stage in ("background_research", "search_strategy"):
        return "Approved automatically" if state == "done" else "Starts after the stage before it"
    if stage == "matching_label":
        return f"{d.get('rq_count', 0)} research questions approved" if state == "done" else "Approve a research question"
    if stage == "data_set":
        if state == "running":
            return f"{d.get('phase') or 'Tagging'} · {d.get('done', 0)}/{d.get('of', 0)}"
        if state == "done":
            return f"Approved · {d.get('matched', 0)} matched, {d.get('irrelevant', 0)} irrelevant"
        if not (d.get("matched") or d.get("irrelevant") or d.get("unmatched")):
            return "Upload article files"
        if d.get("unmatched"):
            return f"{d['unmatched']} articles to match"
        if d.get("pending"):
            return f"{d['matched']} matched · tag them"
        return "Tagged · waiting for your approval"
    if stage == "deliverables":
        if state == "running":
            return f"Deck: {run.get('stage') or 'starting'}"
        if state == "done":
            return "Deck ready"
        return "Deck failed: open it to repair" if run.get("status") == "failed" else "Build the deck"
    return ""


def _stage_pct(f: dict, stage: str, state: str) -> int:
    if state == "done":
        return 100
    return round(_fraction(f, stage) * 100) if state == "running" else 0


def _org_paused(project_id: int) -> bool:
    try:
        from ..providers import outage
        return outage.is_paused((store.get_project(project_id) or {}).get("org_id"))
    except Exception:
        return False


def _summary(project_id: int) -> dict:
    try:
        f = _facts(project_id)
        g = _gates_from(f)
        pct, current = _progress_from(f, g)
        detail = {s: {"state": g[s], "pct": _stage_pct(f, s, g[s]), "sub": _sub(f, s, g[s])} for s in STAGES}
        if any(d["state"] == "running" for d in detail.values()) and _org_paused(project_id):
            for d in detail.values():
                if d["state"] == "running":
                    d["sub"] = "Paused · waiting for a model"
        return {"gates": g, "progress_pct": pct, "current_stage": current, "detail": detail}
    except Exception:
        return {"gates": {s: "open" for s in STAGES}, "progress_pct": 0.0, "current_stage": "brief_scope"}


def require(project_id: int, stage: str) -> None:
    """409 when a stage before `stage` is not done."""
    g = stage_gates(project_id)
    for earlier in STAGES[:STAGES.index(stage)]:
        if g[earlier] != "done":
            raise HTTPException(409, f"Finish {LABELS[earlier]} first")
