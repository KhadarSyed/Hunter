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

import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import TypedDict
from urllib.parse import quote, urlparse

import requests

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
    "tiktok.com": "tiktok",
}
MAX_RSS_RECENCY_HOURS = 24 * 365


class SocialMediaItem(TypedDict):
    publisher_name: str
    published_url: str
    content: str
    author: str
    date_posted: str
    _source: str


class TraditionalMediaItem(TypedDict):
    publisher_name: str
    published_url: str
    title: str
    content: str
    author: str
    published_date: str
    _source: str


class NewsSearchError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# SerpAPI
# --------------------------------------------------------------------------

def _search_serpapi(query: str, country: str, max_results: int, recency_days: int | None = None) -> list[dict]:
    """Raw SerpAPI Google News engine results. Returns [] on any failure (missing key,
    network error, rate limit, bad response) rather than raising. `recency_days`, when given,
    is embedded as a `when:Nd` prefix — the same Google search operator Google News RSS already
    uses (this module's own `_search_google_news_rss`), since SerpAPI's google_news engine is
    the same underlying Google index and honors the same operator."""
    api_key = os.getenv("SERP_API_KEY", "")
    if not api_key:
        logger.debug("SERP_API_KEY not set — skipping SerpAPI search")
        return []

    q = f"when:{recency_days}d {query}" if recency_days else query
    params = {
        "engine": "google_news",
        "q": q,
        "gl": country.lower(),
        "hl": "en",
        "api_key": api_key,
    }
    try:
        r = requests.get(SERPAPI_URL, params=params, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            raise NewsSearchError(f"SerpAPI request failed: {r.status_code} {r.text[:300]}")
        data = r.json()
        if data.get("error"):
            raise NewsSearchError(f"SerpAPI returned an error: {data['error']}")
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
        "_source": "serpapi",
    }


# --------------------------------------------------------------------------
# Tavily
# --------------------------------------------------------------------------

def _search_tavily(query: str, country: str, max_results: int, date_range: tuple | None = None,
                    include_domains: list[str] | None = None) -> list[dict]:
    """Raw Tavily Search API (topic=news) results. Returns [] on any failure (missing key,
    network error, rate limit, bad response) rather than raising. `country` is accepted for
    signature symmetry with `_search_serpapi` but not sent — Tavily's `country` parameter takes
    an enumerated full country name (not an ISO code), and this module deals exclusively in
    ISO 3166-1 alpha-2 codes like the rest of the pipeline, so mapping it is out of scope here.
    `date_range`, when given, is sent as Tavily's own `start_date`/`end_date` params (confirmed
    supported for topic=news via Tavily's public API reference, 2026-09)."""
    api_key = os.getenv("TAVILY_API_KEY", "")
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
        if r.status_code != 200:
            # Never log payload/response text here — it echoes the api_key back on some error
            # paths (e.g. auth failures), and TAVILY_API_KEY must never be logged.
            raise NewsSearchError(f"Tavily request failed: {r.status_code}")
        data = r.json()
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
        "author": "",
        "date": item.get("published_date") or "",
        "_source": "tavily",
    }


# --------------------------------------------------------------------------
# Google News RSS
# --------------------------------------------------------------------------

def _resolve_redirect_url(url: str) -> str:
    """Google News RSS's <link> is always a news.google.com redirect wrapper, never the real
    article URL — Google doesn't expose the target in the feed by design. Follow the HTTP
    redirect chain to the real destination. Best-effort: returns the original url unchanged
    on any failure (timeout, network error, blocked, etc.), never raises."""
    try:
        resp = requests.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True, stream=True,
                             headers={"User-Agent": "Mozilla/5.0"})
        resp.close()
        return resp.url
    except Exception:
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

        parsed.append({
            "title": headline.strip(),
            "link": _xml_text(item.find("link")).strip(),
            "publisher": publisher.strip(),
            "date": _xml_text(item.find("pubDate")).strip(),
            "snippet": _strip_html(_xml_text(item.find("description"))),
            "author": "",
        })

    # Resolve every redirect concurrently — sequential resolution of up to max_results items
    # (each a real network round-trip) would make this the slowest of the 3 sources by far.
    from concurrent.futures import ThreadPoolExecutor

    links = [p["link"] for p in parsed if p["link"]]
    if links:
        with ThreadPoolExecutor(max_workers=10) as pool:
            resolved = dict(zip(links, pool.map(_resolve_redirect_url, links)))
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


def _normalize_rss_item(item: dict) -> dict:
    return {
        "publisher_name": item.get("publisher") or "",
        "published_url": item.get("link") or "",
        "title": item.get("title") or "",
        "content": item.get("snippet") or "",
        "author": item.get("author") or "",
        "date": item.get("date") or "",
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
) -> dict:
    """Search SerpAPI + Tavily + Google News RSS concurrently, normalize into social/traditional
    media buckets, dedupe by URL. Never raises — a down source just contributes nothing.

    `tavily_query`, when given, is sent to Tavily instead of `query` (Tavily favors natural
    language over raw Boolean operators; `query` still goes to SerpAPI/RSS, which are both
    Google-search-flavored and handle Boolean syntax the same way). Defaults to `query` so
    existing single-query callers are unaffected.

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
        futures = {
            pool.submit(_search_serpapi, query, country, max_results, recency_days): "serpapi",
            pool.submit(_search_tavily, tavily_query or query, country, max_results, date_range, include_domains): "tavily",
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
