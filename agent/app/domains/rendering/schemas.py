"""Request/response models for the PowerPoint Renderer route group.

Also contains:
- word_renderer: Request/response models for the Word Report Renderer route group.
"""
from __future__ import annotations

from pydantic import BaseModel


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
