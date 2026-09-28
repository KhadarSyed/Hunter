"""Request/response models for the Analyst Orientation Brief route group."""
from __future__ import annotations

from pydantic import BaseModel


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
