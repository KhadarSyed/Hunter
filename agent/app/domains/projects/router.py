"""Project CRUD routes.

Also contains:
- jobs: Generic job-status lookup routes shared across pipeline stages.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from ...core import store
from .schemas import CreateProjectRequest, UpdateProjectRequest

router = APIRouter()


@router.get("/projects")
def list_projects_route(type: str | None = None):
    return store.list_projects(project_type=type)


@router.post("/projects")
def create_project_route(req: CreateProjectRequest):
    pid = store.create_project(req.project_name, req.spec, project_type=req.project_type)
    project = store.get_project(pid)
    return project


@router.get("/projects/{project_id}")
def get_project_route(project_id: int):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.put("/projects/{project_id}")
def update_project_route(project_id: int, req: UpdateProjectRequest):
    if not store.get_project(project_id):
        raise HTTPException(404, "Project not found")
    store.update_project(project_id, req.project_name, req.spec)
    return store.get_project(project_id)


# ─── Jobs ──────────────────────────────────────────────────────────────

@router.get("/jobs/{project_id}")
def list_project_jobs(project_id: int, job_type: Optional[str] = None):
    return store.list_jobs(project_id, job_type)


@router.get("/job/{job_id}")
def get_job_status(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
