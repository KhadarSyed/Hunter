"""Request/response models for the Projects route group."""
from __future__ import annotations

from pydantic import BaseModel


class CreateProjectRequest(BaseModel):
    project_name: str
    spec: dict = {}
    project_type: str = "research"


class UpdateProjectRequest(BaseModel):
    project_name: str | None = None
    spec: dict | None = None
