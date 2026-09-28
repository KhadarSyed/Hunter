"""Request/response models for the Storyline Builder route group."""
from __future__ import annotations

from pydantic import BaseModel


class GenerateStorylineRequest(BaseModel):
    project_id: int
    reviewer: str = "system"


class ReviewNodeRequest(BaseModel):
    status: str
    reviewer: str = "analyst"


class ReorderRequest(BaseModel):
    node_ids: list[int]
    actor: str = "analyst"


class MergeRequest(BaseModel):
    node_id_a: int
    node_id_b: int
    actor: str = "analyst"


class SplitRequest(BaseModel):
    actor: str = "analyst"


class UpdateNodeRequest(BaseModel):
    title: str | None = None
    narrative_summary: str | None = None
    purpose: str | None = None
    suggested_visual: str | None = None
    priority: str | None = None
    is_key_message: bool | None = None
    is_locked: bool | None = None


class StorylineApprovalRequest(BaseModel):
    reviewer: str = "analyst"


class ValidateStorylinePrereqsRequest(BaseModel):
    project_id: int
