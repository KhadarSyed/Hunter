"""YouTube section-background video resolution — one topically-matched video per brief
section (e.g. "Tesla Model 3 review" for Brand Developments vs "Tesla company overview" for
Introduction), found via the duckduckgo-search library's video search restricted to YouTube
results (license_videos="youtube") — no browser automation, no scraping.

Cache-first / not-found-retry contract mirrors pexels.py and brandfetch.py: a definite
outcome (including "nothing found") is saved and reused; a transient failure (rate limit,
timeout, network error) is NOT cached, so a slow API never permanently blocks a query.
"""
from __future__ import annotations

import logging
import re
import time

from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import DuckDuckGoSearchException

from . import repository

logger = logging.getLogger(__name__)

NOT_FOUND_RETRY_S = 7 * 86_400  # re-check queries with no video after a week

_VIDEO_ID_PATTERN = re.compile(r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})")


class LookupUnavailable(RuntimeError):
    """DuckDuckGo could not answer right now (rate limit, timeout, network) — don't cache."""


def normalize_query(text: str) -> str:
    return " ".join(text.lower().split())


def _extract_video_id(youtube_url: str) -> str | None:
    match = _VIDEO_ID_PATTERN.search(youtube_url or "")
    return match.group(1) if match else None


def resolve_section_video(query: str) -> dict:
    """{query, video_id, embed_url, title, thumbnail_url, cached}: saved table first, then
    a DuckDuckGo video search restricted to YouTube results. Blocking (network) — call from
    a worker thread or FastAPI's threadpool."""
    text = query.strip()
    key = normalize_query(text)
    result = {"query": text, "video_id": None, "embed_url": None, "title": None,
              "thumbnail_url": None, "cached": False}
    if not key:
        return result

    saved = repository.get_youtube_video(key)
    if saved and (saved["video_id"] or time.time() - saved["fetched_at"] < NOT_FOUND_RETRY_S):
        return {**result, "video_id": saved["video_id"], "embed_url": saved["embed_url"],
                "title": saved["title"], "thumbnail_url": saved["thumbnail_url"], "cached": True}

    try:
        videos = DDGS().videos(text, license_videos="youtube", max_results=1)
    except DuckDuckGoSearchException as e:
        logger.warning("YouTube video search unavailable for %r (%s); not cached, will retry", text, e)
        raise LookupUnavailable(type(e).__name__) from e

    if videos:
        video = videos[0]
        video_id = _extract_video_id(video.get("content", ""))
        if video_id:
            result.update(
                video_id=video_id,
                embed_url=(f"https://www.youtube.com/embed/{video_id}"
                           f"?autoplay=1&mute=1&loop=1&playlist={video_id}&controls=0"),
                title=video.get("title"),
                thumbnail_url=(video.get("images") or {}).get("large"),
            )

    repository.save_youtube_video(key, text, result["video_id"], result["embed_url"],
                                   result["title"], result["thumbnail_url"])
    return result
