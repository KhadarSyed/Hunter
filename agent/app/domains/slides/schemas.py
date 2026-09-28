"""Request/response models for the Slide Intelligence route group."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


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
    limit: int = 50


class RetrieveRequest(BaseModel):
    node_id: int
    top_k: int = 10


class MatchStorylineRequest(BaseModel):
    storyline_id: int
