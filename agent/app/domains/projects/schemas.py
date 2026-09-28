"""Request/response models for the Projects route group."""
from __future__ import annotations

from pydantic import BaseModel

from ...core.api import ApiModel


class CreateProjectRequest(BaseModel):
    project_name: str
    spec: dict = {}
    project_type: str = "research"
    brand: str | None = None  # Client name from the New Project form


class UpdateProjectRequest(BaseModel):
    project_name: str | None = None
    spec: dict | None = None
    brand: str | None = None  # Client name from the New Project form


# ─── Response models ─────────────────────────────────────────────────────────

class DeleteProjectResponse(ApiModel):
    ok: bool = True
    project_id: int
    rows_deleted: int
    tables: dict[str, int]  # rows deleted per table


class ProjectResponse(ApiModel):
    """A full `intel_projects` row plus the decoded `spec` blob."""

    id: int
    project_name: str | None = None
    spec_json: str | None = None
    created_at: float | None = None
    updated_at: float | None = None
    project_type: str | None = None
    brand: str | None = None
    spec: dict | None = None


class ProjectListItem(ApiModel):
    """Project-list card: row columns plus display fields derived from the spec."""

    id: int
    project_name: str | None = None
    project_type: str | None = None
    brand: str | None = None
    created_at: float | None = None
    updated_at: float | None = None
    description: str | None = None
    geography: str | None = None
    client: str | None = None


class JobResponse(ApiModel):
    """An `intel_jobs` row; `result` (decoded `result_json`) is present only when set."""

    id: str
    project_id: int | None = None
    job_type: str | None = None
    status: str | None = None
    progress_pct: int | None = None
    progress_message: str | None = None
    result_json: str | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    created_at: float | None = None
