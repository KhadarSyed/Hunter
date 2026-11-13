from __future__ import annotations

from pydantic import Field

from ...core.api import ApiModel


class PlanRequest(ApiModel):
    name: str = Field(min_length=1, max_length=60)
    max_users: int = Field(ge=1, le=100000)
    max_projects: int = Field(ge=1, le=100000)
    duration_months: int = Field(ge=1, le=60)
    price: float = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    active: bool = True


class GrantRequest(ApiModel):
    plan_id: int


class TokenLimitRequest(ApiModel):
    monthly_tokens: int | None = Field(default=None, ge=0)  # None = unlimited
