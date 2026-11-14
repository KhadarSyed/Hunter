"""Login/session/profile routes for the auth domain."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from ...core import object_store, store
from ...core import ws_tickets
from ...core.auth import SESSION_COOKIE_NAME, clear_session_cookie, get_current_user, set_session_cookie
from ...core.config import UPLOAD_DIR
from ..billing import repository as billing_repo
from ..billing import service as billing
from . import recovery, service
from .schemas import (
    ActiveOrgRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyCodeRequest,
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
    WsTicketResponse,
)

router = APIRouter()

GENERIC_LOGIN_ERROR = "Invalid email or password"
ALLOWED_AVATAR_CONTENT_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024


def _to_response(user: dict) -> dict:
    org = billing_repo.org_profile(user["org_id"]) if user["org_id"] else None
    return {
        "id": user["id"], "email": user["email"], "display_name": user["display_name"],
        "role": user["role"], "org_id": user["org_id"], "org_name": org["name"] if org else None,
        "org_logo_url": org.get("logo_url") if org else None,
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


LOGIN_BACKGROUND_KEY = "branding/login-background.jpg"     # S3: HunterAgent/branding/login-background.jpg
LOGIN_BACKGROUND_TTL_S = 3600


@router.get("/login-background", include_in_schema=False)
def login_background():
    """The sign-in page's background photo: a 1-hour signed link to the private S3 copy (public: the page shows it
    before anyone signs in). No S3: 404 and the page keeps its plain background."""
    url = object_store.presigned_url(LOGIN_BACKGROUND_KEY, LOGIN_BACKGROUND_TTL_S) if object_store.enabled() else None
    if not url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No sign-in background")
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/me", response_model=MeResponse)
def me_route(user: Annotated[dict, Depends(get_current_user)]):
    return _to_response(user)


@router.get("/ws-ticket", response_model=WsTicketResponse)
def ws_ticket_route(user: Annotated[dict, Depends(get_current_user)]):
    """A one-minute ticket for opening /ws, which connects to the backend directly and so never sees the cookie."""
    return {"ticket": ws_tickets.issue(user["id"])}


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
    try:
        service.check_password(req.new_password, user["email"])
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    if service.verify_password(req.new_password, user["password_hash"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a password different from the current one")
    store.update_user_password(user["id"], service.hash_password(req.new_password))
    return {"ok": True}


# ─── Forgot password: email → 6-digit code → emailed one-time link → new password (see recovery.py) ──────────

@router.post("/forgot-password")
def forgot_password_route(req: ForgotPasswordRequest):
    """Always the same answer, registered email or not."""
    recovery.request_code(req.email)
    return {"ok": True, "message": "If that email is registered, a 6-digit code is on its way."}


@router.post("/forgot-password/verify")
def verify_code_route(req: VerifyCodeRequest):
    try:
        recovery.verify_code(req.email, req.code)
    except recovery.InvalidCode as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"ok": True, "message": "Code confirmed. We emailed you a link to reset your password (valid 30 minutes)."}


@router.post("/reset-password")
def reset_password_route(req: ResetPasswordRequest):
    try:
        recovery.reset_password(req.token, req.new_password)
    except recovery.InvalidLink as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return {"ok": True}


def _org_name(org_id: int | None) -> str:
    org = store.get_organization_by_id(org_id) if org_id else None
    return org["name"] if org else recovery.BRAND


def _require_role(user: dict, *roles: str) -> None:
    if user["role"] not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")


@router.post("/organizations", response_model=OrganizationResponse)
def create_organization_route(
    req: CreateOrganizationRequest, user: Annotated[dict, Depends(get_current_user)],
):
    _require_role(user, "super_admin")
    if store.org_name_taken(req.name):
        raise HTTPException(status.HTTP_409_CONFLICT, f"An organization named '{req.name.strip()}' already exists")
    if req.logo_url and not req.logo_url.startswith("data:image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The logo must be an uploaded image")
    plans = billing_repo.list_plans()
    plan_id = req.plan_id or (plans[0]["id"] if plans else None)
    if plan_id is None or not billing_repo.get_plan(plan_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a subscription plan")
    existing = store.get_user_by_email(req.admin_email)
    if existing and existing["role"] != "super_admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already in use")
    if existing:     # a Super Admin: linked to the new org; account and role unchanged
        org = store.create_organization_for_member(req.name, existing["id"])
    else:
        temp_password = service.temp_password()
        org = store.create_organization(req.name, req.admin_email, req.admin_display_name,
                                        service.hash_password(temp_password))
    billing_repo.update_org_profile(org["id"], {
        "logo_url": req.logo_url, "procurement_name": req.admin_display_name.strip(),
        "procurement_email": req.admin_email.strip().lower(), "procurement_phone": req.procurement_phone,
        "address": req.address, "country": (req.country or "").lower() or None, "pin_code": req.pin_code})
    billing.grant(org["id"], plan_id, user["id"])
    if existing:
        return {**org, "admin_name": existing.get("display_name"), "admin_email": existing["email"]}
    admin = store.get_user_by_email(req.admin_email)
    sent = bool(admin) and recovery.send_welcome(admin, req.name, temp_password)
    return {**org, "admin_name": req.admin_display_name, "admin_email": req.admin_email,
            "temp_password": temp_password, "email_sent": sent}


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
            raise HTTPException(status.HTTP_409_CONFLICT,
                                 f"{existing['email']} is already a member of this organization")
        if user["role"] != "super_admin":     # an org's Admin never pulls in another client's user
            raise HTTPException(status.HTTP_409_CONFLICT,
                                 f"{existing['email']} already has an account in another organization. "
                                 "Ask the platform administrator to share it with yours.")
        try:
            billing.require_seat(target_org_id)
        except billing.LimitError as e:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(e)) from e
        store.add_user_to_org(existing["id"], target_org_id)
        return {**existing, "temp_password": None}

    if req.role != "super_admin":
        try:
            billing.require_seat(target_org_id)
        except billing.LimitError as e:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(e)) from e
    temp_password = service.temp_password()
    new_id =store.create_user(target_org_id, req.email, service.hash_password(temp_password),
                                req.display_name, req.role)
    if req.role == "super_admin" and req.org_id is not None:     # org-less by design, but listed under that org
        store.add_user_to_org(new_id, req.org_id)
    created = store.get_user_by_id(new_id)
    sent = recovery.send_welcome(created, _org_name(target_org_id or req.org_id), temp_password)
    return {**created, "temp_password": temp_password, "email_sent": sent}


@router.post("/me/active-org", response_model=MeResponse)
def set_active_org_route(req: ActiveOrgRequest, user: Annotated[dict, Depends(get_current_user)],
                         session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None):
    """Switch the organisation this session works in (profile menu). null: back to the user's own org (a Super
    Admin: all organisations)."""
    if req.org_id is not None:
        org = store.get_organization_by_id(req.org_id)
        if not org or org.get("archived_at"):
            raise HTTPException(404, "Organization not found")
        if user["role"] != "super_admin" and not store.is_member_of_org(user["id"], req.org_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of this organization")
    store.set_session_org(session_token, req.org_id)
    return _to_response(store.get_session_user(session_token))


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
    """Admin/Super Admin resets any user they manage to a random temporary password, returned once, which
    the user must change at next login (Admins: their own org's Analysers only, via _require_same_org_analyser;
    Super Admin: anyone)."""
    _require_role(user, "admin", "super_admin")
    _require_same_org_analyser(user, user_id)
    if not store.get_user_by_id(user_id):
        raise HTTPException(404, "User not found")
    temp_password = service.temp_password()
    store.reset_user_password(user_id, service.hash_password(temp_password))
    return ResetPasswordResponse(temp_password=temp_password)


@router.post("/users/{user_id}/send-reset")
def send_reset_email_route(user_id: int, user: Annotated[dict, Depends(get_current_user)]):
    """Admin/Super Admin emails a user a one-time reset link (same scope rules as reset-password)."""
    _require_role(user, "admin", "super_admin")
    _require_same_org_analyser(user, user_id)
    target = store.get_user_by_id(user_id)
    if not target or target.get("archived_at"):
        raise HTTPException(404, "User not found")
    if not recovery.send_reset_link(target):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The reset email could not be sent; check the mail settings")
    return {"ok": True}


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
    object_store.put_bytes(f"avatars/{filename}", data, file.content_type)    # a hosted restart keeps the photo
    avatar_url = f"/uploads/avatars/{filename}"
    store.update_profile(user["id"], user["display_name"], avatar_url)
    return {"avatar_url": avatar_url}
