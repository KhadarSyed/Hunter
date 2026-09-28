"""Request/response models for the Research Plan route group."""
from __future__ import annotations

from pydantic import BaseModel

from ...core.api import ApiModel


class PlanApproveRequest(BaseModel):
    reviewer: str = "analyst"


class PlanRejectRequest(BaseModel):
    notes: str = ""


class PlanRegenerateRequest(BaseModel):
    project_id: int


# ─── Responses ─────────────────────────────────────────────────────────────

class PlanJobStarted(ApiModel):
    job_id: str
    project_id: int


class PlanPrerequisitesResponse(ApiModel):
    ready: bool
    prerequisites: dict


class PlanBlocked(ApiModel):
    status: str
    error: str
    prerequisites: dict


class ResearchPlanRecord(ApiModel):
    """Row of intel_research_plans (SELECT *) plus the decoded `plan` blob."""

    id: int | None = None
    project_id: int | None = None
    version: int | None = None
    status: str | None = None
    plan_json: str | None = None
    source: str | None = None
    approval_status: str | None = None
    approved_by: str | None = None
    approved_at: float | None = None
    notes: str | None = None
    created_at: float | None = None
    plan: dict | None = None
