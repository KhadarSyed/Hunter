"""Request/response models for the deliverable engine API."""
from __future__ import annotations

from pydantic import BaseModel


class DeliverableRunStarted(BaseModel):
    run_id: int


class DeliverableRunPayload(BaseModel):
    run: dict | None = None
    sections: list[dict] = []


class RQCoverage(BaseModel):
    rq_id: str
    has_own_upload: bool   # an approved dataset was uploaded for this question
    shared: int | None = None  # no upload: articles from the other approved uploads matching its Meltwater query


class DataCoverageResponse(BaseModel):
    """Per question, what the deliverable will have from the approved datasets (the engine's routing)."""
    rqs: list[RQCoverage] = []
