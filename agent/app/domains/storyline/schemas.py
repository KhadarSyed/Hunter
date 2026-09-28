"""Request/response models for the Storyline Builder route group."""
from __future__ import annotations

from pydantic import BaseModel

from ...core.api import ApiModel


class GenerateStorylineRequest(BaseModel):
    project_id: int
    reviewer: str = "system"


class ReviewNodeRequest(BaseModel):
    status: str
    reviewer: str = "analyst"


class ReorderRequest(BaseModel):
    node_ids: list[int]
    actor: str = "analyst"


class MergeRequest(BaseModel):
    node_id_a: int
    node_id_b: int
    actor: str = "analyst"


class SplitRequest(BaseModel):
    actor: str = "analyst"


class UpdateNodeRequest(BaseModel):
    title: str | None = None
    narrative_summary: str | None = None
    purpose: str | None = None
    suggested_visual: str | None = None
    priority: str | None = None
    is_key_message: bool | None = None
    is_locked: bool | None = None


class StorylineApprovalRequest(BaseModel):
    reviewer: str = "analyst"


class ValidateStorylinePrereqsRequest(BaseModel):
    project_id: int


# ─── Response models ─────────────────────────────────────────────────────────

class StorylineRecord(ApiModel):
    """An `intel_storylines` row."""

    id: int
    project_id: int | None = None
    narrative_pattern: str | None = None
    title: str | None = None
    executive_summary: str | None = None
    total_duration_minutes: float | None = None
    node_count: int | None = None
    status: str | None = None
    generated_by: str | None = None
    approved_by: str | None = None
    approved_at: float | None = None
    generation_id: str | None = None
    created_at: float | None = None
    updated_at: float | None = None


class StoryNodeRecord(ApiModel):
    """An `intel_story_nodes` row; `is_key_message` / `is_locked` are decoded to bool."""

    id: int
    storyline_id: int | None = None
    section_type: str | None = None
    title: str | None = None
    purpose: str | None = None
    narrative_summary: str | None = None
    suggested_visual: str | None = None
    priority: str | None = None
    estimated_duration_minutes: float | None = None
    confidence_score: float | None = None
    transition_text: str | None = None
    is_key_message: bool | None = None
    is_locked: bool | None = None
    order_position: int | None = None
    status: str | None = None
    reviewed_by: str | None = None
    reviewed_at: float | None = None
    created_at: float | None = None
    updated_at: float | None = None


class StoryNodeDetail(StoryNodeRecord):
    """A story node enriched with its mapped insights (see `get_node_insights`)."""

    insights: list[dict] = []
    insight_count: int = 0


class StorylineAuditEntry(ApiModel):
    """An `intel_storyline_audit` row."""

    id: int
    storyline_id: int | None = None
    node_id: int | None = None
    action: str | None = None
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    actor: str | None = None
    created_at: float | None = None


class StorylineGenerationResponse(ApiModel):
    storyline_id: int
    narrative_pattern: str | None = None
    nodes_created: int
    total_duration_minutes: float | int
    insights_used: int
    insights_unassigned: int
    generation_id: str | None = None


class StorylinePrereqsResponse(ApiModel):
    """Prerequisite check; `blockers` is not currently emitted but would pass through."""

    valid: bool


class StorylineDetailResponse(ApiModel):
    storyline: StorylineRecord
    nodes: list[StoryNodeDetail] = []
    audit_history: list[StorylineAuditEntry] = []


class StorylineValidationResponse(ApiModel):
    """Validation result; `issues` is present only when `valid` is false (passes through)."""

    valid: bool
    warnings: list[str] = []


class StorylineSummaryResponse(ApiModel):
    storyline_count: int
    latest_pattern: str | None = None
    latest_status: str | None = None
    total_nodes: int
    total_duration_minutes: float | int
    node_statuses: dict[str, int] = {}
    latest_storyline_id: int | None = None


class ReorderNodesResponse(ApiModel):
    reordered: bool
    locked_skipped: list[int] = []


class SplitNodeResponse(ApiModel):
    original_node: StoryNodeRecord | None = None
    new_node: StoryNodeRecord | None = None
