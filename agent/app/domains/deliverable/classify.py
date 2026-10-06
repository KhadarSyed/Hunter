"""Per-article LLM labelling. Labels outside the schema become 'unknown'; nothing is invented."""
from __future__ import annotations

import json
import logging

from .ingest import Article

logger = logging.getLogger(__name__)
BATCH = 8
MAX_TEXT = 4000

SCHEMAS: dict[str, dict] = {
    "expert": {"list_field": "experts", "item": {
        "name": None, "expert_type": ["dermatologist", "pediatrician", "other_hcp", "non_hcp_expert"],
        "affiliation": ["affiliated", "independent"], "brand": None, "evidence": None}},
    "celebrity": {"list_field": "celebrities", "item": {
        "name": None, "role": ["spokesperson", "product_mention", "lifestyle"]}},
    "deal": {"list_field": "deals", "item": {
        "product": None, "retailer": None, "deal_type": ["discount", "freebie", "bundle"]}},
    "parenting": {"list_field": "topics", "item": {
        "topic": ["sun_safety", "eczema_dryness", "bathing", "diapering", "ingredients", "sleep_routine", "other"]}},
}

_INSTRUCTIONS = {
    "expert": "List every expert quoted or cited. expert_type: dermatologist, pediatrician, other_hcp "
              "(nurse, pharmacist, other clinician) or non_hcp_expert. affiliation: 'affiliated' only if the "
              "text states a tie to a brand (employee, consultant, paid partner, spokesperson) and name it in "
              "brand; 'independent' only if the text makes clear there is no brand tie; otherwise omit it. "
              "evidence: the exact short phrase that supports the label.",
    "celebrity": "List every celebrity named. role: spokesperson (paid/brand partner), product_mention, or lifestyle.",
    "deal": "List each promoted product with its retailer and deal_type (discount, freebie, bundle).",
    "parenting": "List the parenting-advice topics covered.",
}


class ClassificationUnavailable(RuntimeError):
    pass


def _clean_item(item: dict, spec: dict) -> dict:
    out = {}
    for field, allowed in spec.items():
        value = item.get(field)
        if allowed is None:
            out[field] = str(value or "").strip()
        else:
            out[field] = value if value in allowed else "unknown"
    return out


def _prompt(theme: str, batch: list[Article]) -> list[dict]:
    schema = SCHEMAS[theme]
    docs = [{"url": a.norm_url, "title": a.title, "text": a.text[:MAX_TEXT]} for a in batch]
    system = ("You label news articles for a media-research report. Use only what the article text says. "
              "If something is not stated, omit it. Return JSON only.")
    user = (f"{_INSTRUCTIONS[theme]}\nAlso list 'brands': baby/skincare brand names mentioned.\n"
            f"Return {{\"items\": [{{\"url\": <url>, \"{schema['list_field']}\": [objects with fields "
            f"{json.dumps(list(schema['item']))}], \"brands\": [..]}}]}} with one item per article.\n"
            f"Articles:\n{json.dumps(docs, ensure_ascii=False)}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def classify_theme(articles: list[Article], theme: str, llm, cache: dict) -> dict[str, dict]:
    if llm is None:
        raise ClassificationUnavailable("Azure OpenAI chat is not configured/reachable — cannot classify articles")
    schema = SCHEMAS[theme]
    store = cache.setdefault(theme, {})
    todo = [a for a in articles if a.norm_url not in store]
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        wanted = {a.norm_url for a in batch}
        try:
            parsed = json.loads(llm.chat(_prompt(theme, batch), format_json=True))
        except json.JSONDecodeError:
            logger.warning("classification batch for %s returned invalid JSON; marking unknown", theme)
            parsed = {"items": []}
        for item in parsed.get("items", []):
            url = str(item.get("url", "")).strip().rstrip("/").lower()
            if url not in wanted:
                continue
            store[url] = {schema["list_field"]: [_clean_item(x, schema["item"])
                                                 for x in item.get(schema["list_field"], []) if isinstance(x, dict)],
                          "brands": [str(b).strip() for b in item.get("brands", []) if str(b).strip()]}
        for url in wanted - store.keys():
            store[url] = {schema["list_field"]: [], "brands": [], "status": "unknown"}
    return {a.norm_url: store[a.norm_url] for a in articles}
