"""Request/response models for the Research Specification route group."""
from __future__ import annotations

from pydantic import BaseModel


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
