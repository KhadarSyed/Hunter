"""Request/response models for the Research Plan route group."""
from __future__ import annotations

from pydantic import BaseModel


class PlanApproveRequest(BaseModel):
    reviewer: str = "analyst"


class PlanRejectRequest(BaseModel):
    notes: str = ""


class PlanRegenerateRequest(BaseModel):
    project_id: int
