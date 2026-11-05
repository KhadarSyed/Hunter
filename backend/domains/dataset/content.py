"""Article full text for tagging: one fetch per article, status recorded as content_status."""
from __future__ import annotations

from ..research.article_extractor import get_full_text

MIN_FULL_TEXT_CHARS = 400
_BLOCK_MARKERS = ("401", "403", "429", "blocked")


def fetch(article: dict) -> tuple[str, str]:
    """(content, content_status). Falls back to the export's summary; never bypasses blocks or paywalls."""
    summary = article.get("summary") or ""
    if article.get("channel") == "social":
        return summary, "not_needed"
    res = get_full_text(article["url"])
    status = res.get("status")
    if status == "ok":
        text = "\n\n".join(b["text"] for b in res.get("blocks", []) if b.get("type") == "paragraph")
        if len(text) >= MIN_FULL_TEXT_CHARS:
            return text, "full_text"
    elif status == "paywalled":
        return summary, "summary_only"
    elif status == "failed" and any(m in (res.get("error") or "").lower() for m in _BLOCK_MARKERS):
        return summary, "blocked"
    return summary, "not_reachable"
