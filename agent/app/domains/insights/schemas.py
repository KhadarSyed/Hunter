"""Request/response models for the Insight Generator route group.

Note: RevisionRequest here is a distinct class from research/schemas.py's RevisionRequest
(different fields). insights/router.py imports this one as InsightRevisionRequest.
"""
from __future__ import annotations

from pydantic import BaseModel


class GenerateInsightsRequest(BaseModel):
    project_id: int


class ReviewInsightRequest(BaseModel):
    status: str
    reviewer: str = "analyst"
    notes: str | None = None


class RevisionRequest(BaseModel):
    notes: str
    reviewer: str = "analyst"


class NotesRequest(BaseModel):
    notes: str
    reviewer: str = "analyst"


class ValidatePrereqsRequest(BaseModel):
    project_id: int
