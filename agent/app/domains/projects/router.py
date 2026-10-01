"""Project CRUD routes.

Also contains:
- jobs: Generic job-status lookup routes shared across pipeline stages.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status

from ...core import store
from ...core.auth import get_current_user, require_project_access
from ...core.events import broadcast as _broadcast
from .schemas import (
    CreateProjectRequest,
    DeleteProjectResponse,
    JobResponse,
    ProjectListItem,
    ProjectResponse,
    UpdateProjectRequest,
)

router = APIRouter()


@router.get("/projects", response_model=list[ProjectListItem])
def list_projects_route(
    user: Annotated[dict, Depends(get_current_user)], type: str | None = None,
):
    if user["role"] == "super_admin":
        return store.list_projects(project_type=type)
    if user["org_id"] is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No organization assigned")
    if user["role"] == "admin":
        return store.list_projects(project_type=type, org_id=user["org_id"])
    return store.list_projects(project_type=type, org_id=user["org_id"], owner_user_id=user["id"])


@router.post("/projects", response_model=ProjectResponse)
def create_project_route(
    req: CreateProjectRequest, user: Annotated[dict, Depends(get_current_user)],
):
    pid = store.create_project(req.project_name, req.spec, project_type=req.project_type, brand=req.brand)
    store.set_project_owner(pid, user["org_id"], user["id"])
    project = store.get_project(pid)
    return project


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project_route(project_id: Annotated[int, Path(ge=1)],
                       _access: Annotated[dict, Depends(require_project_access)]):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.put("/projects/{project_id}", response_model=ProjectResponse)
def update_project_route(project_id: Annotated[int, Path(ge=1)], req: UpdateProjectRequest,
                          _access: Annotated[dict, Depends(require_project_access)]):
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    store.update_project(project_id, req.project_name, req.spec, req.brand)
    return store.get_project(project_id)


@router.delete("/projects/{project_id}", response_model=DeleteProjectResponse)
def delete_project_route(project_id: Annotated[int, Path(ge=1)],
                          _access: Annotated[dict, Depends(require_project_access)]):
    """Archive a project (soft delete — see spec §5); rows/files are kept."""
    archived = store.archive_project(project_id)
    if archived is None:
        raise HTTPException(404, "Project not found")
    _broadcast({"type": "project_archived", "project_id": project_id})
    return DeleteProjectResponse(project_id=project_id, rows_deleted=0, tables={})


# ─── Jobs ──────────────────────────────────────────────────────────────

@router.get("/jobs/{project_id}", response_model=list[JobResponse])
def list_project_jobs(project_id: Annotated[int, Path(ge=1)],
                       _access: Annotated[dict, Depends(require_project_access)],
                       job_type: Optional[str] = None):
    return store.list_jobs(project_id, job_type)


@router.get("/job/{job_id}", response_model=JobResponse)
def get_job_status(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
