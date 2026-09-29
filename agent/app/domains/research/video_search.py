"""YouTube section-background video resolution — one topically-matched video per brief
section (e.g. "Tesla Model 3 review" for Brand Developments vs "Tesla company overview" for
Introduction).

Found via a real (stealth-patched, Playwright-driven) browser fetch of DuckDuckGo's video
search page using Scrapling's StealthyFetcher, not the duckduckgo-search library's bare API
call — that bare call hits DuckDuckGo's rate limit almost immediately in practice (confirmed
live: 2 of ~9 section lookups succeeded before every subsequent call was blocked), whereas a
real browser request is not. Title/thumbnail come from YouTube's own public oEmbed endpoint
(stable, unauthenticated, not a scrape) once a video id is known — scraping DDG's obfuscated
result markup for that metadata would be far more fragile than the id extraction itself.

Cache-first / not-found-retry contract mirrors pexels.py and brandfetch.py: a definite
outcome (including "nothing found") is saved and reused; a transient failure (blocked fetch,
timeout, network error) is NOT cached, so a slow or temporarily blocked lookup never
permanently blocks a query.
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlencode

import requests
from scrapling import StealthyFetcher

from . import repository

logger = logging.getLogger(__name__)

NOT_FOUND_RETRY_S = 7 * 86_400  # re-check queries with no video after a week
REQUEST_TIMEOUT_S = 10
FETCH_TIMEOUT_MS = 30_000

_VIDEO_ID_PATTERN = re.compile(r"youtube\.com/watch\?v=([A-Za-z0-9_-]{11})")
_DDG_VIDEO_SEARCH_URL = "https://duckduckgo.com/"
_OEMBED_URL = "https://www.youtube.com/oembed"


class LookupUnavailable(RuntimeError):
    """The video/title lookup could not answer right now — don't cache."""


def normalize_query(text: str) -> str:
    return " ".join(text.lower().split())


def _search_ddg_video_id(query: str) -> str | None:
    """First YouTube video id from DuckDuckGo's video vertical for `query`, or None if the
    page rendered but had no video results. Raises on fetch failure (network, blocked,
    timeout) — callers treat that as LookupUnavailable, distinct from a genuine no-match."""
    qs = urlencode({"q": query, "iar": "videos", "iax": "videos", "ia": "videos"})
    resp = StealthyFetcher.fetch(
        f"{_DDG_VIDEO_SEARCH_URL}?{qs}",
        headless=True, network_idle=True, timeout=FETCH_TIMEOUT_MS, wait=2000,
    )
    body = resp.body.decode("utf-8", errors="ignore") if isinstance(resp.body, bytes) else str(resp.body)
    match = _VIDEO_ID_PATTERN.search(body)
    return match.group(1) if match else None


def _fetch_oembed_metadata(video_id: str) -> dict:
    """{title, thumbnail_url} from YouTube's public oEmbed endpoint — best-effort, an empty
    dict on any failure since the video itself (id/embed_url) is what actually matters for
    the background; title/thumbnail are a nice-to-have."""
    try:
        r = requests.get(_OEMBED_URL, params={
            "url": f"https://www.youtube.com/watch?v={video_id}", "format": "json",
        }, timeout=REQUEST_TIMEOUT_S)
        if r.status_code == 200:
            data = r.json()
            return {"title": data.get("title"), "thumbnail_url": data.get("thumbnail_url")}
    except (requests.RequestException, ValueError):
        logger.warning("YouTube oEmbed lookup failed for %r", video_id, exc_info=True)
    return {}


def resolve_section_video(query: str) -> dict:
    """{query, video_id, embed_url, title, thumbnail_url, cached}: saved table first, then a
    DuckDuckGo video search (via a real browser fetch) restricted to YouTube results, with
    title/thumbnail from YouTube's oEmbed endpoint. Blocking (network) — call from a worker
    thread or FastAPI's threadpool."""
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
        video_id = _search_ddg_video_id(text)
    except Exception as e:
        logger.warning("YouTube video search unavailable for %r (%s); not cached, will retry", text, e)
        raise LookupUnavailable(type(e).__name__) from e

    if video_id:
        meta = _fetch_oembed_metadata(video_id)
        result.update(
            video_id=video_id,
            embed_url=(f"https://www.youtube.com/embed/{video_id}"
                       f"?autoplay=1&mute=1&loop=1&playlist={video_id}&controls=0"),
            title=meta.get("title"),
            thumbnail_url=meta.get("thumbnail_url"),
        )

    repository.save_youtube_video(key, text, result["video_id"], result["embed_url"],
                                   result["title"], result["thumbnail_url"])
    return result
