"""Sample enrichment: tag a bounded sample instead of every row -- N records in total, at least M per research
question, the rest split by each question's volume. The sample is spread evenly through each file, skips rows
already tagged against the questions, and merges into each dataset's stored enrichment by URL (an analyst's manual
edits are never overwritten; records with no URL, left by a misparsed file, are dropped). The deck still reads
every row of every file; enrichment only adds the LLM's tags to the sampled ones.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ...agents.dataset_enrichment import enrich_dataset
from ...core import store
from ..deliverable.ingest import normalize_url
from ..execution.service import _is_excluded, _load_dataset
from .dimensions import dimensions_for_dataset
from .tag_schemas import schema_for_dataset

logger = logging.getLogger(__name__)
TOTAL = 500
PER_RQ = 100


def allocate(available: dict[str, int], total: int = TOTAL, per_rq: int = PER_RQ) -> dict[str, int]:
    """Each key gets min(per_rq, available); what is left of `total` is split by spare volume (largest first)."""
    alloc = {k: min(per_rq, n) for k, n in available.items()}
    spare = {k: available[k] - alloc[k] for k in available}
    left, pool = total - sum(alloc.values()), sum(spare.values())
    if left <= 0 or not pool:
        return alloc
    extra = {k: min(spare[k], left * spare[k] // pool) for k in spare}
    rest = left - sum(extra.values())
    for k in sorted(spare, key=lambda k: -spare[k]):
        while rest > 0 and extra[k] < spare[k]:
            extra[k] += 1
            rest -= 1
    return {k: alloc[k] + extra[k] for k in alloc}


def budget(available: dict[str, int], tagged: dict[str, int], total: int = TOTAL, per_rq: int = PER_RQ) -> dict[str, int]:
    """What each question may still tag when `tagged` records already count against the project's `total` and
    each question's `per_rq` floor -- a rerun tops up, it never tags `total` more."""
    left = max(0, total - sum(tagged.values()))
    floors = {k: min(max(0, per_rq - tagged.get(k, 0)), n) for k, n in available.items()}
    if sum(floors.values()) >= left:
        return allocate(floors, left, 0)
    rest = allocate({k: available[k] - floors[k] for k in available}, left - sum(floors.values()), 0)
    return {k: floors[k] + rest[k] for k in available}


def pick(records: list[dict], n: int, skip: set[str]) -> list[dict]:
    """n records with a URL and text, evenly spaced through the file (so the sample spans the whole period)."""
    seen: set[str] = set()
    candidates = []
    for r in records:
        url = normalize_url(r.get("url") or "")
        if url and (r.get("content") or r.get("title")) and url not in skip and url not in seen:
            seen.add(url)
            candidates.append(r)
    if n <= 0:
        return []
    if n >= len(candidates):
        return candidates
    step = len(candidates) / n
    return [candidates[int(i * step + step / 2)] for i in range(n)]


def _file_records(path: str) -> list[dict]:
    """The dataset file as enrichment records (the same reader the deck uses)."""
    out = []
    for i, row in enumerate(_load_dataset(path)):
        title = str(row.get("headline") or row.get("title") or "").strip()
        content = str(row.get("content") or "").strip()
        out.append({"id": f"f{i}", "title": title or content[:80], "content": content or title,
                    "url": str(row.get("url") or "").strip(), "date": str(row.get("date") or ""),
                    "source_name": str(row.get("source") or row.get("source_name") or ""),
                    "author": str(row.get("author") or ""), "country": str(row.get("country") or ""),
                    "media_type": str(row.get("media_type") or ""), "reach": str(row.get("reach") or ""),
                    "review_status": "relevant", "approval_status": "pending", "disapproval_reason": None,
                    "reviewed_by": None, "reviewed_at": None, "manually_edited": False})
    return out


def _merge(existing: list[dict], tagged: list[dict]) -> list[dict]:
    """Existing records with a URL stay (manual edits untouched); sampled ones update theirs or are appended."""
    kept = [r for r in existing if (r.get("url") or "").strip()]
    by_url = {normalize_url(r["url"]): i for i, r in enumerate(kept)}
    for t in tagged:
        i = by_url.get(normalize_url(t["url"]))
        if i is None:
            kept.append(t)
        elif not kept[i].get("manually_edited"):
            kept[i] = {**kept[i], **{k: v for k, v in t.items() if k != "id"}}
    return kept


def _plan(datasets: list[dict], total: int, per_rq: int) -> list[tuple[dict, list[dict], list[dict]]]:
    """(dataset, records to sample, existing enrichment) for every dataset with a file."""
    loaded = []
    for ds in datasets:
        raw = (store.get_dataset_by_id(ds["id"]) or {}).get("enrichment_json")
        existing = json.loads(raw) if raw else []
        skip = {normalize_url(r.get("url") or "") for r in existing
                if r.get("url") and ("question_tags" in r or _is_excluded(r))}
        records = _file_records(ds["file_path"])
        loaded.append((ds, pick(records, len(records), skip), existing))
    by_rq: dict[str, list[int]] = {}
    tagged: dict[str, int] = {}
    for i, (ds, _, existing) in enumerate(loaded):
        rq = ds.get("research_question_id") or "unmapped"
        by_rq.setdefault(rq, []).append(i)
        tagged[rq] = tagged.get(rq, 0) + sum(1 for r in existing if "question_tags" in r)
    rq_alloc = budget({rq: sum(len(loaded[i][1]) for i in idx) for rq, idx in by_rq.items()}, tagged, total, per_rq)
    plan = []
    for rq, idx in by_rq.items():
        ds_alloc = allocate({str(i): len(loaded[i][1]) for i in idx}, rq_alloc[rq], 0)
        for i in idx:
            ds, candidates, existing = loaded[i]
            plan.append((ds, pick(candidates, ds_alloc[str(i)], set()), existing))
    return plan


def _retag_with_schema(datasets: list[dict], brand: str, competitors: list[str], llm, emit) -> int:
    """Articles already in the sample but tagged before their question had a dynamic tag schema are tagged again
    against it -- the same articles, so the sample does not grow; an analyst's manual edits are never redone."""
    retagged = 0
    for ds in datasets:
        schema = schema_for_dataset(ds, llm)
        raw = (store.get_dataset_by_id(ds["id"]) or {}).get("enrichment_json")
        existing = json.loads(raw) if raw else []
        stale = [r for r in existing if schema and schema.tags and "question_tags" in r
                 and ("dynamic_tags" not in r or "question_summary" not in r)
                 and not r.get("manually_edited") and (r.get("url") or "").strip() and (r.get("content") or r.get("title"))]
        if not stale:
            continue
        stale = [{**r, "content": r.get("content") or r.get("title")} for r in stale]
        result = enrich_dataset(stale, brand, competitors, llm_client=llm, emit=emit,
                                dimensions=dimensions_for_dataset(ds, llm), tag_schema=schema)
        store.update_dataset_enrichment(ds["id"], "done", enrichment=_merge(existing, result["records"]))
        retagged += len(stale)
    return retagged


def run_sample(project_id: int, llm, total: int = TOTAL, per_rq: int = PER_RQ, emit=None) -> dict:
    datasets = [d for d in store.get_datasets_by_project(project_id)
                if d.get("approval_status") == "approved" and d.get("file_path") and Path(d["file_path"]).exists()]
    project = store.get_project(project_id) or {}
    spec = project.get("spec") or {}
    brand = (spec.get("commissioning_brand") or {}).get("name") or project.get("brand") or project.get("name") or ""
    competitors = [e["name"] for e in spec.get("validated_entities") or [] if e.get("type") == "competitor"]
    retagged = _retag_with_schema(datasets, brand, competitors, llm, emit)
    by_rq: dict[str, int] = {}
    for ds, sample, existing in _plan(datasets, total, per_rq):
        if not sample:
            continue
        rq = ds.get("research_question_id") or "unmapped"
        store.update_dataset_enrichment(ds["id"], "processing", enrichment=existing or None)
        try:
            result = enrich_dataset(sample, brand, competitors, llm_client=llm, emit=emit,
                                    dimensions=dimensions_for_dataset(ds, llm), tag_schema=schema_for_dataset(ds, llm))
        except Exception as e:
            logger.error("sample enrichment of dataset %s failed: %s", ds["id"], type(e).__name__)
            store.update_dataset_enrichment(ds["id"], "error", enrichment=existing or None, error=str(e)[:300])
            raise
        store.update_dataset_enrichment(ds["id"], "done", enrichment=_merge(existing, result["records"]))
        by_rq[rq] = by_rq.get(rq, 0) + len(sample)
    return {"by_rq": by_rq, "total": sum(by_rq.values()), "retagged": retagged}
