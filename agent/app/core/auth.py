"""Session-cookie authentication: the get_current_user dependency every
authenticated endpoint depends on, plus the one-time Super Admin bootstrap
seed. require_project_access (Task 4) is appended to this same module."""
from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Path, Response, status

from ..domains.auth import service
from . import store

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "session_token"
SEED_SUPER_ADMIN_EMAIL = "khadar.syed@infovision.com"
SEED_SUPER_ADMIN_TEMP_PASSWORD = "ChangeMe#2026"


def seed_super_admin_if_missing() -> None:
    """Idempotent: inserts the first Super Admin only if no user with that
    email exists yet. Called once from main.py's lifespan, right after
    store.init_intelligence_db()."""
    if store.get_user_by_email(SEED_SUPER_ADMIN_EMAIL):
        return
    store.create_user(
        org_id=None,
        email=SEED_SUPER_ADMIN_EMAIL,
        password_hash=service.hash_password(SEED_SUPER_ADMIN_TEMP_PASSWORD),
        display_name="Khadar Syed",
        role="super_admin",
        must_change_password=True,
    )
    logger.info("Seeded initial Super Admin: %s", SEED_SUPER_ADMIN_EMAIL)


def set_session_cookie(response: Response, token: str, expires_at: float) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME, token, httponly=True, samesite="lax",
        secure=False,  # dev over plain HTTP; revisit if deployed behind HTTPS
        max_age=int(expires_at - time.time()),
    )


def get_current_user(session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict:
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = store.get_session_user(session_token)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid")
    return user


def require_project_access(
    project_id: Annotated[int, Path(ge=1)],
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if user["role"] == "super_admin":
        return user
    if project.get("org_id") != user["org_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this project")
    if user["role"] == "analyser" and project.get("owner_user_id") != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this project")
    return user
