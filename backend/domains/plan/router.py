"""Research plan routes: generate, approve, reject, regenerate, validate."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from ...core import store
from ...core.api import OkResponse
from ...core.auth import require_project_access
from ...core.events import broadcast as _broadcast
from ...core.jobs import submit
from ..strategy.schemas import GenerateStrategyRequest
from . import service as planner_service
from .schemas import (
    PlanApproveRequest,
    PlanBlocked,
    PlanJobStarted,
    PlanPrerequisitesResponse,
    PlanRegenerateRequest,
    PlanRejectRequest,
    ResearchPlanRecord,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/plan/generate", response_model=PlanJobStarted | PlanBlocked)
def generate_research_plan(req: GenerateStrategyRequest):
    """Generate a Research Plan for the given project."""

    project = store.get_project(req.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    prereqs = planner_service.validate_prerequisites(req.project_id)
    if not prereqs["ready"]:
        return {
            "status": "blocked",
            "error": "Prerequisites not met",
            "prerequisites": prereqs["prerequisites"],
        }

    job_id = f"plan_{uuid.uuid4().hex[:12]}"
    store.create_job(job_id, req.project_id, "research_plan")

    def worker():
        logger.info("[plan:%s] Starting plan generation for project %s", job_id, req.project_id)
        store.update_job(job_id, status="running", progress_pct=10,
                         progress_message="Validating prerequisites")
        _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                     "progress_pct": 10, "message": "Validating prerequisites"})

        try:
            def emit(event_type, payload):
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                             "progress_pct": 50, "message": str(payload.get("status", event_type))})

            result = planner_service.generate_plan(req.project_id, emit=emit)

            if result.get("status") == "completed":
                store.update_job(job_id, status="completed", progress_pct=100,
                                 progress_message="Research plan generated",
                                 result={"plan_id": result["plan_id"], "project_id": req.project_id})
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "completed",
                             "progress_pct": 100, "message": "Research plan generated"})
            else:
                error = result.get("error", "Plan generation failed")
                store.update_job(job_id, status="failed", error=error)
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed",
                             "error": error})

        except Exception as e:
            logger.error("[plan:%s] Unhandled error: %s", job_id, e, exc_info=True)
            store.update_job(job_id, status="failed", error=str(e))
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed", "error": str(e)})

    submit(worker, name="plan:generate")
    return {"job_id": job_id, "project_id": req.project_id}


@router.get("/plan/{project_id}", response_model=ResearchPlanRecord)
def get_research_plan(project_id: Annotated[int, Path(ge=1)],
                       _access: Annotated[dict, Depends(require_project_access)]):
    """Get the latest Research Plan for a project."""
    plan = store.get_latest_plan(project_id)
    if not plan:
        raise HTTPException(404, "No research plan found for this project")
    return plan


@router.post("/plan/{plan_id}/approve", response_model=OkResponse)
def approve_research_plan(plan_id: Annotated[int, Path(ge=1)], req: PlanApproveRequest):
    """Approve a Research Plan."""
    ok = store.approve_plan(plan_id, req.reviewer)
    if not ok:
        raise HTTPException(404, "Plan not found")
    _broadcast({"type": "intel_plan_approved", "plan_id": plan_id})
    return {"ok": True}


@router.post("/plan/{plan_id}/reject", response_model=OkResponse)
def reject_research_plan(plan_id: Annotated[int, Path(ge=1)], req: PlanRejectRequest):
    """Reject a Research Plan."""
    ok = store.reject_plan(plan_id, req.notes)
    if not ok:
        raise HTTPException(404, "Plan not found")
    return {"ok": True}


@router.post("/plan/regenerate", response_model=PlanJobStarted | PlanBlocked)
def regenerate_research_plan(req: PlanRegenerateRequest):
    """Regenerate a plan — same as generate but implies a prior plan exists."""
    return generate_research_plan(GenerateStrategyRequest(project_id=req.project_id))


@router.post("/plan/validate", response_model=PlanPrerequisitesResponse)
def validate_plan_prerequisites(req: GenerateStrategyRequest):
    """Check whether prerequisites are met for plan generation."""
    return planner_service.validate_prerequisites(req.project_id)
