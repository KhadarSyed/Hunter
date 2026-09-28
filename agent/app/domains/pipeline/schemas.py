"""Request/response models for the Pipeline Orchestrator route group."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from ...core.api import ApiModel

Number = int | float


class StartPipelineRequest(BaseModel):
    project_id: int
    mode: str = "full"
    start_stage: Optional[str] = None
    single_stage: Optional[str] = None
    user: str = "system"


class RetryStageRequest(BaseModel):
    stage_id: str


class ClearCacheRequest(BaseModel):
    stage_id: Optional[str] = None


# ─── Responses ───────────────────────────────────────────────────────────

class PipelineActionResponse(ApiModel):
    """start / run-stage / run-from / pause / resume / cancel.

    Failures come back with HTTP 200 and only an `error` key (passed through as an
    extra field), so every declared field is optional."""
    run_id: str | None = None
    status: str | None = None


class RetryStageResponse(PipelineActionResponse):
    stage_id: str | None = None


class PipelineRun(ApiModel):
    """Row of intel_pipeline_runs; *_json columns are decoded when valid JSON."""
    id: str
    project_id: int
    status: str
    execution_mode: str
    current_stage: str | None = None
    start_stage: str | None = None
    completed_stages_json: Any = None
    remaining_stages_json: Any = None
    skipped_stages_json: Any = None
    progress_pct: Number | None = None
    estimated_remaining_ms: Number | None = None
    user: str | None = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    created_at: float


class PipelineStage(ApiModel):
    """Row of intel_pipeline_stages; *_json columns are decoded when valid JSON."""
    id: int
    run_id: str
    stage_id: str
    stage_name: str
    status: str
    version: int | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    dependencies_json: Any = None
    execution_time_ms: Number | None = None
    started_at: float | None = None
    completed_at: float | None = None
    logs_json: Any = None
    warnings_json: Any = None
    errors_json: Any = None
    cache_status: str | None = None
    result_json: Any = None
    created_at: float


class PipelineStatusResponse(PipelineRun):
    stages: list[PipelineStage]


class PipelinePerformance(ApiModel):
    total_runs: int
    completed_runs: int | None = None
    failed_runs: int | None = None
    avg_duration_ms: Number | None = None
    cache_entries: int
    cache_hit_ratio: Number
    stage_averages: dict[str, dict]
    cache_breakdown: dict[str, int]


class ProjectPipelineStatusResponse(ApiModel):
    project_id: int
    stage_statuses: dict[str, dict]
    latest_run: PipelineRun | None = None
    recent_runs: list[PipelineRun]
    performance: PipelinePerformance
    dependency_graph: dict[str, dict]


class TimelineEntry(ApiModel):
    stage_id: str
    stage_name: str
    status: str
    started_at: float | None = None
    completed_at: float | None = None
    execution_time_ms: Number | None = None
    cache_status: str | None = None


class PipelineLogEntry(ApiModel):
    """Row of intel_pipeline_logs; details_json is decoded when valid JSON."""
    id: int
    run_id: str
    stage_id: str | None = None
    level: str | None = None
    message: str
    details_json: Any = None
    created_at: float


class CacheMetricsResponse(ApiModel):
    total_entries: int
    entries: list[dict]
    stages_cached: list[str]


class CacheClearResponse(ApiModel):
    cleared: int


class DependencyGraphNode(ApiModel):
    name: str
    order: int
    dependencies: list[str]
    downstream: list[str]
    requires_approval: bool


class StageStatus(ApiModel):
    """Per-stage status; extra keys (id, count, approved, total) vary by stage."""
    stage_id: str
    name: str
    order: int
    status: str
    exists: bool
