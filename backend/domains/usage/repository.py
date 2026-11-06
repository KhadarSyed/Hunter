"""SQL for LLM usage rows, model prices and usage settings."""
from __future__ import annotations

import time

from ...core.db import _conn

_COLS = ("ts", "org_id", "project_id", "stage", "user_id", "provider", "model", "deployment_type", "kind",
         "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens", "requests", "credits",
         "latency_ms", "cache_hit", "error", "cost_usd")


def insert_usage(row: dict) -> None:
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
