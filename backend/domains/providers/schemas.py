"""Request/response models for an organisation's LLM providers. The API key is write-only: responses carry a hint."""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

from ...core.api import ApiModel

ProviderType = Literal["openai_compatible", "azure_openai", "anthropic", "gemini"]
_NEEDS_URL = ("openai_compatible", "azure_openai")


class ProviderFields(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider_type: ProviderType
    base_url: str = Field(default="", max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_version: str = Field(default="", max_length=40)
    reads_images: bool | None = None    # can it read images (photo checks)? None = not known; learned on first refusal

    @model_validator(mode="after")
    def _check(self) -> "ProviderFields":
        self.name, self.model = self.name.strip(), self.model.strip()
        self.base_url, self.api_version = self.base_url.strip().rstrip("/"), self.api_version.strip()
        if not self.name or not self.model:
            raise ValueError("Name and model are required")
        if self.provider_type in _NEEDS_URL and not self.base_url:
            raise ValueError("Base URL is required for this provider type")
        if self.base_url:
            from ..deckstudio.verbatims import is_public_http   # local: same lazy import as core/safe_fetch
            u = urlparse(self.base_url)
            if u.scheme != "https" or not u.netloc:
                raise ValueError("Base URL must be an https:// address")
            if not is_public_http(self.base_url):           # the server calls it: never an address inside our network
                raise ValueError("Base URL must be a public internet address")
        return self


class ProviderCreate(ProviderFields):
    org_id: int | None = None           # Super Admin picks the org; an Admin always manages their own
    api_key: str = Field(min_length=1, max_length=500)


class ProviderUpdate(ProviderFields):
    api_key: str = Field(default="", max_length=500)    # blank keeps the saved key


class ProviderTestRequest(ProviderFields):
    org_id: int | None = None
    provider_id: int | None = None      # testing an edit of a saved provider: a blank key uses the saved one
    api_key: str = Field(default="", max_length=500)


class ProviderEnabled(ApiModel):
    """Switch a saved model on or off (off: never called, not even as a fallback)."""
    enabled: bool


class PlatformAccess(ApiModel):
    """Super Admin: may this org's calls use the platform model (GPT, billed to the platform)?"""
    org_id: int | None = None
    enabled: bool


class ProviderRecord(ApiModel):
    id: int
    org_id: int
    name: str
    provider_type: str
    base_url: str
    model: str
    api_version: str
    key_hint: str
    is_default: bool
    enabled: bool = True
    reads_images: bool | None = None
    status: str
    last_error: str
    last_tested_at: float | None = None
    last_latency_ms: int | None = None
    updated_at: float

    @classmethod
    def from_row(cls, row: dict) -> "ProviderRecord":
        images = row.get("reads_images")
        return cls(**{**{k: row[k] for k in cls.model_fields if k in row}, "is_default": bool(row["is_default"]),
                      "enabled": bool(row.get("enabled", 1)),
                      "reads_images": None if images is None else bool(images)})


class ProvidersResponse(ApiModel):
    org_id: int
    org_name: str
    platform_model: str
    platform_llm: bool                  # the org may run on the platform model (InfoVision)
    providers: list[ProviderRecord]
    outage: dict | None = None          # live outage: acting_provider_id, down_since, paused, last_error, failed_calls


class TestResult(ApiModel):
    ok: bool
    latency_ms: int
    reply: str
    error: str
