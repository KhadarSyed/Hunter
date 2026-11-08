"""Org-managed Data Source credential routes: list, set key, validate.

Admin/Super Admin manage their own org's Tavily/SerpAPI keys; the bell-icon
notification (ProfileMenu/Sidebar) reads the same list filtered to 'expired'.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from ...core.auth import get_current_user
from ...core.db import _conn
from . import repository as ds_repo
from . import service
from .schemas import FIRECRAWL_DEFAULTS, DataSourceRecord, SourceSettings, UpsertKeyRequest, ValidateResult

router = APIRouter()


def _effective_org_id(user: dict) -> int:
    """Admin: their own org. Super Admin has org_id=NULL by design (not tied to one org),
    so they manage the seeded Default Organization's keys here — this app is effectively
    single-tenant in practice despite the multi-org data model (see CLAUDE.md)."""
    if user["org_id"] is not None:
        return user["org_id"]
    conn = _conn()
    row = conn.execute("SELECT id FROM organizations WHERE name = 'Default Organization'").fetchone()
    conn.close()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No default organization found")
    return row["id"]


def _require_admin(user: dict) -> None:
    if user["role"] not in ("admin", "super_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")


@router.get("/datasources", response_model=list[DataSourceRecord])
def list_datasources(user: Annotated[dict, Depends(get_current_user)]):
    _require_admin(user)
    org_id = _effective_org_id(user)
    rows = {r["source"]: r for r in ds_repo.get_org_sources(org_id)}
    return [DataSourceRecord.from_row(s, rows.get(s)) for s in ds_repo.SOURCES]


Source = Annotated[str, Path(pattern="^(tavily|serpapi|firecrawl)$")]


@router.put("/datasources/{source}", response_model=DataSourceRecord)
def set_datasource_key(source: Source, req: UpsertKeyRequest, user: Annotated[dict, Depends(get_current_user)]):
    """Save (encrypted). Firecrawl's key is checked first: rejected (401) is refused, unreachable is saved as
    'unverified' and checked on first use, out of credits is saved as 'quota'."""
    _require_admin(user)
    key = req.api_key.strip()
    if not key:
        raise HTTPException(422, "API key is required")
    org_id = _effective_org_id(user)
    if source == "firecrawl":
        settings = {**FIRECRAWL_DEFAULTS, **SourceSettings(**(req.settings or {})).model_dump()}
        state, msg = service.check_firecrawl(key)
        if state == "expired":
            raise HTTPException(422, msg)
        row = ds_repo.upsert_key(org_id, source, key, user["id"], status=state, error=msg, settings=settings)
    else:
        row = ds_repo.upsert_key(org_id, source, key, user["id"])
    return DataSourceRecord.from_row(source, row)


@router.patch("/datasources/{source}/settings", response_model=DataSourceRecord)
def set_datasource_settings(source: Source, req: SourceSettings, user: Annotated[dict, Depends(get_current_user)]):
    _require_admin(user)
    if source != "firecrawl":
        raise HTTPException(422, f"{source} has no settings")
    row = ds_repo.update_settings(_effective_org_id(user), source, req.model_dump())
    if not row:
        raise HTTPException(404, "Save the key first")
    return DataSourceRecord.from_row(source, row)


@router.delete("/datasources/{source}", response_model=DataSourceRecord)
def remove_datasource_key(source: Source, user: Annotated[dict, Depends(get_current_user)]):
    """Remove the org's key: the source is no longer used (Tavily/SerpAPI fall back to the shared keys)."""
    _require_admin(user)
    ds_repo.delete_key(_effective_org_id(user), source)
    return DataSourceRecord.from_row(source, None)


@router.post("/datasources/{source}/validate", response_model=ValidateResult)
def validate_datasource_key(
    source: Source,
    user: Annotated[dict, Depends(get_current_user)],
):
    _require_admin(user)
    org_id = _effective_org_id(user)
    api_key = ds_repo.get_key(org_id, source)
    if not api_key:
        raise HTTPException(404, f"No {source} key configured for your organization")
    result_status, error = service.validate_and_record(org_id, source, api_key)
    return ValidateResult(source=source, status=result_status, error=error)
