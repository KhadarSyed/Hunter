"""Evidence library routes: ingest, review, classify, annotate, restore."""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Path, Query

from ...core import store
from ...core.api import OkResponse
from . import service as elib
from .schemas import (
    AnnotateRequest,
    AnnotationCreated,
    BulkReviewRequest,
    BulkReviewResult,
    ClassifyRequest,
    CoverageError,
    CoverageReport,
    DuplicateGroup,
    EvidenceDetail,
    HighValueRequest,
    IngestRequest,
    IngestResult,
    LibraryAuditEntry,
    LibraryItem,
    LibrarySummaryMetrics,
    RepresentativeRequest,
    ReviewRequest,
)

router = APIRouter()


@router.post("/library/ingest", response_model=IngestResult)
def ingest_library_evidence(req: IngestRequest):
    return elib.ingest_evidence(req.project_id, req.run_id)


@router.post("/library/bulk-review", response_model=BulkReviewResult)
def bulk_review_library(req: BulkReviewRequest):
    result = elib.bulk_review(req.item_ids, req.status, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/library/detail/{item_id}", response_model=EvidenceDetail)
def get_library_detail(item_id: Annotated[int, Path(ge=1)]):
    result = elib.get_evidence_detail(item_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/library/audit/{item_id}", response_model=list[LibraryAuditEntry])
def get_library_audit(item_id: Annotated[int, Path(ge=1)]):
    return store.get_library_audit(item_id)


@router.get("/library/{project_id}", response_model=list[LibraryItem])
def list_library(
    project_id: Annotated[int, Path(ge=1)],
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
    limit: Annotated[int, Query(ge=1, le=10000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
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


@router.get("/library/{project_id}/summary", response_model=LibrarySummaryMetrics)
def get_library_summary(project_id: Annotated[int, Path(ge=1)]):
    return elib.get_summary_metrics(project_id)


@router.get("/library/{project_id}/coverage", response_model=CoverageReport | CoverageError)
def get_library_coverage(project_id: Annotated[int, Path(ge=1)]):
    return elib.get_coverage_report(project_id)


@router.get("/library/{project_id}/duplicates", response_model=list[DuplicateGroup])
def get_library_duplicates(project_id: Annotated[int, Path(ge=1)]):
    return store.get_duplicate_groups(project_id)


@router.post("/library/{item_id}/review", response_model=LibraryItem)
def review_library_item(item_id: Annotated[int, Path(ge=1)], req: ReviewRequest):
    result = elib.review_evidence(item_id, req.status, req.reviewer, req.note)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/library/{item_id}/annotate", response_model=AnnotationCreated)
def annotate_library_item(item_id: Annotated[int, Path(ge=1)], req: AnnotateRequest):
    ann_id = elib.add_annotation(item_id, req.note, req.author)
    return {"annotation_id": ann_id}


@router.post("/library/{item_id}/classify", response_model=OkResponse)
def classify_library_item(item_id: Annotated[int, Path(ge=1)], req: ClassifyRequest):
    result = elib.update_classification(
        item_id, objective_id=req.objective_id, unit_id=req.unit_id,
        confidence=req.confidence, reviewer=req.reviewer,
    )
    if isinstance(result, dict) and result.get("success") is False:
        raise HTTPException(404, result.get("error", "Not found"))
    return {"ok": True}


@router.post("/library/{item_id}/representative", response_model=OkResponse)
def mark_library_representative(item_id: Annotated[int, Path(ge=1)], req: RepresentativeRequest):
    result = elib.mark_representative(item_id, req.is_representative)
    if isinstance(result, dict) and result.get("success") is False:
        raise HTTPException(404, result.get("error", "Not found"))
    return {"ok": True}


@router.post("/library/{item_id}/high-value", response_model=OkResponse)
def mark_library_high_value(item_id: Annotated[int, Path(ge=1)], req: HighValueRequest):
    result = elib.mark_high_value(item_id, req.is_high_value)
    if isinstance(result, dict) and result.get("success") is False:
        raise HTTPException(404, result.get("error", "Not found"))
    return {"ok": True}


@router.post("/library/{item_id}/restore", response_model=LibraryItem)
def restore_library_item(item_id: Annotated[int, Path(ge=1)]):
    result = elib.restore_rejected(item_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result
