"""Request/response models for the Presentation Composer route group.

GeneratePresentationRequest is also used by the SOV/Theme Archetype endpoints in
composer/router.py.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


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
