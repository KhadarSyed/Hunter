"""Request/response models for the Search Strategy route group.

GenerateStrategyRequest is reused by the Plan route group (imported from here rather
than duplicated) since Strategy is its primary/first use.
"""
from __future__ import annotations

from pydantic import BaseModel


class EditQueryRequest(BaseModel):
    query_type: str
    query_text: str


class GenerateStrategyRequest(BaseModel):
    project_id: int


class FinalApprovalRequest(BaseModel):
    reviewer: str = "analyst"
    sample_evaluation_waived: bool = False
    acknowledge_meltwater_validation: bool = False


class EditRQRequest(BaseModel):
    question_id: str
    question: str
    query: str = ""
