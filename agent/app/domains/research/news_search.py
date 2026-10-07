"""Google News RSS + SerpAPI + Tavily search, normalized into social/traditional media buckets.

Three independent sources feed `fetch_and_normalize()`:
  - SerpAPI's Google News engine (`SERP_API_KEY` env var) — richer metadata, rate-limited.
  - Tavily Search API (`TAVILY_API_KEY` env var) — general web/news search, rate-limited.
  - Google News RSS (`https://news.google.com/rss/search`) — keyless, no API limits.

Each source is queried and parsed independently via plain `requests` (matching
`azure_openai_client.py`'s and `nvidia_embed_client.py`'s preference for raw HTTP clients over
SDKs — Tavily has an official `tavily-python` SDK, but a raw `requests.post` keeps this module's
three sources consistent with each other and with the rest of the codebase). A failure in any
source is logged and degrades to an empty list for that source — `fetch_and_normalize()` never
raises because one or more sources are down. When BOTH SerpAPI and Tavily contribute nothing
(down, unconfigured, or erroring), the return value's `"degraded"` flag is set so callers can
surface a "results are from Google News RSS only" notice — RSS itself is never allowed to block
the pipeline.

Wired into `domains/research/web_research.py`'s `_ddg_web_search`/`_ddg_news_search`.
"""
from __future__ import annotations

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Callable, TypedDict
from urllib.parse import quote, urlparse

import requests

from ...core import serp_keys

logger = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search"
TAVILY_API_URL = "https://api.tavily.com/search"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"

# Social-platform domains that get their own bucket instead of being treated as traditional
# media. Confirmed (this session) against `web_research_adapter.py`'s `BLOCKED_DOMAINS` — these
# are the entries that move to the social bucket here rather than being rejected outright.
SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "reddit.com",
    "quora.com",
}

DEFAULT_TIMEOUT = 15
DEFAULT_RSS_RECENCY_HOURS = 24 * 7  # 7 days — reasonable "fresh news" default window

# Single source of truth for "is this a social platform" — used both to classify a fetched
# item's platform (multi_source._platform_for_url) and to bias a fetch toward these domains
# (multi_source's social-preference query variant, Tavily's include_domains).
SOCIAL_PLATFORM_DOMAINS = {
    "twitter.com": "twitter", "x.com": "twitter", "instagram.com": "instagram",
    "facebook.com": "facebook", "reddit.com": "reddit", "linkedin.com": "linkedin",
    "tiktok.com": "tiktok", "truthsocial.com": "truth_social",
}
MAX_RSS_RECENCY_HOURS = 24 * 365


class SocialMediaItem(TypedDict):
    publisher_name: str
    published_url: str
    content: str
    author: str
    date_posted: str
    thumbnail: str
    _source: str


class TraditionalMediaItem(TypedDict):
    publisher_name: str
    published_url: str
    title: str
    content: str
    author: str
    published_date: str
    thumbnail: str
    _source: str


class NewsSearchError(RuntimeError):
    pass


# Ordered by specificity — a personal byline (author/journalist/...) should win over a generic
# organizational field (source/brand/company/...) when both are present on the same raw item.
_IDENTITY_KEYWORDS = [
    # Traditional media
    "author", "journalist", "reporter", "writer", "editor", "columnist", "contributor",
    "correspondent", "publisher", "publication", "newsroom", "news desk",
    # Social media
    "account", "accountname", "username", "handle", "screen_name", "profile", "creator",
    "channel", "channelname", "owner", "page", "influencer",
    # Generic
    "source", "organization", "brand", "company",
]


def _find_identity_value(raw: object) -> str:
    """Best-effort: scan a raw source item's keys for anything matching a known identity/
    authorship keyword (see _IDENTITY_KEYWORDS), returning the first match's string value in
    keyword-priority order. Different sources use wildly different field names for "who
    wrote/posted this" (author, journalist, handle, channel, ...) — this generic scan covers
    variants not manually mapped per source. Recurses one level into nested dicts (e.g.
    SerpAPI's `source: {...}`)."""
    if not isinstance(raw, dict):
        return ""

    def _normalize_key(key: str) -> str:
        return key.lower().replace("_", "").replace(" ", "")

    flat: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, str) and value.strip():
            flat[_normalize_key(key)] = value.strip()
        elif isinstance(value, list) and value and isinstance(value[0], str) and value[0].strip():
            flat[_normalize_key(key)] = value[0].strip()
        elif isinstance(value, dict):
            nested = _find_identity_value(value)
            if nested:
                flat[_normalize_key(key)] = nested

    for keyword in _IDENTITY_KEYWORDS:
        keyword_normalized = keyword.replace(" ", "")
        for key, value in flat.items():
            if keyword_normalized in key:
                return value
    return ""


# --------------------------------------------------------------------------
# SerpAPI
# --------------------------------------------------------------------------

def _search_serpapi(query: str, country: str, max_results: int, recency_days: int | None = None,
                     api_key_override: str | None = None,
                     on_result: Callable[[bool, str | None], None] | None = None) -> list[dict]:
    """Raw SerpAPI Google News engine results. Returns [] on any failure (missing key,
    network error, rate limit, bad response) rather than raising. `recency_days`, when given,
    is embedded as a `when:Nd` prefix — the same Google search operator Google News RSS already
    uses (this module's own `_search_google_news_rss`), since SerpAPI's google_news engine is
    the same underlying Google index and honors the same operator. `api_key_override`, when
    given (an org's own configured key — see domains/datasources/), is used instead of the
    global SERP_API_KEY env var. `on_result(ok, error)`, when given, is called once with
    whether THIS call indicates the key itself is valid — only a 401/403 or a vendor
    "invalid api key" error counts as ok=False; network/rate-limit issues are inconclusive
    and don't call it at all, so they never flip a key's status."""
    q = f"when:{recency_days}d {query}" if recency_days else query
    params = {
        "engine": "google_news",
        "q": q,
        "gl": country.lower(),
        "hl": "en",
    }
    try:
        r = serp_keys.get(SERPAPI_URL, params, DEFAULT_TIMEOUT, override=api_key_override)
        if r is None:
            logger.debug("No SerpAPI key available — skipping SerpAPI search")
            return []
        if r.status_code in (401, 403):
            if on_result:
                on_result(False, f"SerpAPI rejected this key ({r.status_code})")
            return []
        if r.status_code != 200:
            raise NewsSearchError(f"SerpAPI request failed: {r.status_code} {r.text[:300]}")
        data = r.json()
        if data.get("error"):
            error = str(data["error"])
            if "api key" in error.lower() and "invalid" in error.lower():
                if on_result:
                    on_result(False, error)
                return []
            raise NewsSearchError(f"SerpAPI returned an error: {error}")
        if on_result:
            on_result(True, None)
    except Exception:
        logger.exception("SerpAPI search failed for query=%r", query)
        return []

    return list(data.get("news_results", []))[:max_results]


def _normalize_serpapi_item(item: dict) -> dict:
    source = item.get("source")
    publisher = ""
    author = ""
    if isinstance(source, dict):
        publisher = source.get("name") or ""
        authors = source.get("authors") or []
        if authors:
            author = authors[0]
    elif isinstance(source, str):
        publisher = source
    if not author:
        author = _find_identity_value(item)

    return {
        "publisher_name": publisher,
        "published_url": item.get("link") or "",
        "title": item.get("title") or "",
        # SerpAPI's google_news engine never returns a snippet/description field (confirmed
        # against a live response — only title/source/link/date/iso_date/thumbnail come back),
        # so content is legitimately empty for serpapi-sourced items.
        "content": item.get("snippet") or "",
        "author": author,
        # Prefer iso_date (true ISO 8601, e.g. "2026-09-22T11:00:05Z") over the human-readable
        # "date" (e.g. "09/22/2026, 11:00 AM, +0000 UTC") — both parse, but iso_date is
        # unambiguous and is what SerpAPI actually provides for this purpose.
        "date": item.get("iso_date") or item.get("date") or "",
        "thumbnail": item.get("thumbnail") or "",
        "_source": "serpapi",
    }


# --------------------------------------------------------------------------
# Tavily
# --------------------------------------------------------------------------

def _search_tavily(query: str, country: str, max_results: int, date_range: tuple | None = None,
                    include_domains: list[str] | None = None, api_key_override: str | None = None,
                    on_result: Callable[[bool, str | None], None] | None = None) -> list[dict]:
    """Raw Tavily Search API (topic=news) results. Returns [] on any failure (missing key,
    network error, rate limit, bad response) rather than raising. `country` is accepted for
    signature symmetry with `_search_serpapi` but not sent — Tavily's `country` parameter takes
    an enumerated full country name (not an ISO code), and this module deals exclusively in
    ISO 3166-1 alpha-2 codes like the rest of the pipeline, so mapping it is out of scope here.
    `date_range`, when given, is sent as Tavily's own `start_date`/`end_date` params (confirmed
    supported for topic=news via Tavily's public API reference, 2026-09). `api_key_override`
    and `on_result` mirror `_search_serpapi` — see its docstring."""
    api_key = api_key_override or os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        logger.debug("TAVILY_API_KEY not set — skipping Tavily search")
        return []

    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "topic": "news",
        "max_results": max_results,
        "include_answer": False,
        "include_published_date": True,
    }
    if date_range is not None:
        payload["start_date"] = _coerce_datetime(date_range[0]).strftime("%Y-%m-%d")
        payload["end_date"] = _coerce_datetime(date_range[1]).strftime("%Y-%m-%d")
    if include_domains:
        payload["include_domains"] = include_domains
        payload["include_domains_mode"] = "filter"
    try:
        r = requests.post(TAVILY_API_URL, json=payload, timeout=DEFAULT_TIMEOUT)
        if r.status_code in (401, 403):
            if on_result:
                on_result(False, f"Tavily rejected this key ({r.status_code})")
            return []
        if r.status_code != 200:
            # Never log payload/response text here — it echoes the api_key back on some error
            # paths (e.g. auth failures), and TAVILY_API_KEY must never be logged.
            raise NewsSearchError(f"Tavily request failed: {r.status_code}")
        data = r.json()
        if on_result:
            on_result(True, None)
    except Exception:
        logger.exception("Tavily search failed for query=%r", query)
        return []

    return list(data.get("results", []))[:max_results]


def _normalize_tavily_item(item: dict) -> dict:
    return {
        "publisher_name": _extract_domain(item.get("url") or ""),
        "published_url": item.get("url") or "",
        "title": item.get("title") or "",
        "content": item.get("content") or "",
        "author": _find_identity_value(item),
        "date": item.get("published_date") or "",
        "thumbnail": "",  # Tavily returns images only as a separate top-level array (needs
                          # include_images=True), not tied to a specific result — out of scope
        "_source": "tavily",
    }


# --------------------------------------------------------------------------
# Google News RSS
# --------------------------------------------------------------------------

_GOOGLE_BATCHEXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
# Fixed non-identifying params Google's own front-end sends on every garturlreq call —
# confirmed stable (2026-10) by inspecting a live decode response; not a credential or
# anything caller-specific, just the request shape its batchexecute endpoint expects.
_GARTURLREQ_PREFIX = ["en-IN", "IN", ["FINANCE_TOP_INDICES", "GENESIS_PUBLISHER_SECTION", "WEB_TEST_1_0_0"],
                      None, None, 1, 1, "IN:en", None, None, None, None, None, None, None, False, 5]


def _decode_google_news_url(url: str) -> str:
    """Google News RSS's <link> is a news.google.com/rss/articles/<id> wrapper — Google
    stopped exposing the real target via a plain HTTP redirect some time ago (the wrapper page
    returns 200 with an interstitial, never a 3xx), so a redirect-follow silently returns the
    wrapper URL unchanged. The wrapper page instead embeds a `data-n-a-id`/`data-n-a-sg`/
    `data-n-a-ts` triplet that Google's own front-end posts to its internal batchexecute RPC
    (`Fbv4je` / "garturlreq") to resolve the real article URL — reverse-engineered and verified
    live against a real article link (2026-10). Best-effort at every step: returns the original
    url unchanged on any failure (missing attributes, network error, unexpected response shape),
    never raises — a failed decode must never block the rest of the search results."""
    if "news.google.com" not in url:
        return url
    try:
        page = requests.get(url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        page.raise_for_status()
        html = page.text
        id_match = re.search(r'data-n-a-id="([^"]+)"', html)
        sig_match = re.search(r'data-n-a-sg="([^"]+)"', html)
        ts_match = re.search(r'data-n-a-ts="([^"]+)"', html)
        if not (id_match and sig_match and ts_match):
            return url

        article_id, signature, timestamp = id_match.group(1), sig_match.group(1), ts_match.group(1)
        inner = json.dumps([
            "garturlreq",
            [_GARTURLREQ_PREFIX, "en-IN", "IN", True, [3, 5, 9, 19], 1, True, "990638521", 0, 0, None, 0],
            article_id, int(timestamp), signature,
        ])
        f_req = json.dumps([[["Fbv4je", inner, None, "generic"]]])

        resp = requests.post(
            _GOOGLE_BATCHEXECUTE_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                     "User-Agent": "Mozilla/5.0"},
            data={"f.req": f_req}, timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        # Response is ")]}'\n\n" followed by a JSON array; the decoded URL is nested two levels
        # deep as a JSON-encoded string inside the first row's 3rd element.
        body = resp.text.split("\n", 2)[-1]
        outer = json.loads(body)
        garturlres = json.loads(outer[0][2])
        decoded_url = garturlres[1]
        return decoded_url if isinstance(decoded_url, str) and decoded_url.startswith("http") else url
    except Exception:
        logger.debug("Google News URL decode failed for %r; using wrapper link as-is", url, exc_info=True)
        return url


def _search_google_news_rss(query: str, recency_hours: int, country: str) -> list[dict]:
    """Raw Google News RSS results (keyless). Returns [] on any failure."""
    full_query = query
    rss_url = GOOGLE_NEWS_RSS_URL
    final_query = f"when:{recency_hours}h {full_query}"
    url = f"{rss_url}?q={quote(final_query)}&hl=en-US&gl={country}&ceid={country}:en"

    try:
        r = requests.get(url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        logger.exception("Google News RSS fetch failed for query=%r", query)
        return []

    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []

    parsed = []
    for item in items:
        title_raw = _xml_text(item.find("title"))
        source_el = item.find("source")
        publisher = _xml_text(source_el)

        # Google News RSS wraps titles as "Headline - Publisher"; fall back to splitting the
        # title when the <source> element is absent.
        headline = title_raw
        if not publisher and " - " in title_raw:
            headline, _, publisher = title_raw.rpartition(" - ")

        description_raw = _xml_text(item.find("description"))
        parsed.append({
            "title": headline.strip(),
            "link": _xml_text(item.find("link")).strip(),
            "publisher": publisher.strip(),
            "date": _xml_text(item.find("pubDate")).strip(),
            "snippet": _strip_html(description_raw),
            "thumbnail": _extract_first_img_src(description_raw),
            "author": "",
        })

    # Resolve every redirect concurrently — sequential resolution of up to max_results items
    # (each a real network round-trip) would make this the slowest of the 3 sources by far.
    from concurrent.futures import ThreadPoolExecutor

    links = [p["link"] for p in parsed if p["link"]]
    if links:
        with ThreadPoolExecutor(max_workers=10) as pool:
            resolved = dict(zip(links, pool.map(_decode_google_news_url, links)))
        for p in parsed:
            if p["link"] in resolved:
                p["link"] = resolved[p["link"]]

    return parsed


def _xml_text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text


def _strip_html(raw: str) -> str:
    """Minimal tag stripper — Google News RSS descriptions wrap the snippet in <a>/<font> tags."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", text).strip()


def _extract_first_img_src(raw_html: str) -> str:
    """Best-effort: Google News RSS's <description> sometimes embeds a thumbnail as an <img>
    tag before it's stripped down to the display snippet."""
    if not raw_html:
        return ""
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html)
    return match.group(1) if match else ""


def _normalize_rss_item(item: dict) -> dict:
    return {
        "publisher_name": item.get("publisher") or "",
        "published_url": item.get("link") or "",
        "title": item.get("title") or "",
        "content": item.get("snippet") or "",
        "author": item.get("author") or "",
        "date": item.get("date") or "",
        "thumbnail": item.get("thumbnail") or "",
        "_source": "google_news_rss",
    }


# --------------------------------------------------------------------------
# Domain bucketing
# --------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _is_social_domain(url: str) -> bool:
    domain = _extract_domain(url)
    if not domain:
        return False
    return any(domain == d or domain.endswith("." + d) for d in SOCIAL_DOMAINS)


def _bucket_item(norm: dict) -> tuple[str, dict]:
    if _is_social_domain(norm["published_url"]):
        item: SocialMediaItem = {
            "publisher_name": norm["publisher_name"],
            "published_url": norm["published_url"],
            "content": norm["content"] or norm["title"],
            "author": norm["author"],
            "date_posted": norm["date"],
            "thumbnail": norm.get("thumbnail", ""),
            "_source": norm["_source"],
        }
        return "social_media", item

    item: TraditionalMediaItem = {
        "publisher_name": norm["publisher_name"],
        "published_url": norm["published_url"],
        "title": norm["title"],
        "content": norm["content"],
        "author": norm["author"],
        "published_date": norm["date"],
        "thumbnail": norm.get("thumbnail", ""),
        "_source": norm["_source"],
    }
    return "traditional_media", item


# --------------------------------------------------------------------------
# Date parsing / range filtering
# --------------------------------------------------------------------------

def _parse_date(date_str: str) -> datetime | None:
    """Best-effort parse across the date formats these two sources actually emit.
    Returns None (never raises) when the string doesn't match anything known."""
    if not date_str:
        return None
    date_str = date_str.strip()

    # RFC 822 — Google News RSS <pubDate>, e.g. "Tue, 23 Sep 2026 10:00:00 GMT".
    try:
        dt = parsedate_to_datetime(date_str)
        if dt is not None:
            return dt.replace(tzinfo=None)
    except Exception:
        pass

    # ISO 8601.
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass

    # SerpAPI google_news engine style, e.g. "09/23/2026, 10:00 AM, +0000 UTC".
    try:
        cleaned = date_str.replace(" UTC", "").strip()
        return datetime.strptime(cleaned, "%m/%d/%Y, %I:%M %p, %z").replace(tzinfo=None)
    except Exception:
        pass

    return None


def _coerce_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    raise TypeError(f"date_range entries must be date/datetime, got {type(value)!r}")


def _within_range(date_str: str, date_range: tuple) -> bool:
    """Stringent filter: an unparseable date, or one outside the window, fails the check
    (dropped by the caller) — this is a deliberate reversal of the old soft/advisory
    behavior, which kept items it couldn't verify."""
    parsed = _parse_date(date_str)
    if parsed is None:
        logger.debug("Unparseable date %r — dropping item under stringent date filter", date_str)
        return False
    start = _coerce_datetime(date_range[0])
    # +1 day, exclusive upper bound: date_range[1] is coerced to midnight of that date, so
    # without this an item published any time later that same day (almost always true for
    # "today", the most relevant part of a short window) would fail the range check.
    end = _coerce_datetime(date_range[1]) + timedelta(days=1)
    return start <= parsed < end


def _recency_hours_for_range(date_range: tuple | None) -> int:
    if not date_range:
        return DEFAULT_RSS_RECENCY_HOURS
    start = _coerce_datetime(date_range[0])
    hours = int((datetime.utcnow() - start).total_seconds() // 3600)
    return max(1, min(hours, MAX_RSS_RECENCY_HOURS))


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def fetch_and_normalize(
    query: str,
    country: str = "US",
    date_range: tuple | None = None,
    max_results: int = 20,
    tavily_query: str | None = None,
    include_domains: list[str] | None = None,
    api_keys: dict[str, str] | None = None,
    on_source_result: Callable[[str, bool, str | None], None] | None = None,
) -> dict:
    """Search SerpAPI + Tavily + Google News RSS concurrently, normalize into social/traditional
    media buckets, dedupe by URL. Never raises — a down source just contributes nothing.

    `tavily_query`, when given, is sent to Tavily instead of `query` (Tavily favors natural
    language over raw Boolean operators; `query` still goes to SerpAPI/RSS, which are both
    Google-search-flavored and handle Boolean syntax the same way). Defaults to `query` so
    existing single-query callers are unaffected.

    `api_keys` (optional {"tavily": ..., "serpapi": ...}) overrides the global env-var keys
    with an org's own configured keys (see domains/datasources/). `on_source_result(source,
    ok, error)`, when given, is called for each of tavily/serpapi once per call with whether
    that specific call indicates the key is valid — wired by research/router.py into
    domains/datasources/service.record_result() so a key's status reflects real usage.

    Returns {"social_media": [...], "traditional_media": [...], "degraded": bool,
    "failed_sources": [...]}. "degraded" is True only when BOTH SerpAPI and Tavily contributed
    zero results (unconfigured, erroring, or genuinely empty) — RSS alone is never enough to
    avoid the flag, since it's the fallback the flag exists to announce. RSS itself failing too
    is also captured in "failed_sources" but doesn't change the AND condition driving "degraded".
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    recency_days = None
    if date_range is not None:
        recency_days = max(1, (date.today() - _coerce_datetime(date_range[0]).date()).days)

    pool = ThreadPoolExecutor(max_workers=3)
    results_by_source: dict[str, list[dict]] = {"serpapi": [], "tavily": [], "google_news_rss": []}
    try:
        api_keys = api_keys or {}
        on_serpapi_result = (lambda ok, error: on_source_result("serpapi", ok, error)) if on_source_result else None
        on_tavily_result = (lambda ok, error: on_source_result("tavily", ok, error)) if on_source_result else None
        futures = {
            pool.submit(_search_serpapi, query, country, max_results, recency_days,
                        api_keys.get("serpapi"), on_serpapi_result): "serpapi",
            pool.submit(_search_tavily, tavily_query or query, country, max_results, date_range,
                        include_domains, api_keys.get("tavily"), on_tavily_result): "tavily",
            pool.submit(_search_google_news_rss, query,
                        recency_hours=_recency_hours_for_range(date_range), country=country): "google_news_rss",
        }
        try:
            for future in as_completed(futures, timeout=DEFAULT_TIMEOUT + 5):
                source = futures[future]
                try:
                    results_by_source[source] = future.result()
                except Exception:
                    logger.exception("%s fetch raised unexpectedly", source)
                    results_by_source[source] = []
        except TimeoutError:
            # as_completed's own timeout, not an individual source's — at least one future is
            # still running. Collect whatever already finished; abandon the rest (contributing
            # nothing) rather than let this propagate and fail the whole caller, honoring this
            # function's documented "never raises" contract.
            for future, source in futures.items():
                if future.done():
                    try:
                        results_by_source[source] = future.result()
                    except Exception:
                        results_by_source[source] = []
                else:
                    logger.warning("%s fetch timed out — abandoning, contributing nothing", source)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    serpapi_raw = results_by_source["serpapi"]
    tavily_raw = results_by_source["tavily"]
    rss_raw = results_by_source["google_news_rss"][:max_results]

    normalized = [_normalize_serpapi_item(i) for i in serpapi_raw]
    normalized += [_normalize_tavily_item(i) for i in tavily_raw]
    normalized += [_normalize_rss_item(i) for i in rss_raw]

    buckets: dict[str, list[dict]] = {"social_media": [], "traditional_media": []}
    seen_urls: set[str] = set()

    for norm in normalized:
        url = norm["published_url"]
        if not url:
            logger.debug("Dropping %s result with no URL: %r", norm["_source"], norm.get("title"))
            continue
        if url in seen_urls:
            continue
        if date_range is not None and not _within_range(norm["date"], date_range):
            continue
        seen_urls.add(url)
        bucket, item = _bucket_item(norm)
        buckets[bucket].append(item)

    failed_sources = []
    if not serpapi_raw:
        failed_sources.append("serpapi")
    if not tavily_raw:
        failed_sources.append("tavily")
    if not rss_raw:
        failed_sources.append("google_news_rss")

    return {
        **buckets,
        "degraded": not serpapi_raw and not tavily_raw,
        "failed_sources": failed_sources,
    }
