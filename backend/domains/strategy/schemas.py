"""Request/response models for the Search Strategy route group.

GenerateStrategyRequest is reused by the Plan route group (imported from here rather
than duplicated) since Strategy is its primary/first use.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from ...core.api import ApiModel


class EditQueryRequest(BaseModel):
    query_type: str
    query_text: str


class GenerateStrategyRequest(BaseModel):
    project_id: int


class FinalApprovalRequest(BaseModel):
    reviewer: str = "analyst"
    sample_evaluation_waived: bool = False
    acknowledge_meltwater_validation: bool = False


class EnrichmentStartResponse(ApiModel):
    job_id: str
    dataset_id: int


class AddRQRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    query: str = Field(default="", max_length=10000)

    @field_validator("question", "query", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class AddRQResult(ApiModel):
    question_id: str


class EditRQRequest(BaseModel):
    question_id: str
    question: str
    query: str = ""


# ─── Response models ─────────────────────────────────────────────────────────
# Row models declare columns in table order so the serialized key order is unchanged.

class StrategyJobStarted(ApiModel):
    job_id: str
    project_id: int


class QueryVersion(ApiModel):
    """intel_query_versions row."""

    id: int
    strategy_id: int
    version_label: str | None = None
    query_type: str | None = None
    query_text: str | None = None
    is_active: int | None = None
    created_at: float | None = None


class SearchStrategyResponse(ApiModel):
    strategy_id: int
    version: int
    approval_status: str | None = None
    strategy: dict
    query_versions: list[QueryVersion]
    created_at: float | None = None


class EditQueryResponse(ApiModel):
    version_id: int
    validation_issues: list[str]
    validation_status: str


class FinalApprovalResult(ApiModel):
    """Either {approved: False, blocking_reasons} or the full approval record."""

    approved: bool


class DatasetUploadResponse(ApiModel):
    dataset_id: int
    job_id: str
    file_name: str | None = None
    processing_status: str
    research_question_id: str | None = None


class DatasetRecord(ApiModel):
    """intel_datasets row plus decoded column_mapping / stats / preview."""

    id: int
    project_id: int
    file_name: str | None = None
    file_path: str | None = None
    record_count: int | None = None
    column_mapping_json: str | None = None
    stats_json: str | None = None
    preview_json: str | None = None
    approval_status: str | None = None
    approved_by: str | None = None
    approved_at: float | None = None
    created_at: float | None = None
    processing_status: str | None = None
    processing_error: str | None = None
    research_question_id: str | None = None
    column_mapping: dict
    stats: dict
    preview: list[dict]


class EvaluationUploadResponse(ApiModel):
    job_id: str
    eval_id: int


class SampleEvaluationRecord(ApiModel):
    """intel_sample_evaluations row; decoded `evaluation` passes through when present."""

    id: int
    project_id: int
    strategy_id: int
    file_name: str | None = None
    file_path: str | None = None
    evaluation_json: str | None = None
    status: str | None = None
    created_at: float | None = None
