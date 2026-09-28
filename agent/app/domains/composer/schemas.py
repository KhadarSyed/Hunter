"""Request/response models for the Presentation Composer route group.

GeneratePresentationRequest is also used by the SOV/Theme Archetype endpoints in
composer/router.py.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from ...core.api import ApiModel

Number = int | float


class GeneratePresentationRequest(BaseModel):
    project_id: int
    reviewer: str = "system"


class UpdatePCSlideRequest(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    narrative: Optional[str] = None
    key_message: Optional[str] = None
    recommended_visual: Optional[str] = None
    recommended_chart: Optional[str] = None
    layout_recommendation: Optional[str] = None
    speaker_notes: Optional[str] = None
    slide_purpose: Optional[str] = None


class ReorderPCSlidesRequest(BaseModel):
    slide_ids: list[int]


class SelectLayoutRequest(BaseModel):
    layout: str
    rationale: str = ""


class SelectVisualRequest(BaseModel):
    visual: str


class ReviewPCSlideRequest(BaseModel):
    status: str
    reviewer: str = "analyst"


class ApprovePCRequest(BaseModel):
    reviewer: str = "analyst"


# ─── Responses ───────────────────────────────────────────────────────────

class PCPresentation(ApiModel):
    """Row of intel_pc_presentations."""
    id: int
    project_id: int
    storyline_id: int
    title: str
    executive_summary: str | None = None
    narrative_pattern: str | None = None
    total_slides: int | None = None
    estimated_duration_minutes: Number | None = None
    status: str
    generated_by: str | None = None
    approved_by: str | None = None
    approved_at: float | None = None
    generation_id: str | None = None
    created_at: float
    updated_at: float


class PCSlide(ApiModel):
    """Row of intel_pc_slides; *_json columns are decoded when valid JSON."""
    id: int
    presentation_id: int
    slide_number: int
    slide_purpose: str
    title: str
    subtitle: str | None = None
    narrative: str | None = None
    business_objective: str | None = None
    key_message: str | None = None
    speaker_notes: str | None = None
    recommended_visual: str | None = None
    recommended_chart: str | None = None
    layout_recommendation: str | None = None
    layout_rationale: str | None = None
    content_blocks_json: Any = None
    evidence_ids_json: Any = None
    insight_ids_json: Any = None
    historical_refs_json: Any = None
    confidence_json: Any = None
    overall_confidence: Number | None = None
    transition_to_next: str | None = None
    status: str
    is_locked: int | None = None
    reviewed_by: str | None = None
    reviewed_at: float | None = None
    created_at: float
    updated_at: float


class PCAuditEntry(ApiModel):
    """Row of intel_pc_audit."""
    id: int
    presentation_id: int
    slide_id: int | None = None
    action: str
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    actor: str | None = None
    created_at: float


class GeneratePresentationResponse(ApiModel):
    presentation_id: int
    storyline_id: int
    slides_created: int
    estimated_duration_minutes: Number
    generation_id: str


class GenerateSOVPresentationResponse(GeneratePresentationResponse):
    entities_analyzed: int


class PrerequisiteCheckResponse(ApiModel):
    valid: bool


class SOVAnalysisResponse(ApiModel):
    entities: list[dict]
    total_qualifying_records: int
    trend: dict
    date_range: dict
    dataset_source: str
    context_label: str
    narratives: dict


class ThemeClassificationResponse(ApiModel):
    entity: str
    total_records: int
    classification_method: str
    themes: list[dict]
    executive_takeaway: Any = None
    date_range: Any = None
    dataset_source: Any = None
    context_label: Any = None
    sample_based: bool


class PresentationSummaryResponse(ApiModel):
    presentation_count: int
    latest_status: str | None = None
    total_slides: int
    total_duration_minutes: Number
    slide_statuses: dict[str, int]
    latest_presentation_id: int | None = None
    latest_storyline_id: int | None = None


class PresentationDetailResponse(ApiModel):
    presentation: PCPresentation
    slides: list[PCSlide]
    audit_history: list[PCAuditEntry]
    total_duration_minutes: Number
    flow_analysis: Any = None


class ReorderSlidesResponse(ApiModel):
    reordered: bool
    locked_skipped: list[int]


class PresentationValidationResponse(ApiModel):
    """`issues` is present only when valid is False (passes through as an extra key)."""
    valid: bool
    warnings: list[str]


class TransitionsResponse(ApiModel):
    transitions_updated: int
