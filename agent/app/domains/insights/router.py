"""Analysis & Insights routes: generate, review, revise, regenerate."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from ...core import store
from . import service as igen
from .schemas import (
    GenerateInsightsRequest,
    InsightDetailResponse,
    InsightEvidenceItem,
    InsightGenerationResponse,
    InsightPrereqsResponse,
    InsightQualityResponse,
    InsightRecord,
    InsightsSummaryResponse,
    NotesRequest,
    ReviewInsightRequest,
    ValidatePrereqsRequest,
)
from .schemas import (
    RevisionRequest as InsightRevisionRequest,
)

router = APIRouter()

IdPath = Annotated[int, Path(ge=1)]


@router.post("/insights/generate", response_model=InsightGenerationResponse)
def generate_insights(req: GenerateInsightsRequest):
    result = igen.generate_insights(req.project_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/validate-prereqs", response_model=InsightPrereqsResponse)
def validate_insight_prereqs(req: ValidatePrereqsRequest):
    return igen.validate_prerequisites(req.project_id)


@router.get("/insights/detail/{insight_id}", response_model=InsightDetailResponse)
def get_insight_detail(insight_id: IdPath):
    result = igen.get_insight_detail(insight_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/insights/{insight_id}/validate", response_model=InsightQualityResponse)
def validate_insight_quality(insight_id: IdPath):
    return igen.validate_insight_quality(insight_id)


@router.get("/insights/{insight_id}/evidence", response_model=list[InsightEvidenceItem])
def get_insight_evidence(insight_id: IdPath):
    return igen.get_supporting_evidence(insight_id)


@router.get("/insights/{project_id}", response_model=list[InsightRecord])
def list_insights(
    project_id: IdPath,
    objective_id: str | None = None,
    insight_type: str | None = None,
    status: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: Annotated[int, Query(ge=1, le=100000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
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


@router.get("/insights/{project_id}/summary", response_model=InsightsSummaryResponse)
def get_insights_summary(project_id: IdPath):
    return igen.get_insights_summary(project_id)


@router.post("/insights/{insight_id}/review", response_model=InsightRecord)
def review_insight(insight_id: IdPath, req: ReviewInsightRequest):
    result = igen.review_insight(insight_id, req.status, reviewer=req.reviewer, notes=req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/{insight_id}/revision", response_model=InsightRecord)
def request_insight_revision(insight_id: IdPath, req: InsightRevisionRequest):
    result = igen.request_revision(insight_id, req.notes, reviewer=req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/{insight_id}/notes", response_model=InsightRecord)
def update_insight_notes(insight_id: IdPath, req: NotesRequest):
    result = igen.update_analyst_notes(insight_id, req.notes, reviewer=req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/{insight_id}/regenerate", response_model=InsightRecord)
def regenerate_insight(insight_id: IdPath):
    result = igen.regenerate_insight(insight_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result
