"""Analysis & Insights routes: generate, review, revise, regenerate."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core import store
from . import service as igen
from .schemas import (
    GenerateInsightsRequest,
    NotesRequest,
    ReviewInsightRequest,
    ValidatePrereqsRequest,
)
from .schemas import (
    RevisionRequest as InsightRevisionRequest,
)

router = APIRouter()


@router.post("/insights/generate")
def generate_insights(req: GenerateInsightsRequest):
    result = igen.generate_insights(req.project_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/validate-prereqs")
def validate_insight_prereqs(req: ValidatePrereqsRequest):
    return igen.validate_prerequisites(req.project_id)


@router.get("/insights/detail/{insight_id}")
def get_insight_detail(insight_id: int):
    result = igen.get_insight_detail(insight_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/insights/{insight_id}/validate")
def validate_insight_quality(insight_id: int):
    return igen.validate_insight_quality(insight_id)


@router.get("/insights/{insight_id}/evidence")
def get_insight_evidence(insight_id: int):
    return igen.get_supporting_evidence(insight_id)


@router.get("/insights/{project_id}")
def list_insights(
    project_id: int,
    objective_id: str | None = None,
    insight_type: str | None = None,
    status: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
):
    return store.list_insights(
        project_id,
        objective_id=objective_id,
        insight_type=insight_type,
        status=status,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )


@router.get("/insights/{project_id}/summary")
def get_insights_summary(project_id: int):
    return igen.get_insights_summary(project_id)


@router.post("/insights/{insight_id}/review")
def review_insight(insight_id: int, req: ReviewInsightRequest):
    result = igen.review_insight(insight_id, req.status, reviewer=req.reviewer, notes=req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/{insight_id}/revision")
def request_insight_revision(insight_id: int, req: InsightRevisionRequest):
    result = igen.request_revision(insight_id, req.notes, reviewer=req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/{insight_id}/notes")
def update_insight_notes(insight_id: int, req: NotesRequest):
    result = igen.update_analyst_notes(insight_id, req.notes, reviewer=req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/{insight_id}/regenerate")
def regenerate_insight(insight_id: int):
    result = igen.regenerate_insight(insight_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result
