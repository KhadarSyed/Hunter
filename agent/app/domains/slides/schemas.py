"""Request/response models for the Slide Intelligence route group."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ...core.api import ApiModel


class IngestPresentationRequest(BaseModel):
    file_path: str


class UpdateSlideMetadataRequest(BaseModel):
    slide_purpose: Optional[str] = None
    layout_type: Optional[str] = None
    visual_type: Optional[str] = None
    narrative_role: Optional[str] = None
    report_type: Optional[str] = None
    industry: Optional[str] = None
    client: Optional[str] = None
    brand: Optional[str] = None
    data_density: Optional[str] = None
    executive_suitability: Optional[str] = None
    visual_complexity: Optional[str] = None


class SlideSearchRequest(BaseModel):
    query: str
    slide_purpose: Optional[str] = None
    layout_type: Optional[str] = None
    visual_type: Optional[str] = None
    client: Optional[str] = None
    report_type: Optional[str] = None
    limit: int = Field(50, ge=1, le=5000)


class RetrieveRequest(BaseModel):
    node_id: int
    top_k: int = Field(10, ge=1, le=100)


class MatchStorylineRequest(BaseModel):
    storyline_id: int


# ─── Response models ─────────────────────────────────────────────────────────

class PresentationRecord(ApiModel):
    """An `intel_si_presentations` row."""

    id: int
    filename: str | None = None
    file_path: str | None = None
    file_size: int | None = None
    file_hash: str | None = None
    slide_count: int | None = None
    processed_count: int | None = None
    status: str | None = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    created_at: float | None = None


class SlideRecord(ApiModel):
    """An `intel_si_slides` row; `has_*`, `is_excluded`, `is_template_approved` decoded to bool.

    Count columns, text blobs and `thumbnail_b64` pass through undeclared.
    """

    id: int
    presentation_id: int | None = None
    slide_number: int | None = None
    title_text: str | None = None
    has_chart: bool | None = None
    has_table: bool | None = None
    has_image: bool | None = None
    slide_purpose: str | None = None
    layout_type: str | None = None
    visual_type: str | None = None
    narrative_role: str | None = None
    report_type: str | None = None
    industry: str | None = None
    client: str | None = None
    brand: str | None = None
    classification_confidence: float | None = None
    is_excluded: bool | None = None
    is_template_approved: bool | None = None
    status: str | None = None
    processed_at: float | None = None
    created_at: float | None = None


class IngestPresentationResponse(ApiModel):
    presentation_id: int
    filename: str | None = None
    total_slides: int | None = None
    processed: int | None = None
    failed: int | None = None
    projects_detected: int | None = None
    status: str | None = None


class SlideIntelDashboardResponse(ApiModel):
    presentation_count: int
    total_slides: int
    processed_slides: int
    excluded_slides: int
    template_families: int
    detected_projects: int
    duplicate_count: int
    purpose_distribution: dict[str, int] = {}
    layout_distribution: dict[str, int] = {}
    client_distribution: dict[str, int] = {}


class DetectedProjectRecord(ApiModel):
    """An `intel_si_detected_projects` row."""

    id: int
    presentation_id: int | None = None
    project_name: str | None = None
    client_name: str | None = None
    brand_name: str | None = None
    analyst_name: str | None = None
    start_slide: int | None = None
    end_slide: int | None = None
    slide_count: int | None = None
    confidence: float | None = None
    is_confirmed: int | None = None
    created_at: float | None = None


class ProcessingLogEntry(ApiModel):
    """An `intel_si_processing_logs` row."""

    id: int
    presentation_id: int | None = None
    step: str | None = None
    slide_number: int | None = None
    status: str | None = None
    message: str | None = None
    duration_ms: float | None = None
    created_at: float | None = None


class PresentationStatusResponse(ApiModel):
    presentation: PresentationRecord
    purpose_distribution: dict[str, int] = {}
    layout_distribution: dict[str, int] = {}
    detected_projects: list[DetectedProjectRecord] = []
    recent_logs: list[ProcessingLogEntry] = []


class SlideCorrectionEntry(ApiModel):
    """An `intel_si_corrections` row."""

    id: int
    slide_id: int | None = None
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    corrected_by: str | None = None
    created_at: float | None = None


class StorylineMatchRecord(ApiModel):
    """An `intel_si_storyline_matches` row joined with slide columns; JSON lists decoded."""

    id: int
    storyline_id: int | None = None
    node_id: int | None = None
    slide_id: int | None = None
    similarity_score: float | None = None
    match_reason: str | None = None
    recommended_elements: list | str | None = None
    elements_not_to_reuse: list | str | None = None
    recommended_layout: str | None = None
    recommended_visual: str | None = None
    recommended_chart: str | None = None
    confidence: float | None = None
    is_accepted: bool | None = None
    created_at: float | None = None
    slide_number: int | None = None
    title_text: str | None = None
    slide_purpose: str | None = None
    layout_type: str | None = None
    visual_type: str | None = None
    client: str | None = None
    presentation_id: int | None = None


class SlideDetailResponse(ApiModel):
    slide: SlideRecord
    corrections: list[SlideCorrectionEntry] = []
    storyline_matches: list[StorylineMatchRecord] = []


class SlideMetadataUpdateResponse(ApiModel):
    slide_id: int
    fields_updated: list[str] = []


class SlideExclusionResponse(ApiModel):
    slide_id: int
    is_excluded: bool


class SlideReprocessResponse(ApiModel):
    slide_id: int
    status: str


class TemplateFamilyRecord(ApiModel):
    """An `intel_si_template_families` row; `required_inputs` JSON-decoded when set."""

    id: int
    family_name: str | None = None
    typical_layout: str | None = None
    typical_visual: str | None = None
    typical_purpose: str | None = None
    required_inputs: list | str | None = None
    recommended_usage: str | None = None
    member_count: int | None = None
    is_approved: bool | None = None
    created_at: float | None = None
    updated_at: float | None = None


class TemplateMemberRecord(ApiModel):
    """An `intel_si_template_members` row joined with slide columns."""

    id: int
    family_id: int | None = None
    slide_id: int | None = None
    is_representative: int | None = None
    similarity_score: float | None = None
    created_at: float | None = None
    slide_number: int | None = None
    title_text: str | None = None
    slide_purpose: str | None = None
    layout_type: str | None = None
    presentation_id: int | None = None


class TemplateDetailResponse(ApiModel):
    family: TemplateFamilyRecord
    members: list[TemplateMemberRecord] = []


class TemplateApprovalResponse(ApiModel):
    family_id: int
    is_approved: bool


class StylePatternRecord(ApiModel):
    """An `intel_si_style_patterns` row; `pattern_data` / `source_slides` JSON-decoded."""

    id: int
    presentation_id: int | None = None
    pattern_type: str | None = None
    pattern_name: str | None = None
    pattern_data: dict | list | str | None = None
    frequency: int | None = None
    source_slides: list | dict | str | None = None
    created_at: float | None = None


class SlideSearchResponse(ApiModel):
    query: str
    results: list[SlideRecord] = []
    count: int


class RetrievedSlide(ApiModel):
    """One scored slide from `retrieval.retrieve_for_node`."""

    slide_id: int
    slide_number: int | None = None
    presentation_id: int | None = None
    title_text: str | None = None
    slide_purpose: str | None = None
    layout_type: str | None = None
    visual_type: str | None = None
    client: str | None = None
    similarity_score: float | None = None
    match_reason: str | None = None
    recommended_elements: list | None = None
    elements_not_to_reuse: list | None = None
    confidence: float | None = None


class SlideRetrievalResponse(ApiModel):
    """Slides retrieved for a node; `section_type` / `message` vary by branch (pass through)."""

    node_id: int
    results: list[RetrievedSlide] = []


class StorylineMatchRunResponse(ApiModel):
    """`node_results` items are either per-node match counts or per-node errors."""

    storyline_id: int
    total_nodes: int
    total_matches: int
    node_results: list[dict] = []


class NodeMatchGroup(ApiModel):
    node_id: int
    section_type: str | None = None
    title: str | None = None
    matches: list[StorylineMatchRecord] = []


class StorylineMatchesResponse(ApiModel):
    storyline_id: int
    total_matches: int
    nodes: list[NodeMatchGroup] = []


class NodeRecommendationResponse(ApiModel):
    node_id: int
    section_type: str | None = None
    best_layout: str | None = None
    best_visual: str | None = None
    best_chart: str | None = None
    best_content_hierarchy: list[str] = []
    best_callout_style: str | None = None
    best_evidence_placement: str | None = None
    best_title_style: str | None = None
    historical_slides: list[RetrievedSlide] = []
    alternative_layouts: list[str] = []


class DuplicateGroup(ApiModel):
    slide_ids: list[int] = []
    count: int
    sample_text: str | None = None


class DuplicateDetectionResponse(ApiModel):
    duplicate_groups: list[DuplicateGroup] = []
    total_groups: int
    total_duplicate_slides: int
