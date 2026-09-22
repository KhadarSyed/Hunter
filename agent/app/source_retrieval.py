"""Fetch source articles for QC verification. Caches results to avoid re-fetching."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests

from . import intelligence_store as store

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

PAYWALL_INDICATORS = [
    "subscribe to continue",
    "subscribe to read",
    "this content is for subscribers",
    "paywall",
    "premium content",
    "sign in to access",
    "create an account",
    "you've reached your limit",
    "free articles remaining",
]


def fetch_source(url: str) -> dict[str, Any] | None:
    """Fetch a source URL, extract headline and text. Uses cache."""
    if not url or not url.startswith("http"):
        return None

    cached = store.get_cached_source(url)
    if cached:
        if cached.get("extracted_date"):
            return cached
        # Re-fetch if cached entry is missing extracted_date (old cache)
        logger.debug("Re-fetching %s — cached entry has no extracted_date", url)

    result = _fetch_and_extract(url)
    store.upsert_source_cache(url, **result)
    return {**result, "url": url}


def _fetch_and_extract(url: str) -> dict[str, Any]:
    """Fetch URL and extract headline + text content."""
    try:
        resp = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )

        info: dict[str, Any] = {
            "status_code": resp.status_code,
            "is_accessible": resp.status_code == 200,
            "is_paywalled": 0,
            "extracted_headline": "",
            "extracted_date": "",
            "extracted_text": "",
            "fetch_error": None,
        }

        if resp.status_code != 200:
            info["is_accessible"] = 0
            info["fetch_error"] = f"HTTP {resp.status_code}"
            return info

        html = resp.text
        info["extracted_headline"] = _extract_headline(html)
        info["extracted_date"] = _extract_date(html)
        info["extracted_text"] = _extract_text(html)

        html_lower = html.lower()
        for indicator in PAYWALL_INDICATORS:
            if indicator in html_lower:
                info["is_paywalled"] = 1
                break

        return info

    except requests.exceptions.Timeout:
        return {"status_code": 0, "is_accessible": 0, "fetch_error": "Timeout", "is_paywalled": 0}
    except requests.exceptions.ConnectionError:
        return {"status_code": 0, "is_accessible": 0, "fetch_error": "Connection failed", "is_paywalled": 0}
    except Exception as e:
        return {"status_code": 0, "is_accessible": 0, "fetch_error": str(e)[:200], "is_paywalled": 0}


def _extract_headline(html: str) -> str:
    """Extract the most likely headline from HTML."""
    og = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)', html, re.IGNORECASE)
    if og:
        return _clean_text(og.group(1))

    twitter = re.search(r'<meta\s+name=["\']twitter:title["\']\s+content=["\']([^"\']+)', html, re.IGNORECASE)
    if twitter:
        return _clean_text(twitter.group(1))

    h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
    if h1:
        return _clean_text(h1.group(1))

    title = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if title:
        text = _clean_text(title.group(1))
        if " | " in text:
            text = text.split(" | ")[0].strip()
        if " - " in text:
            text = text.split(" - ")[0].strip()
        return text

    return ""


def _extract_date(html: str) -> str:
    """Extract the publication date from HTML metadata."""
    for ld_match in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        try:
            import json
            ld = json.loads(ld_match.group(1))
            items = ld if isinstance(ld, list) else [ld]
            for item in items:
                if not isinstance(item, dict):
                    continue
                for key in ("datePublished", "dateCreated"):
                    val = item.get(key, "")
                    if val:
                        return val[:25]
        except (ValueError, TypeError):
            pass

    og = re.search(
        r'<meta\s+property=["\']article:published_time["\']\s+content=["\']([^"\']+)',
        html, re.IGNORECASE,
    )
    if og:
        return og.group(1).strip()[:25]

    for attr in ("date", "pubdate", "publish-date", "sailthru.date"):
        m = re.search(
            rf'<meta\s+name=["\'](?:i)?{re.escape(attr)}["\']\s+content=["\']([^"\']+)',
            html, re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()[:25]

    time_el = re.search(r'<time[^>]+datetime=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if time_el:
        return time_el.group(1).strip()[:25]

    return ""


def _extract_text(html: str) -> str:
    """Extract visible text from HTML, focusing on article content."""
    for tag in ("script", "style", "nav", "header", "footer", "aside"):
        html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', html, flags=re.DOTALL | re.IGNORECASE)

    article = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL | re.IGNORECASE)
    if article:
        html = article.group(1)

    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    text = _decode_entities(text)
    return text[:5000]


def _clean_text(html_text: str) -> str:
    text = re.sub(r'<[^>]+>', '', html_text)
    text = _decode_entities(text)
    return re.sub(r'\s+', ' ', text).strip()


def _decode_entities(text: str) -> str:
    import html
    return html.unescape(text)
