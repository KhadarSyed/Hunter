"""Pipeline Orchestrator routes: cross-stage run control, caching, dependency graph."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from . import service as orchestrator
from .schemas import ClearCacheRequest, RetryStageRequest, StartPipelineRequest

router = APIRouter()


@router.post("/pipeline/start")
def start_pipeline_route(req: StartPipelineRequest):
    return orchestrator.start_pipeline(
        req.project_id, mode=req.mode,
        start_stage=req.start_stage,
        single_stage=req.single_stage,
        user=req.user,
    )


@router.post("/pipeline/{run_id}/pause")
def pause_pipeline_route(run_id: str):
    return orchestrator.pause_pipeline(run_id)


@router.post("/pipeline/{run_id}/resume")
def resume_pipeline_route(run_id: str):
    return orchestrator.resume_pipeline(run_id)


@router.post("/pipeline/{run_id}/cancel")
def cancel_pipeline_route(run_id: str):
    return orchestrator.cancel_pipeline(run_id)


@router.post("/pipeline/{run_id}/retry")
def retry_stage_route(run_id: str, req: RetryStageRequest):
    return orchestrator.retry_stage(run_id, req.stage_id)


@router.post("/pipeline/run-stage")
def run_single_stage_route(req: StartPipelineRequest):
    return orchestrator.run_single_stage(
        req.project_id, req.single_stage or req.start_stage or "brief_scope",
        user=req.user,
    )


@router.post("/pipeline/run-from")
def run_from_stage_route(req: StartPipelineRequest):
    return orchestrator.run_from_stage(
        req.project_id, req.start_stage or "brief_scope",
        user=req.user,
    )


@router.get("/pipeline/status/{run_id}")
def pipeline_status_route(run_id: str):
    result = orchestrator.get_pipeline_status(run_id)
    if not result:
        raise HTTPException(404, "Pipeline run not found")
    return result


@router.get("/pipeline/project/{project_id}")
def project_pipeline_status_route(project_id: int):
    return orchestrator.get_project_status(project_id)


@router.get("/pipeline/timeline/{run_id}")
def pipeline_timeline_route(run_id: str):
    return orchestrator.get_execution_timeline(run_id)


@router.get("/pipeline/logs/{run_id}")
def pipeline_logs_route(run_id: str, stage_id: Optional[str] = None):
    return orchestrator.get_pipeline_logs(run_id, stage_id)


@router.get("/pipeline/metrics/{project_id}")
def pipeline_metrics_route(project_id: int):
    return orchestrator.get_performance_metrics(project_id)


@router.get("/pipeline/cache/{project_id}")
def pipeline_cache_route(project_id: int):
    return orchestrator.get_cache_metrics(project_id)


@router.post("/pipeline/cache/{project_id}/clear")
def clear_pipeline_cache_route(project_id: int, req: ClearCacheRequest):
    if req.stage_id:
        count = orchestrator.clear_stage_cache(project_id, req.stage_id)
    else:
        count = orchestrator.clear_project_cache(project_id)
    return {"cleared": count}


@router.get("/pipeline/graph")
def dependency_graph_route():
    return orchestrator.get_dependency_graph()


@router.get("/pipeline/stages/{project_id}")
def project_stages_route(project_id: int):
    return orchestrator.get_project_stage_statuses(project_id)
