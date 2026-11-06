"""Request bodies for the Data set API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DecisionRequest(BaseModel):
    article_ids: list[int] = Field(min_length=1, max_length=50_000)
    rq_id: str | None = None
    status: Literal["approved", "irrelevant", "pending"]
    reason: str | None = Field(default=None, max_length=1000)


class UndoRequest(BaseModel):
    undo_token: str


class ArticleEdit(BaseModel):
    sentiment: Literal["Positive", "Neutral", "Negative"] | None = None
    themes: list[str] | None = Field(default=None, max_length=3)
    brands: list[str] | None = Field(default=None, max_length=50)


class RQQuery(BaseModel):
    query: str = Field(min_length=1, max_length=20_000, pattern=r"\S")
