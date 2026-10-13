"""Response models for the QC flow route group."""
from __future__ import annotations

from typing import Any

from ...core.api import ApiModel, OkResponse

Number = int | float


class QCUploadResponse(ApiModel):
    """`parse_error` is present only when parse_status is "error" (passed through as an extra key)."""
    report_id: int
    file_name: str | None = None
    parse_status: str


class QCReport(ApiModel):
    """Row of qc_reports; columns_json / field_mapping are decoded when valid JSON."""
    id: int
    project_id: int
    file_name: str
    file_path: str
    row_count: int | None = None
    column_count: int | None = None
    columns_json: Any = None
    field_mapping: Any = None
    parse_status: str | None = None
    parse_error: str | None = None
    created_at: float
    updated_at: float


class QCPreviewResponse(ApiModel):
    """`error` is present only when the file could not be parsed (extra key)."""
    status: str | None = None
    preview: list


class QCAllRowsResponse(ApiModel):
    """`columns` is absent when the file could not be parsed (extra key)."""
    rows: list


class QCFieldMappingSaveResponse(OkResponse):
    report_id: int


class QCRunStartResponse(ApiModel):
    status: str
    report_id: int
    job_id: str


class QCRun(ApiModel):
    """Row of qc_runs (score_breakdown is decoded only on the single-run endpoint)."""
    id: int
    report_id: int
    status: str | None = None
    total_rows: int | None = None
    total_checks: int | None = None
    total_findings: int | None = None
    score: Number | None = None
    score_breakdown: Any = None
    started_at: float | None = None
    completed_at: float | None = None
    created_at: float


class QCFinding(ApiModel):
    """Row of qc_findings."""
    id: int
    run_id: int
    report_id: int
    check_type: str
    row_number: int | None = None
    column_name: str | None = None
    severity: str
    message: str
    expected: str | None = None
    actual: str | None = None
    source_url: str | None = None
    analyst_action: str | None = None
    created_at: float


class QCExportResponse(ApiModel):
    export_id: int
    file_name: str
    file_path: str
