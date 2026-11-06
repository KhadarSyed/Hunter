"""Session-cookie authentication: the get_current_user dependency every
authenticated endpoint depends on, plus the one-time Super Admin bootstrap
seed. require_project_access (Task 4) is appended to this same module.

Note: both `core.store` and `domains.auth.service` are imported locally inside
each function that needs them, not at module level. Every domain router
imports require_project_access from this module; core.store's own wildcard
imports (from ..domains.<x>.repository import *) always run
backend/domains/__init__.py first, which imports every router — so a
module-level import of either `store` or `domains.auth.service` here would
create a circular import whenever this module is imported before
backend.domains has already been fully initialized (e.g. main.py imports
this module before importing the domains package)."""
from __future__ import annotations

import logging
import os
import secrets
import time
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Path, Request, Response, status

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "session_token"
SEED_SUPER_ADMIN_EMAIL = "khadar.syed@infovision.com"
# While must_change_password is set, a user may only reach these (everything else answers 403).
MUST_CHANGE_ALLOWED_PATHS = frozenset({"/api/auth/change-password", "/api/auth/me", "/api/auth/logout"})


SEED_ORGANIZATION = "InfoVision"
SEED_SUPER_ADMINS = (
    (SEED_SUPER_ADMIN_EMAIL, "Khadar Syed"),
    ("sweta.shah@infovision.com", "Sweta Shah"),
    ("harish.thulasiram@infovision.com", "Harish Thulasiram"),
)


def seed_super_admin_if_missing() -> None:
    """Idempotent, on every startup: the InfoVision organization and its Super Admins always exist. A missing
    account is created with the default password (to be changed at first sign-in); an existing one keeps its
    password and is (re)made a Super Admin linked to InfoVision. Called from main.py's lifespan, right after
    store.init_intelligence_db()."""
    from . import store  # local: avoids a circular import — see module docstring
    from ..domains.auth import service  # local: avoids a circular import — see module docstring
    org = store.find_organization_by_name(SEED_ORGANIZATION)
    org_id = org["id"] if org else store.create_bare_organization(SEED_ORGANIZATION)
    if org and org.get("archived_at"):
        store.reactivate_organization(org_id)
    for email, name in SEED_SUPER_ADMINS:
        user = store.get_user_by_email(email)
        if user is None:
            password = os.environ.get("SEED_SUPER_ADMIN_PASSWORD") or ""
            if not password:
                password = secrets.token_urlsafe(12)
                logger.warning("Seeded Super Admin %s with temporary password %s (set SEED_SUPER_ADMIN_PASSWORD "
                               "to choose it); it must be changed at first sign-in", email, password)
            user_id = store.create_user(org_id=None, email=email,
                                        password_hash=service.hash_password(password),
                                        display_name=name, role="super_admin", must_change_password=True)
            logger.info("Seeded Super Admin: %s", email)
        else:
            user_id = user["id"]
            if user["role"] != "super_admin" or user.get("org_id") is not None or user.get("archived_at"):
                store.make_super_admin(user_id)
                logger.info("Made %s a Super Admin", email)
        if not store.is_member_of_org(user_id, org_id):
            store.add_user_to_org(user_id, org_id)


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


def get_current_user(request: Request,
                     session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict:
    from . import store  # local: avoids a circular import — see module docstring
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = store.get_session_user(session_token)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid")
    if user.get("must_change_password") and request.url.path not in MUST_CHANGE_ALLOWED_PATHS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required")
    from ..domains.usage import service as usage  # local: avoids a circular import — see module docstring
    usage.fill(user_id=user.get("id"), org_id=user.get("org_id"))
    return user


def can_access_project(project: dict, user: dict) -> bool:
    """The one project-access rule, shared by the REST dependencies and the /ws event filter."""
    if user["role"] == "super_admin":
        return True
    if user["org_id"] is None or project.get("org_id") != user["org_id"]:
        return False
    return not (user["role"] == "analyser" and project.get("owner_user_id") != user["id"])


def _check_project_access(project: dict, user: dict) -> None:
    if not can_access_project(project, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this project")
    from ..domains.usage import service as usage  # local: avoids a circular import — see module docstring
    usage.fill(project_id=project["id"], org_id=project.get("org_id"))


def _require_owner_access(project_id: int | None, user: dict, what: str) -> dict:
    """The shared tail of every ID-keyed access dependency: the row's project must exist and be the user's."""
    from . import store  # local: avoids a circular import — see module docstring
    project = store.get_project(int(project_id)) if project_id else None
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
    _check_project_access(project, user)
    return user


def _project_id_by_sql(sql: str, row_id: int | str) -> int | None:
    """For rows no repository getter covers: one SELECT returning the owning project_id."""
    from .db import _conn  # local: avoids a circular import — see module docstring
    conn = _conn()
    try:
        row = conn.execute(sql, (row_id,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


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


def require_strategy_access(
    strategy_id: Annotated[int, Path(ge=1)],
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Ownership check for routes keyed by strategy_id: resolve the strategy's project, then apply the
    same rule as require_project_access."""
    from . import store  # local: avoids a circular import — see module docstring
    project_id = store.get_strategy_project_id(strategy_id)
    project = store.get_project(project_id) if project_id else None
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
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


IdPath = Annotated[int, Path(ge=1)]
UserDep = Annotated[dict, Depends(get_current_user)]


def require_spec_access(spec_id: IdPath, user: UserDep) -> dict:
    from . import store  # local: avoids a circular import — see module docstring
    return _require_owner_access((store.get_spec_by_id(spec_id) or {}).get("project_id"), user, "Spec")


def require_clarification_access(clarification_id: IdPath, user: UserDep) -> dict:
    return _require_owner_access(_project_id_by_sql(
        "SELECT s.project_id FROM intel_spec_clarifications c "
        "JOIN intel_research_specifications s ON s.id = c.spec_id WHERE c.id = ?", clarification_id),
        user, "Clarification")


def require_brief_access(brief_id: IdPath, user: UserDep) -> dict:
    from . import store  # local: avoids a circular import — see module docstring
    return _require_owner_access((store.get_brief_by_id(brief_id) or {}).get("project_id"), user, "Brief")


def require_research_access(research_id: IdPath, user: UserDep) -> dict:
    from . import store  # local: avoids a circular import — see module docstring
    return _require_owner_access((store.get_research_by_id(research_id) or {}).get("project_id"), user, "Research")


def require_research_item_access(item_id: IdPath, user: UserDep) -> dict:
    from . import store  # local: avoids a circular import — see module docstring
    return _require_owner_access((store.get_research_item(item_id) or {}).get("project_id"), user, "Item")


def require_job_access(job_id: str, user: UserDep) -> dict:
    from . import store  # local: avoids a circular import — see module docstring
    return _require_owner_access((store.get_job(job_id) or {}).get("project_id"), user, "Job")


def require_plan_access(plan_id: IdPath, user: UserDep) -> dict:
    return _require_owner_access(_project_id_by_sql(
        "SELECT project_id FROM intel_research_plans WHERE id = ?", plan_id), user, "Plan")


def require_qc_report_access(report_id: IdPath, user: UserDep) -> dict:
    from . import store  # local: avoids a circular import — see module docstring
    return _require_owner_access((store.get_qc_report(report_id) or {}).get("project_id"), user, "Report")


def require_qc_run_access(run_id: IdPath, user: UserDep) -> dict:
    return _require_owner_access(_project_id_by_sql(
        "SELECT r.project_id FROM qc_runs q JOIN qc_reports r ON r.id = q.report_id WHERE q.id = ?", run_id),
        user, "QC run")


def require_qc_finding_access(finding_id: IdPath, user: UserDep) -> dict:
    return _require_owner_access(_project_id_by_sql(
        "SELECT r.project_id FROM qc_findings f JOIN qc_reports r ON r.id = f.report_id WHERE f.id = ?",
        finding_id), user, "Finding")


def require_qc_export_access(export_id: IdPath, user: UserDep) -> dict:
    return _require_owner_access(_project_id_by_sql(
        "SELECT r.project_id FROM qc_exports e JOIN qc_runs q ON q.id = e.run_id "
        "JOIN qc_reports r ON r.id = q.report_id WHERE e.id = ?", export_id), user, "Export")


def check_project_id_access(project_id: int | None, user: dict) -> None:
    """For routes that take project_id from the body, query or a form field rather than the path."""
    _require_owner_access(project_id, user, "Project")
