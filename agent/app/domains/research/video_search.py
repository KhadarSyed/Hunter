"""YouTube section-background video resolution — one topically-matched video per brief
section (e.g. "Tesla Model 3 review" for Brand Developments vs "Tesla company overview" for
Introduction), restricted to the brand's own official YouTube channel.

Found via a real (stealth-patched, Playwright-driven) browser fetch of DuckDuckGo's video
search page using Scrapling's StealthyFetcher, not the duckduckgo-search library's bare API
call — that bare call hits DuckDuckGo's rate limit almost immediately in practice (confirmed
live: 2 of ~9 section lookups succeeded before every subsequent call was blocked), whereas a
real browser request is not.

A plain topical query (e.g. "Tesla company overview") ranks third-party commentary/reaction
channels first — confirmed live (top results were "Read With Joy!", "Mido Explained", "Torque
News", never Tesla's own channel), and those videos routinely have dramatic documentary-style
title cards baked into the frames, which read as unprofessional in an analyst briefing. Two
mitigations, both confirmed live: (1) append "official" to the search query, which reliably
surfaces the real official channel near the top (confirmed: "Tesla official" ranked Tesla's
own channel #1 and #2, vs. zero official results without it); (2) verify every candidate via
YouTube's oEmbed author_name against the brand name (_is_official_channel) before accepting
it, walking down the ranked results until an official match is found. If none of the top
candidates are official, the section gets no video rather than a wrong-source one — showing
nothing is preferable to showing an unaffiliated creator's content.

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
MAX_CANDIDATES = 8  # how many ranked results to check for an official-channel match

_VIDEO_ID_PATTERN = re.compile(r"youtube\.com/watch\?v=([A-Za-z0-9_-]{11})")
_DDG_VIDEO_SEARCH_URL = "https://duckduckgo.com/"
_OEMBED_URL = "https://www.youtube.com/oembed"

# Common corporate-channel suffix words — "Tesla Motors" or "Coca-Cola Company" are still the
# official channel; "Tesla Owners Club" or "Tesla Daily" are fan/commentary channels that
# happen to contain the brand name and must NOT match.
_OFFICIAL_SUFFIX_WORDS = {
    "motors", "inc", "corp", "corporation", "company", "co", "official",
    "hq", "global", "worldwide", "media", "group", "brand", "brands",
}


class LookupUnavailable(RuntimeError):
    """The video/title lookup could not answer right now — don't cache."""


def normalize_query(text: str) -> str:
    return " ".join(text.lower().split())


def _is_official_channel(author_name: str | None, brand: str) -> bool:
    """True only for an (near-)exact brand-name channel match — "Tesla" or "Tesla Motors"
    for brand "Tesla", never a fan/commentary channel that merely mentions the brand."""
    if not author_name or not brand:
        return False
    a_words = re.findall(r"[a-z0-9]+", author_name.lower())
    b_words = re.findall(r"[a-z0-9]+", brand.lower())
    if not a_words or not b_words:
        return False
    if a_words == b_words:
        return True
    if a_words[:len(b_words)] == b_words:
        extra = a_words[len(b_words):]
        return all(w in _OFFICIAL_SUFFIX_WORDS for w in extra)
    return False


def _search_ddg_video_ids(query: str, max_candidates: int = MAX_CANDIDATES) -> list[str]:
    """Ranked, deduplicated YouTube video ids from DuckDuckGo's video vertical for `query`
    (empty list if the page rendered but had no video results). Raises on fetch failure
    (network, blocked, timeout) — callers treat that as LookupUnavailable, distinct from a
    genuine no-match."""
    qs = urlencode({"q": query, "iar": "videos", "iax": "videos", "ia": "videos"})
    resp = StealthyFetcher.fetch(
        f"{_DDG_VIDEO_SEARCH_URL}?{qs}",
        headless=True, network_idle=True, timeout=FETCH_TIMEOUT_MS, wait=2000,
    )
    body = resp.body.decode("utf-8", errors="ignore") if isinstance(resp.body, bytes) else str(resp.body)
    ids: list[str] = []
    for match in _VIDEO_ID_PATTERN.finditer(body):
        vid = match.group(1)
        if vid not in ids:
            ids.append(vid)
        if len(ids) >= max_candidates:
            break
    return ids


def _fetch_oembed_metadata(video_id: str) -> dict:
    """{title, thumbnail_url, author_name} from YouTube's public oEmbed endpoint —
    best-effort, an empty dict on any failure."""
    try:
        r = requests.get(_OEMBED_URL, params={
            "url": f"https://www.youtube.com/watch?v={video_id}", "format": "json",
        }, timeout=REQUEST_TIMEOUT_S)
        if r.status_code == 200:
            data = r.json()
            return {"title": data.get("title"), "thumbnail_url": data.get("thumbnail_url"),
                     "author_name": data.get("author_name")}
    except (requests.RequestException, ValueError):
        logger.warning("YouTube oEmbed lookup failed for %r", video_id, exc_info=True)
    return {}


def resolve_section_video(query: str, brand_name: str = "") -> dict:
    """{query, video_id, embed_url, title, thumbnail_url, cached}: saved table first, then a
    DuckDuckGo video search (via a real browser fetch, query biased with "official") walked
    in ranked order until a result whose channel matches `brand_name` is found — never a
    third-party channel's video. Blocking (network) — call from a worker thread or FastAPI's
    threadpool."""
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

    search_text = f"{text} official" if brand_name else text
    try:
        candidate_ids = _search_ddg_video_ids(search_text)
    except Exception as e:
        logger.warning("YouTube video search unavailable for %r (%s); not cached, will retry", text, e)
        raise LookupUnavailable(type(e).__name__) from e

    video_id = None
    meta: dict = {}
    for candidate_id in candidate_ids:
        candidate_meta = _fetch_oembed_metadata(candidate_id)
        if not brand_name or _is_official_channel(candidate_meta.get("author_name"), brand_name):
            video_id, meta = candidate_id, candidate_meta
            break

    if video_id:
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
