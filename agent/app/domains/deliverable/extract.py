"""Per-article entity extraction for the fields a plan needs, cached by URL so re-runs are free and stable."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

from ...core import store
from .engine_types import EngineRow

logger = logging.getLogger(__name__)
BATCH = 8
EXTRACT_SAMPLE = 400     # articles classified per question: the most-read ones, so cost is bounded on 40k+ rows
EXTRACT_WORKERS = 4      # concurrent model calls; one batch at a time made big questions take minutes
MAX_TEXT = 3000

FIELDS: dict[str, dict] = {
    "experts": {"name": None, "expert_type": ["dermatologist", "pediatrician", "other_hcp", "non_hcp_expert"],
                "affiliation": ["affiliated", "independent"], "brand": None},
    "celebrities": {"name": None, "role": ["spokesperson", "product_mention", "lifestyle"]},
    "brands": {"name": None},
    "products": {"name": None},
    "retailers": {"name": None},
}
_INSTRUCTIONS = {
    "experts": "List every expert quoted or cited. expert_type: dermatologist, pediatrician, other_hcp (nurse, "
               "pharmacist, other clinician) or non_hcp_expert. affiliation 'affiliated' only if the article states a "
               "brand tie (works for, paid by, partners with, spokesperson for) and put that brand in brand; "
               "'independent' only if stated; otherwise 'unknown'.",
    "celebrities": "List every celebrity named. role: spokesperson (paid / brand partner), product_mention, or lifestyle.",
    "brands": "List every consumer brand named.",
    "products": "List every specific product named.",
    "retailers": "List every retailer named (Amazon, Target, Walmart, ...).",
}


class ExtractionUnavailable(RuntimeError):
    pass


def _clean(item: dict, schema: dict) -> dict | None:
    if not isinstance(item, dict) or not str(item.get("name") or "").strip():
        return None
    out = {}
    for key, allowed in schema.items():
        value = item.get(key)
        if allowed is None:
            out[key] = str(value).strip() if value else ""
        else:
            out[key] = value if value in allowed else "unknown"
    return out


def _classify_batch(llm, batch: list[EngineRow], kind: str, example: str) -> dict:
    arts = [{"id": i, "title": r.article.title, "text": r.article.text[:MAX_TEXT]} for i, r in enumerate(batch)]
    messages = [
        {"role": "system", "content": _INSTRUCTIONS[kind] + " Use only what each article says; unknown stays "
         f"'unknown'. Return JSON only: {{\"results\": [{{\"id\": <id>, \"items\": [{example}]}}]}}"},
        {"role": "user", "content": "ARTICLES:" + json.dumps(arts, ensure_ascii=False)},
    ]
    try:
        parsed = json.loads(llm.chat(messages, format_json=True))
    except (json.JSONDecodeError, RuntimeError) as e:
        raise ExtractionUnavailable(f"extraction failed: {e}") from e
    return {r.get("id"): r.get("items") or [] for r in parsed.get("results") or [] if isinstance(r, dict)}


def most_read(rows: list[EngineRow], n: int = EXTRACT_SAMPLE) -> list[EngineRow]:
    return sorted(rows, key=lambda r: (-r.article.reach, -r.copies, r.article.norm_url))[:n]


def _classify_resilient(llm, batch: list[EngineRow], kind: str, example: str) -> dict:
    """A refused batch (Azure's content filter, a malformed reply) is retried one article at a time, so only the
    article that trips it is left out. Raises only when every article fails."""
    try:
        return _classify_batch(llm, batch, kind, example)
    except ExtractionUnavailable:
        if len(batch) == 1:
            raise
    out: dict = {}
    for i, row in enumerate(batch):
        try:
            out[i] = _classify_batch(llm, [row], kind, example).get(0, [])
        except ExtractionUnavailable as e:
            logger.warning("extraction skipped one article for %s: %s", kind, str(e)[:80])
    if not out:
        raise ExtractionUnavailable("every article in the batch was refused")
    return out


def extract(llm, rows: list[EngineRow], kind: str, progress=None) -> dict[str, list[dict]]:
    """`progress(done, total)` is called as articles are classified (cached ones count as done at once)."""
    schema = FIELDS[kind]
    out: dict[str, list[dict]] = {}
    todo = []
    for row in rows:
        cached = store.get_cached_classification(row.article.norm_url, kind)
        if cached is None:
            todo.append(row)
        else:
            out[row.article.norm_url] = cached
    done = len(rows) - len(todo)
    if progress:
        progress(done, len(rows))
    if not todo:
        return out
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        raise ExtractionUnavailable("Azure OpenAI is not reachable")
    model = getattr(llm, "model_name", "") or "azure-openai"
    example = json.dumps({k: (v[0] if v else "") for k, v in schema.items()})
    batches = [todo[start:start + BATCH] for start in range(0, len(todo), BATCH)]
    with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as pool:
        futures = {pool.submit(_classify_resilient, llm, batch, kind, example): batch for batch in batches}
        failed = 0
        for fut in as_completed(futures):
            batch = futures[fut]
            try:
                by_id = fut.result()
            except ExtractionUnavailable as e:
                failed += 1
                logger.warning("extraction batch for %s failed: %s", kind, str(e)[:80])
                by_id = {}
            for i, row in enumerate(batch):     # results are saved here, on one thread; refused ones retry later
                if i not in by_id:
                    continue
                items = [c for c in (_clean(it, schema) for it in by_id[i]) if c]
                store.save_cached_classification(row.article.norm_url, kind, items, model)
                out[row.article.norm_url] = items
            done += len(batch)
            if progress:
                progress(done, len(rows))
    if failed == len(batches):
        raise ExtractionUnavailable("Azure OpenAI refused every batch")
    return out
