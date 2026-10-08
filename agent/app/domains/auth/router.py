"""Login/session/profile routes for the auth domain."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Response, UploadFile, status

from ...core import store
from ...core.auth import SESSION_COOKIE_NAME, clear_session_cookie, get_current_user, set_session_cookie
from ...core.config import UPLOAD_DIR
from . import service
from .schemas import (
    ChangePasswordRequest,
    CreateOrganizationRequest,
    CreateUserRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    OrganizationResponse,
    ReassignProjectsRequest,
    ResetPasswordResponse,
    UpdateProfileRequest,
    UserOrganizationRow,
    UserResponse,
)

router = APIRouter()

GENERIC_LOGIN_ERROR = "Invalid email or password"
ALLOWED_AVATAR_CONTENT_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024


def _to_response(user: dict) -> dict:
    org = store.get_organization_by_id(user["org_id"]) if user["org_id"] else None
    return {
        "id": user["id"], "email": user["email"], "display_name": user["display_name"],
        "role": user["role"], "org_id": user["org_id"], "org_name": org["name"] if org else None,
        "avatar_url": user["avatar_url"], "must_change_password": bool(user["must_change_password"]),
    }


@router.post("/login", response_model=LoginResponse)
def login_route(req: LoginRequest, response: Response):
    locked = store.is_locked_out(req.email)
    user = store.get_user_by_email(req.email)
    # Always run a bcrypt check, win or lose, so response time doesn't reveal
    # whether the email is registered (see service.DUMMY_PASSWORD_HASH).
    password_hash = user["password_hash"] if user else service.DUMMY_PASSWORD_HASH
    valid = service.verify_password(req.password, password_hash)
    if locked or not user or user["archived_at"] is not None or not valid:
        if user:
            store.record_failed_login(req.email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)
    store.clear_failed_logins(req.email)
    token, expires_at = store.create_session(user["id"])
    set_session_cookie(response, token, expires_at)
    return _to_response(user)


@router.get("/me", response_model=MeResponse)
def me_route(user: Annotated[dict, Depends(get_current_user)]):
    return _to_response(user)


@router.post("/logout")
def logout_route(response: Response,
                  session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None):
    if session_token:
        store.delete_session(session_token)
    clear_session_cookie(response)
    return {"ok": True}


@router.post("/change-password")
def change_password_route(
    req: ChangePasswordRequest, user: Annotated[dict, Depends(get_current_user)],
):
    if not service.verify_password(req.current_password, user["password_hash"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if len(req.new_password) < service.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Password must be at least {service.MIN_PASSWORD_LENGTH} characters")
    store.update_user_password(user["id"], service.hash_password(req.new_password))
    return {"ok": True}


def _require_role(user: dict, *roles: str) -> None:
    if user["role"] not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")


@router.post("/organizations", response_model=OrganizationResponse)
def create_organization_route(
    req: CreateOrganizationRequest, user: Annotated[dict, Depends(get_current_user)],
):
    _require_role(user, "super_admin")
    if len(req.admin_temp_password) < service.MIN_PASSWORD_LENGTH:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                             f"Password must be at least {service.MIN_PASSWORD_LENGTH} characters")
    existing = store.get_user_by_email(req.admin_email)
    if existing and existing["role"] == "super_admin":     # linked to the new org; account and role unchanged
        org = store.create_organization_for_member(req.name, existing["id"])
        return {**org, "admin_name": existing.get("display_name"), "admin_email": existing["email"]}
    if existing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already in use")
    org = store.create_organization(
        req.name, req.admin_email, req.admin_display_name,
        service.hash_password(req.admin_temp_password))
    return {**org, "admin_name": req.admin_display_name, "admin_email": req.admin_email}


@router.get("/organizations", response_model=list[OrganizationResponse])
def list_organizations_route(user: Annotated[dict, Depends(get_current_user)]):
    _require_role(user, "super_admin")
    return store.list_organizations()


@router.post("/organizations/{org_id}/archive")
def archive_organization_route(org_id: int, user: Annotated[dict, Depends(get_current_user)]):
    _require_role(user, "super_admin")
    result = store.archive_organization(org_id)
    if result is None:
        raise HTTPException(404, "Organization not found")
    return {"ok": True}


@router.post("/organizations/{org_id}/reactivate")
def reactivate_organization_route(org_id: int, user: Annotated[dict, Depends(get_current_user)]):
    _require_role(user, "super_admin")
    result = store.reactivate_organization(org_id)
    if result is None:
        raise HTTPException(404, "Organization not found")
    return {"ok": True}


@router.get("/archived")
def list_archived_route(user: Annotated[dict, Depends(get_current_user)]):
    _require_role(user, "super_admin")
    return store.list_archived()


@router.post("/users", response_model=UserResponse)
def create_user_route(req: CreateUserRequest, user: Annotated[dict, Depends(get_current_user)]):
    _require_role(user, "admin", "super_admin")
    if user["role"] == "admin" and req.role != "analyser":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins can only create Analysers")
    if req.role == "super_admin" and user["role"] != "super_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a Super Admin can create another Super Admin")
    if user["role"] == "admin":
        target_org_id = user["org_id"]
    elif req.role == "super_admin":
        target_org_id = None  # Super Admins are org-less by design
    else:
        if req.org_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                 "org_id is required when creating an admin or analyser")
        target_org_id = req.org_id

    existing = store.get_user_by_email(req.email)
    if existing:
        # A user can belong to multiple orgs — adding an existing email to a *different*
        # org links them to it instead of rejecting; the same org is still a duplicate.
        if target_org_id is None or store.is_member_of_org(existing["id"], target_org_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                 "This user is already a member of this organization")
        store.add_user_to_org(existing["id"], target_org_id)
        return {**existing, "temp_password": None}

    temp_password = req.temp_password or service.generate_temp_password()
    if len(temp_password) < service.MIN_PASSWORD_LENGTH:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                             f"Password must be at least {service.MIN_PASSWORD_LENGTH} characters")
    new_id = store.create_user(target_org_id, req.email, service.hash_password(temp_password),
                                req.display_name, req.role)
    if req.role == "super_admin" and req.org_id is not None:     # org-less by design, but listed under that org
        store.add_user_to_org(new_id, req.org_id)
    created = store.get_user_by_id(new_id)
    return {**created, "temp_password": temp_password}


@router.get("/me/organizations", response_model=list[UserOrganizationRow])
def list_my_organizations_route(user: Annotated[dict, Depends(get_current_user)]):
    """Every org the current user belongs to (primary + additional memberships) —
    ProfileMenu's "organizations you're mapped to" list."""
    return store.list_user_organizations(user["id"])


@router.delete("/users/{user_id}")
def delete_user_route(user_id: int, user: Annotated[dict, Depends(get_current_user)]):
    """Permanent delete (distinct from archive) — Super Admin only, since this removes the
    row outright rather than hiding it, and an Admin's own-org scoping isn't a substitute
    for that judgment call."""
    _require_role(user, "super_admin")
    if not store.get_user_by_id(user_id):
        raise HTTPException(404, "User not found")
    if user_id == user["id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete your own account")
    store.delete_user(user_id)
    return {"ok": True}


@router.delete("/organizations/{org_id}")
def delete_organization_route(org_id: int, user: Annotated[dict, Depends(get_current_user)]):
    """Permanent delete (distinct from archive) — Super Admin only."""
    _require_role(user, "super_admin")
    if not store.get_organization(org_id):
        raise HTTPException(404, "Organization not found")
    store.delete_organization(org_id)
    return {"ok": True}


@router.post("/users/{user_id}/reset-password", response_model=ResetPasswordResponse)
def reset_user_password_route(user_id: int, user: Annotated[dict, Depends(get_current_user)]):
    """Admin/Super Admin sets a fresh auto-generated temp password for any user they manage
    (Admins: their own org's Analysers only, via _require_same_org_analyser; Super Admin: anyone)
    — shown once in the response so it can be handed to the user."""
    _require_role(user, "admin", "super_admin")
    _require_same_org_analyser(user, user_id)
    if not store.get_user_by_id(user_id):
        raise HTTPException(404, "User not found")
    temp_password = service.generate_temp_password()
    store.reset_user_password(user_id, service.hash_password(temp_password))
    return ResetPasswordResponse(temp_password=temp_password)


@router.get("/users", response_model=list[UserResponse])
def list_users_route(user: Annotated[dict, Depends(get_current_user)], org_id: int | None = None):
    _require_role(user, "admin", "super_admin")
    if user["role"] == "admin":
        return store.list_users(org_id=user["org_id"])
    return store.list_users(org_id=org_id)


def _require_same_org_analyser(user: dict, target_user_id: int) -> None:
    """An Admin may only act on Analysers within their own org — never another
    org's users, and never a Super Admin or another org's Admin."""
    if user["role"] == "super_admin":
        return
    target = store.get_user_by_id(target_user_id)
    if not target or target["org_id"] != user["org_id"] or target["role"] != "analyser":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this user")


@router.post("/users/{user_id}/archive")
def archive_user_route(user_id: int, user: Annotated[dict, Depends(get_current_user)]):
    _require_role(user, "admin", "super_admin")
    _require_same_org_analyser(user, user_id)
    result = store.archive_user(user_id)
    if result is None:
        raise HTTPException(404, "User not found")
    return {"ok": True}


@router.post("/users/{user_id}/reactivate")
def reactivate_user_route(user_id: int, user: Annotated[dict, Depends(get_current_user)]):
    _require_role(user, "super_admin")
    result = store.reactivate_user(user_id)
    if result is None:
        raise HTTPException(404, "User not found")
    return {"ok": True}


@router.post("/users/{user_id}/reassign-projects")
def reassign_projects_route(user_id: int, req: ReassignProjectsRequest,
                              user: Annotated[dict, Depends(get_current_user)]):
    _require_role(user, "admin", "super_admin")
    _require_same_org_analyser(user, user_id)
    _require_same_org_analyser(user, req.to_user_id)
    count = store.reassign_projects(user_id, req.to_user_id)
    return {"ok": True, "reassigned": count}


@router.patch("/profile")
def update_profile_route(req: UpdateProfileRequest, user: Annotated[dict, Depends(get_current_user)]):
    store.update_profile(user["id"], req.display_name)
    return {"ok": True}


_AVATAR_EXT_BY_CONTENT_TYPE = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
}


@router.post("/profile/avatar")
async def upload_avatar_route(
    user: Annotated[dict, Depends(get_current_user)], file: UploadFile = File(...),
):
    if file.content_type not in ALLOWED_AVATAR_CONTENT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                             "Avatar must be a PNG, JPEG, GIF, or WebP image")
    data = await file.read()
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                             f"Avatar must be {MAX_AVATAR_BYTES // (1024 * 1024)}MB or smaller")
    avatars_dir = UPLOAD_DIR / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    # Extension is derived from the validated content-type, never the client-supplied
    # filename — an uploaded "evil.html" with an image content-type is still saved as .png/etc.
    ext = _AVATAR_EXT_BY_CONTENT_TYPE[file.content_type]
    filename = f"avatar_{user['id']}_{uuid.uuid4().hex[:8]}{ext}"
    dest = avatars_dir / filename
    dest.write_bytes(data)
    avatar_url = f"/uploads/avatars/{filename}"
    store.update_profile(user["id"], user["display_name"], avatar_url)
    return {"avatar_url": avatar_url}
