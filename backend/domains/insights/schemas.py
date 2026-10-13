"""Request/response models for the Insight Generator route group.

Note: RevisionRequest here is a distinct class from research/schemas.py's RevisionRequest
(different fields). insights/router.py imports this one as InsightRevisionRequest.
"""
from __future__ import annotations

from pydantic import BaseModel

from ...core.api import ApiModel


class GenerateInsightsRequest(BaseModel):
    project_id: int


class ReviewInsightRequest(BaseModel):
    status: str
    reviewer: str = "analyst"
    notes: str | None = None


class RevisionRequest(BaseModel):
    notes: str = ""     # optional guidance
    reviewer: str = "analyst"


class NotesRequest(BaseModel):
    notes: str
    reviewer: str = "analyst"


class ValidatePrereqsRequest(BaseModel):
    project_id: int


# ─── Response models ─────────────────────────────────────────────────────────

class InsightRecord(ApiModel):
    """An `intel_insights` row; `platforms_represented` is JSON-decoded when it parses."""

    id: int
    project_id: int | None = None
    objective_id: str | None = None
    insight_type: str | None = None
    title: str | None = None
    executive_summary: str | None = None
    observation: str | None = None
    interpretation: str | None = None
    business_impact: str | None = None
    confidence_score: float | None = None
    confidence_rationale: str | None = None
    evidence_count: int | None = None
    platforms_represented: list | str | None = None
    date_coverage: str | None = None
    contradictory_evidence: str | None = None
    limitations: str | None = None
    recommended_visualisation: str | None = None
    analyst_notes: str | None = None
    status: str | None = None
    reviewed_by: str | None = None
    reviewed_at: float | None = None
    generation_id: str | None = None
    created_at: float | None = None
    updated_at: float | None = None


class InsightEvidenceItem(ApiModel):
    """Insight↔library-item mapping joined with the library item and its evidence row.

    `quality_components` / `metrics` (decoded JSON) are added only when the source column
    is set, so they are left undeclared and pass through as extras.
    """

    mapping_id: int
    insight_id: int | None = None
    library_item_id: int | None = None
    role: str | None = None
    mapping_created_at: float | None = None
    li_id: int | None = None
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


class InsightAuditEntry(ApiModel):
    """An `intel_insight_audit` row."""

    id: int
    insight_id: int | None = None
    action: str | None = None
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    actor: str | None = None
    created_at: float | None = None


class InsightGenerationResponse(ApiModel):
    generated: int
    objectives_covered: int
    objectives_skipped: int
    generation_id: str


class InsightPrereqsResponse(ApiModel):
    """Prerequisite check; `blockers` is not currently emitted but would pass through."""

    valid: bool


class InsightDetailResponse(ApiModel):
    insight: InsightRecord
    evidence: list[InsightEvidenceItem] = []
    supporting_evidence: list[InsightEvidenceItem] = []
    contradictory_evidence: list[InsightEvidenceItem] = []
    audit_history: list[InsightAuditEntry] = []


class InsightQualityResponse(ApiModel):
    """Quality check; `issues` is present only when `valid` is false (passes through)."""

    valid: bool
    warnings: list[str] = []


class InsightsSummaryResponse(ApiModel):
    total_insights: int
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    avg_confidence: float
    total_evidence_mapped: int
    objectives_covered: int
