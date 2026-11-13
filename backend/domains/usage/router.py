"""Usage dashboard API: cost and tokens per day, model, stage and project, scoped to the caller's role."""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import ColumnElement, and_, false, or_, select, true

from ...core import store
from ...core.auth import get_current_user, require_project_access
from ..providers import repository as provider_repo
from . import repository as repo
from .models import intel_projects, llm_usage as U
from .schemas import PriceRequest, SettingsRequest

router = APIRouter(prefix="/usage", tags=["usage"])
UserDep = Annotated[dict, Depends(get_current_user)]
DateParam = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")]
_TOK = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
_DAY_SECONDS = timedelta(days=1).total_seconds()


# Its own alias: the dashboards also join intel_projects, and a same-name subquery would be auto-correlated to it.
_SCOPE_P = intel_projects.alias("scope_projects")


def _scope_where(user: dict, org_id: int | None = None) -> ColumnElement:
    """The role scope on llm_usage, mirroring core.auth.can_access_project: through the project's org and owner, with
    project-less rows falling back to the row's own org / user. org_id narrows a super_admin only."""
    def org_rows(org: int) -> ColumnElement:
        return or_(U.c.project_id.in_(select(_SCOPE_P.c.id).where(_SCOPE_P.c.org_id == org)),
                   and_(U.c.project_id.is_(None), U.c.org_id == org))
    role = user["role"]
    if role == "super_admin":
        return true() if org_id is None else org_rows(org_id)
    if user.get("org_id") is None:
        return false()
    if role == "admin":
        return org_rows(user["org_id"])
    own = select(_SCOPE_P.c.id).where(_SCOPE_P.c.org_id == user["org_id"], _SCOPE_P.c.owner_user_id == user["id"])
    return or_(U.c.project_id.in_(own), and_(U.c.project_id.is_(None), U.c.user_id == user["id"]))


def _epoch(day: str) -> float:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid date {day}") from None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def _filters(user: dict, date_from: str | None, date_to: str | None, org_id: int | None,
             project_id: int | None, stage: str | None, model: str | None,
             sub_stage: str | None = None) -> ColumnElement:
    conds = [_scope_where(user, org_id)]
    if date_from:
        conds.append(U.c.ts >= _epoch(date_from))
    if date_to:   # inclusive UTC day: everything before the next midnight
        conds.append(U.c.ts < _epoch(date_to) + _DAY_SECONDS)
    for col, val in (("project_id", project_id), ("stage", stage), ("model", model), ("sub_stage", sub_stage)):
        if val is not None:
            conds.append(U.c[col] == val)
    return and_(*conds)


def _pick(row: dict, *keys: str) -> dict:
    return {k: row[k] for k in keys}


def _with_sub_stages(by_stage: list[dict], rows: list[dict]) -> list[dict]:
    """by_stage rows, each with its sub-stages assembled from one (stage, sub_stage, provider, model) grouping."""
    subs: dict = {}
    for r in rows:     # arrive ordered by tokens desc, so each sub-stage's models are too
        sub = subs.setdefault(r["stage"], {}).setdefault(r["sub_stage"], {
            "sub_stage": r["sub_stage"], "calls": 0, **{k: 0 for k in _TOK}, "cost_usd": 0.0,
            "latency_sum": 0, "latency_n": 0, "models": []})
        for k in ("calls", *_TOK, "latency_sum", "latency_n"):
            sub[k] += r[k]
        sub["cost_usd"] += float(r["cost_usd"])
        sub["models"].append(_pick(r, "provider", "model", "total_tokens", "cost_usd"))
    out = []
    for st in by_stage:
        items = []
        for sub in subs.get(st["stage"], {}).values():
            n, total = sub.pop("latency_n"), sub.pop("latency_sum")
            items.append({**sub, "avg_latency_ms": round(total / n) if n else None})
        out.append({**st, "sub_stages": sorted(items, key=lambda x: -x["total_tokens"])})
    return out


def trend_grain(date_from: str | None, date_to: str | None) -> str:
    """The trend's bucket for a range: under 7 days hourly, to ~3 months daily, to 3 years monthly, then yearly."""
    from datetime import date
    if not date_from or not date_to:
        return "day"
    days = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days + 1
    return "hour" if days < 7 else "day" if days <= 92 else "month" if days <= 3 * 366 else "year"


@router.get("/summary")
def usage_summary(user: UserDep, date_from: DateParam = None, date_to: DateParam = None, org_id: int | None = None,
                  project_id: int | None = None, stage: str | None = None, model: str | None = None) -> dict:
    cond = _filters(user, date_from, date_to, org_id, project_id, stage, model)
    grain = trend_grain(date_from, date_to)
    s = repo.summary(cond, grain)
    # "saved by cache": cache hits x the model's average cost of a real (non-hit) chat call in range
    saved = sum(m["cache_hits"] * float(m["avg_chat_cost"] or 0) for m in s["by_model"])
    total = sum(p["total_tokens"] for p in s["by_project"])
    models: dict = {}
    for r in s["project_models"]:
        models.setdefault(r["project_id"], []).append(
            _pick(r, "provider", "model", "input_tokens", "output_tokens", "total_tokens", "cost_usd"))
    stages: dict = {}
    for r in s["project_stages"]:   # rows arrive ordered by tokens desc, so stages[pid][0] is the top stage
        stages.setdefault(r["project_id"], []).append(_pick(r, "stage", "total_tokens", "cost_usd"))
    by_project = [{**_pick(p, "project_id", "project_name", "owner_name", "cost_usd", *_TOK, "calls"),
                   "share_pct": round(100 * p["total_tokens"] / total, 2) if total else 0.0,
                   "top_stage": stages[p["project_id"]][0]["stage"],
                   "models": models[p["project_id"]], "stages": stages[p["project_id"]]}
                  for p in s["by_project"]]
    now = time.time()
    by_model = [{**_pick(m, "provider", "model", "deployment_type", "calls", *_TOK, "cost_usd"),
                 # no price row: its cost shows "no price set", not a misleading $0 (Settings -> LLM Providers)
                 "priced": repo.price_for(m["provider"], m["model"], m["deployment_type"] or "", now) is not None}
                for m in s["by_model"]]
    return {
        "kpis": {**_pick(s["kpi"], "cost_usd", *_TOK, "calls", "cache_hits", "nvidia_credits"),
                 "saved_by_cache_usd": saved, "unpriced_models": sum(not m["priced"] for m in by_model)},
        "grain": grain,
        "trend": s["trend"],
        "by_model": by_model,
        "by_stage": _with_sub_stages(s["by_stage"], s["sub_stages"]),
        "by_project": by_project,
    }


@router.get("/calls")
def usage_calls(user: UserDep, date_from: DateParam = None, date_to: DateParam = None, org_id: int | None = None,
                project_id: int | None = None, stage: str | None = None, model: str | None = None,
                sub_stage: Annotated[str | None, Query(max_length=64)] = None,
                offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
    cond = _filters(user, date_from, date_to, org_id, project_id, stage, model, sub_stage)
    rows, total = repo.calls(cond, limit, offset)
    return {"rows": rows, "total": total}


def _settings() -> dict:
    return {"deployment_type": repo.get_setting("azure_deployment_type", "global"),
            "region": repo.get_setting("azure_price_region", "southindia")}


@router.get("/prices")
def usage_prices(_user: UserDep) -> dict:
    return {"prices": repo.list_prices(), **_settings()}


def _require_super(user: dict) -> None:
    if user["role"] != "super_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super admin only")


def _may_price(user: dict, provider: str, model: str) -> bool:
    """Super admin: any price. Org admin: a model only its own org runs (the platform model for a platform-LLM org,
    or one of its providers' models), since a price row is shared by every org on that provider type and model."""
    if user["role"] == "super_admin":
        return True
    org = user.get("org_id")
    if user["role"] != "admin" or not org:
        return False
    owners = provider_repo.orgs_using_model(provider, model)
    platform = (provider == "azure_openai" and model == os.getenv("AZURE_OPENAI_MODEL", "")
                and store.org_uses_platform_llm(org))
    return (platform or bool(owners)) and owners <= {org}


@router.put("/prices")
def usage_put_price(body: PriceRequest, user: UserDep) -> dict:
    if not _may_price(user, body.provider, body.model):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can set prices only for your organization's own models")
    first = repo.price_for(body.provider, body.model, body.deployment_type, time.time()) is None
    # a model's first price also costs its earlier calls (they were stored at $0 for want of a price)
    effective = min(body.effective_from, repo.first_use_day(body.provider, body.model) or body.effective_from) \
        if first else body.effective_from
    repo.upsert_price(body.provider, body.model, body.deployment_type, body.input_per_m, body.cached_per_m,
                      body.output_per_m, effective, "manual")
    price = {"input_per_m": body.input_per_m, "cached_per_m": body.cached_per_m, "output_per_m": body.output_per_m}
    n = repo.recost(body.provider, body.model, body.deployment_type, effective, price)
    return {"ok": True, "effective_from": effective, "recosted_calls": n}


@router.put("/settings")
def usage_put_settings(body: SettingsRequest, user: UserDep) -> dict:
    _require_super(user)
    if body.deployment_type:
        repo.set_setting("azure_deployment_type", body.deployment_type)
    if body.region:
        repo.set_setting("azure_price_region", body.region)
    return _settings()


@router.get("/projects/{project_id}/total")
def usage_project_total(project_id: int, _user: Annotated[dict, Depends(require_project_access)]) -> dict:
    return repo.project_total(project_id)
