"""Request/response models for the Background Research route group.

ApproveRequest is also reused by the Strategy route group (imported from here rather
than duplicated).
"""
from __future__ import annotations

from pydantic import BaseModel

from ...core.api import ApiModel


class StartResearchRequest(BaseModel):
    spec: dict
    project_id: int | None = None


class ApproveRequest(BaseModel):
    reviewer: str = "analyst"
    notes: str = ""
    override_blocking: bool = False


class RevisionRequest(BaseModel):
    notes: str


class NewsApprovalRequest(BaseModel):
    item_index: int
    status: str
    notes: str = ""


# ─── Response models ─────────────────────────────────────────────────────────

class ResearchJobStarted(ApiModel):
    job_id: str
    project_id: int


class ResearchJobStatus(ApiModel):
    job_id: str
    status: str
    progress_pct: int | float | None = None
    progress_message: str | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None


class ResearchResults(ApiModel):
    research_id: int
    version: int
    approval_status: str | None = None
    enrichment_status: str | None = None
    research: dict
    llm_output: dict | None = None
    can_approve: bool
    blocking_reasons: list[str]
    created_at: float | None = None


class ResearchApprovalResult(ApiModel):
    """Either {approved: False, blocking_reasons} or {ok, approved: True, overridden}."""

    approved: bool


class BrandLogoResponse(ApiModel):
    brand_name: str
    logo_url: str | None = None
    source: str | None = None  # brandfetch | google | none
    domain: str | None = None
    cached: bool = False  # True = served from the brand_logos table


class PexelsImageResponse(ApiModel):
    query: str
    image_url: str | None = None
    photographer: str | None = None
    source_url: str | None = None
    cached: bool = False  # True = served from the pexels_images table
