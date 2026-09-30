"""Login/session/profile routes for the auth domain."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from ...core import store
from ...core.auth import SESSION_COOKIE_NAME, get_current_user, set_session_cookie
from . import service
from .schemas import ChangePasswordRequest, LoginRequest, LoginResponse, MeResponse

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
