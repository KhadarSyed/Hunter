"""Settings API for the exclusion list: Admins and Analysers manage their organization's excluded websites and
keywords (a Super Admin, their own organization's)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, UploadFile, status

from ...core import store
from ...core.api import OkResponse
from ...core.auth import get_current_user
from . import service
from .schemas import AddExclusionRequest, BulkExclusionRequest, ExclusionRecord, ImportResult

router = APIRouter()
User = Annotated[dict, Depends(get_current_user)]
MAX_RULES = 5000
ROLES = ("super_admin", "admin", "analyser")


def _member(user: dict) -> dict:
    if user["role"] not in ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to manage exclusions")
    return user


@router.get("/exclusions", response_model=list[ExclusionRecord])
def list_exclusions(user: User):
    org = _member(user)["org_id"]
    learned = service.overrides(org)
    out = []
    for r in store.list_exclusions(org):
        m = learned.get(f"{r['kind']}:{r['value'].lower()}") or {}
        out.append({**r, "kept_relevant": int(m.get("count", 0)),
                    "last_comment": ((m.get("notes") or [{}])[0].get("comment")) or None})
    return out


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


def _import(user: dict, kind: str, raw: list[str]) -> dict:
    existing = store.list_exclusions(user["org_id"])
    plan = service.prepare(kind, raw, existing)
    if not plan["add"] and not plan["duplicates"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "No websites found. Use domains such as example.com, separated by commas or new lines"
                            if kind == "domain" else "No keywords found")
    room = MAX_RULES - len(existing)
    if len(plan["add"]) > room:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"This adds {len(plan['add'])} but only {max(room, 0)} more fit (at most {MAX_RULES} "
                            "exclusions per organization)")
    added = store.add_exclusions(user["org_id"], kind, plan["add"], user["id"])
    total = sum(1 for r in existing if r["kind"] == kind) + added
    return {"added": added, "duplicates": plan["duplicates"], "invalid": plan["invalid"][:20],
            "invalid_count": len(plan["invalid"]), "total": total}


@router.post("/exclusions/bulk", response_model=ImportResult)
def bulk_exclusions(req: BulkExclusionRequest, user: User):
    """Paste: many websites (or keywords) separated by commas, semicolons, spaces or new lines."""
    return _import(_member(user), req.kind, service.split_values(req.text, req.kind))


@router.post("/exclusions/import", response_model=ImportResult)
async def import_exclusions(user: User, file: UploadFile = File(...), kind: str = Form("domain")):
    """Upload an .xlsx, .csv, .txt or .json list (every cell / string is read; headers like "Domain" are skipped)."""
    _member(user)
    if kind not in ("domain", "keyword"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "kind must be domain or keyword")
    data = await file.read(service.MAX_IMPORT_BYTES + 1)
    try:
        raw = service.values_from_file(file.filename or "", data, kind)
    except service.ImportError_ as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return _import(user, kind, raw)


@router.delete("/exclusions/{exclusion_id}", response_model=OkResponse)
def delete_exclusion(exclusion_id: Annotated[int, Path(ge=1)], user: User):
    _member(user)
    row = store.get_exclusion(exclusion_id)
    if not row or row["org_id"] != user["org_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exclusion not found")
    store.delete_exclusion(exclusion_id)
    return {"ok": True}
