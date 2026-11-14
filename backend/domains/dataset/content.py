"""Article full text for tagging: one fetch per article, status recorded as content_status."""
from __future__ import annotations

from ..research.article_extractor import get_full_text

MIN_FULL_TEXT_CHARS = 400
_BLOCK_MARKERS = ("401", "403", "429", "blocked")


def fetch(article: dict) -> tuple[str, str, str]:
    """(content, content_status, author from the page's byline or ''). Falls back to the export's summary; never
    bypasses blocks or paywalls, and a site that keeps refusing is not scraped again (article_extractor)."""
    summary = article.get("summary") or ""
    if article.get("channel") == "social":
        return summary, "not_needed", ""
    res = get_full_text(article["url"])
    status, author = res.get("status"), res.get("author") or ""
    if status == "ok":
        text = "\n\n".join(b["text"] for b in res.get("blocks", []) if b.get("type") == "paragraph")
        if len(text) >= MIN_FULL_TEXT_CHARS:
            return text, "full_text", author
    elif status == "paywalled":
        return summary, "summary_only", author
    elif status == "failed" and any(m in (res.get("error") or "").lower() for m in _BLOCK_MARKERS):
        return summary, "blocked", author
    return summary, "not_reachable", author
