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
    notes: str = ""     # optional guidance


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
    video_url: str | None = None
    photographer: str | None = None
    source_url: str | None = None
    cached: bool = False  # True = served from the pexels_images table


class SectionVideoResponse(ApiModel):
    query: str
    video_id: str | None = None
    embed_url: str | None = None
    title: str | None = None
    thumbnail_url: str | None = None
    cached: bool = False  # True = served from the youtube_videos table


class FetchPreviewRequest(BaseModel):
    project_id: int


class FetchPreviewStarted(ApiModel):
    job_id: str
    project_id: int


class ResearchItemView(ApiModel):
    id: int
    topic: str
    source_api: str
    publication: str | None = None
    domain: str | None = None
    title: str | None = None
    content: str | None = None
    url: str
    author: str | None = None
    thumbnail_url: str | None = None
    published_date: float
    keywords_matched: list[str] = []
    relevant: bool = True


class ResearchItemsListResponse(ApiModel):
    items: list[ResearchItemView]
    total: int


class ArticleBlock(ApiModel):
    type: str  # "heading" | "paragraph" | "image"
    text: str | None = None
    src: str | None = None
    alt: str | None = None


class ArticleFullTextResponse(ApiModel):
    status: str  # "ok" | "failed" | "paywalled" | "social_media" | "video"
    title: str | None = None
    blocks: list[ArticleBlock] = []
    error: str | None = None
    platform: str | None = None  # e.g. "YouTube", "Facebook" — set for social_media/video
    embed_url: str | None = None  # set for video (YouTube) only
    cached: bool = False
