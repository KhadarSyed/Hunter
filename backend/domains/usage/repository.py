"""SQL for LLM usage rows, model prices and usage settings."""
from __future__ import annotations

import time

from ...core.db import _conn

_COLS = ("ts", "org_id", "project_id", "stage", "user_id", "provider", "model", "deployment_type", "kind",
         "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens", "requests", "credits",
         "latency_ms", "cache_hit", "error", "cost_usd", "sub_stage", "error_reason")


def insert_usage(row: dict) -> None:
    row = {"sub_stage": "", "error_reason": "", **row}      # NOT NULL: older writers leave them empty
    conn = _conn()
    try:
        conn.execute(f"INSERT INTO llm_usage ({', '.join(_COLS)}) VALUES ({', '.join('?' for _ in _COLS)})",
                     tuple(row.get(c) for c in _COLS))
        conn.commit()
    finally:
        conn.close()


def price_for(provider: str, model: str, deployment_type: str, at_ts: float) -> dict | None:
    """The price in force at at_ts: an exact model match first, else the longest stored model name that prefixes it
    (a response model 'gpt-5-2025-08-07' is priced by a 'gpt-5' row)."""
    day = time.strftime("%Y-%m-%d", time.gmtime(at_ts))
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM llm_prices WHERE provider = ? AND deployment_type IN (?, '') AND effective_from <= ? "
            "ORDER BY effective_from DESC", (provider, deployment_type, day)).fetchall()]
    finally:
        conn.close()
    exact = [r for r in rows if r["model"] == model]
    if exact:
        return exact[0]
    prefixed = sorted((r for r in rows if model.startswith(r["model"])), key=lambda r: -len(r["model"]))
    return prefixed[0] if prefixed else None


def upsert_price(provider: str, model: str, deployment_type: str, input_per_m: float, cached_per_m: float,
                 output_per_m: float, effective_from: str, source: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO llm_prices (provider, model, deployment_type, input_per_m, cached_per_m, output_per_m, "
            "effective_from, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (provider, model, deployment_type, effective_from) DO UPDATE SET "
            "input_per_m = EXCLUDED.input_per_m, cached_per_m = EXCLUDED.cached_per_m, "
            "output_per_m = EXCLUDED.output_per_m, source = EXCLUDED.source",
            (provider, model, deployment_type, input_per_m, cached_per_m, output_per_m, effective_from, source))
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default: str = "") -> str:
    conn = _conn()
    try:
        row = conn.execute("SELECT value FROM llm_settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    conn = _conn()
    try:
        conn.execute("INSERT INTO llm_settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value))
        conn.commit()
    finally:
        conn.close()


def has_price_row(provider: str, model: str) -> bool:
    conn = _conn()
    try:
        return conn.execute("SELECT 1 FROM llm_prices WHERE provider = ? AND model = ? LIMIT 1",
                            (provider, model)).fetchone() is not None
    finally:
        conn.close()


def earlier_price(provider: str, model: str, deployment_type: str, before_day: str) -> dict | None:
    """The latest row for exactly this model and deployment type that starts before before_day."""
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM llm_prices WHERE provider = ? AND model = ? AND deployment_type = ? "
                           "AND effective_from < ? ORDER BY effective_from DESC LIMIT 1",
                           (provider, model, deployment_type, before_day)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---- reads for the usage API -------------------------------------------------------------------------------------
_TOK = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
_SUMS = ", ".join(f"COALESCE(SUM(u.{c}), 0) AS {c}" for c in _TOK) + ", COALESCE(SUM(u.cost_usd), 0) AS cost_usd"
# trend bucket per grain, as UTC text: 2026-11-07T04 / 2026-11-07 / 2026-11 / 2026
_BUCKET = {"hour": 'YYYY-MM-DD"T"HH24', "day": "YYYY-MM-DD", "month": "YYYY-MM", "year": "YYYY"}


def _num(v):
    """Postgres SUM() of integers is numeric (Decimal); the API wants plain int / float."""
    from decimal import Decimal
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _rows(sql: str, params) -> list[dict]:
    conn = _conn()
    try:
        return [{k: _num(v) for k, v in dict(r).items()} for r in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()


def summary(where: str, params: list, grain: str = "day") -> dict:
    """Every aggregate of the dashboard; `where` is the scope + filters on llm_usage aliased u."""
    base = f"FROM llm_usage u WHERE {where}"
    kpi = _rows(f"SELECT {_SUMS}, COUNT(*) AS calls, COALESCE(SUM(u.cache_hit), 0) AS cache_hits, "
                f"COALESCE(SUM(u.credits), 0) AS nvidia_credits {base}", params)[0]
    by_model = _rows(
        f"SELECT u.provider, u.model, u.deployment_type, COUNT(*) AS calls, {_SUMS}, "
        f"COALESCE(SUM(u.cache_hit), 0) AS cache_hits, "
        f"AVG(CASE WHEN u.cache_hit = 0 AND u.kind = 'chat' THEN u.cost_usd END) AS avg_chat_cost "
        f"{base} GROUP BY u.provider, u.model, u.deployment_type ORDER BY SUM(u.cost_usd) DESC, u.model", params)
    bucket = f"to_char(to_timestamp(u.ts) AT TIME ZONE 'UTC', '{_BUCKET[grain]}')"
    trend = _rows(f"SELECT {bucket} AS bucket, u.provider, u.model, COALESCE(SUM(u.cost_usd), 0) AS cost_usd, "
                  f"COALESCE(SUM(u.total_tokens), 0) AS total_tokens {base} "
                  f"GROUP BY 1, u.provider, u.model ORDER BY 1, u.provider, u.model", params)
    by_stage = _rows(f"SELECT u.stage, COUNT(*) AS calls, {_SUMS} {base} GROUP BY u.stage "
                     f"ORDER BY SUM(u.total_tokens) DESC", params)
    sub_stages = _rows(
        f"SELECT u.stage, u.sub_stage, u.provider, u.model, COUNT(*) AS calls, {_SUMS}, "
        f"COALESCE(SUM(CASE WHEN u.cache_hit = 0 THEN u.latency_ms END), 0) AS latency_sum, "
        f"COALESCE(SUM(1 - u.cache_hit), 0) AS latency_n "
        f"{base} GROUP BY u.stage, u.sub_stage, u.provider, u.model ORDER BY SUM(u.total_tokens) DESC", params)
    by_project = _rows(
        f"SELECT u.project_id, MAX(p.project_name) AS project_name, MAX(o.display_name) AS owner_name, {_SUMS}, "
        f"COUNT(*) AS calls FROM llm_usage u LEFT JOIN intel_projects p ON p.id = u.project_id "
        f"LEFT JOIN users o ON o.id = p.owner_user_id WHERE {where} "
        f"GROUP BY u.project_id ORDER BY SUM(u.total_tokens) DESC, u.project_id", params)
    project_models = _rows(
        f"SELECT u.project_id, u.provider, u.model, {_SUMS} {base} "
        f"GROUP BY u.project_id, u.provider, u.model ORDER BY SUM(u.total_tokens) DESC", params)
    project_stages = _rows(
        f"SELECT u.project_id, u.stage, {_SUMS} {base} GROUP BY u.project_id, u.stage "
        f"ORDER BY SUM(u.total_tokens) DESC", params)
    return {"kpi": kpi, "by_model": by_model, "trend": trend, "by_stage": by_stage, "sub_stages": sub_stages,
            "by_project": by_project, "project_models": project_models, "project_stages": project_stages}


def calls(where: str, params: list, limit: int, offset: int) -> tuple[list[dict], int]:
    total = _rows(f"SELECT COUNT(*) AS n FROM llm_usage u WHERE {where}", params)[0]["n"]
    rows = _rows(
        "SELECT u.ts, u.project_id, p.project_name, u.stage, u.sub_stage, u.provider, u.model, u.kind, "
        "u.input_tokens, u.cached_input_tokens, u.output_tokens, u.total_tokens, u.cost_usd, u.latency_ms, "
        "u.cache_hit, u.error, u.error_reason "
        f"FROM llm_usage u LEFT JOIN intel_projects p ON p.id = u.project_id WHERE {where} "
        "ORDER BY u.ts DESC, u.id DESC LIMIT ? OFFSET ?", [*params, limit, offset])
    return rows, total


def project_total(project_id: int) -> dict:
    r = _rows("SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd, COALESCE(SUM(total_tokens), 0) AS total_tokens "
              "FROM llm_usage WHERE project_id = ?", [project_id])[0]
    return {"cost_usd": float(r["cost_usd"]), "total_tokens": int(r["total_tokens"])}


def list_prices() -> list[dict]:
    return _rows("SELECT provider, model, deployment_type, input_per_m, cached_per_m, output_per_m, effective_from, "
                 "source FROM llm_prices ORDER BY provider, model, deployment_type, effective_from DESC", [])
