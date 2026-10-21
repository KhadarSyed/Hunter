"""Jev classification of research items for the All Articles table: is the item really about the brief's brand
(a probability, against namesakes like Jabil for JBL), and its tone toward that brand.

Both questions go to Jev in one call per item (core/jev_client.py), so answers are always one of the allowed
labels -- constrained decoding, no free text to parse. Answers are stored with the brand they were for and
reused; a call classifies at most MAX_PER_CALL new items, so a large project fills in over a few views.
Without a Jev key nothing is classified: the table keeps its rule-based Relevant column (EntityValidator).
"""
from __future__ import annotations

from ...core import jev_client
from . import repository

MAX_PER_CALL = 500
CONTENT_CHARS = 2000
ABOUT_BRAND_MIN = 0.5  # at or above: about the brand (shown as relevant)

SENTIMENTS = {
    "positive": "Favourable to the brand: praise, success, good news, recommendation",
    "neutral": "Factual or mixed, with no clear lean for or against the brand",
    "negative": "Unfavourable to the brand: criticism, failure, recall, controversy, complaint",
}
_EMPTY = {"about_brand": None, "sentiment": None, "sentiment_confidence": None}


def questions(brand: str, category: str) -> dict[str, dict]:
    subject = f"{brand} ({category})" if category else brand
    return {
        "about_brand": jev_client.noul(
            f"Is this article or post genuinely about {subject}?",
            true=f"It is about {brand} itself: its products, business, people, news or customers",
            false=f"It is about something else that shares the name, or mentions {brand} only in passing"),
        "sentiment": jev_client.choice(f"What is the tone of this article or post toward {brand}?", SENTIMENTS),
    }


def _state(item: dict) -> str:
    return f"{item.get('title') or ''}\n\n{(item.get('content') or '')[:CONTENT_CHARS]}"


def _stored(item: dict, brand: str) -> dict:
    """The item's saved answers, only if they were for this brand."""
    if item.get("classified_for") != brand:
        return dict(_EMPTY)
    return {"about_brand": item.get("about_brand"), "sentiment": item.get("sentiment"),
            "sentiment_confidence": item.get("sentiment_confidence")}


def classify_items(items: list[dict], brand: str, category: str) -> tuple[dict[int, dict], str]:
    """{item id: {about_brand, sentiment, sentiment_confidence}} and the method: "jev" (all answered),
    "jev_partial" (some still to classify on a later call) or "rules" (no Jev key, or no brand to ask about)."""
    if not (jev_client.is_configured() and brand):
        return {i["id"]: _stored(i, brand) for i in items}, "rules"
    pending = [i for i in items if i.get("classified_for") != brand]
    batch = pending[:MAX_PER_CALL]
    answers = jev_client.ask_many([_state(i) for i in batch], questions(brand, category))

    fresh: dict[int, dict] = {}
    for item, answer in zip(batch, answers):
        if answer is None:
            continue
        try:
            sentiment = answer["sentiment"]
            fresh[item["id"]] = {"about_brand": float(answer["about_brand"]["noul"]),
                                 "sentiment": str(sentiment["choice"]),
                                 "sentiment_confidence": float(sentiment["confidence"])}
        except (KeyError, TypeError, ValueError):
            continue  # an answer in an unexpected shape: left for the next call
    repository.save_item_classifications(
        [(item_id, a["about_brand"], a["sentiment"], a["sentiment_confidence"], brand) for item_id, a in fresh.items()])

    result = {i["id"]: fresh.get(i["id"]) or _stored(i, brand) for i in items}
    if batch and not any(answers):  # Jev answered nothing (key rejected, API down): the rule-based column stands
        return result, "rules"
    return result, "jev" if len(fresh) == len(pending) else "jev_partial"
