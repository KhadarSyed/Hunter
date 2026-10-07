"""YouTube section-background video resolution — one topically-matched video per brief
section (e.g. "Tesla Model 3 review" for Brand Developments vs "Tesla company overview" for
Introduction), restricted to the brand's own official YouTube channel.

━━━ Channel-first resolution (primary path) ━━━

Live testing (2026-10, against Subway, Chick-fil-A and McDonald's) showed DuckDuckGo's video
vertical — this module's original and only strategy — ranks third-party "rise and fall" /
"business case study" explainer channels above a brand's real official channel for *every*
generic query tried ("{brand} company overview official", "{brand} latest news official"):
zero official results in the top 8 candidates for any of the three brands. The strict
official-channel name check (`_is_official_channel`) was working exactly as designed in
rejecting all of them — the problem is upstream, in what DuckDuckGo's video ranking surfaces,
not in the acceptance check.

So the primary path no longer gambles on a topical video query ranking the right channel at
all: it resolves the brand's own channel URL first (via SerpAPI's plain `engine=google` web
search for "{brand} official youtube channel" — confirmed live to return the real channel,
e.g. youtube.com/user/subway, as the #1 organic result), then fetches that channel's own
`/videos` listing directly (via Scrapling's StealthyFetcher, since that page is JS-rendered)
and takes its first video id. That id is official by construction — no name-matching
heuristic needed, and no topical relevance to lose since every section already gets some
real footage from the brand's own channel. The channel URL itself is cached per-brand
(`_CHANNEL_CACHE_PREFIX` key in the same youtube_videos table) so only the first section/
competitor lookup for a given brand pays the SerpAPI + channel-page-fetch cost.

━━━ Fallback path (original strategy) ━━━

When channel discovery finds nothing (SerpAPI unconfigured/down, or no discoverable channel
for a smaller brand), this falls back to the original per-query strategy: a real
(stealth-patched, Playwright-driven) browser fetch of DuckDuckGo's video search page via
Scrapling's StealthyFetcher — not the duckduckgo-search library's bare API call, which hits
DuckDuckGo's rate limit almost immediately in practice (confirmed live: 2 of ~9 section
lookups succeeded before every subsequent call was blocked), whereas a real browser request
is not — with every candidate verified via YouTube's oEmbed author_name against the brand
name (`_is_official_channel`) before acceptance. If none of the top candidates are official,
the section gets no video rather than a wrong-source one — showing nothing (the caller then
falls back to Pexels stock footage) is preferable to showing an unaffiliated creator's
content.

Cache-first / not-found-retry contract mirrors pexels.py and brandfetch.py: a definite
outcome (including "nothing found") is saved and reused; a transient failure (blocked fetch,
timeout, network error) is NOT cached, so a slow or temporarily blocked lookup never
permanently blocks a query.
"""
from __future__ import annotations

import logging
import os
import re
import time
import zlib
from urllib.parse import quote, urlencode

import requests
from scrapling import StealthyFetcher

from ...core import serp_keys
from . import repository

logger = logging.getLogger(__name__)

NOT_FOUND_RETRY_S = 7 * 86_400  # re-check queries with no video after a week
REQUEST_TIMEOUT_S = 10
FETCH_TIMEOUT_MS = 30_000
MAX_CANDIDATES = 8  # how many ranked results to check for an official-channel match
# An in-channel search's results load via a follow-up XHR after the initial page render —
# confirmed live (Chick-fil-A's channel): a 2s wait (fine for the plain /videos listing,
# which is server-rendered) returned a 1.12MB page with zero video ids for "company
# overview"/"brand story", while the same query at 4s returned real results. The /videos
# listing itself doesn't need this longer wait, so only the search path pays it.
CHANNEL_SEARCH_WAIT_MS = 4000

_VIDEO_ID_PATTERN = re.compile(r"youtube\.com/watch\?v=([A-Za-z0-9_-]{11})")
_CHANNEL_PAGE_VIDEO_ID_PATTERN = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')
_CHANNEL_URL_PATTERN = re.compile(r"youtube\.com/(@[\w.\-]+|channel/UC[\w-]+|user/[\w.\-]+)")
_DDG_VIDEO_SEARCH_URL = "https://duckduckgo.com/"
_OEMBED_URL = "https://www.youtube.com/oembed"
_SERPAPI_URL = "https://serpapi.com/search"
_CHANNEL_CACHE_PREFIX = "__official_channel__:"

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


def _cached_channel_url(brand_name: str) -> tuple[str | None, bool]:
    """(channel_url, is_fresh) from the youtube_videos cache under the brand's channel-cache
    key — channel_url is None for a cached "nothing found", is_fresh False means the cached
    miss is old enough to deserve a retry. No cache row at all returns (None, False) so the
    caller always attempts discovery on a true cache-miss."""
    saved = repository.get_youtube_video(_CHANNEL_CACHE_PREFIX + brand_name.lower().strip())
    if not saved:
        return None, False
    is_fresh = bool(saved["embed_url"]) or (time.time() - saved["fetched_at"] < NOT_FOUND_RETRY_S)
    return saved["embed_url"], is_fresh


def _save_channel_url(brand_name: str, channel_url: str | None) -> None:
    key = _CHANNEL_CACHE_PREFIX + brand_name.lower().strip()
    repository.save_youtube_video(key, brand_name, None, channel_url, None, None)


def _discover_official_channel_url(brand_name: str) -> str | None:
    """The brand's own YouTube channel URL (e.g. "https://www.youtube.com/user/subway"),
    found via a plain SerpAPI Google web search for "{brand} official youtube channel" —
    confirmed live to rank the real channel as the #1 organic result where DuckDuckGo's video
    vertical ranked zero official results in its top 8 for the same brands (see module
    docstring). Returns None (not raises) when SERP_API_KEY is unset or no organic result
    links to a youtube.com channel — both are legitimate "nothing to find here" outcomes, not
    transient failures, so the caller is free to cache None. Raises only on a genuine
    request-level failure (network, timeout), which the caller must NOT cache."""
    params = {
        "engine": "google",
        "q": f'"{brand_name}" official youtube channel',
        "num": 10,
    }
    r = serp_keys.get(_SERPAPI_URL, params, 20)
    if r is None:
        return None
    if r.status_code in (401, 403):
        logger.warning("SerpAPI rejected key during channel discovery for %r (%s)", brand_name, r.status_code)
        return None
    if r.status_code != 200:
        raise RuntimeError(f"SerpAPI channel discovery failed: {r.status_code}")
    data = r.json()
    for result in data.get("organic_results", []):
        link = result.get("link") or ""
        match = _CHANNEL_URL_PATTERN.search(link)
        if match:
            return f"https://www.youtube.com/{match.group(1)}"
    return None


def _video_ids_from_page(url: str, wait_ms: int, max_ids: int = 5) -> list[str]:
    """Deduplicated, in-document-order videoIds found in `url`'s rendered body (fetched via
    Scrapling since these pages are JS-rendered) — empty list if the page rendered but had
    no video. Raises on fetch failure (network, blocked, timeout), same LookupUnavailable
    contract as `_search_ddg_video_ids`."""
    resp = StealthyFetcher.fetch(url, headless=True, network_idle=True, timeout=FETCH_TIMEOUT_MS, wait=wait_ms)
    body = resp.body.decode("utf-8", errors="ignore") if isinstance(resp.body, bytes) else str(resp.body)
    ids: list[str] = []
    for match in _CHANNEL_PAGE_VIDEO_ID_PATTERN.finditer(body):
        vid = match.group(1)
        if vid not in ids:
            ids.append(vid)
        if len(ids) >= max_ids:
            break
    return ids


def _fetch_first_channel_video(channel_url: str, variety_key: str = "") -> dict:
    """{video_id, title, thumbnail_url} for a video from `channel_url`'s own /videos tab —
    picks a `variety_key`-derived index among its most recent uploads rather than always the
    very first, so different sections (or different competitors, which all share this same
    fallback) don't all collapse to showing the identical clip. Deterministic per key (same
    section always picks the same video, so the result is still cacheable), just not the
    same video as every OTHER key. Empty dict if the page rendered but no video id could be
    extracted."""
    ids = _video_ids_from_page(channel_url.rstrip("/") + "/videos", wait_ms=2000)
    if not ids:
        return {}
    video_id = ids[zlib.crc32(variety_key.encode()) % len(ids)] if variety_key else ids[0]
    meta = _fetch_oembed_metadata(video_id)
    return {"video_id": video_id, "title": meta.get("title"), "thumbnail_url": meta.get("thumbnail_url")}


def _fetch_channel_video(channel_url: str, topic_query: str, brand_name: str) -> dict:
    """{video_id, title, thumbnail_url} for a video from `channel_url` matching
    `topic_query` — tried first via that channel's own in-channel search (e.g.
    youtube.com/@chickfila/search?query=...), so the section gets a topically relevant
    video rather than whatever the channel uploaded most recently. Falls back to the
    channel's plain /videos listing (still official, just not topically matched, and varied
    by `topic_query` — see `_fetch_first_channel_video`) when the in-channel search has no
    results for this topic — confirmed live that some topics (e.g. "company overview",
    "brand story") return nothing for a QSR brand's ad-heavy channel while others (e.g.
    "latest news") do. Empty dict only if neither path finds a video at all."""
    topic = topic_query
    if brand_name:
        topic = re.sub(re.escape(brand_name), "", topic, flags=re.IGNORECASE).strip()
    if topic:
        search_url = f"{channel_url.rstrip('/')}/search?query={quote(topic)}"
        video_id = next(iter(_video_ids_from_page(search_url, wait_ms=CHANNEL_SEARCH_WAIT_MS, max_ids=1)), None)
        if video_id:
            meta = _fetch_oembed_metadata(video_id)
            return {"video_id": video_id, "title": meta.get("title"), "thumbnail_url": meta.get("thumbnail_url")}
    return _fetch_first_channel_video(channel_url, variety_key=topic_query)


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


def _embed_url_for(video_id: str) -> str:
    return (f"https://www.youtube.com/embed/{video_id}"
            f"?autoplay=1&mute=1&loop=1&playlist={video_id}&controls=0")


def _resolve_via_official_channel(topic_query: str, brand_name: str) -> dict | None:
    """Channel-first path (see module docstring): resolve the brand's own channel URL
    (cached per-brand), then find a video on that channel matching `topic_query` (falling
    back to the channel's most recent upload if nothing matches the topic — see
    `_fetch_channel_video`). Returns None — not a dict — when the channel-first path finds
    nothing at all, so the caller knows to fall back to the per-query DDG strategy; never
    raises for a legitimate "nothing to find", only for a transient fetch failure
    (LookupUnavailable, consistent with the fallback path's contract)."""
    channel_url, is_fresh = _cached_channel_url(brand_name)
    if channel_url is None and is_fresh:
        return None  # cached "no official channel found", still within the retry window

    if not channel_url:
        try:
            channel_url = _discover_official_channel_url(brand_name)
        except Exception as e:
            logger.warning("Official-channel discovery unavailable for %r (%s); not cached, will retry",
                           brand_name, e)
            raise LookupUnavailable(type(e).__name__) from e
        _save_channel_url(brand_name, channel_url)
        if not channel_url:
            return None

    try:
        video = _fetch_channel_video(channel_url, topic_query, brand_name)
    except Exception as e:
        logger.warning("Official-channel video fetch unavailable for %r (%s); not cached, will retry",
                       channel_url, e)
        raise LookupUnavailable(type(e).__name__) from e

    if not video.get("video_id"):
        return None
    return {
        "video_id": video["video_id"],
        "embed_url": _embed_url_for(video["video_id"]),
        "title": video.get("title"),
        "thumbnail_url": video.get("thumbnail_url"),
    }


def resolve_section_video(query: str, brand_name: str = "") -> dict:
    """{query, video_id, embed_url, title, thumbnail_url, cached}: saved table first, then
    the brand's own official channel (channel-first path — see module docstring), then a
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

    video_id = None
    meta: dict = {}

    if brand_name:
        channel_result = _resolve_via_official_channel(text, brand_name)
        if channel_result:
            video_id = channel_result["video_id"]
            meta = {"title": channel_result["title"], "thumbnail_url": channel_result["thumbnail_url"]}

    if not video_id:
        search_text = f"{text} official" if brand_name else text
        try:
            candidate_ids = _search_ddg_video_ids(search_text)
        except Exception as e:
            logger.warning("YouTube video search unavailable for %r (%s); not cached, will retry", text, e)
            raise LookupUnavailable(type(e).__name__) from e

        for candidate_id in candidate_ids:
            candidate_meta = _fetch_oembed_metadata(candidate_id)
            if not brand_name or _is_official_channel(candidate_meta.get("author_name"), brand_name):
                video_id, meta = candidate_id, candidate_meta
                break

    if video_id:
        result.update(
            video_id=video_id,
            embed_url=_embed_url_for(video_id),
            title=meta.get("title"),
            thumbnail_url=meta.get("thumbnail_url"),
        )

    repository.save_youtube_video(key, text, result["video_id"], result["embed_url"],
                                   result["title"], result["thumbnail_url"])
    return result
