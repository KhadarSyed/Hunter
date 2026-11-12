"""LLM usage rows, model prices and usage settings through SQLAlchemy Core (models.py). The dashboard reads take a
SQLAlchemy condition on llm_usage built by usage/router.py (role scope + filters)."""
from __future__ import annotations

import time
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, case, func, insert, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import sa
from .models import intel_projects as P
from .models import llm_prices as prices
from .models import llm_settings as settings
from .models import llm_usage as U
from .models import users as O

_COLS = ("ts", "org_id", "project_id", "stage", "user_id", "provider", "model", "deployment_type", "kind",
         "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens", "requests", "credits",
         "latency_ms", "cache_hit", "error", "cost_usd", "sub_stage", "error_reason")
_TOK = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
# trend bucket per grain, as UTC text: 2026-11-07T04 / 2026-11-07 / 2026-11 / 2026 (fixed strings, never user input)
_BUCKET = {"hour": 'YYYY-MM-DD"T"HH24', "day": "YYYY-MM-DD", "month": "YYYY-MM", "year": "YYYY"}


def _num(v):
    """Postgres SUM() of integers is numeric (Decimal); the API wants plain int / float."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _rows(query) -> list[dict]:
    with sa.begin() as conn:
        return [{k: _num(v) for k, v in r._mapping.items()} for r in conn.execute(query)]


def _first(query) -> dict | None:
    rows = _rows(query)
    return rows[0] if rows else None


# ---- writes and price/settings lookups ----------------------------------------------------------------------------

def insert_usage(row: dict) -> None:
    row = {"sub_stage": "", "error_reason": "", **row}      # NOT NULL: older writers leave them empty
    with sa.begin() as conn:
        conn.execute(insert(U).values({c: row.get(c) for c in _COLS}))


def price_for(provider: str, model: str, deployment_type: str, at_ts: float) -> dict | None:
    """The price in force at at_ts: an exact model match first, else the longest stored model name that prefixes it
    (a response model 'gpt-5-2025-08-07' is priced by a 'gpt-5' row)."""
    day = time.strftime("%Y-%m-%d", time.gmtime(at_ts))
    rows = _rows(select(prices).where(prices.c.provider == provider,
                                      prices.c.deployment_type.in_([deployment_type, ""]),
                                      prices.c.effective_from <= day).order_by(prices.c.effective_from.desc()))
    exact = [r for r in rows if r["model"] == model]
    if exact:
        return exact[0]
    prefixed = sorted((r for r in rows if model.startswith(r["model"])), key=lambda r: -len(r["model"]))
    return prefixed[0] if prefixed else None


def upsert_price(provider: str, model: str, deployment_type: str, input_per_m: float, cached_per_m: float,
                 output_per_m: float, effective_from: str, source: str) -> None:
    stmt = pg_insert(prices).values(provider=provider, model=model, deployment_type=deployment_type,
                                    input_per_m=input_per_m, cached_per_m=cached_per_m, output_per_m=output_per_m,
                                    effective_from=effective_from, source=source)
    keys = [prices.c.provider, prices.c.model, prices.c.deployment_type, prices.c.effective_from]
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=keys, set_={
            c: stmt.excluded[c] for c in ("input_per_m", "cached_per_m", "output_per_m", "source")}))


def get_setting(key: str, default: str = "") -> str:
    row = _first(select(settings.c.value).where(settings.c.key == key))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    stmt = pg_insert(settings).values(key=key, value=value)
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=[settings.c.key], set_={"value": stmt.excluded.value}))


def has_price_row(provider: str, model: str) -> bool:
    return _first(select(prices.c.id).where(prices.c.provider == provider, prices.c.model == model).limit(1)) is not None


def earlier_price(provider: str, model: str, deployment_type: str, before_day: str) -> dict | None:
    """The latest row for exactly this model and deployment type that starts before before_day."""
    return _first(select(prices).where(prices.c.provider == provider, prices.c.model == model,
                                       prices.c.deployment_type == deployment_type,
                                       prices.c.effective_from < before_day)
                  .order_by(prices.c.effective_from.desc()).limit(1))


# ---- reads for the usage API -------------------------------------------------------------------------------------

def _sums() -> list:
    return [func.coalesce(func.sum(U.c[c]), 0).label(c) for c in _TOK] + \
           [func.coalesce(func.sum(U.c.cost_usd), 0).label("cost_usd")]


def _by_tokens():
    return func.sum(U.c.total_tokens).desc()


def summary(cond: ColumnElement, grain: str = "day") -> dict:
    """Every aggregate of the dashboard; `cond` is the scope + filters on llm_usage (usage/router.py)."""
    calls = func.count().label("calls")
    cache_hits = func.coalesce(func.sum(U.c.cache_hit), 0).label("cache_hits")
    kpi = _rows(select(*_sums(), calls, cache_hits, func.coalesce(func.sum(U.c.credits), 0).label("nvidia_credits"))
                .where(cond))[0]
    model_cols = (U.c.provider, U.c.model, U.c.deployment_type)
    by_model = _rows(select(*model_cols, calls, *_sums(), cache_hits,
                            func.avg(case((and_(U.c.cache_hit == 0, U.c.kind == "chat"), U.c.cost_usd)))
                            .label("avg_chat_cost"))
                     .where(cond).group_by(*model_cols).order_by(func.sum(U.c.cost_usd).desc(), U.c.model))
    fmt = literal_column(f"'{_BUCKET[grain]}'")      # a literal, so GROUP BY sees the same expression as SELECT
    bucket = func.to_char(func.timezone("UTC", func.to_timestamp(U.c.ts)), fmt)
    trend = _rows(select(bucket.label("bucket"), U.c.provider, U.c.model,
                         func.coalesce(func.sum(U.c.cost_usd), 0).label("cost_usd"),
                         func.coalesce(func.sum(U.c.total_tokens), 0).label("total_tokens"))
                  .where(cond).group_by(bucket, U.c.provider, U.c.model).order_by(bucket, U.c.provider, U.c.model))
    by_stage = _rows(select(U.c.stage, calls, *_sums()).where(cond).group_by(U.c.stage).order_by(_by_tokens()))
    stage_cols = (U.c.stage, U.c.sub_stage, U.c.provider, U.c.model)
    sub_stages = _rows(select(*stage_cols, calls, *_sums(),
                              func.coalesce(func.sum(case((U.c.cache_hit == 0, U.c.latency_ms))), 0)
                              .label("latency_sum"),
                              func.coalesce(func.sum(1 - U.c.cache_hit), 0).label("latency_n"))
                       .where(cond).group_by(*stage_cols).order_by(_by_tokens()))
    by_project = _rows(select(U.c.project_id, func.max(P.c.project_name).label("project_name"),
                              func.max(O.c.display_name).label("owner_name"), *_sums(), calls)
                       .select_from(U.outerjoin(P, P.c.id == U.c.project_id)
                                    .outerjoin(O, O.c.id == P.c.owner_user_id))
                       .where(cond).group_by(U.c.project_id).order_by(_by_tokens(), U.c.project_id))
    project_models = _rows(select(U.c.project_id, U.c.provider, U.c.model, *_sums()).where(cond)
                           .group_by(U.c.project_id, U.c.provider, U.c.model).order_by(_by_tokens()))
    project_stages = _rows(select(U.c.project_id, U.c.stage, *_sums()).where(cond)
                           .group_by(U.c.project_id, U.c.stage).order_by(_by_tokens()))
    return {"kpi": kpi, "by_model": by_model, "trend": trend, "by_stage": by_stage, "sub_stages": sub_stages,
            "by_project": by_project, "project_models": project_models, "project_stages": project_stages}


def calls(cond: ColumnElement, limit: int, offset: int) -> tuple[list[dict], int]:
    total = _rows(select(func.count().label("n")).select_from(U).where(cond))[0]["n"]
    rows = _rows(select(U.c.ts, U.c.project_id, P.c.project_name, U.c.stage, U.c.sub_stage, U.c.provider, U.c.model,
                        U.c.kind, *(U.c[c] for c in _TOK[:3]), U.c.total_tokens, U.c.cost_usd, U.c.latency_ms,
                        U.c.cache_hit, U.c.error, U.c.error_reason)
                 .select_from(U.outerjoin(P, P.c.id == U.c.project_id)).where(cond)
                 .order_by(U.c.ts.desc(), U.c.id.desc()).limit(limit).offset(offset))
    return rows, total


def project_total(project_id: int) -> dict:
    r = _rows(select(func.coalesce(func.sum(U.c.cost_usd), 0).label("cost_usd"),
                     func.coalesce(func.sum(U.c.total_tokens), 0).label("total_tokens"))
              .where(U.c.project_id == project_id))[0]
    return {"cost_usd": float(r["cost_usd"]), "total_tokens": int(r["total_tokens"])}


def list_prices() -> list[dict]:
    return _rows(select(prices.c.provider, prices.c.model, prices.c.deployment_type, prices.c.input_per_m,
                        prices.c.cached_per_m, prices.c.output_per_m, prices.c.effective_from, prices.c.source)
                 .order_by(prices.c.provider, prices.c.model, prices.c.deployment_type,
                           prices.c.effective_from.desc()))


def stage_cost_since(project_id: int, stage: str, since: float) -> float:
    """What one stage of a project cost since a moment (a tagging job's start), in USD."""
    r = _rows(select(func.coalesce(func.sum(U.c.cost_usd), 0).label("c"))
              .where(U.c.project_id == project_id, U.c.stage == stage, U.c.ts >= since))[0]
    return float(r["c"])
