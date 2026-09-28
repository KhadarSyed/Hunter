"""Request/response models for the Research Specification route group."""
from __future__ import annotations

from pydantic import BaseModel

from ...core.api import ApiModel


class GenerateSpecRequest(BaseModel):
    project_id: int
    raw_brief_text: str = ""
    use_llm: bool = False


class UpdateSpecSectionRequest(BaseModel):
    section_key: str
    content: str | dict | list
    analyst_note: str = ""


class ApproveSpecSectionRequest(BaseModel):
    section_key: str
    reviewer: str = "analyst"


class LockSpecSectionRequest(BaseModel):
    section_key: str
    locked_by: str = "analyst"


class ApproveSpecRequest(BaseModel):
    reviewer: str = "analyst"


class RejectSpecRequest(BaseModel):
    reason: str = ""
    reviewer: str = "analyst"


class RegenerateSpecRequest(BaseModel):
    raw_brief_text: str = ""
    use_llm: bool = False
    confirm_overwrite_locked: bool = False


class ResolveClarificationRequest(BaseModel):
    answer: str
    resolved_by: str = "analyst"


class AddClarificationRequest(BaseModel):
    question: str
    section_key: str = ""
    is_blocking: bool = True


# ─── Response models ─────────────────────────────────────────────────────────

class SpecClarification(ApiModel):
    """An `intel_spec_clarifications` row (`is_blocking` is SQLite 0/1)."""

    id: int
    spec_id: int | None = None
    section_key: str | None = None
    question: str | None = None
    is_blocking: int | None = None
    answer: str | None = None
    resolved_by: str | None = None
    resolved_at: float | None = None
    created_at: float | None = None
    updated_at: float | None = None


class SpecReadinessResponse(ApiModel):
    status: str
    blocking_issues: list[str] = []
    warnings: list[str] = []
    section_status: dict[str, str] = {}
    filled_count: int | None = None
    total_count: int | None = None
    completeness_pct: int | None = None


class SpecResponse(ApiModel):
    """An `intel_research_specifications` row plus decoded `spec`/`readiness`, per-section
    approval rows keyed by section_key, and the spec's clarifications."""

    id: int
    project_id: int | None = None
    version: int | None = None
    spec_json: str | None = None
    raw_brief_text: str | None = None
    status: str | None = None
    readiness_status: str | None = None
    readiness_json: str | None = None
    approval_status: str | None = None
    approved_by: str | None = None
    approved_at: float | None = None
    rejected_reason: str | None = None
    generation_source: str | None = None
    llm_model: str | None = None
    docx_path: str | None = None
    docx_generated_at: float | None = None
    notes: str | None = None
    created_at: float | None = None
    updated_at: float | None = None
    spec: dict | None = None
    readiness: dict | None = None
    section_approvals: dict[str, dict] = {}
    clarifications: list[dict] = []


class GeneratedSpecResponse(ApiModel):
    """Result of generate/regenerate; `clarifications` is present only on generate."""

    spec_id: int
    spec: dict | None = None
    readiness: dict | None = None


class SpecSectionStatusResponse(ApiModel):
    status: str
    section_key: str


class SpecStatusResponse(ApiModel):
    status: str
    spec_id: int


class SpecRenderResponse(ApiModel):
    status: str
    docx_path: str | None = None


class SpecVersionItem(ApiModel):
    id: int
    version: int | None = None
    status: str | None = None
    readiness_status: str | None = None
    approval_status: str | None = None
    generation_source: str | None = None
    docx_path: str | None = None
    created_at: float | None = None
    updated_at: float | None = None


class SpecAuditEntry(ApiModel):
    id: int
    spec_id: int | None = None
    action: str | None = None
    section_key: str | None = None
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    actor: str | None = None
    created_at: float | None = None


class ClarificationStatusResponse(ApiModel):
    status: str
    clarification_id: int
