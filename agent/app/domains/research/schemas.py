"""Request/response models for the Background Research route group.

ApproveRequest is also reused by the Strategy route group (imported from here rather
than duplicated).
"""
from __future__ import annotations

from pydantic import BaseModel


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
