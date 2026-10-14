"""Request bodies for the agent routes."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AutopilotStart(BaseModel):
    input_folder: str | None = Field(default=None, max_length=500)


class CopilotMessage(BaseModel):
    message: str = Field(default="", max_length=4000)
    confirm: str | None = Field(default=None, max_length=64)


class RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
