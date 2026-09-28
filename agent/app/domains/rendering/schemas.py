"""Request/response models for the PowerPoint Renderer route group.

Also contains:
- word_renderer: Request/response models for the Word Report Renderer route group.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ...core.api import ApiModel

Number = int | float


class RenderPresentationRequest(BaseModel):
    presentation_id: int
    theme_id: str = "hunter_default"
    actor: str = "system"


class RenderSlideRequest(BaseModel):
    theme_id: str = "hunter_default"
    actor: str = "system"


class RenderSectionRequest(BaseModel):
    purpose: str
    theme_id: str = "hunter_default"
    actor: str = "system"


# ─── Word Renderer ─────────────────────────────────────────────────────

class RenderWordReportRequest(BaseModel):
    presentation_id: int
    theme_id: str = "hunter_default"
    actor: str = "system"


class RenderWordSectionRequest(BaseModel):
    section_name: str
    theme_id: str = "hunter_default"
    actor: str = "system"


# ─── Responses ───────────────────────────────────────────────────────────

class RenderJob(ApiModel):
    """Row of intel_render_jobs; *_json columns are decoded when valid JSON."""
    id: str
    presentation_id: int
    job_type: str
    status: str
    progress_pct: Number | None = None
    progress_message: str | None = None
    slide_ids_json: Any = None
    theme_id: str | None = None
    output_path: str | None = None
    output_size_bytes: int | None = None
    warnings_json: Any = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    created_at: float


class RenderPresentationResponse(ApiModel):
    job_id: str
    status: str
    output_path: str
    file_size_bytes: int
    slide_count: int
    render_duration_ms: int
    warnings: list
    version: int
    rendered_presentation_id: int


class RenderSlideResponse(ApiModel):
    job_id: str
    status: str
    output_path: str
    file_size_bytes: int
    render_duration_ms: int


class RenderSectionResponse(RenderSlideResponse):
    slide_count: int
    warnings: list


class Theme(ApiModel):
    """Row of intel_themes; color_palette_json is decoded when valid JSON."""
    id: str
    name: str
    description: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    accent_color: str | None = None
    background_color: str | None = None
    text_color: str | None = None
    font_heading: str | None = None
    font_body: str | None = None
    color_palette_json: Any = None
    is_default: int | None = None
    is_active: int | None = None
    created_at: float
    updated_at: float


class RenderValidationResponse(ApiModel):
    valid: bool
    issues: list[str]
    warnings: list[str]


class RenderSummaryResponse(ApiModel):
    total_renders: int
    total_jobs: int
    latest_job: RenderJob | None = None
    latest_render: dict | None = None
    has_download: bool
    history_count: int


class RenderHistoryEntry(ApiModel):
    """Row of intel_render_history / intel_word_history."""
    id: int
    presentation_id: int
    job_id: str
    action: str
    actor: str | None = None
    details_json: Any = None
    created_at: float


class RenderMetric(ApiModel):
    """Row of intel_render_metrics."""
    id: int
    job_id: str
    slide_id: int
    slide_number: int
    render_type: str
    duration_ms: Number | None = None
    warnings_json: Any = None
    created_at: float


class WordJob(ApiModel):
    """Row of intel_word_jobs; *_json columns are decoded when valid JSON."""
    id: str
    presentation_id: int
    job_type: str
    status: str
    progress_pct: Number | None = None
    progress_message: str | None = None
    sections_json: Any = None
    theme_id: str | None = None
    output_path: str | None = None
    output_size_bytes: int | None = None
    warnings_json: Any = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    created_at: float


class RenderWordReportResponse(ApiModel):
    job_id: str
    status: str
    output_path: str
    file_size_bytes: int
    section_count: int
    word_count: int
    render_duration_ms: int
    warnings: list
    version: int
    document_id: int


class RenderWordSectionResponse(ApiModel):
    job_id: str
    status: str
    section: str
    output_path: str
    file_size_bytes: int
    render_duration_ms: int


class WordRenderSummaryResponse(ApiModel):
    total_renders: int
    total_jobs: int
    latest_job: WordJob | None = None
    latest_document: dict | None = None
    has_download: bool
    history_count: int


class WordMetric(ApiModel):
    """Row of intel_word_metrics."""
    id: int
    job_id: str
    section_name: str
    section_number: int | None = None
    render_type: str
    duration_ms: Number | None = None
    element_count: int | None = None
    warnings_json: Any = None
    created_at: float
