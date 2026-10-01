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


class CreateOrganizationRequest(ApiModel):
    name: str
    admin_email: str
    admin_display_name: str
    admin_temp_password: str


class OrganizationResponse(ApiModel):
    id: int
    name: str
    admin_name: str | None = None
    admin_email: str | None = None
    archived_at: float | None = None


class CreateUserRequest(ApiModel):
    email: str
    display_name: str
    role: str  # 'admin' | 'analyser' | 'super_admin' — router enforces who may pick which
    temp_password: str


class UserResponse(ApiModel):
    id: int
    org_id: int | None = None
    email: str
    display_name: str
    role: str
    avatar_url: str | None = None
    archived_at: float | None = None


class ReassignProjectsRequest(ApiModel):
    to_user_id: int


class UpdateProfileRequest(ApiModel):
    display_name: str
