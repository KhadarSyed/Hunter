"""Org guardrails: the org's Admin adds, edits and deletes them; a Super Admin can read any org's."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from ...core.api import ApiModel
from ...core.auth import get_current_user
from . import repository as repo
from . import service

router = APIRouter(prefix="/guardrails", tags=["guardrails"])
User = Annotated[dict, Depends(get_current_user)]


class GuardrailRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=100_000)
    active: bool = True


def _admin_org(user: dict) -> int:
    if user["role"] != "admin" or not user.get("org_id"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the organization's Admin can change guardrails")
    return user["org_id"]


def _own(gid: int, user: dict) -> dict:
    row = repo.get_guardrail(gid)
    if not row or row["org_id"] != _admin_org(user):
        raise HTTPException(404, "Guardrail not found")
    return row


class ContentPolicy(ApiModel):
    allow_editorial_images: bool


def _policy_org(user: dict) -> int:
    org = user.get("org_id")
    if not org:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No organization")
    return org


@router.get("/policy")
def get_policy(user: User):
    """The org's deck image policy: licence-safe photos only (default) or editorial article / web images too."""
    from ...core import store
    return {"allow_editorial_images": store.get_allow_editorial_images(_policy_org(user))}


@router.put("/policy")
def set_policy(req: ContentPolicy, user: User):
    org = _admin_org(user)
    from ...core import store
    store.set_allow_editorial_images(org, req.allow_editorial_images)
    return {"allow_editorial_images": req.allow_editorial_images}


@router.get("")
def list_route(user: User, org_id: int | None = None):
    if user["role"] == "super_admin":
        target = org_id or user.get("active_org_id")
    else:
        target = user.get("org_id")
    if not target:
        return []
    return repo.list_guardrails(target)


@router.post("")
def add_route(req: GuardrailRequest, user: User):
    org_id = _admin_org(user)
    gid = repo.add_guardrail(org_id, req.title.strip(), req.body, req.active, user["id"])
    service.changed(org_id)
    return repo.get_guardrail(gid)


@router.put("/{gid}")
def update_route(gid: int, req: GuardrailRequest, user: User):
    row = _own(gid, user)
    repo.update_guardrail(gid, req.title.strip(), req.body, req.active, user["id"])
    service.changed(row["org_id"])
    return repo.get_guardrail(gid)


@router.delete("/{gid}")
def delete_route(gid: int, user: User):
    row = _own(gid, user)
    repo.delete_guardrail(gid)
    service.changed(row["org_id"])
    return {"ok": True}
