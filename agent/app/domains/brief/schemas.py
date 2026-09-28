"""Request/response models for the Analyst Orientation Brief route group."""
from __future__ import annotations

from pydantic import BaseModel

from ...core.api import ApiModel, OkResponse


class GenerateBriefRequest(BaseModel):
    project_id: int


class UpdateBriefSectionRequest(BaseModel):
    section_key: str
    content: str
    analyst_note: str = ""


class ApproveBriefRequest(BaseModel):
    reviewer: str = "analyst"


class RejectBriefRequest(BaseModel):
    notes: str = ""


# ─── Response models ─────────────────────────────────────────────────────────

class ParsedBriefFileResponse(ApiModel):
    text: str
    file_name: str | None = None
    ocr_used: bool  # kept for older clients: True when NVIDIA parsing produced the text
    extraction_method: str  # "nvidia" | "native"
    model: str | None = None  # NVIDIA model used, when extraction_method == "nvidia"
    pages: int | None = None


class GeneratedBriefResponse(ApiModel):
    brief_id: int
    brief: dict | None = None


class AnalystBriefResponse(ApiModel):
    brief_id: int
    version: int | None = None
    approval_status: str | None = None
    brief: dict | None = None
    docx_path: str | None = None
    docx_generated_at: float | None = None
    research_approved: bool | None = None
    created_at: float | None = None
    updated_at: float | None = None


class BriefRenderResponse(OkResponse):
    docx_path: str | None = None


class BriefVersionItem(ApiModel):
    id: int
    version: int | None = None
    status: str | None = None
    approval_status: str | None = None
    docx_path: str | None = None
    created_at: float | None = None
    updated_at: float | None = None
