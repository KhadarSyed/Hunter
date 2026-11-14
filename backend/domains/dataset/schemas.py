"""Request bodies for the Data set API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DecisionRequest(BaseModel):
    article_ids: list[int] = Field(min_length=1, max_length=50_000)
    rq_id: str | None = None
    status: Literal["approved", "irrelevant", "pending"]
    reason: str | None = Field(default=None, max_length=1000)


class KeepRequest(BaseModel):
    """Why a blocked article is relevant after all (required: the organization learns from it)."""
    comment: str = Field(min_length=3, max_length=1000, pattern=r"\S")


class CommentRequest(BaseModel):
    """An analyst's note for the agent: about the article (article tagging) or about one research question."""
    scope: Literal["article", "rq"] = "article"
    rq_id: str | None = Field(default=None, max_length=40)
    text: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class EnrichmentEdit(BaseModel):
    """The drill-down's edited rich tags (the media-intelligence format); validated before it is saved."""
    enrichment: dict
    author_type: str | None = Field(default=None, max_length=60)
    comment: str | None = Field(default=None, max_length=1000)


class RqRowEdit(BaseModel):
    """The drill-down's edited research-question row (approve / reject go through /decisions)."""
    match_confidence: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = Field(default=None, max_length=2000)
    tags: dict | None = None
    comment: str | None = Field(default=None, max_length=1000)


class ScopeRequest(BaseModel):
    """The Data set scope filter: an outlet country ('' = every country) and an ISO date range ('' = no bound)."""
    country: str = Field(default="", max_length=80)
    day_from: str = Field(default="", alias="from", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    day_to: str = Field(default="", alias="to", pattern=r"^(\d{4}-\d{2}-\d{2})?$")


class UndoRequest(BaseModel):
    undo_token: str


class ArticleEdit(BaseModel):
    sentiment: Literal["Positive", "Neutral", "Negative"] | None = None
    themes: list[str] | None = Field(default=None, max_length=3)
    brands: list[str] | None = Field(default=None, max_length=50)
    comment: str | None = Field(default=None, max_length=1000)     # why: the AI learns from it for similar articles


class RQQuery(BaseModel):
    query: str = Field(min_length=1, max_length=20_000, pattern=r"\S")
