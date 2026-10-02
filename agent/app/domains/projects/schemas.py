"""Request/response models for the Projects route group."""
from __future__ import annotations

from pydantic import BaseModel, model_validator

from ...core.api import ApiModel

# Fields the New Project form requires for every project, keyed by the name they're
# stored under in `spec` — mirrors the frontend's `qcFieldsValid`/`researchFieldsValid`
# checks in web/src/pages/NewProject.tsx so client and server reject the same inputs.
# File upload is intentionally excluded — it's one of two ways to fill in the brief
# text (the other being paste/type), never required on its own.
_QC_REQUIRED_SPEC_FIELDS = ("geography",)
_RESEARCH_REQUIRED_SPEC_FIELDS = ("geography", "research_type", "time_period", "raw_brief")


def _require_project_fields(project_name: str, brand: str | None, project_type: str, spec: dict) -> None:
    missing = []
    if not project_name.strip():
        missing.append("project_name")
    if not (brand or "").strip():
        missing.append("brand (Client)")
    required_spec_fields = _QC_REQUIRED_SPEC_FIELDS if project_type == "monitoring_qc" else _RESEARCH_REQUIRED_SPEC_FIELDS
    for field in required_spec_fields:
        if not str(spec.get(field) or "").strip():
            missing.append(f"spec.{field}")
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")


class CreateProjectRequest(BaseModel):
    project_name: str
    spec: dict = {}
    project_type: str = "research"
    brand: str | None = None  # Client name from the New Project form

    @model_validator(mode="after")
    def _check_required_fields(self) -> "CreateProjectRequest":
        _require_project_fields(self.project_name, self.brand, self.project_type, self.spec)
        return self


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
    brief_source: dict | None = None  # {type: pdf|docx|pptx|xlsx|doc|ppt|xls|txt|text, file_name}


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
