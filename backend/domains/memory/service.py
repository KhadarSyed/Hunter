"""Agentic memory shared by every pipeline stage.

Scopes: global (every org), org (every project of one organisation), project, user. Types and where each lives:
  short_term   the prompt a call is built from; domains/agent/memory.context() for the copilot/autopilot
  episodic     what happened: agent_events, written for every stage job by record_episode() (store.update_job)
  semantic     facts: agent_memory "fact" rows per project, entity facts per org
  procedural   how to do it: lessons learned from validation failures, fed into the next prompt (lessons())
  long_term    everything here is persisted in Postgres; llm_cache is the long-term recall of exact GPT answers
  entity       per org, per brand: industry, competitors, products, audiences, web-grounded executives/launches
  relationship per org: brand -> competitor / product / audience edges
  reflection   per project: what failed in a stage and what the retry was told (reflect())
  user         per user: preferences that follow the user across projects

Every function here is best-effort: memory must never fail or slow a stage, so errors are logged and the caller
gets the "nothing remembered" answer."""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
import time
from contextlib import contextmanager
from typing import Any, Iterable, Optional

from ...core import store

logger = logging.getLogger(__name__)

TYPES = ("short_term", "episodic", "semantic", "procedural", "long_term", "entity", "relationship", "reflection",
         "user", "llm_cache")
LLM_CACHE_TTL = 7 * 86400          # an identical prompt within a week gets the same answer without a GPT call
GROUNDING_TTL = 14 * 86400         # web-grounded executives/launches go stale, so they are re-searched after this
MAX_LESSONS = 6
MAX_REFLECTIONS = 10

_fresh: contextvars.ContextVar[bool] = contextvars.ContextVar("memory_fresh", default=False)


@contextmanager
def fresh():
    """Inside this block nothing is recalled (writes still happen): Reanalyze / Regenerate must ask GPT again."""
    token = _fresh.set(True)
    try:
        yield
    finally:
        _fresh.reset(token)


def _safe(default):
    def wrap(fn):
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logger.warning("memory %s skipped: %s: %s", fn.__name__, type(e).__name__, e)
                return default
        inner.__name__ = fn.__name__
        inner.__doc__ = fn.__doc__
        return inner
    return wrap


def brand_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


# ─── long_term: exact GPT answer recall ──────────────────────────────────────

def llm_key(model: str, messages: list[dict], format_json: bool) -> str:
    raw = json.dumps([model, format_json, messages], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


@_safe(None)
def recall_llm(key: str) -> Optional[str]:
    if _fresh.get():
        return None
    item = store.get_memory_item("global", "", "llm_cache", key)
    return item["value"] if item else None


@_safe(None)
def remember_llm(key: str, text: str) -> None:
    if text and text.strip():
        store.put_memory_item("global", "", "llm_cache", key, text, ttl_seconds=LLM_CACHE_TTL)


# ─── entity + relationship (org scope) ───────────────────────────────────────

def _org(project_id: Optional[int]) -> str:
    project = store.get_project(project_id) if project_id else None
    return str((project or {}).get("org_id") or "")


@_safe(None)
def learn_from_spec(project_id: int, spec: dict) -> None:
    """Store the brand's entity facts and relationships from an analysed spec, for every project of the org."""
    org = _org(project_id)
    brand = (spec.get("commissioning_brand") or {}).get("name") or ""
    key = brand_key(brand)
    if not org or not key:
        return
    by_type: dict[str, list[str]] = {}
    for e in spec.get("validated_entities") or []:
        if e.get("name") and e.get("type"):
            by_type.setdefault(e["type"], []).append(e["name"])
    industry = spec.get("industry") or {}
    facts = {"name": brand, "industry": industry.get("name") if isinstance(industry, dict) else industry,
             "competitors": by_type.get("competitor", []), "products": by_type.get("product", []),
             "audiences": by_type.get("audience", []), "project_id": project_id}
    store.put_memory_item("org", org, "entity", key, facts)
    for kind, rel in (("competitor", "competes_with"), ("product", "makes"), ("audience", "targets")):
        for other in by_type.get(kind, []):
            store.put_memory_item("org", org, "relationship", f"{key}|{rel}|{brand_key(other)}",
                                  {"from": brand, "rel": rel, "to": other, "project_id": project_id})


@_safe(None)
def recall_entity(project_id: Optional[int], brand: str) -> Optional[dict]:
    if _fresh.get():
        return None
    org, key = _org(project_id), brand_key(brand)
    item = store.get_memory_item("org", org, "entity", key) if org and key else None
    return item["value"] if item else None


@_safe("")
def entity_prompt(project_id: Optional[int], brand: str) -> str:
    """What earlier projects of this org learned about the brand, as a hint the brief still overrides."""
    facts = recall_entity(project_id, brand)
    if not facts:
        return ""
    lines = [f"- {label}: {', '.join(facts[k])}" for k, label in
             (("competitors", "Competitors"), ("products", "Products"), ("audiences", "Audiences")) if facts.get(k)]
    if facts.get("industry"):
        lines.insert(0, f"- Industry: {facts['industry']}")
    if not lines:
        return ""
    return (f"\n\nKNOWN FROM EARLIER PROJECTS ABOUT {facts['name']} (use when the brief does not say otherwise; "
            "the brief always wins):\n" + "\n".join(lines))


@_safe(None)
def recall_grounding(project_id: Optional[int], brand: str) -> Optional[list[dict]]:
    if _fresh.get():
        return None
    org, key = _org(project_id), brand_key(brand)
    item = store.get_memory_item("org", org, "entity", f"grounded:{key}") if org and key else None
    return item["value"] if item else None


@_safe(None)
def remember_grounding(project_id: Optional[int], brand: str, added: list[dict]) -> None:
    org, key = _org(project_id), brand_key(brand)
    if org and key:
        store.put_memory_item("org", org, "entity", f"grounded:{key}", added, ttl_seconds=GROUNDING_TTL)


# ─── procedural + reflection ─────────────────────────────────────────────────

def _field(field: str) -> str:
    return re.sub(r"\[\d+\]", "[]", field or "")


@_safe(None)
def reflect(agent: str, errors: Iterable[Any], project_id: Optional[int] = None) -> None:
    """Turn one attempt's validation failures into lessons: a reflection on the project, and a procedural lesson
    (with a count) shared by every later run of `agent`. `errors` are ValidationError-like (field, message) or str."""
    pairs = [(_field(getattr(e, "field", "")) or re.sub(r"\d+", "#", str(e))[:60], getattr(e, "message", str(e)))
             for e in errors]
    if not pairs:
        return
    for field, message in pairs:
        key = f"{agent}:{field}"
        old = store.get_memory_item("global", "", "procedural", key)
        count = (old["value"].get("count", 0) if old else 0) + 1
        store.put_memory_item("global", "", "procedural", key, {"agent": agent, "field": field,
                                                                 "message": message[:300], "count": count})
    if project_id:
        old = store.get_memory_item("project", str(project_id), "reflection", agent)
        history = (old["value"] if old else [])[-(MAX_REFLECTIONS - 1):]
        history.append({"at": time.time(), "failed": [f for f, _ in pairs]})
        store.put_memory_item("project", str(project_id), "reflection", agent, history)


@_safe("")
def lessons(agent: str) -> str:
    """The checks `agent` failed most often before, as a prompt section, so the first attempt passes them."""
    items = [i["value"] for i in store.list_memory_items("global", "", "procedural", limit=200)
             if i["value"].get("agent") == agent]
    items.sort(key=lambda v: -v.get("count", 0))
    if not items:
        return ""
    lines = [f"- {v['field']}: {v['message']}" for v in items[:MAX_LESSONS]]
    return "\n\nLESSONS FROM EARLIER RUNS (these checks failed before; get them right first time):\n" + "\n".join(lines)


# ─── episodic ────────────────────────────────────────────────────────────────

@_safe(None)
def record_episode(job_id: str, status: str, error: str = "") -> None:
    """One agent_events row per finished stage job: which stage, how it ended, how long it took."""
    job = store.get_job(job_id)
    if not job or not job.get("project_id"):
        return
    took = round(time.time() - (job.get("started_at") or job.get("created_at") or time.time()), 1)
    store.add_agent_event(job["project_id"], "pipeline", f"{job.get('job_type')}_{status}",
                          {"job_id": job_id, "seconds": took, "error": (error or job.get("error") or "")[:300]})


# ─── user ────────────────────────────────────────────────────────────────────

@_safe(None)
def remember_user(user_id: Optional[int], key: str, value) -> None:
    if user_id:
        store.put_memory_item("user", str(user_id), "user", key, value)


@_safe({})
def user_prefs(user_id: Optional[int]) -> dict:
    if not user_id:
        return {}
    return {i["key"]: i["value"] for i in store.list_memory_items("user", str(user_id), "user")}


@_safe([])
def stats() -> list[dict]:
    return store.memory_stats()
