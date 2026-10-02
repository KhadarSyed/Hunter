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
    org_name: str | None = None
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
    temp_password: str | None = None  # None = auto-generate (see service.generate_temp_password)
    org_id: int | None = None  # Super Admin only: which org a new admin/analyser joins


class ResetPasswordResponse(ApiModel):
    ok: bool = True
    temp_password: str  # plaintext, shown once so the Admin can hand it to the user


class UserOrganizationRow(ApiModel):
    id: int
    name: str
    is_primary: bool


class UserResponse(ApiModel):
    id: int
    org_id: int | None = None
    email: str
    display_name: str
    role: str
    avatar_url: str | None = None
    archived_at: float | None = None
    created_at: float | None = None
    # Populated only by the create-user response (plaintext, shown once so the Admin
    # can hand it to the new user) — always None on list/get/archive responses.
    temp_password: str | None = None


class ReassignProjectsRequest(ApiModel):
    to_user_id: int


class UpdateProfileRequest(ApiModel):
    display_name: str
