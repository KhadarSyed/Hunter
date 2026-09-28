"""Request/response models for the Research Execution route group."""
from __future__ import annotations

from pydantic import BaseModel

from ...core.api import ApiModel


class ExecutionStartRequest(BaseModel):
    project_id: int


class RetryUnitRequest(BaseModel):
    project_id: int


# ─── Responses ─────────────────────────────────────────────────────────────

class ExecutionJobStarted(ApiModel):
    job_id: str
    project_id: int


class ExecutionResumeStarted(ApiModel):
    job_id: str


class ExecutionUnitStatus(ApiModel):
    id: int | None = None
    unit_id: str | None = None
    objective_id: str | None = None
    method: str | None = None
    status: str | None = None
    progress_pct: int | None = None
    records_processed: int | None = None
    evidence_count: int | None = None
    error: str | None = None


class ExecutionLogSummary(ApiModel):
    level: str | None = None
    message: str | None = None
    unit_id: str | None = None
    created_at: float | None = None


class ExecutionStatusResponse(ApiModel):
    run_id: int
    project_id: int | None = None
    plan_id: int | None = None
    status: str | None = None
    total_units: int | None = None
    completed_units: int | None = None
    failed_units: int | None = None
    skipped_units: int | None = None
    total_evidence: int | None = None
    elapsed_seconds: float | None = None
    started_at: float | None = None
    finished_at: float | None = None
    units: list[ExecutionUnitStatus] = []
    logs: list[ExecutionLogSummary] = []


class RetryUnitCompleted(ApiModel):
    status: str
    evidence_count: int
    run_id: int


class RetryUnitFailed(ApiModel):
    status: str
    error: str | None = None


class EvidenceRecord(ApiModel):
    """Row of intel_evidence (SELECT *); decoded `metrics` passes through when present."""

    id: int | None = None
    run_id: int | None = None
    unit_id: str | None = None
    objective_id: str | None = None
    evidence_type: str | None = None
    platform: str | None = None
    source: str | None = None
    date: str | None = None
    text_excerpt: str | None = None
    metrics_json: str | None = None
    confidence: str | None = None
    method: str | None = None
    rationale: str | None = None
    dataset: str | None = None
    created_at: float | None = None


class ExecutionLogRecord(ApiModel):
    """Row of intel_execution_logs (SELECT *)."""

    id: int | None = None
    run_id: int | None = None
    unit_id: str | None = None
    level: str | None = None
    message: str | None = None
    created_at: float | None = None
