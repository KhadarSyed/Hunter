"""Login/session/profile routes for the auth domain."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from ...core import store
from ...core.auth import SESSION_COOKIE_NAME, get_current_user, set_session_cookie
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
    UpdateProfileRequest,
    UserResponse,
)

router = APIRouter()

GENERIC_LOGIN_ERROR = "Invalid email or password"


def _to_response(user: dict) -> dict:
    return {
        "id": user["id"], "email": user["email"], "display_name": user["display_name"],
        "role": user["role"], "org_id": user["org_id"], "avatar_url": user["avatar_url"],
        "must_change_password": bool(user["must_change_password"]),
    }


@router.post("/login", response_model=LoginResponse)
def login_route(req: LoginRequest, response: Response):
    if store.is_locked_out(req.email):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)
    user = store.get_user_by_email(req.email)
    if not user or user["archived_at"] is not None or not service.verify_password(
        req.password, user["password_hash"]
    ):
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
    response.delete_cookie(SESSION_COOKIE_NAME)
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
    if store.get_user_by_email(req.admin_email):
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
    if store.get_user_by_email(req.email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already in use")
    target_org_id = user["org_id"] if user["role"] == "admin" else None
    new_id = store.create_user(target_org_id, req.email, service.hash_password(req.temp_password),
                                req.display_name, req.role)
    return store.get_user_by_id(new_id)


@router.get("/users", response_model=list[UserResponse])
def list_users_route(user: Annotated[dict, Depends(get_current_user)], org_id: int | None = None):
    _require_role(user, "admin", "super_admin")
    if user["role"] == "admin":
        return store.list_users(org_id=user["org_id"])
    return store.list_users(org_id=org_id)


@router.post("/users/{user_id}/archive")
def archive_user_route(user_id: int, user: Annotated[dict, Depends(get_current_user)]):
    _require_role(user, "admin", "super_admin")
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
    count = store.reassign_projects(user_id, req.to_user_id)
    return {"ok": True, "reassigned": count}


@router.patch("/profile")
def update_profile_route(req: UpdateProfileRequest, user: Annotated[dict, Depends(get_current_user)]):
    store.update_profile(user["id"], req.display_name)
    return {"ok": True}
