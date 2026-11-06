"""Usage dashboard API: cost and tokens per day, model, stage and project, scoped to the caller's role."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...core.auth import get_current_user, require_project_access
from . import repository as repo
from .schemas import PriceRequest, SettingsRequest

router = APIRouter(prefix="/usage", tags=["usage"])
UserDep = Annotated[dict, Depends(get_current_user)]
DateParam = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")]
_TOK = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
_DAY_SECONDS = timedelta(days=1).total_seconds()


def _scope_where(user: dict, org_id: int | None = None) -> tuple[str, list]:
    """The role scope on llm_usage (alias u), mirroring core.auth.can_access_project: through the project's org and
    owner, with project-less rows falling back to the row's own org / user. org_id narrows a super_admin only."""
    role = user["role"]
    if role == "super_admin":
        if org_id is None:
            return "TRUE", []
        return ("(u.project_id IN (SELECT id FROM intel_projects WHERE org_id = ?) "
                "OR (u.project_id IS NULL AND u.org_id = ?))", [org_id, org_id])
    if user.get("org_id") is None:
        return "FALSE", []
    if role == "admin":
        return ("(u.project_id IN (SELECT id FROM intel_projects WHERE org_id = ?) "
                "OR (u.project_id IS NULL AND u.org_id = ?))", [user["org_id"], user["org_id"]])
    return ("(u.project_id IN (SELECT id FROM intel_projects WHERE org_id = ? AND owner_user_id = ?) "
            "OR (u.project_id IS NULL AND u.user_id = ?))", [user["org_id"], user["id"], user["id"]])


def _epoch(day: str) -> float:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid date {day}") from None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def _filters(user: dict, date_from: str | None, date_to: str | None, org_id: int | None,
             project_id: int | None, stage: str | None, model: str | None,
             sub_stage: str | None = None) -> tuple[str, list]:
    sql, params = _scope_where(user, org_id)
    parts = [sql]
    if date_from:
        parts.append("u.ts >= ?")
        params.append(_epoch(date_from))
    if date_to:   # inclusive UTC day: everything before the next midnight
        parts.append("u.ts < ?")
        params.append(_epoch(date_to) + _DAY_SECONDS)
    for col, val in (("project_id", project_id), ("stage", stage), ("model", model), ("sub_stage", sub_stage)):
        if val is not None:
            parts.append(f"u.{col} = ?")
            params.append(val)
    return " AND ".join(parts), params


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


@router.get("/summary")
def usage_summary(user: UserDep, date_from: DateParam = None, date_to: DateParam = None, org_id: int | None = None,
                  project_id: int | None = None, stage: str | None = None, model: str | None = None) -> dict:
    where, params = _filters(user, date_from, date_to, org_id, project_id, stage, model)
    s = repo.summary(where, params)
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
    return {
        "kpis": {**_pick(s["kpi"], "cost_usd", *_TOK, "calls", "cache_hits", "nvidia_credits"),
                 "saved_by_cache_usd": saved},
        "trend": s["trend"],
        "by_model": [_pick(m, "provider", "model", "deployment_type", "calls", *_TOK, "cost_usd")
                     for m in s["by_model"]],
        "by_stage": _with_sub_stages(s["by_stage"], s["sub_stages"]),
        "by_project": by_project,
    }


@router.get("/calls")
def usage_calls(user: UserDep, date_from: DateParam = None, date_to: DateParam = None, org_id: int | None = None,
                project_id: int | None = None, stage: str | None = None, model: str | None = None,
                sub_stage: Annotated[str | None, Query(max_length=64)] = None,
                offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
    where, params = _filters(user, date_from, date_to, org_id, project_id, stage, model, sub_stage)
    rows, total = repo.calls(where, params, limit, offset)
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


@router.put("/prices")
def usage_put_price(body: PriceRequest, user: UserDep) -> dict:
    _require_super(user)
    repo.upsert_price(body.provider, body.model, body.deployment_type, body.input_per_m, body.cached_per_m,
                      body.output_per_m, body.effective_from, "manual")
    return {"ok": True}


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
