"""Settings API for the exclusion list: Admins and Analysers manage their organization's excluded websites and
keywords (a Super Admin, their own organization's)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from ...core import store
from ...core.api import OkResponse
from ...core.auth import get_current_user
from . import service
from .schemas import AddExclusionRequest, ExclusionRecord

router = APIRouter()
User = Annotated[dict, Depends(get_current_user)]
MAX_RULES = 500
ROLES = ("super_admin", "admin", "analyser")


def _member(user: dict) -> dict:
    if user["role"] not in ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to manage exclusions")
    return user


@router.get("/exclusions", response_model=list[ExclusionRecord])
def list_exclusions(user: User):
    return store.list_exclusions(_member(user)["org_id"])


@router.post("/exclusions", response_model=ExclusionRecord, status_code=status.HTTP_201_CREATED)
def add_exclusion(req: AddExclusionRequest, user: User):
    _member(user)
    value = service.normalize_domain(req.value) if req.kind == "domain" else service.normalize_keyword(req.value)
    if not value:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Enter a website or domain such as example.com" if req.kind == "domain" else "Enter a keyword")
    existing = store.list_exclusions(user["org_id"])
    if any(r["kind"] == req.kind and r["value"].lower() == value.lower() for r in existing):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{value} is already excluded")
    if len(existing) >= MAX_RULES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"At most {MAX_RULES} exclusions per organization")
    return store.add_exclusion(user["org_id"], req.kind, value, user["id"])


@router.delete("/exclusions/{exclusion_id}", response_model=OkResponse)
def delete_exclusion(exclusion_id: Annotated[int, Path(ge=1)], user: User):
    _member(user)
    row = store.get_exclusion(exclusion_id)
    if not row or row["org_id"] != user["org_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exclusion not found")
    store.delete_exclusion(exclusion_id)
    return {"ok": True}
