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
