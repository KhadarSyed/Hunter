"""Request/response models for the Publishing & Quality Gateway route group."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ...core.api import ApiModel

Number = int | float


class PubValidateRequest(BaseModel):
    project_id: int
    presentation_id: int
    actor: str = "system"


class PubApprovalRequest(BaseModel):
    project_id: int
    presentation_id: int
    actor: str = "system"
    notes: str | None = None


class PubPackageRequest(BaseModel):
    project_id: int
    presentation_id: int
    actor: str = "system"


class PubVersionRequest(BaseModel):
    project_id: int
    presentation_id: int
    actor: str = "system"
    notes: str | None = None


# ─── Responses ───────────────────────────────────────────────────────────

class ValidationRunResponse(ApiModel):
    validation_id: int
    readiness_score: Number
    readiness_class: str
    scores: dict
    issues: list[dict]
    warnings: list
    critical_count: int
    total_issues: int
    duration_ms: int


class CompareOutputsResponse(ApiModel):
    diff_id: int
    match_pct: float
    differences: list
    summary: dict


class PackageBuildResponse(ApiModel):
    package_id: int
    package_path: str
    package_size_bytes: int
    file_count: int
    contents: list
    version: str | None = None


class VersionCreateResponse(ApiModel):
    version_id: int
    version_label: str
    major: int
    minor: int
    revision: int


class ApprovalActionResponse(ApiModel):
    approval_id: int
    status: str
    version_id: int | None = None


class PublishResponse(ApprovalActionResponse):
    package_id: int | None = None
    published_at: float


class PubStats(ApiModel):
    validations: int
    packages: int
    versions: int
    downloads: int
    publications: int


class ReadinessSummaryResponse(ApiModel):
    readiness_score: Number | None = None
    readiness_class: str | None = None
    scores: Any = None
    latest_validation_id: int | None = None
    latest_version: str | None = None
    latest_version_status: str | None = None
    latest_package_id: int | None = None
    latest_package_status: str | None = None
    diff_match_pct: Number | None = None
    latest_approval_action: str | None = None
    stats: PubStats


class PubVersion(ApiModel):
    """Row of intel_pub_versions."""
    id: int
    project_id: int
    presentation_id: int
    major: int
    minor: int
    revision: int
    version_label: str | None = None
    pipeline_version: str | None = None
    renderer_version: str | None = None
    presentation_version: int | None = None
    approval_status: str | None = None
    approved_by: str | None = None
    approved_at: float | None = None
    notes: str | None = None
    created_at: float


class PubAuditEntry(ApiModel):
    """Row of intel_pub_audit; details_json is decoded when valid JSON."""
    id: int
    project_id: int
    presentation_id: int | None = None
    entity_type: str
    entity_id: int | None = None
    action: str
    actor: str | None = None
    details_json: Any = None
    created_at: float


class PubValidation(ApiModel):
    """Row of intel_pub_validations; *_json columns are decoded when valid JSON."""
    id: int
    project_id: int
    presentation_id: int
    status: str
    readiness_score: Number | None = None
    readiness_class: str | None = None
    scores_json: Any = None
    issues_json: Any = None
    warnings_json: Any = None
    pptx_job_id: str | None = None
    word_job_id: str | None = None
    validated_by: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    created_at: float


class PubDiffReport(ApiModel):
    """Row of intel_pub_diff_reports; *_json columns are decoded when valid JSON."""
    id: int
    validation_id: int
    project_id: int
    presentation_id: int
    status: str
    match_pct: Number | None = None
    differences_json: Any = None
    summary_json: Any = None
    created_at: float


class PubPackage(ApiModel):
    """Row of intel_pub_packages; *_json columns are decoded when valid JSON."""
    id: int
    project_id: int
    presentation_id: int
    version_id: int | None = None
    validation_id: int | None = None
    status: str
    package_path: str | None = None
    package_size_bytes: int | None = None
    manifest_json: Any = None
    contents_json: Any = None
    created_by: str | None = None
    created_at: float
    finished_at: float | None = None


class PubDownload(ApiModel):
    """Row of intel_pub_downloads."""
    id: int
    project_id: int
    package_id: int | None = None
    file_type: str
    file_path: str
    file_size_bytes: int | None = None
    downloaded_by: str | None = None
    created_at: float


class PubApproval(ApiModel):
    """Row of intel_pub_approvals."""
    id: int
    project_id: int
    presentation_id: int
    version_id: int | None = None
    action: str
    status: str
    actor: str | None = None
    notes: str | None = None
    created_at: float
