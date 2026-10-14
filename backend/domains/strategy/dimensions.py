"""Each research question's breakdown dimensions (sport, injury type, ...), derived once and stored.

Enrichment tags every record against these and the deliverable charts them, so both read the same stored copy.
A question is re-derived when its text or query changes, or when it was derived without the LLM and one is now
reachable. The LLM is asked about every question, so one with no keyword lists can still get judged categories.
"""
from __future__ import annotations

import hashlib

from ...agents import question_dimensions as qd
from ...core import store


def _brand_terms(project: dict, queries: list[str]) -> list[str]:
    """The project's brand and competitors, plus any OR group every query shares (the brand clause)."""
    spec = project.get("spec") or {}
    names = [project.get("brand") or "", project.get("name") or ""]
    names += [e.get("name") or "" for e in spec.get("validated_entities") or []
              if e.get("type") in ("brand", "competitor", "primary_brand")]
    groups = [{frozenset(g) for g in qd.query_groups(q, [])} for q in queries if q]
    shared = set.intersection(*groups) if len(groups) > 1 else set()
    return [n for n in names if n] + [t for g in shared for t in g]


def _signature(question: str, query: str, brands: list[str]) -> str:
    return hashlib.sha1("\n".join([question, query, *sorted(brands)]).encode("utf-8")).hexdigest()


def project_dimensions(project_id: int, llm=None) -> dict[str, list[qd.Dimension]]:
    strategy = (store.get_latest_strategy(project_id) or {}).get("strategy") or {}
    questions = strategy.get("research_question_queries") or []
    brands = _brand_terms(store.get_project(project_id) or {}, [q.get("query") or "" for q in questions])
    stored = store.get_question_dimensions(project_id)
    llm_ok = llm is not None and getattr(llm, "is_reachable", lambda: False)()
    out: dict[str, list[qd.Dimension]] = {}
    for i, q in enumerate(questions, start=1):
        rq_id = q.get("question_id") or f"RQ{i}"
        question, query = q.get("question") or "", q.get("query") or ""
        sig = _signature(question, query, brands)
        cached = stored.get(rq_id)
        if cached and cached["signature"] == sig and (cached["source"] == "llm" or not llm_ok):
            out[rq_id] = qd.from_json(cached["dimensions"])
            continue
        dims, source = qd.derive_with_source(llm if llm_ok else None, question, query, brands)
        store.save_question_dimensions(project_id, rq_id, sig, qd.to_json(dims), source)
        out[rq_id] = dims
    return out


def _union(dim_lists: list[list[qd.Dimension]]) -> list[qd.Dimension]:
    """Dimensions of several questions as one list: the same key merges its values."""
    merged: dict[str, qd.Dimension] = {}
    for dims in dim_lists:
        for d in dims:
            have = merged.get(d.key)
            if have is None:
                merged[d.key] = d
                continue
            names = {v.name for v in have.values}
            merged[d.key] = qd.Dimension(have.key, have.label, have.values + tuple(v for v in d.values if v.name not in names))
    return list(merged.values())


def dimensions_for_dataset(dataset: dict, llm=None) -> list[qd.Dimension]:
    """The dimensions of the question a dataset was uploaded for; every question's when it is not mapped to one."""
    by_rq = project_dimensions(dataset["project_id"], llm)
    rq = dataset.get("research_question_id")
    return by_rq[rq] if rq in by_rq else _union(list(by_rq.values()))
