"""Project CRUD routes.

Also contains:
- jobs: Generic job-status lookup routes shared across pipeline stages.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status

from ...core import store
from ...core.auth import get_current_user, require_job_access, require_project_access
from ...core.events import broadcast as _broadcast
from ..billing import service as billing
from .schemas import (
    CreateProjectRequest,
    DeleteProjectResponse,
    GatesResponse,
    JobResponse,
    ProjectListItem,
    ProjectLogoResponse,
    ProjectResponse,
    UpdateProjectRequest,
    _require_project_fields,
)
from .logo import project_logo
from . import gates

router = APIRouter()


def _with_progress(projects: list[dict]) -> list[dict]:
    # shortcut: a few queries per project, run in parallel and cached 4 s; batch into one query when projects > 200
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        sums = list(pool.map(lambda p: gates.summary(p["id"]), projects))
    return [{**p, "progress_pct": s["progress_pct"], "current_stage": s["current_stage"]} for p, s in zip(projects, sums)]


@router.get("/projects", response_model=list[ProjectListItem])
def list_projects_route(
    user: Annotated[dict, Depends(get_current_user)], type: str | None = None,
):
    if user["role"] == "super_admin":
        return _with_progress(store.list_projects(project_type=type, org_id=user.get("active_org_id")))
    if user["org_id"] is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No organization assigned")
    if user["role"] == "admin":
        return _with_progress(store.list_projects(project_type=type, org_id=user["org_id"]))
    return _with_progress(store.list_projects(project_type=type, org_id=user["org_id"], owner_user_id=user["id"]))


@router.get("/projects/{project_id}/gates", response_model=GatesResponse)
def project_gates_route(project_id: Annotated[int, Path(ge=1)],
                        _access: Annotated[dict, Depends(require_project_access)]):
    return gates.summary(project_id)


@router.post("/projects", response_model=ProjectResponse)
def create_project_route(
    req: CreateProjectRequest, user: Annotated[dict, Depends(get_current_user)],
):
    try:
        billing.require_project_slot(user["org_id"])
    except billing.LimitError as e:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(e)) from e
    if store.project_name_taken(user["org_id"], req.project_name):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A project named '{req.project_name.strip()}' already exists in this organization")
    pid = store.create_project(req.project_name, req.spec, project_type=req.project_type, brand=req.brand)
    store.set_project_owner(pid, user["org_id"], user["id"])
    project = store.get_project(pid)
    _broadcast({"type": "project_created", "project_id": pid})
    return project


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project_route(project_id: Annotated[int, Path(ge=1)],
                       _access: Annotated[dict, Depends(require_project_access)]):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/projects/{project_id}/logo", response_model=ProjectLogoResponse)
def get_project_logo_route(project_id: Annotated[int, Path(ge=1)],
                           _access: Annotated[dict, Depends(require_project_access)]):
    """The client brand's logo, else a photo of the brief's main theme for a project with no client brand."""
    logo = project_logo(project_id)
    if logo is None:
        raise HTTPException(404, "Project not found")
    return logo


@router.put("/projects/{project_id}", response_model=ProjectResponse)
def update_project_route(project_id: Annotated[int, Path(ge=1)], req: UpdateProjectRequest,
                          _access: Annotated[dict, Depends(require_project_access)]):
    existing = store.get_project(project_id)
    if not existing:
        raise HTTPException(404, "Project not found")
    try:
        _require_project_fields(
            req.project_name if req.project_name is not None else existing["project_name"],
            req.brand if req.brand is not None else existing.get("brand"),
            existing.get("project_type") or "research",
            {**(existing.get("spec") or {}), **(req.spec or {})},
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    if req.project_name is not None and store.project_name_taken(existing.get("org_id"), req.project_name, project_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A project named '{req.project_name.strip()}' already exists in this organization")
    store.update_project(project_id, req.project_name, req.spec, req.brand)
    return store.get_project(project_id)


@router.delete("/projects/{project_id}", response_model=DeleteProjectResponse)
def delete_project_route(project_id: Annotated[int, Path(ge=1)],
                          _access: Annotated[dict, Depends(require_project_access)]):
    """Delete a project for good: every row that belongs to it, the files those rows point at, its deliverables
    folder (store.delete_project). The dialog says so: this cannot be undone."""
    deleted = store.delete_project(project_id)
    if deleted is None:
        raise HTTPException(404, "Project not found")
    _broadcast({"type": "project_deleted", "project_id": project_id})
    return DeleteProjectResponse(project_id=project_id, rows_deleted=sum(deleted.values()), tables=deleted)


# ─── Jobs ──────────────────────────────────────────────────────────────

@router.get("/jobs/{project_id}", response_model=list[JobResponse])
def list_project_jobs(project_id: Annotated[int, Path(ge=1)],
                       _access: Annotated[dict, Depends(require_project_access)],
                       job_type: Optional[str] = None):
    return store.list_jobs(project_id, job_type)


@router.get("/job/{job_id}", response_model=JobResponse, dependencies=[Depends(require_job_access)])
def get_job_status(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
