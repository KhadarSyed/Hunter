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
    has_own_upload: bool = Field(description="True when at least one article is approved for this question")
    shared: int | None = Field(default=None, description="Articles approved for this question (Data set tab); "
                                                         "the deck section reads exactly these")


class DataCoverageResponse(BaseModel):
    """Per question, how many articles are approved for it (approved article-RQ rows; a draft question has 0)."""
    rqs: list[RQCoverage] = []
