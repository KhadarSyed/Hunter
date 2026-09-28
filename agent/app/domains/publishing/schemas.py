"""Request/response models for the Publishing & Quality Gateway route group."""
from __future__ import annotations

from pydantic import BaseModel


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
