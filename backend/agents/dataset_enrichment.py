"""Dataset Enrichment Agent -- tags every record in an uploaded Data Sources
export with sentiment, themes, signals, entities, and per-brand sentiment
scores, via batched LLM calls.

Requires `title` and `content` per record (both must be present and
non-empty) -- records missing either are skipped and reported separately
rather than sent to the LLM.

Like every other agent in this codebase, classification is LLM-driven but
the batching/retry/merge orchestration around it is deterministic and
auditable -- no field is ever invented when the LLM omits it; it comes back
null and the record is flagged.

v1.0.0 -- Initial implementation.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

from ..core.llm_provider import HybridLLMClient
from . import question_dimensions as qd
from . import question_tag_schema as ts

EventFn = Callable[[str, dict], None]

BATCH_SIZE = 8
MAX_ROUNDS = 3

SENTIMENTS = ["Positive", "Neutral", "Negative"]
BRAND_MENTIONS = ("literal", "figurative", "none")
AUTHOR_TYPES = ["Consumer", "Parent", "Athlete", "Coach", "Healthcare professional", "Journalist / media",
                "Influencer / creator", "Brand / company", "Retailer", "Organisation", "Unknown"]


SYSTEM_PROMPT = """\
You are a media-monitoring enrichment agent. You read news articles and \
social media posts and tag each one with structured analysis for a PR/brand \
intelligence platform. You NEVER fabricate information not supported by the \
text -- when genuinely uncertain, lower the confidence score rather than \
guessing with false certainty.

For EVERY article/post supplied, return ALL of these fields:

- id: the exact id supplied with that article (string).
- overall_sentiment: one of "Positive", "Neutral", "Negative" -- the
  general tone of the piece.
- overall_sentiment_confidence: 0.0-1.0.
- themes: {"primary": "<short theme>", "secondary": "<short theme or null>",
  "tertiary": "<short theme or null>"} -- the main subjects/angles discussed,
  most prominent first. secondary/tertiary are null if the piece is too
  short or narrow to support a second/third distinct theme.
- signals: a short array of notable signals or patterns worth flagging to an
  analyst (e.g. "pricing complaint", "recall mention", "viral moment",
  "executive quote", "regulatory reference") -- empty array if none.
- entities: {"brands": [...], "companies": [...], "organizations": [...],
  "people": [...], "products": [...], "events": [...]} -- named entities
  actually mentioned in the text, by category. Empty arrays where none
  found. A company that is also the brand of interest still belongs in
  "brands".
- brand_sentiments: an array with one entry per brand actually discussed
  (the primary brand AND any competitor/other brand named), each:
  {"brand": "<name>", "is_primary": true|false, "sentiment": "Positive"|
  "Neutral"|"Negative", "confidence": 0.0-1.0}. Only include a brand here if
  the text says something substantive about it, not a bare mention.
- author_type: who wrote or posted it, one of: Consumer, Parent, Athlete,
  Coach, Healthcare professional, Journalist / media, Influencer / creator,
  Brand / company, Retailer, Organisation, Unknown.
- brand_mention: how the text uses the brand of interest's name: "literal"
  (the product or company itself), "figurative" (a figure of speech, e.g.
  "a band-aid solution", "they need a band-aid, and quickly") or "none".
- question_tags: only when QUESTION DIMENSIONS are supplied -- an object with
  one key per dimension key, each an array of that dimension's value names
  the text actually talks about (exact names from the list; [] if none).
  These are what the research questions ask about (e.g. which sport, which
  injury type), so tag them carefully.
- dynamic_tags, tag_evidence, tag_confidence: only when a DYNAMIC TAG SCHEMA
  is supplied. dynamic_tags has one key per schema tag_name the article
  supports: a classification gets one allowed value, a multi_classification or
  entity gets an array (entities exactly as written in the article).
  tag_evidence gives, per tag, an exact quote copied from the article that
  supports it; tag_confidence a 0.0-1.0 number per tag. Use only the article:
  omit a tag it does not support, never add tags outside the schema, never
  score or weight anything.
- question_summary: only when a DYNAMIC TAG SCHEMA is supplied -- one
  sentence, from the article only, on what it says that bears on the
  schema's question (or that it says nothing about it).
- reason: one sentence explaining why you tagged it this way (what in the
  text drove the overall sentiment and theme calls).

Return ONLY a JSON object: {"articles": [ ...one entry per supplied article, \
same ids, same order not required... ]}
"""


def _extract_json_object(text: str) -> dict:
    """Pull the first valid JSON object from LLM output, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    brace_start = text.find("{")
    if brace_start == -1:
        raise ValueError("No JSON object found in LLM response")
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[brace_start:], start=brace_start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[brace_start:i + 1])
    raise ValueError("Unbalanced JSON object in LLM response")


def chunk(items: list, size: int) -> list[list]:
    if size < 1:
        size = 1
    return [items[i:i + size] for i in range(0, len(items), size)]


def _blank_tags(reason: str) -> dict:
    return {
        "overall_sentiment": None,
        "overall_sentiment_confidence": None,
        "themes": {"primary": None, "secondary": None, "tertiary": None},
        "signals": [],
        "entities": {"brands": [], "companies": [], "organizations": [], "people": [], "products": [], "events": []},
        "brand_sentiments": [],
        "reason": None,
        "enrichment_error": reason,
    }


def _dimensions_prompt(dimensions: list[qd.Dimension] | None) -> str:
    if not dimensions:
        return ""
    listed = [{"key": d.key, "label": d.label, "values": [v.name for v in d.values]} for d in dimensions]
    return f"QUESTION DIMENSIONS (tag question_tags against these):\n{json.dumps(listed, ensure_ascii=False)}\n\n"


def _schema_prompt(tag_schema: ts.TagSchema | None) -> str:
    if not tag_schema or not tag_schema.tags:
        return ""
    return (f"DYNAMIC TAG SCHEMA for the question \"{tag_schema.question}\" (fill dynamic_tags, tag_evidence, "
            f"tag_confidence against it):\n{ts.prompt_block(tag_schema)}\n\n")


def _build_user_prompt(batch: list[dict], brand: str, competitors: list[str],
                       dimensions: list[qd.Dimension] | None = None, tag_schema: ts.TagSchema | None = None) -> str:
    articles_payload = [
        {
            "id": a["id"],
            "title": a.get("title", "")[:300],
            "content": a.get("content", "")[:1500],
        }
        for a in batch
    ]
    return (
        f"Brand of interest: {brand or '(not specified)'}\n"
        f"Known competitors: {', '.join(competitors) if competitors else '(none specified)'}\n\n"
        f"{_dimensions_prompt(dimensions)}"
        f"{_schema_prompt(tag_schema)}"
        f"Articles to tag:\n{json.dumps(articles_payload, ensure_ascii=False)}"
    )


def tag_batch(llm_client: HybridLLMClient, batch: list[dict], brand: str, competitors: list[str],
              dimensions: list[qd.Dimension] | None = None, tag_schema: ts.TagSchema | None = None) -> list[dict]:
    """One LLM call tagging a batch; raises on failure (caller retries/repairs)."""
    raw = llm_client.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(batch, brand, competitors, dimensions, tag_schema)},
        ],
        format_json=True,
    )
    data = _extract_json_object(raw)
    return data.get("articles", [])


def _question_tags(record: dict, llm_tags, dimensions: list[qd.Dimension]) -> dict[str, list[str]]:
    """The LLM's tags where they name real values; the question's own keywords for any dimension it left out
    or filled with names that are not in the list."""
    keyword = None
    out: dict[str, list[str]] = {}
    llm_tags = llm_tags if isinstance(llm_tags, dict) else {}
    for dim in dimensions:
        valid = qd.valid_names(llm_tags.get(dim.key), dim)
        if valid is None:
            if keyword is None:
                keyword = qd.tag_text(f"{record.get('title') or ''}\n{record.get('content') or ''}", dimensions)
            valid = keyword[dim.key]
        out[dim.key] = valid
    return out


_DYNAMIC_KEYS = ("dynamic_tags", "tag_evidence", "tag_confidence", "tag_schema_question", "question_summary")
MAX_SUMMARY = 300


def _finish(record: dict, tag: dict, dimensions: list[qd.Dimension] | None,
            tag_schema: ts.TagSchema | None = None) -> dict:
    author = tag.get("author_type")
    merged = {**record, **{k: v for k, v in tag.items() if k != "id"},
              "author_type": author if author in AUTHOR_TYPES else "Unknown",
              "brand_mention": tag.get("brand_mention") if tag.get("brand_mention") in BRAND_MENTIONS else ""}
    if dimensions:
        merged["question_tags"] = _question_tags(record, tag.get("question_tags"), dimensions)
    else:
        merged.pop("question_tags", None)
    for key in _DYNAMIC_KEYS:
        merged.pop(key, None)
    if tag_schema and tag_schema.tags:
        text = f"{record.get('title') or ''}\n{record.get('content') or ''}"
        tags, evidence, confidence = ts.clean_article_tags(tag_schema, tag.get("dynamic_tags"), tag.get("tag_evidence"),
                                                            tag.get("tag_confidence"), text)
        merged.update(dynamic_tags=tags, tag_evidence=evidence, tag_confidence=confidence,
                      tag_schema_question=tag_schema.question_id,
                      question_summary=" ".join(str(tag.get("question_summary") or "").split())[:MAX_SUMMARY])
    return merged


def _tag_batch_with_repair(
    llm_client: HybridLLMClient, batch: list[dict], brand: str, competitors: list[str],
    dimensions: list[qd.Dimension] | None = None, tag_schema: ts.TagSchema | None = None,
) -> list[dict]:
    """Tag a batch, re-requesting whatever the model leaves out of its response.

    The model does not reliably return one entry per article at larger batch
    sizes; each round asks only for the ids still missing, which also covers
    transient per-batch failures without re-paying for articles that already
    tagged successfully.
    """
    collected: dict[str, dict] = {}
    outstanding = list(batch)
    last_error = ""

    for round_number in range(1, MAX_ROUNDS + 1):
        if not outstanding:
            break
        try:
            tagged = tag_batch(llm_client, outstanding, brand, competitors, dimensions, tag_schema)
            for entry in tagged:
                key = str(entry.get("id"))
                if key and key not in collected:
                    collected[key] = entry
        except Exception as exc:  # noqa: BLE001 -- one bad batch must not kill the run
            last_error = str(exc)
            logger.warning("[dataset_enrichment] Round %s failed: %s", round_number, exc)
        outstanding = [a for a in batch if str(a["id"]) not in collected]

    reason = last_error or "missing from response after repair rounds"
    return [collected.get(str(a["id"])) or {"id": a["id"], **_blank_tags(reason)} for a in batch]


def enrich_dataset(
    records: list[dict],
    brand: str,
    competitors: list[str],
    *,
    llm_client: HybridLLMClient,
    emit: EventFn | None = None,
    dimensions: list[qd.Dimension] | None = None,
    tag_schema: ts.TagSchema | None = None,
) -> dict:
    """Enrich every record with title+content present. Records missing either
    are returned unmodified with `enrichment_error` set, never sent to the LLM.

    Parameters
    ----------
    records : list of dicts, each with at least "id", "title", "content" —
        plus whatever original columns the caller wants carried through
        (url, date, source_name, author, country, media_type, reach, ...).
    brand : the project's primary brand name.
    competitors : known competitor brand names from the search strategy.
    emit : optional callback for progress events (start/batch/complete).

    Returns
    -------
    dict with keys: records (the merged, enriched list, same order as input),
    tagged_count, skipped_count, failed_count, elapsed_seconds.
    """
    if emit is None:
        emit = lambda event_type, payload: None

    start = time.time()

    # Content is the hard requirement; title is not — a social post typically has
    # no separate headline, just body text (the loader backfills a display title
    # from the content in that case, so this only excludes genuinely empty rows).
    taggable = [r for r in records if (r.get("content") or "").strip()]
    taggable_ids = {r["id"] for r in taggable}
    skipped = [r for r in records if r["id"] not in taggable_ids]

    batches = chunk(taggable, BATCH_SIZE)
    emit("enrichment_started", {"total_records": len(records), "taggable": len(taggable), "skipped": len(skipped)})

    import concurrent.futures
    results: dict[str, dict] = {}
    completed = 0

    def worker(batch: list[dict]) -> list[dict]:
        return _tag_batch_with_repair(llm_client, batch, brand, competitors, dimensions, tag_schema)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(worker, b): b for b in batches}
        for future in concurrent.futures.as_completed(futures):
            tags = future.result()
            for t in tags:
                results[str(t.get("id"))] = t
            completed += 1
            emit("enrichment_batch", {
                "completed_batches": completed,
                "total_batches": len(batches),
                "tagged_count": len(results),
                "total_taggable": len(taggable),
            })

    merged: list[dict] = []
    failed_count = 0
    for r in records:
        if r["id"] not in taggable_ids:
            merged.append(_finish(r, _blank_tags("missing title or content"), dimensions, tag_schema))
            continue
        tag = results.get(str(r["id"])) or {"id": r["id"], **_blank_tags("no result returned")}
        if tag.get("enrichment_error"):
            failed_count += 1
        merged.append(_finish(r, tag, dimensions, tag_schema))

    elapsed = round(time.time() - start, 1)
    emit("enrichment_complete", {
        "tagged_count": len(taggable) - failed_count,
        "failed_count": failed_count,
        "skipped_count": len(skipped),
        "elapsed_seconds": elapsed,
    })

    return {
        "records": merged,
        "tagged_count": len(taggable) - failed_count,
        "skipped_count": len(skipped),
        "failed_count": failed_count,
        "elapsed_seconds": elapsed,
    }
