"""Session-cookie authentication: the get_current_user dependency every
authenticated endpoint depends on, plus the one-time Super Admin bootstrap
seed. require_project_access (Task 4) is appended to this same module.

Note: both `core.store` and `domains.auth.service` are imported locally inside
each function that needs them, not at module level. Every domain router
imports require_project_access from this module; core.store's own wildcard
imports (from ..domains.<x>.repository import *) always run
agent/app/domains/__init__.py first, which imports every router — so a
module-level import of either `store` or `domains.auth.service` here would
create a circular import whenever this module is imported before
agent.app.domains has already been fully initialized (e.g. main.py imports
this module before importing the domains package)."""
from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Path, Response, status

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "session_token"
SEED_SUPER_ADMIN_EMAIL = "khadar.syed@infovision.com"
SEED_SUPER_ADMIN_TEMP_PASSWORD = "ChangeMe#2026"


def seed_super_admin_if_missing() -> None:
    """Idempotent: inserts the first Super Admin only if no user with that
    email exists yet. Called once from main.py's lifespan, right after
    store.init_intelligence_db()."""
    from . import store  # local: avoids a circular import — see module docstring
    if store.get_user_by_email(SEED_SUPER_ADMIN_EMAIL):
        return
    from ..domains.auth import service  # local: avoids a circular import — see module docstring
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
    from .config import get_app_settings  # local: avoids a circular import — see module docstring
    # Cross-origin deploys (FE on Vercel, BE on Render) need SameSite=None, which browsers
    # only honor alongside Secure — and Secure cookies are dropped over plain HTTP, which is
    # what local dev (http://localhost) uses. So this only flips to None/Secure in production.
    is_production = get_app_settings().is_production
    response.set_cookie(
        SESSION_COOKIE_NAME, token, httponly=True,
        samesite="none" if is_production else "lax",
        secure=is_production,
        max_age=int(expires_at - time.time()),
    )


def clear_session_cookie(response: Response) -> None:
    from .config import get_app_settings  # local: avoids a circular import — see module docstring
    # Browsers only clear a cookie when the delete request's samesite/secure attributes
    # match how it was set (see set_session_cookie) — a bare delete_cookie() silently no-ops
    # in production against a SameSite=None;Secure cookie.
    is_production = get_app_settings().is_production
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        samesite="none" if is_production else "lax",
        secure=is_production,
    )


def get_current_user(session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict:
    from . import store  # local: avoids a circular import — see module docstring
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = store.get_session_user(session_token)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid")
    return user


def _check_project_access(project: dict, user: dict) -> None:
    if user["role"] == "super_admin":
        return
    if user["org_id"] is None or project.get("org_id") != user["org_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this project")
    if user["role"] == "analyser" and project.get("owner_user_id") != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this project")


def require_project_access(
    project_id: Annotated[int, Path(ge=1)],
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    from . import store  # local: avoids a circular import — see module docstring
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    _check_project_access(project, user)
    return user


def require_dataset_access(
    dataset_id: Annotated[int, Path(ge=1)],
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Same ownership check as require_project_access, but for routes keyed by
    dataset_id instead of project_id (the dataset-enrichment routes) — resolves
    the dataset's project first, then applies the identical rule."""
    from . import store  # local: avoids a circular import — see module docstring
    dataset = store.get_dataset_by_id(dataset_id)
    if not dataset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    project = store.get_project(dataset["project_id"])
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    _check_project_access(project, user)
    return user
