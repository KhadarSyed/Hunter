"""Request/response models for the Pipeline Orchestrator route group."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


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
