"""An organisation's own chat LLM providers: list, add, edit (replace the key), remove, set default, test.

An Admin manages their (active) org; a Super Admin any org (org_id query/body, else their active org). Keys are
encrypted at rest and never returned. A new provider becomes the default; removing the default promotes the newest
one left. Changing the default applies to the org's next chat call.
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ...core import secret_box, store
from ...core.auth import get_current_user
from . import repository as repo
from . import service
from .schemas import (ProviderCreate, ProviderRecord, ProvidersResponse, ProviderTestRequest, ProviderUpdate,
                      TestResult)

router = APIRouter()
UserDep = Annotated[dict, Depends(get_current_user)]


def _org(user: dict, org_id: int | None) -> int:
    if user["role"] == "super_admin":
        org = org_id or user.get("org_id")
        if not org:
            raise HTTPException(400, "Pick an organization")
    elif user["role"] == "admin" and user.get("org_id") and org_id in (None, user["org_id"]):
        org = user["org_id"]
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an organization admin can manage LLM providers")
    if not store.get_organization_by_id(org):
        raise HTTPException(404, "Organization not found")
    return org


def _owned(user: dict, provider_id: int) -> dict:
    row = repo.get(provider_id)
    if not row:
        raise HTTPException(404, "Provider not found")
    _org(user, row["org_id"])
    return row


def _fields(body) -> dict:
    return {f: getattr(body, f) for f in repo.FIELDS}


def _saved_key(row: dict) -> str:
    try:
        return secret_box.decrypt(row["api_key_enc"])
    except secret_box.SecretUnreadable as e:
        repo.record_test(row["id"], False, str(e), 0)
        raise HTTPException(422, str(e)) from e


@router.get("/llm-providers", response_model=ProvidersResponse)
def list_providers(user: UserDep, org_id: int | None = None):
    org = _org(user, org_id)
    return {"org_id": org, "org_name": store.get_organization_by_id(org)["name"],
            "platform_model": os.getenv("AZURE_OPENAI_MODEL", "") or "not configured",
            "platform_llm": store.org_uses_platform_llm(org),
            "providers": [ProviderRecord.from_row(r) for r in repo.list_for_org(org)]}


@router.get("/llm-providers/status")
def provider_status(user: UserDep):
    """Any member: does the active org have a model? (New Project warns before the first AI step would fail.)"""
    org = user.get("org_id")
    if not org:
        return {"ready": True, "source": "platform", "model": os.getenv("AZURE_OPENAI_MODEL", "")}
    row = repo.default_for_org(org)
    if row:
        return {"ready": True, "source": "org", "model": row["model"], "name": row["name"]}
    if store.org_uses_platform_llm(org):
        return {"ready": True, "source": "platform", "model": os.getenv("AZURE_OPENAI_MODEL", "")}
    return {"ready": False, "source": "none", "model": "", "can_manage": user["role"] in ("admin", "super_admin")}


@router.post("/llm-providers", response_model=ProviderRecord)
def create_provider(body: ProviderCreate, user: UserDep):
    org = _org(user, body.org_id)
    key = body.api_key.strip()
    if not key:
        raise HTTPException(422, "API key is required")
    pid = repo.create(org, _fields(body), secret_box.encrypt(key), secret_box.hint(key), user["id"])
    repo.set_default(org, pid)          # the newest provider takes over: first priority
    service.invalidate(org)
    return ProviderRecord.from_row(repo.get(pid))


@router.put("/llm-providers/{provider_id}", response_model=ProviderRecord)
def update_provider(provider_id: int, body: ProviderUpdate, user: UserDep):
    row = _owned(user, provider_id)
    key = body.api_key.strip()
    repo.update(provider_id, _fields(body), secret_box.encrypt(key) if key else None,
                secret_box.hint(key) if key else None, user["id"])
    service.invalidate(row["org_id"])
    return ProviderRecord.from_row(repo.get(provider_id))


@router.delete("/llm-providers/{provider_id}")
def delete_provider(provider_id: int, user: UserDep):
    row = _owned(user, provider_id)
    repo.delete(provider_id)
    if row["is_default"]:               # the newest provider left takes over (none left: no model)
        nxt = repo.newest_for_org(row["org_id"])
        if nxt:
            repo.set_default(row["org_id"], nxt["id"])
    service.invalidate(row["org_id"])
    return {"ok": True}


@router.post("/llm-providers/use-platform")
def use_platform(user: UserDep, org_id: int | None = None):
    """No default provider: the org's chat calls go back to the platform model."""
    org = _org(user, org_id)
    if not store.org_uses_platform_llm(org):
        raise HTTPException(400, "This organization runs on its own models: add or pick one instead")
    repo.set_default(org, None)
    service.invalidate(org)
    return {"ok": True}


@router.post("/llm-providers/test", response_model=TestResult)
def test_draft(body: ProviderTestRequest, user: UserDep):
    """Test settings before (or without) saving them; a blank key on an edit uses the saved key."""
    key = body.api_key.strip()
    if body.provider_id:
        row = _owned(user, body.provider_id)
        key = key or _saved_key(row)
    else:
        _org(user, body.org_id)
    if not key:
        raise HTTPException(422, "API key is required")
    return service.test_connection(_fields(body), key)


@router.post("/llm-providers/{provider_id}/default", response_model=ProviderRecord)
def make_default(provider_id: int, user: UserDep):
    row = _owned(user, provider_id)
    repo.set_default(row["org_id"], provider_id)
    service.invalidate(row["org_id"])
    return ProviderRecord.from_row(repo.get(provider_id))


@router.post("/llm-providers/{provider_id}/test", response_model=TestResult)
def test_saved(provider_id: int, user: UserDep):
    row = _owned(user, provider_id)
    result = service.test_connection({f: row[f] for f in repo.FIELDS}, _saved_key(row))
    repo.record_test(provider_id, result["ok"], result["error"], result["latency_ms"])
    return result
