"""Research execution routes: start, status, pause/resume/cancel, retry, evidence, logs."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ...core import store
from ...core.api import OkResponse
from ...core.auth import require_project_access
from ...core.events import broadcast as _broadcast
from ...core.jobs import submit
from . import service as executor_service
from .schemas import (
    EvidenceRecord,
    ExecutionJobStarted,
    ExecutionLogRecord,
    ExecutionResumeStarted,
    ExecutionStartRequest,
    ExecutionStatusResponse,
    RetryUnitCompleted,
    RetryUnitFailed,
    RetryUnitRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/execution/start", response_model=ExecutionJobStarted)
def start_execution(req: ExecutionStartRequest):
    """Start executing the approved Research Plan."""

    project = store.get_project(req.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    job_id = f"exec_{uuid.uuid4().hex[:12]}"
    store.create_job(job_id, req.project_id, "research_execution")

    def worker():
        store.update_job(job_id, status="running", progress_pct=10,
                         progress_message="Starting execution")
        _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                     "progress_pct": 10, "message": "Starting execution"})

        try:
            def emit(event_type, payload):
                # Human-readable text per event type — covers both phases this worker's
                # `emit` is threaded through: auto-plan generation (executor_service.
                # start_execution calls planner_service.generate_plan with this same emit,
                # which in turn hands it to agents/research_planner.py) and the actual
                # per-unit execution loop. Without this mapping the message was the bare
                # event_type string with an empty unit_id for every planner-phase event
                # (e.g. "auto_plan: "), which is why the UI showed nothing useful before
                # a plan existed.
                if event_type == "auto_plan":
                    message = "No approved research plan found — generating one automatically..."
                elif event_type == "planner_generating":
                    message = payload.get("status", "Running research planner...")
                elif event_type == "research_planner_started":
                    message = (f"Planning {payload.get('research_questions', 0)} research "
                               f"question(s) for {payload.get('client', '')}...")
                elif event_type == "research_planner_attempt":
                    message = f"Planner attempt {payload.get('attempt', 1)}..."
                elif event_type == "research_planner_reasoning":
                    message = payload.get("status", "LLM designing research strategy...")
                elif event_type == "research_planner_error":
                    message = f"Planner error: {payload.get('error', '')}"
                elif event_type == "research_planner_validated":
                    message = (f"Plan drafted — {payload.get('objectives', 0)} objectives, "
                               f"{payload.get('errors', 0)} errors, {payload.get('warnings', 0)} warnings")
                elif event_type == "research_planner_failed":
                    message = "Planner failed — falling back to a deterministic plan"
                elif event_type == "research_planner_complete":
                    message = (f"Plan ready — {payload.get('objectives', 0)} objectives covering "
                               f"{payload.get('questions_covered', 0)}/{payload.get('total_questions', 0)} "
                               f"research questions")
                elif event_type == "executor_unit_start":
                    message = f"Running {payload.get('unit_id', '')} — method: {payload.get('method', '')}"
                elif event_type == "executor_unit_done":
                    message = (f"{payload.get('unit_id', '')} done — "
                               f"{payload.get('completed', 0)}/{payload.get('total', 0)} units complete")
                else:
                    message = event_type

                # Progress percentage is only meaningful once real units are running
                # (where total/completed are unit counts); during the planning phase it
                # stays at a fixed pre-execution value rather than defaulting to 0 or 100.
                if event_type.startswith("executor_unit"):
                    total = payload.get("total", 1)
                    completed = payload.get("completed", 0)
                    pct = min(90, 10 + int(80 * completed / max(total, 1)))
                else:
                    pct = 10

                store.update_job(job_id, status="running", progress_pct=pct, progress_message=message)
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                             "progress_pct": pct, "message": message})
                _broadcast({"type": "intel_execution_update", "project_id": req.project_id,
                             "event": event_type, "payload": payload})

            result = executor_service.start_execution(req.project_id, emit=emit)

            if result.get("status") in ("completed", "completed_with_errors"):
                store.update_job(job_id, status="completed", progress_pct=100,
                                 progress_message="Execution complete",
                                 result=result)
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "completed",
                             "progress_pct": 100, "message": "Execution complete"})
            elif result.get("status") == "blocked":
                store.update_job(job_id, status="failed", error=result.get("error", "Blocked"))
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed",
                             "error": result.get("error")})
            else:
                store.update_job(job_id, status=result.get("status", "failed"),
                                 error=result.get("error"))
                _broadcast({"type": "intel_job_update", "job_id": job_id,
                             "status": result.get("status", "failed"),
                             "error": result.get("error")})

            _broadcast({"type": "intel_execution_complete", "project_id": req.project_id,
                         "result": result})

        except Exception as e:
            logger.error("[execution:%s] Unhandled error: %s", job_id, e, exc_info=True)
            store.update_job(job_id, status="failed", error=str(e))
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed",
                         "error": str(e)})

    submit(worker, name="execution:start")
    return {"job_id": job_id, "project_id": req.project_id}


@router.get("/execution/{project_id}", response_model=ExecutionStatusResponse)
def get_execution_status(project_id: Annotated[int, Path(ge=1)],
                          _access: Annotated[dict, Depends(require_project_access)]):
    """Get the current execution status for a project."""
    status = executor_service.get_execution_status(project_id)
    if not status:
        raise HTTPException(404, "No execution found for this project")
    return status


@router.post("/execution/{run_id}/pause", response_model=OkResponse)
def pause_execution(run_id: Annotated[int, Path(ge=1)]):
    """Pause a running execution."""
    ok = executor_service.pause_execution(run_id)
    if not ok:
        raise HTTPException(404, "Run not found or not pausable")
    _broadcast({"type": "intel_execution_update", "event": "paused", "run_id": run_id})
    return {"ok": True}


@router.post("/execution/{run_id}/resume", response_model=ExecutionResumeStarted)
def resume_execution(run_id: Annotated[int, Path(ge=1)], req: ExecutionStartRequest):
    """Resume a paused execution."""

    job_id = f"exec_resume_{uuid.uuid4().hex[:8]}"
    store.create_job(job_id, req.project_id, "research_execution_resume")

    def worker():
        store.update_job(job_id, status="running", progress_pct=10,
                         progress_message="Resuming execution")

        try:
            def emit(event_type, payload):
                _broadcast({"type": "intel_execution_update", "project_id": req.project_id,
                             "event": event_type, "payload": payload})

            result = executor_service.resume_execution(req.project_id, run_id, emit=emit)
            store.update_job(job_id, status="completed", progress_pct=100,
                             progress_message="Resume complete", result=result)
            _broadcast({"type": "intel_execution_complete", "project_id": req.project_id,
                         "result": result})
        except Exception as e:
            store.update_job(job_id, status="failed", error=str(e))

    submit(worker, name="execution:resume")
    return {"job_id": job_id}


@router.post("/execution/{run_id}/cancel", response_model=OkResponse)
def cancel_execution(run_id: Annotated[int, Path(ge=1)]):
    """Cancel a running execution."""
    ok = executor_service.cancel_execution(run_id)
    if not ok:
        raise HTTPException(404, "Run not found or not cancellable")
    _broadcast({"type": "intel_execution_update", "event": "cancelled", "run_id": run_id})
    return {"ok": True}


@router.post("/execution/{run_id}/retry/{unit_id}", response_model=RetryUnitCompleted | RetryUnitFailed)
def retry_execution_unit(run_id: Annotated[int, Path(ge=1)], unit_id: str, req: RetryUnitRequest):
    """Retry a single failed execution unit."""

    result = executor_service.retry_unit(req.project_id, run_id, unit_id)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error", "Retry failed"))
    _broadcast({"type": "intel_execution_update", "project_id": req.project_id,
                 "event": "unit_retried", "payload": {"unit_id": unit_id, "result": result}})
    return result


@router.get("/execution/{run_id}/evidence", response_model=list[EvidenceRecord])
def get_execution_evidence(run_id: Annotated[int, Path(ge=1)], unit_id: Optional[str] = None):
    """Get evidence collected during execution."""
    return store.get_evidence(run_id, unit_id)


@router.get("/execution/{run_id}/logs", response_model=list[ExecutionLogRecord])
def get_execution_logs(run_id: Annotated[int, Path(ge=1)], limit: Annotated[int, Query(ge=1, le=1000)] = 100):
    """Get execution logs."""
    return store.get_execution_logs(run_id, limit)
