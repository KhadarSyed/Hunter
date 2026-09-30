"""Pydantic request/response models for the auth domain."""
from __future__ import annotations

from ...core.api import ApiModel


class LoginRequest(ApiModel):
    email: str
    password: str


class LoginResponse(ApiModel):
    id: int
    email: str
    display_name: str
    role: str
    org_id: int | None = None
    avatar_url: str | None = None
    must_change_password: bool


class MeResponse(LoginResponse):
    pass


class ChangePasswordRequest(ApiModel):
    current_password: str
    new_password: str
