"""Request/response models for the Data Sources route group."""
from __future__ import annotations

from pydantic import BaseModel

from ...core.api import ApiModel

VENDOR_META: dict[str, dict[str, str]] = {
    "tavily": {
        "display_name": "Tavily",
        "renew_url": "https://app.tavily.com/home",
    },
    "serpapi": {
        "display_name": "SerpAPI",
        "renew_url": "https://serpapi.com/manage-api-key",
    },
}


def _mask(api_key: str) -> str:
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}{'*' * (len(api_key) - 8)}{api_key[-4:]}"


class UpsertKeyRequest(BaseModel):
    api_key: str


class DataSourceRecord(ApiModel):
    source: str
    display_name: str
    renew_url: str
    configured: bool
    masked_key: str | None = None
    status: str = "not_configured"  # not_configured | ok | expired
    expired_at: float | None = None
    last_error: str | None = None
    updated_at: float | None = None

    @classmethod
    def from_row(cls, source: str, row: dict | None) -> "DataSourceRecord":
        meta = VENDOR_META[source]
        if row is None:
            return cls(source=source, display_name=meta["display_name"], renew_url=meta["renew_url"],
                        configured=False)
        return cls(
            source=source, display_name=meta["display_name"], renew_url=meta["renew_url"],
            configured=True, masked_key=_mask(row["api_key"]), status=row["status"],
            expired_at=row["expired_at"], last_error=row["last_error"], updated_at=row["updated_at"],
        )


class ValidateResult(ApiModel):
    source: str
    status: str  # ok | expired
    error: str | None = None
