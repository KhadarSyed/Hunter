"""Request bodies for the usage API."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PriceRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)
    deployment_type: Literal["", "global", "datazone", "regional"] = ""
    input_per_m: float = Field(ge=0)
    cached_per_m: float = Field(ge=0)
    output_per_m: float = Field(ge=0)
    effective_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("effective_from")
    @classmethod
    def _real_date(cls, v: str) -> str:
        date.fromisoformat(v)       # 2026-13-45 is a 422, not a stored row
        return v


class SettingsRequest(BaseModel):
    deployment_type: Literal["global", "datazone", "regional"] | None = None
    region: str | None = Field(default=None, min_length=1, max_length=64)
