"""Request/response models for the Evidence Library route group."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class IngestRequest(BaseModel):
    project_id: int
    run_id: int


class ReviewRequest(BaseModel):
    status: str
    reviewer: str = "analyst"
    note: Optional[str] = None


class AnnotateRequest(BaseModel):
    note: str
    author: str = "analyst"


class BulkReviewRequest(BaseModel):
    item_ids: list[int]
    status: str
    reviewer: str = "analyst"


class ClassifyRequest(BaseModel):
    objective_id: Optional[str] = None
    unit_id: Optional[str] = None
    confidence: Optional[str] = None
    reviewer: str = "analyst"


class RepresentativeRequest(BaseModel):
    is_representative: bool = True


class HighValueRequest(BaseModel):
    is_high_value: bool = True
