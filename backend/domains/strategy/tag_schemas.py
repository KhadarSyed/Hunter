"""Each research question's dynamic tag schema -- the tags the question needs, mapped to the Review table's columns --
derived once and stored, like its dimensions. Re-derived when the question, its query or the Review columns change, or
when it was derived without the LLM and one is now reachable."""
from __future__ import annotations

import hashlib
import json

from ...agents import question_tag_schema as ts
from ...core import store
from .dimensions import project_dimensions


def review_columns(dims_by_rq: dict) -> list[dict]:
    """The Review table's question columns: one per dimension key across every question (as the table draws them)."""
    seen: dict[str, str] = {}
    for dims in dims_by_rq.values():
        for d in dims:
            seen.setdefault(d.key, d.label)
    return [{"key": k, "label": v} for k, v in seen.items()]


def _signature(question: str, query: str, columns: list[dict]) -> str:
    return hashlib.sha1("\n".join([question, query, json.dumps(columns, sort_keys=True)]).encode("utf-8")).hexdigest()


def project_tag_schemas(project_id: int, llm=None) -> dict[str, ts.TagSchema]:
    strategy = (store.get_latest_strategy(project_id) or {}).get("strategy") or {}
    questions = strategy.get("research_question_queries") or []
    dims_by_rq = project_dimensions(project_id, llm)
    columns = review_columns(dims_by_rq)
    stored = store.get_question_tag_schemas(project_id)
    llm_ok = llm is not None and getattr(llm, "is_reachable", lambda: False)()
    out: dict[str, ts.TagSchema] = {}
    for i, q in enumerate(questions, start=1):
        rq_id = q.get("question_id") or f"RQ{i}"
        question, query = q.get("question") or "", q.get("query") or ""
        sig = _signature(question, query, columns)
        cached = stored.get(rq_id)
        if cached and cached["signature"] == sig and (cached["source"] == "llm" or not llm_ok):
            out[rq_id] = ts.from_json(cached["schema"])
            continue
        schema, source = ts.derive(llm if llm_ok else None, rq_id, question, query, columns, dims_by_rq.get(rq_id))
        store.save_question_tag_schema(project_id, rq_id, sig, ts.to_json(schema), source)
        out[rq_id] = schema
    return out


def schema_for_dataset(dataset: dict, llm=None) -> ts.TagSchema | None:
    """The schema of the question a dataset was uploaded for (none when it is not mapped to one)."""
    return project_tag_schemas(dataset["project_id"], llm).get(dataset.get("research_question_id") or "")
