"""Request/response models for the exclusion list."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...core.api import ApiModel


class ExclusionRecord(ApiModel):
    id: int
    kind: Literal["domain", "keyword"]
    value: str
    created_at: float


class AddExclusionRequest(ApiModel):
    kind: Literal["domain", "keyword"]
    value: str = Field(min_length=1, max_length=200)
