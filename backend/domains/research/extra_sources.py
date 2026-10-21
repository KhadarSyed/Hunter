"""YouTube, Bluesky and SearXNG as extra sources for news_search.fetch_and_normalize().

Each search_* returns raw items in the same shape news_search's _normalize_* functions build
(publisher_name / published_url / title / content / author / date / thumbnail / _source), so they flow
through the same date filter, URL dedup and social/traditional bucketing. A source that is not
configured, or fails, contributes [] -- these never raise, like the other three sources.

Env: YOUTUBE_API_KEY (YouTube Data API v3), BLUESKY_HANDLE + BLUESKY_APP_PASSWORD (Bluesky's public
search now refuses anonymous calls), SEARXNG_URL (a self-hosted SearXNG with JSON output enabled).
Results are in English with the brief's country, matching SerpAPI and Google News RSS (hl=en, gl=country).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date, datetime, timezone
from urllib.parse import urlparse

import requests

from . import page_signals

logger = logging.getLogger(__name__)

TIMEOUT_S = 15
# Time a source's search requests may take in total before it stops paging and returns what it has.
# Generous: completeness matters more than speed, and each request still has its own timeout.
BUDGET_S = 120
SEARCH_LANGUAGE = "en"  # same as SerpAPI's hl=en and the RSS feed's hl=en-US
MAX_PAGES = 3

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
BLUESKY_PUBLIC = "https://public.api.bsky.app/xrpc"
BLUESKY_PDS = "https://bsky.social/xrpc"
BLUESKY_TOKEN_REUSE_S = 90 * 60  # accessJwt lives ~2h; sign-ins are capped (~30 per 5 min), so reuse it

_bluesky_session: dict = {}
_bluesky_lock = threading.Lock()


def is_configured(source: str) -> bool:
    if source == "youtube":
        return bool(os.environ.get("YOUTUBE_API_KEY", "").strip())
    if source == "bluesky":  # public search refuses anonymous calls, so credentials are required
        return bool(os.environ.get("BLUESKY_HANDLE", "").strip() and os.environ.get("BLUESKY_APP_PASSWORD", "").strip())
    if source == "searxng":
        return bool(os.environ.get("SEARXNG_URL", "").strip())
    return False


def _timeout(deadline: float) -> float:
    """Per-request timeout that never runs past the source's budget; TimeoutError once it is spent."""
    left = deadline - time.monotonic()
    if left < 1:
        raise TimeoutError("source time budget spent")
    return min(TIMEOUT_S, left)


def _bounds(date_range: tuple | None) -> tuple[datetime, datetime] | None:
    """(start of first day, end of last day) in UTC, or None for no range."""
    if not date_range:
        return None
    start, end = (d.date() if isinstance(d, datetime) else d for d in date_range[:2])
    return (datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
            datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _same_language(langs: list, language: str = SEARCH_LANGUAGE) -> bool:
    """False only when the item declares languages and none is ours; zxx/und/mul declare nothing."""
    known = [l.split("-")[0].lower() for l in langs if l and l.lower() not in ("zxx", "und", "mul")]
    return not known or language in known


# --------------------------------------------------------------------------
# YouTube -- search.list costs 100 of the 10,000 free daily units; videos + channels lookups 1 each
# --------------------------------------------------------------------------

def _youtube_get(path: str, params: dict, key: str, deadline: float) -> dict:
    # key in a header, not the URL, so request logging can't leak it
    r = requests.get(f"{YOUTUBE_API}/{path}", params=params, headers={"X-Goog-Api-Key": key},
                     timeout=_timeout(deadline))
    r.raise_for_status()
    return r.json()


def search_youtube(query: str, country: str, date_range: tuple | None, max_results: int) -> list[dict]:
    """Videos for the query in the brief's window and country. A video whose channel declares another
    country, or whose audio is declared in another language, is dropped; undeclared ones are kept."""
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        return []
    params = {"part": "snippet", "type": "video", "q": query, "order": "relevance",
              "maxResults": min(max_results, 50), "regionCode": country.upper(),
              "relevanceLanguage": SEARCH_LANGUAGE}
    if bounds := _bounds(date_range):
        params |= {"publishedAfter": _iso(bounds[0]), "publishedBefore": _iso(bounds[1])}
    deadline = time.monotonic() + BUDGET_S
    try:
        hits = [h for h in _youtube_get("search", params, key, deadline).get("items", [])
                if h.get("id", {}).get("videoId")]
    except (requests.RequestException, ValueError, KeyError, TypeError, TimeoutError) as e:
        logger.warning("YouTube search failed: %s", type(e).__name__)
        return []
    if not hits:
        return []
    try:  # language and channel country only filter; without them the videos are still kept
        ids = ",".join(h["id"]["videoId"] for h in hits)
        videos = {v["id"]: v.get("snippet", {})
                  for v in _youtube_get("videos", {"part": "snippet", "id": ids}, key, deadline).get("items", [])}
        channel_ids = ",".join(sorted({h["snippet"].get("channelId", "") for h in hits} - {""}))
        countries = {c["id"]: c["snippet"].get("country") for c in
                     _youtube_get("channels", {"part": "snippet", "id": channel_ids}, key, deadline).get("items", [])}
    except (requests.RequestException, ValueError, KeyError, TypeError, TimeoutError) as e:
        logger.warning("YouTube language/country lookup failed, videos kept unfiltered: %s", type(e).__name__)
        videos, countries = {}, {}

    out = []
    for h in hits:
        vid, sn = h["id"]["videoId"], h["snippet"]
        declared = videos.get(vid, {})
        channel_country = countries.get(sn.get("channelId"))
        if channel_country and channel_country.upper() != country.upper():
            continue
        if not _same_language([declared.get("defaultAudioLanguage"), declared.get("defaultLanguage")]):
            continue
        out.append({
            "publisher_name": sn.get("channelTitle") or "YouTube",
            "published_url": f"https://www.youtube.com/watch?v={vid}",
            "title": sn.get("title") or "",
            "content": sn.get("description") or "",
            "author": sn.get("channelTitle") or "",
            "date": sn.get("publishedAt") or "",
            "thumbnail": ((sn.get("thumbnails") or {}).get("high") or {}).get("url") or "",
            "_source": "youtube",
        })
    return out


# --------------------------------------------------------------------------
# Bluesky -- public search first; anonymous calls now get 403, so sign in with an app password
# --------------------------------------------------------------------------

def _bluesky_token(deadline: float, force_new: bool = False) -> str | None:
    handle = os.environ.get("BLUESKY_HANDLE", "").strip()
    password = os.environ.get("BLUESKY_APP_PASSWORD", "").strip()
    if not (handle and password):
        return None
    with _bluesky_lock:
        if force_new:
            _bluesky_session.clear()
        if _bluesky_session.get("jwt") and time.time() - _bluesky_session["at"] < BLUESKY_TOKEN_REUSE_S:
            return _bluesky_session["jwt"]
        r = requests.post(f"{BLUESKY_PDS}/com.atproto.server.createSession",
                          json={"identifier": handle, "password": password}, timeout=_timeout(deadline))
        r.raise_for_status()
        _bluesky_session.update(jwt=r.json()["accessJwt"], at=time.time())
        return _bluesky_session["jwt"]


def _bluesky_signed_get(params: dict, token: str, deadline: float) -> requests.Response:
    return requests.get(f"{BLUESKY_PDS}/app.bsky.feed.searchPosts", params=params,
                        headers={"Authorization": f"Bearer {token}"}, timeout=_timeout(deadline))


def _token_expired(r: requests.Response) -> bool:
    """401, or the 400 Bluesky sends for an expired/revoked token -- not any 400 (a bad query is one too),
    since every fresh sign-in counts against the ~30 per 5 minutes cap."""
    if r.status_code == 401:
        return True
    try:
        return r.status_code == 400 and r.json().get("error") in ("ExpiredToken", "InvalidToken")
    except ValueError:
        return False


def _bluesky_page(params: dict, deadline: float) -> dict:
    r = requests.get(f"{BLUESKY_PUBLIC}/app.bsky.feed.searchPosts", params=params, timeout=_timeout(deadline))
    if r.status_code in (401, 403) and (jwt := _bluesky_token(deadline)):
        r = _bluesky_signed_get(params, jwt, deadline)
        if _token_expired(r) and (jwt := _bluesky_token(deadline, force_new=True)):
            r = _bluesky_signed_get(params, jwt, deadline)
    r.raise_for_status()
    return r.json()


def search_bluesky(query: str, date_range: tuple | None, max_results: int) -> list[dict]:
    """Top posts for the query in the window, in English. Bluesky has no location, so no country filter.
    Image-only posts (no text, no link card) are skipped: there is nothing in them to analyse."""
    params = {"q": query, "sort": "top", "limit": min(max_results, 100), "lang": SEARCH_LANGUAGE}
    if bounds := _bounds(date_range):
        params |= {"since": _iso(bounds[0]), "until": _iso(bounds[1])}
    posts: list[dict] = []
    deadline = time.monotonic() + BUDGET_S
    try:
        for _ in range(MAX_PAGES):
            data = _bluesky_page(params, deadline)
            posts += data.get("posts", [])
            cursor = data.get("cursor")
            if len(posts) >= max_results or not data.get("posts") or not cursor or cursor == params.get("cursor"):
                break
            params["cursor"] = cursor
    except (requests.RequestException, ValueError, KeyError, TypeError, TimeoutError) as e:
        logger.warning("Bluesky search stopped: %s", type(e).__name__)  # pages already fetched are kept

    out = []
    for p in posts[:max_results]:
        record, author = p.get("record") or {}, p.get("author") or {}
        embed = p.get("embed") or {}
        external = embed.get("external") or {}
        text = record.get("text") or external.get("title") or ""
        if not text.strip() or not _same_language(record.get("langs") or []):
            continue
        handle = author.get("handle", "")
        out.append({
            "publisher_name": "Bluesky",
            "published_url": f"https://bsky.app/profile/{handle}/post/{p.get('uri', '').rsplit('/', 1)[-1]}",
            "title": text[:120],
            "content": text,
            "author": author.get("displayName") or handle,
            "date": record.get("createdAt") or "",
            "thumbnail": (embed.get("images") or [{}])[0].get("thumb") or external.get("thumb") or "",
            "_source": "bluesky",
        })
    return out


# --------------------------------------------------------------------------
# SearXNG -- general + news. Its engines rarely give a date or a publisher country, so every result is
# vetted from the web itself (page_signals): the date its page declares, and the country its publisher's
# footer / About / Contact pages name. Nothing is guessed.
# --------------------------------------------------------------------------

VET_WORKERS = 8


def _vet(items: list[dict], country: str) -> list[dict]:
    """Each result's publish date from its own page (the page wins over the engine's), then its
    publisher's country: a publisher in another country is dropped; one that names none is kept."""
    from concurrent.futures import ThreadPoolExecutor

    host_of = lambda item: (urlparse(item["published_url"]).hostname or "").lower()  # noqa: E731
    hosts = list(dict.fromkeys(host_of(i) for i in items))
    with ThreadPoolExecutor(max_workers=VET_WORKERS) as pool:
        dates = list(pool.map(lambda i: page_signals.published_date(page_signals.fetch_html(i["published_url"])), items))
        countries = dict(zip(hosts, pool.map(lambda h: page_signals.publisher_country(f"https://{h}/"), hosts)))

    # A site that refuses us still counts (it is shown as paid): its date then comes from the engine or the
    # link itself (/2026/10/21/), so a subscription publisher's article is not lost for want of a readable page.
    kept = [{**i, "date": d or i["date"] or page_signals.date_from_url(i["published_url"])}
            for i, d in zip(items, dates) if countries.get(host_of(i)) in (None, country.upper())]
    logger.info("SearXNG vetting: %s results, %s dated by their page, %s dropped as another country's publisher, "
                "%s of %s sites named no country", len(items), sum(map(bool, dates)), len(items) - len(kept),
                sum(c is None for c in countries.values()), len(hosts))
    return kept


def _searxng_time_range(date_range: tuple | None) -> str | None:
    """SearXNG only knows coarse buckets; the exact window is applied by the caller's date filter."""
    bounds = _bounds(date_range)
    if not bounds:
        return None
    days = (date.today() - bounds[0].date()).days
    return next((bucket for bucket, limit in (("day", 1), ("week", 7), ("month", 31), ("year", 366)) if days <= limit), None)


def search_searxng(query: str, country: str, date_range: tuple | None, max_results: int) -> list[dict]:
    """Web and news results from the SearXNG engines, asked for in English for the brief's country (e.g.
    en-US), then vetted page by page (see _vet). Slow by design: every result's page and every new
    publisher's home, About and Contact pages are read."""
    base = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
    if not base:
        return []
    params = {"q": query, "format": "json", "categories": "general,news",
              "language": f"{SEARCH_LANGUAGE}-{country.upper()}"}
    if time_range := _searxng_time_range(date_range):
        params["time_range"] = time_range
    results: list[dict] = []
    deadline = time.monotonic() + BUDGET_S
    try:
        for page in range(1, MAX_PAGES + 1):
            r = requests.get(f"{base}/search", params={**params, "pageno": page}, timeout=_timeout(deadline))
            r.raise_for_status()
            batch = r.json().get("results", [])
            results += batch
            if not batch or len(results) >= max_results:
                break
    except (requests.RequestException, ValueError, TimeoutError) as e:
        logger.warning("SearXNG search stopped: %s", type(e).__name__)  # pages already fetched are kept

    items = [{
        "publisher_name": res.get("source") or res.get("engine") or "",
        "published_url": res.get("url") or "",
        "title": res.get("title") or "",
        "content": res.get("content") or "",
        "author": res.get("author") or "",
        "date": res.get("publishedDate") or "",
        "thumbnail": res.get("thumbnail") or res.get("img_src") or "",
        "_source": "searxng",
    } for res in results[:max_results] if isinstance(res, dict) and res.get("url")]
    return _vet(items, country)
