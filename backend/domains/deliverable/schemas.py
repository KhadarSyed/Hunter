"""Request/response models for the deliverable engine API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DeliverableRunStarted(BaseModel):
    run_id: int


class DeckDesignChange(BaseModel):
    """Deck colours as 6 hex digits, no '#'; an omitted colour keeps its current value."""
    primary: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    accent: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")


class DeckDesign(BaseModel):
    primary: str
    accent: str
    swatches: list[str] = []
    can_reset: bool = False


class DeckDesignResult(BaseModel):
    applied: list[str] = []
    rejected: dict[str, str] = {}
    html: str = "deck.html"     # the deck file to show: preview.html after a preview


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
