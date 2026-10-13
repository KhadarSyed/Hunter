"""Request/response models for the deliverable engine API."""
from __future__ import annotations

from pydantic import BaseModel


class DeliverableRunStarted(BaseModel):
    run_id: int


class DeliverableRunPayload(BaseModel):
    run: dict | None = None
    sections: list[dict] = []
