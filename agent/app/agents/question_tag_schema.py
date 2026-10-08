"""Question-driven dynamic tagging: the question, not a fixed taxonomy, decides what each article is tagged with.

For each research question the LLM derives the minimum tag schema needed to answer it -- a Yes/No classification for
"what proportion is deal/sale-led?", an expert type plus the cited expert's name and organisation for "which experts
are cited?" -- with a definition, allowed values and an extraction rule per tag. Articles are then tagged against that
schema with quoted evidence and a confidence. Every tag is mapped to an existing Review-table column; one that has no
column is flagged UNMAPPED_REVIEW_CRITERION. Points and weights belong to the Review table: nothing here scores.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TAG_TYPES = ("classification", "multi_classification", "entity")
MAX_TAGS = 6
MAX_ALLOWED = 12
MAX_ENTITIES = 10
MAX_EVIDENCE = 300
MIN_ALLOWED = 2
UNMAPPED = "UNMAPPED_REVIEW_CRITERION"
FROM_REVIEW_TABLE = "READ_FROM_REVIEW_TABLE"

_PROMPT = (
    "You are a question-driven dynamic tagging engine for media intelligence. Read the research QUESTION and derive "
    "the MINIMUM set of article-level tags needed to answer it. There is no fixed taxonomy: derive tags only from what "
    "the question asks. A question about a proportion of coverage gets a Yes/No classification for that coverage "
    "characteristic (e.g. deal_sale_led: Yes/No), optionally one supporting classification (e.g. deal_type). A question "
    "about who or what is cited gets the classification and the entities it needs (e.g. expert_cited Yes/No, "
    "expert_type, expert_name, expert_organization). Add entity tags (brands, competitor brands, companies, "
    "organizations, people, experts, conditions, products, events, sports, locations) ONLY when the question needs them. "
    f"At most {MAX_TAGS} tags. tag_type is one of {', '.join(TAG_TYPES)}; classifications list their allowed_values "
    "(include \"Unknown\" or \"None\" when an article may not say), entities list none. For each tag also give "
    "review_column: the key of the existing REVIEW COLUMN that records this tag, or null when none does. Never output "
    "points, weights or scores. Return JSON only: {\"question_intent\": \"<snake_case>\", \"required_tags\": "
    "[{\"tag_name\": \"<snake_case>\", \"tag_type\": \"...\", \"definition\": \"...\", \"allowed_values\": [...], "
    "\"extraction_rule\": \"...\", \"review_column\": \"<key or null>\"}]}"
)


@dataclass(frozen=True)
class TagDef:
    tag_name: str
    tag_type: str
    definition: str
    allowed_values: tuple[str, ...]
    extraction_rule: str
    review_column: str | None


@dataclass(frozen=True)
class TagSchema:
    question_id: str
    question: str
    question_intent: str
    tags: tuple[TagDef, ...]
    review_columns: tuple[tuple[str, str], ...]      # (key, label) of the Review-table columns when it was derived


MAX_NAME = 40


def _snake(name: str) -> str:
    """snake_case, at most MAX_NAME characters, cut at a word boundary."""
    words = [w for w in re.split(r"[^a-z0-9]+", str(name or "").lower()) if w]
    out = ""
    for w in words:
        if len(out) + len(w) + (1 if out else 0) > MAX_NAME:
            break
        out = f"{out}_{w}" if out else w
    return out or (words[0][:MAX_NAME] if words else "")


def _tags_from(data, columns: dict[str, str]) -> tuple[TagDef, ...]:
    out, seen = [], set()
    for raw in (data.get("required_tags") or []) if isinstance(data, dict) else []:
        if not isinstance(raw, dict):
            continue
        name, kind = _snake(raw.get("tag_name")), str(raw.get("tag_type") or "").strip()
        definition = str(raw.get("definition") or "").strip()[:300]
        if not name or name in seen or kind not in TAG_TYPES or not definition:
            continue
        allowed = tuple(dict.fromkeys(str(v).strip()[:40] for v in (raw.get("allowed_values") or [])
                                      if str(v).strip()))[:MAX_ALLOWED] if kind != "entity" else ()
        if kind != "entity" and len(allowed) < MIN_ALLOWED:
            continue
        column = str(raw.get("review_column") or "")
        seen.add(name)
        out.append(TagDef(name, kind, definition, allowed, str(raw.get("extraction_rule") or "").strip()[:300],
                          column if column in columns else None))
        if len(out) == MAX_TAGS:
            break
    return tuple(out)


def _from_dimensions(rq_id: str, question: str, dims, columns: dict[str, str]) -> TagSchema:
    """No LLM: the question's Review columns (its dimensions) are the schema, one multi-value tag each."""
    tags = tuple(TagDef(d.key, "multi_classification", f"{d.label} the article is about.",
                        tuple(v.name for v in d.values)[:MAX_ALLOWED],
                        "The values the article names" if not d.judged else "Judged from the article",
                        d.key if d.key in columns else None) for d in dims or [])
    return TagSchema(rq_id, question, "breakdown", tags, tuple(columns.items()))


def derive(llm, rq_id: str, question: str, query: str, review_columns: list[dict], dims=None) -> tuple[TagSchema, str]:
    """(schema, "llm" | "dimensions"): the tags this question needs, each mapped to a Review column when one exists."""
    columns = {str(c["key"]): str(c.get("label") or c["key"]) for c in review_columns or [] if c.get("key")}
    fallback = (_from_dimensions(rq_id, question, dims, columns), "dimensions")
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return fallback
    user = (f"QUESTION: {question}\nSEARCH QUERY: {query[:1500]}\n"
            f"REVIEW COLUMNS: {json.dumps([{'key': k, 'label': v} for k, v in columns.items()])}")
    try:
        data = json.loads(llm.chat([{"role": "system", "content": _PROMPT}, {"role": "user", "content": user}],
                                   format_json=True) or "{}")
    except Exception as e:  # noqa: BLE001 -- any LLM failure means the Review columns stand in
        logger.warning("question tag schema for %s fell back: %s", rq_id, type(e).__name__)
        return fallback
    tags = _tags_from(data, columns)
    if not tags:
        return fallback
    intent = _snake(data.get("question_intent")) or "answer_question"
    return TagSchema(rq_id, question, intent, tags, tuple(columns.items())), "llm"


def review_mapping(schema: TagSchema) -> list[dict]:
    """Each tag against the Review table: its column, or UNMAPPED. Points and weights are read there, never made up."""
    labels = dict(schema.review_columns)
    return [{"question_id": schema.question_id, "tag_name": t.tag_name, "review_column": t.review_column,
             "review_criterion": labels.get(t.review_column) if t.review_column else None,
             "mapping_status": "MAPPED" if t.review_column else UNMAPPED,
             "points": FROM_REVIEW_TABLE, "weight": FROM_REVIEW_TABLE} for t in schema.tags]


def to_json(schema: TagSchema) -> dict:
    return {"question_id": schema.question_id, "question": schema.question, "question_intent": schema.question_intent,
            "required_tags": [{"tag_name": t.tag_name, "tag_type": t.tag_type, "definition": t.definition,
                               "allowed_values": list(t.allowed_values), "extraction_rule": t.extraction_rule,
                               "review_column": t.review_column} for t in schema.tags],
            "review_columns": [{"key": k, "label": v} for k, v in schema.review_columns]}


def from_json(data: dict) -> TagSchema:
    return TagSchema(data["question_id"], data.get("question") or "", data.get("question_intent") or "",
                     tuple(TagDef(t["tag_name"], t["tag_type"], t.get("definition") or "",
                                  tuple(t.get("allowed_values") or ()), t.get("extraction_rule") or "",
                                  t.get("review_column")) for t in data.get("required_tags") or []),
                     tuple((c["key"], c.get("label") or c["key"]) for c in data.get("review_columns") or []))


def prompt_block(schema: TagSchema) -> str:
    """The schema as the enrichment prompt states it."""
    return json.dumps([{"tag_name": t.tag_name, "tag_type": t.tag_type, "definition": t.definition,
                        "allowed_values": list(t.allowed_values), "extraction_rule": t.extraction_rule}
                       for t in schema.tags], ensure_ascii=False)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _canonical(value, allowed: tuple[str, ...]) -> str | None:
    lookup = {a.lower(): a for a in allowed}
    return lookup.get(str(value or "").strip().lower())


def clean_article_tags(schema: TagSchema, tags, evidence, confidence, text: str) -> tuple[dict, dict, dict]:
    """Only the schema's tags; classifications from their allowed values; entities and evidence that the article
    itself contains (nothing inferred beyond it); confidence clamped to 0-1."""
    body = _norm(text)
    tags = tags if isinstance(tags, dict) else {}
    out: dict = {}
    for t in schema.tags:
        raw = tags.get(t.tag_name)
        if t.tag_type == "classification":
            value = _canonical(raw[0] if isinstance(raw, list) and raw else raw, t.allowed_values)
            if value:
                out[t.tag_name] = value
        elif t.tag_type == "multi_classification":
            values = [v for v in (_canonical(x, t.allowed_values) for x in (raw if isinstance(raw, list) else [raw])) if v]
            if values:
                out[t.tag_name] = list(dict.fromkeys(values))
        else:
            names = [str(x).strip() for x in (raw if isinstance(raw, list) else [raw]) if str(x or "").strip()]
            found = [n for n in dict.fromkeys(names) if _norm(n) in body][:MAX_ENTITIES]
            if found:
                out[t.tag_name] = found
    evidence = evidence if isinstance(evidence, dict) else {}
    quoted = {k: str(v).strip()[:MAX_EVIDENCE] for k, v in evidence.items()
              if k in out and str(v or "").strip() and _norm(v) in body}
    confidence = confidence if isinstance(confidence, dict) else {}
    scores = {}
    for k, v in confidence.items():
        if k in out and isinstance(v, (int, float)) and not isinstance(v, bool):
            scores[k] = max(0.0, min(1.0, float(v)))
    return out, quoted, scores
