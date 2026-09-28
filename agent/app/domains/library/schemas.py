"""Request/response models for the Evidence Library route group."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from ...core.api import ApiModel


class IngestRequest(BaseModel):
    project_id: int
    run_id: int


class ReviewRequest(BaseModel):
    status: str
    reviewer: str = "analyst"
    note: Optional[str] = None


class AnnotateRequest(BaseModel):
    note: str
    author: str = "analyst"


class BulkReviewRequest(BaseModel):
    item_ids: list[int]
    status: str
    reviewer: str = "analyst"


class ClassifyRequest(BaseModel):
    objective_id: Optional[str] = None
    unit_id: Optional[str] = None
    confidence: Optional[str] = None
    reviewer: str = "analyst"


class RepresentativeRequest(BaseModel):
    is_representative: bool = True


class HighValueRequest(BaseModel):
    is_high_value: bool = True


# ─── Responses ─────────────────────────────────────────────────────────────

class IngestResult(ApiModel):
    ingested: int
    skipped: int
    duplicates_found: int
    total: int


class BulkReviewResult(ApiModel):
    updated: int


class AnnotationCreated(ApiModel):
    annotation_id: int | None = None


class LibraryItem(ApiModel):
    """Library item joined with its evidence row (_LIBRARY_JOIN_SELECT).

    Decoded `quality_components` / `metrics` blobs pass through when present."""

    id: int | None = None
    project_id: int | None = None
    evidence_id: int | None = None
    review_status: str | None = None
    quality_score: float | None = None
    quality_components_json: str | None = None
    relevance_score: float | None = None
    is_representative: int | None = None
    is_high_value: int | None = None
    canonical_id: int | None = None
    duplicate_group: str | None = None
    objective_id: str | None = None
    unit_id: str | None = None
    reviewed_by: str | None = None
    reviewed_at: float | None = None
    created_at: float | None = None
    updated_at: float | None = None
    run_id: int | None = None
    evidence_type: str | None = None
    platform: str | None = None
    source: str | None = None
    date: str | None = None
    text_excerpt: str | None = None
    metrics_json: str | None = None
    confidence: str | None = None
    method: str | None = None
    rationale: str | None = None
    dataset: str | None = None
    evidence_created_at: float | None = None


class LibraryAuditEntry(ApiModel):
    """Row of intel_library_audit (SELECT *)."""

    id: int | None = None
    library_item_id: int | None = None
    action: str | None = None
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    actor: str | None = None
    created_at: float | None = None


class LibraryAnnotation(ApiModel):
    """Row of intel_library_annotations (SELECT *)."""

    id: int | None = None
    library_item_id: int | None = None
    author: str | None = None
    note: str | None = None
    created_at: float | None = None


class EvidenceDetail(ApiModel):
    item: LibraryItem
    annotations: list[LibraryAnnotation] = []
    audit_history: list[LibraryAuditEntry] = []
    duplicate_group_members: list[LibraryItem] = []


class DuplicateGroup(ApiModel):
    group: str | None = None
    count: int | None = None
    canonical_id: int | None = None


class LibrarySummaryMetrics(ApiModel):
    total_items: int
    by_status: dict
    representative: int
    high_value: int
    duplicate_groups: int
    objective_coverage: dict


class CoverageReport(ApiModel):
    objectives: list[dict]
    summary: dict


class CoverageError(ApiModel):
    error: str
