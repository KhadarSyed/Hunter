"""Request/response models for the Data Sources route group."""
from __future__ import annotations

from pydantic import BaseModel, Field

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
    "firecrawl": {
        "display_name": "Firecrawl",
        "renew_url": "https://www.firecrawl.dev/app/api-keys",
    },
}

# Firecrawl's research options (Settings > Data Sources): on/off, results per search, scrape full pages for summaries
FIRECRAWL_DEFAULTS = {"enabled": True, "max_results": 5, "full_content": True}


def _mask(api_key: str) -> str:
    """Only the last 4 characters are ever shown."""
    return f"••••{api_key[-4:]}" if len(api_key) > 4 else "••••"


class UpsertKeyRequest(BaseModel):
    api_key: str
    settings: dict | None = None


class SourceSettings(BaseModel):
    enabled: bool = True
    max_results: int = Field(default=5, ge=1, le=20)
    full_content: bool = True


class DataSourceRecord(ApiModel):
    source: str
    display_name: str
    renew_url: str
    configured: bool
    masked_key: str | None = None
    status: str = "not_configured"  # not_configured | ok | expired | unverified | quota
    expired_at: float | None = None
    last_error: str | None = None
    updated_at: float | None = None
    settings: dict | None = None    # Firecrawl only

    @classmethod
    def from_row(cls, source: str, row: dict | None) -> "DataSourceRecord":
        meta = VENDOR_META[source]
        defaults = FIRECRAWL_DEFAULTS if source == "firecrawl" else None
        if row is None:
            return cls(source=source, display_name=meta["display_name"], renew_url=meta["renew_url"],
                       configured=False, settings=defaults)
        return cls(
            source=source, display_name=meta["display_name"], renew_url=meta["renew_url"],
            configured=True, masked_key=_mask(row["api_key"]), status=row["status"],
            expired_at=row["expired_at"], last_error=row["last_error"], updated_at=row["updated_at"],
            settings={**defaults, **(row.get("settings") or {})} if defaults else None,
        )


class ValidateResult(ApiModel):
    source: str
    status: str  # ok | expired | unverified | quota
    error: str | None = None
