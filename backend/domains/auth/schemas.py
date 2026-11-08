"""Pydantic request/response models for the auth domain."""
from __future__ import annotations

from pydantic import Field

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
    org_logo_url: str | None = None     # the organization's own logo (data: URI), shown as the workspace badge
    avatar_url: str | None = None
    must_change_password: bool


class MeResponse(LoginResponse):
    pass


class ActiveOrgRequest(ApiModel):
    org_id: int | None = None


class ForgotPasswordRequest(ApiModel):
    email: str = Field(min_length=3, max_length=320)


class VerifyCodeRequest(ApiModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(pattern=r"^\s*\d{6}\s*$")


class ResetPasswordRequest(ApiModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class WsTicketResponse(ApiModel):
    ticket: str


class ChangePasswordRequest(ApiModel):
    current_password: str
    new_password: str


class CreateOrganizationRequest(ApiModel):
    name: str
    admin_email: str            # the procurement manager's email: becomes the org's Admin
    admin_display_name: str
    logo_url: str | None = Field(default=None, max_length=1_500_000)   # data: URI from the form's upload
    procurement_phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=2)            # ISO 3166-1 alpha-2
    pin_code: str | None = Field(default=None, max_length=20)
    plan_id: int | None = None   # first subscription (default: the cheapest active plan)


class OrganizationResponse(ApiModel):
    id: int
    name: str
    admin_name: str | None = None
    admin_email: str | None = None
    archived_at: float | None = None
    temp_password: str | None = None  # only on create: the new admin's one-time password


class CreateUserRequest(ApiModel):
    email: str
    display_name: str
    role: str  # 'admin' | 'analyser' | 'super_admin' — router enforces who may pick which
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
