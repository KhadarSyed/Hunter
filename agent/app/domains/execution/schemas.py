"""Request/response models for the Research Execution route group."""
from __future__ import annotations

from pydantic import BaseModel


class ExecutionStartRequest(BaseModel):
    project_id: int


class RetryUnitRequest(BaseModel):
    project_id: int
