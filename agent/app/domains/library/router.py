"""Evidence library routes: ingest, review, classify, annotate, restore."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from ...core import store
from . import service as elib
from .schemas import (
    AnnotateRequest,
    BulkReviewRequest,
    ClassifyRequest,
    HighValueRequest,
    IngestRequest,
    RepresentativeRequest,
    ReviewRequest,
)

router = APIRouter()


@router.post("/library/ingest")
def ingest_library_evidence(req: IngestRequest):
    return elib.ingest_evidence(req.project_id, req.run_id)


@router.post("/library/bulk-review")
def bulk_review_library(req: BulkReviewRequest):
    result = elib.bulk_review(req.item_ids, req.status, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/library/detail/{item_id}")
def get_library_detail(item_id: int):
    result = elib.get_evidence_detail(item_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/library/audit/{item_id}")
def get_library_audit(item_id: int):
    return store.get_library_audit(item_id)


@router.get("/library/{project_id}")
def list_library(
    project_id: int,
    review_status: Optional[str] = None,
    objective_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    method: Optional[str] = None,
    platform: Optional[str] = None,
    confidence: Optional[str] = None,
    is_representative: Optional[bool] = None,
    is_high_value: Optional[bool] = None,
    search: Optional[str] = None,
    sort_by: str = "quality_score",
    sort_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
):
    return elib.search_evidence(
        project_id,
        query=search,
        review_status=review_status,
        objective_id=objective_id,
        unit_id=unit_id,
        method=method,
        platform=platform,
        confidence=confidence,
        is_representative=is_representative,
        is_high_value=is_high_value,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )


@router.get("/library/{project_id}/summary")
def get_library_summary(project_id: int):
    return elib.get_summary_metrics(project_id)


@router.get("/library/{project_id}/coverage")
def get_library_coverage(project_id: int):
    return elib.get_coverage_report(project_id)


@router.get("/library/{project_id}/duplicates")
def get_library_duplicates(project_id: int):
    return store.get_duplicate_groups(project_id)


@router.post("/library/{item_id}/review")
def review_library_item(item_id: int, req: ReviewRequest):
    result = elib.review_evidence(item_id, req.status, req.reviewer, req.note)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/library/{item_id}/annotate")
def annotate_library_item(item_id: int, req: AnnotateRequest):
    ann_id = elib.add_annotation(item_id, req.note, req.author)
    return {"annotation_id": ann_id}


@router.post("/library/{item_id}/classify")
def classify_library_item(item_id: int, req: ClassifyRequest):
    result = elib.update_classification(
        item_id, objective_id=req.objective_id, unit_id=req.unit_id,
        confidence=req.confidence, reviewer=req.reviewer,
    )
    if isinstance(result, dict) and result.get("success") is False:
        raise HTTPException(404, result.get("error", "Not found"))
    return {"ok": True}


@router.post("/library/{item_id}/representative")
def mark_library_representative(item_id: int, req: RepresentativeRequest):
    result = elib.mark_representative(item_id, req.is_representative)
    if isinstance(result, dict) and result.get("success") is False:
        raise HTTPException(404, result.get("error", "Not found"))
    return {"ok": True}


@router.post("/library/{item_id}/high-value")
def mark_library_high_value(item_id: int, req: HighValueRequest):
    result = elib.mark_high_value(item_id, req.is_high_value)
    if isinstance(result, dict) and result.get("success") is False:
        raise HTTPException(404, result.get("error", "Not found"))
    return {"ok": True}


@router.post("/library/{item_id}/restore")
def restore_library_item(item_id: int):
    result = elib.restore_rejected(item_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result
