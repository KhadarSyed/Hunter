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
    kept_relevant: int = 0              # how often analysts kept a blocked article for this rule (org memory)
    last_comment: str | None = None     # their latest reason


class AddExclusionRequest(ApiModel):
    kind: Literal["domain", "keyword"]
    value: str = Field(min_length=1, max_length=200)


class BulkExclusionRequest(ApiModel):
    kind: Literal["domain", "keyword"] = "domain"
    text: str = Field(min_length=1, max_length=500_000)     # separated by commas, semicolons, spaces or new lines


class ImportResult(ApiModel):
    added: int
    duplicates: int
    invalid: list[str]          # first ones only
    invalid_count: int
    total: int                  # rules of this kind after the import
