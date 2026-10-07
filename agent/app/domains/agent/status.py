"""Where a project is in the pipeline, step by step, and the next step a deterministic driver would take."""
from __future__ import annotations

from ...core import store

STEP_KEYS = ("scope", "research", "brief", "strategy", "datasets", "deliverable")
LABELS = {"scope": "Scope", "research": "Background research", "brief": "Analyst brief", "strategy": "Search strategy",
          "datasets": "Datasets", "deliverable": "Deck"}
ENRICH_MAX_RECORDS = 2000
_RUNNING_JOB = ("pending", "running", "queued")
_JOB_FOR = {"scope": "spec_generation", "research": "background_research", "strategy": "search_strategy"}


def _approved(row: dict | None) -> bool:
    return bool(row) and row.get("approval_status") == "approved"


def _job_running(jobs: list[dict], step: str) -> bool:
    kind = _JOB_FOR.get(step)
    return bool(kind) and any(j.get("job_type") == kind and j.get("status") in _RUNNING_JOB for j in jobs)


def _state(row: dict | None, running: bool) -> str:
    if running:
        return "waiting"
    if _approved(row):
        return "done"
    return "ready" if row else "todo"


def _datasets_state(datasets: list[dict]) -> str:
    if not datasets:
        return "todo"
    if any(d.get("processing_status") not in ("done", "error") or d.get("enrichment_status") == "running" for d in datasets):
        return "waiting"
    usable = [d for d in datasets if d.get("processing_status") == "done"]
    if usable and all(_approved(d) for d in usable):
        return "done"
    return "ready" if usable else "failed"


def _run_state(run: dict | None) -> str:
    if not run:
        return "todo"
    if run.get("status") == "completed" and not run.get("studio_pptx_path"):
        return "failed"                 # the classic files shipped but the deck itself did not: not delivered
    return {"running": "waiting", "completed": "done", "failed": "failed"}.get(run.get("status"), "todo")


def project_status(project_id: int) -> dict:
    project = store.get_project(project_id) or {}
    jobs = store.list_jobs(project_id)
    spec, research = store.get_latest_spec(project_id), store.get_latest_research(project_id)
    brief, strategy = store.get_latest_brief(project_id), store.get_latest_strategy(project_id)
    datasets, run = store.get_datasets_by_project(project_id), store.get_latest_deliverable_run(project_id)
    research_done = bool(research)          # the row is written when research finishes; its status stays "draft"
    states = {
        "scope": _state(spec, _job_running(jobs, "scope")),
        "research": "waiting" if _job_running(jobs, "research") else ("done" if research_done else "todo"),
        "brief": _state(brief, False),
        "strategy": _state(strategy, _job_running(jobs, "strategy")),
        "datasets": _datasets_state(datasets),
        "deliverable": _run_state(run),
    }
    no_deck = bool(run) and run.get("status") == "completed" and not run.get("studio_pptx_path")
    details = {"deliverable": "the deck step failed" if no_deck else (run or {}).get("error") or (run or {}).get("stage") or "",
               "datasets": f"{len(datasets)} uploaded"}
    status = {"project_id": project_id, "name": project.get("name") or project.get("project_name") or "",
              "steps": [{"key": k, "label": LABELS[k], "state": states[k], "detail": details.get(k, "")} for k in STEP_KEYS],
              "datasets": datasets, "run": run}
    status["next"] = next_step(status)
    return status


def next_step(status: dict) -> str | None:
    states = {s["key"]: s["state"] for s in status["steps"]}
    for key in STEP_KEYS:
        state = states[key]
        if state == "waiting":
            return "wait"
        if state == "done":
            continue
        if key == "scope":
            return "approve_scope" if state == "ready" else "generate_scope"
        if key == "research":
            return "run_research"
        if key == "brief":
            return "approve_brief"
        if key == "strategy":
            return "approve_strategy" if state == "ready" else "generate_strategy"
        if key == "datasets":
            pending = [d for d in status["datasets"] if d.get("processing_status") == "done" and not _approved(d)]
            if not pending:
                return "upload_datasets"
            d = pending[0]
            small = (d.get("record_count") or 0) <= ENRICH_MAX_RECORDS
            return "enrich_dataset" if small and d.get("enrichment_status") not in ("done", "error") else "approve_dataset"
        return "run_deliverable"
    return None
