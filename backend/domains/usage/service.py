"""Records every paid LLM call (tokens, cost) with who and where it ran. Never raises: a failed record is a warning,
the LLM answer is still returned."""
from __future__ import annotations

import contextlib
import contextvars
import logging
import time

from . import repository as repo

logger = logging.getLogger(__name__)
STAGES = ("brief_scope", "background_research", "search_strategy", "matching_label", "dataset_tagging",
          "deck_engine", "deck_studio", "agent", "qc", "other")
# One mutable dict per request or job: the auth dependencies fill it in place, so the endpoint's thread (a copied
# context holding the same dict) sees what they set.
SCOPE: contextvars.ContextVar[dict | None] = contextvars.ContextVar("llm_scope", default=None)


def current() -> dict:
    return dict(SCOPE.get() or {})


@contextlib.contextmanager
def scope(**fields):
    """A new scope holder for a job or block: the outer scope's fields, overridden by these."""
    token = SCOPE.set({**current(), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        SCOPE.reset(token)


def fill(**fields) -> None:
    """Fill the current holder in place (auth dependencies call this); no holder, nothing to fill."""
    holder = SCOPE.get()
    if holder is not None:
        holder.update({k: v for k, v in fields.items() if v is not None})


def deployment_type(provider: str) -> str:
    return repo.get_setting("azure_deployment_type", "global") if provider == "azure_openai" else ""


def cost_usd(provider: str, model: str, dep_type: str, input_tokens: int, cached_input_tokens: int,
             output_tokens: int, at_ts: float) -> float:
    p = repo.price_for(provider, model, dep_type, at_ts)
    if not p:
        return 0.0
    fresh = max(0, input_tokens - cached_input_tokens)
    return (fresh * p["input_per_m"] + cached_input_tokens * p["cached_per_m"]
            + output_tokens * p["output_per_m"]) / 1_000_000


def record(provider: str, model: str, kind: str, *, input_tokens: int = 0, cached_input_tokens: int = 0,
           output_tokens: int = 0, requests: int = 1, credits: float = 0.0, latency_ms: int = 0,
           cache_hit: bool = False, error: bool = False, reason: str = "") -> None:
    try:
        s, now, model = current(), time.time(), model or "unknown"
        dep = deployment_type(provider)
        stage = s.get("stage") if s.get("stage") in STAGES else "other"
        row = {
            "ts": now, "org_id": s.get("org_id"), "project_id": s.get("project_id"), "stage": stage,
            "sub_stage": str(s.get("sub_stage") or "")[:64],
            "user_id": s.get("user_id"), "provider": provider, "model": model, "deployment_type": dep,
            "kind": kind, "input_tokens": int(input_tokens), "cached_input_tokens": int(cached_input_tokens),
            "output_tokens": int(output_tokens), "total_tokens": int(input_tokens) + int(output_tokens),
            "requests": int(requests), "credits": float(credits), "latency_ms": int(latency_ms),
            "cache_hit": int(cache_hit), "error": int(error), "error_reason": str(reason)[:200] if error else "",
            "cost_usd": 0.0 if cache_hit else cost_usd(provider, model, dep, input_tokens, cached_input_tokens,
                                                       output_tokens, now)}
        repo.insert_usage(row)
    except Exception as e:
        logger.warning("LLM usage not recorded: %s", type(e).__name__)
        return
    _broadcast(row)


def _broadcast(row: dict) -> None:
    """Live feed for the Usage page; delivery follows the project's access rules (no project: super admins)."""
    try:
        from ...core import events
        events.broadcast({"type": "llm_usage", **row})
    except Exception as e:
        logger.debug("usage broadcast skipped: %s", type(e).__name__)
