"""Research execution routes: start, status, pause/resume/cancel, retry, evidence, logs."""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException

from ...core import store
from ...core.events import broadcast as _broadcast
from . import service as executor_service
from .schemas import ExecutionStartRequest, RetryUnitRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/execution/start")
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
                total = payload.get("total", 1)
                completed = payload.get("completed", 0)
                pct = min(90, 10 + int(80 * completed / max(total, 1)))
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                             "progress_pct": pct,
                             "message": f"{event_type}: {payload.get('unit_id', '')}"})
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

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "project_id": req.project_id}


@router.get("/execution/{project_id}")
def get_execution_status(project_id: int):
    """Get the current execution status for a project."""
    status = executor_service.get_execution_status(project_id)
    if not status:
        raise HTTPException(404, "No execution found for this project")
    return status


@router.post("/execution/{run_id}/pause")
def pause_execution(run_id: int):
    """Pause a running execution."""
    ok = executor_service.pause_execution(run_id)
    if not ok:
        raise HTTPException(404, "Run not found or not pausable")
    _broadcast({"type": "intel_execution_update", "event": "paused", "run_id": run_id})
    return {"ok": True}


@router.post("/execution/{run_id}/resume")
def resume_execution(run_id: int, req: ExecutionStartRequest):
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

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id}


@router.post("/execution/{run_id}/cancel")
def cancel_execution(run_id: int):
    """Cancel a running execution."""
    ok = executor_service.cancel_execution(run_id)
    if not ok:
        raise HTTPException(404, "Run not found or not cancellable")
    _broadcast({"type": "intel_execution_update", "event": "cancelled", "run_id": run_id})
    return {"ok": True}


@router.post("/execution/{run_id}/retry/{unit_id}")
def retry_execution_unit(run_id: int, unit_id: str, req: RetryUnitRequest):
    """Retry a single failed execution unit."""

    result = executor_service.retry_unit(req.project_id, run_id, unit_id)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error", "Retry failed"))
    _broadcast({"type": "intel_execution_update", "project_id": req.project_id,
                 "event": "unit_retried", "payload": {"unit_id": unit_id, "result": result}})
    return result


@router.get("/execution/{run_id}/evidence")
def get_execution_evidence(run_id: int, unit_id: Optional[str] = None):
    """Get evidence collected during execution."""
    return store.get_evidence(run_id, unit_id)


@router.get("/execution/{run_id}/logs")
def get_execution_logs(run_id: int, limit: int = 100):
    """Get execution logs."""
    return store.get_execution_logs(run_id, limit)
