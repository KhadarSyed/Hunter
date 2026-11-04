"""Full-article extraction for the "All Articles" reader popup.

Fetches a research item's source URL and extracts its main content as an ordered list of
blocks (heading / paragraph / image), preserving the original page's interleaving of text
and images so the frontend can render "the same format the website shows" rather than a
flat text dump. Plain `requests` first (fast, works for the large majority of sites); falls
back to Scrapling's StealthyFetcher — a real, stealth-patched browser — only when the plain
fetch looks bot-blocked, mirroring video_search.py's established escalation pattern rather
than paying the browser-automation cost on every lookup.

Results are cached by URL in `research_article_fulltext` (see core/db.py's migration 15) —
a paywalled/failed page is still cached so a bad URL doesn't get re-scraped on every view;
only a transient fetch exception is left uncached so a temporary network blip gets retried.
"""
from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from ...core.db import _conn

logger = logging.getLogger(__name__)

# These aren't articles — no paragraph content, and most actively block scrapers — so
# extraction is skipped entirely in favor of "open the real post" (or, for YouTube, an
# embeddable video since that's freely embeddable with no auth).
_SOCIAL_PLATFORMS = {
    "facebook.com": "Facebook", "instagram.com": "Instagram",
    "twitter.com": "Twitter/X", "x.com": "Twitter/X", "tiktok.com": "TikTok",
}
_YOUTUBE_DOMAINS = {"youtube.com", "youtu.be"}
_YOUTUBE_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")

FETCH_TIMEOUT_S = 15
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
MAX_BLOCKS = 80
MIN_PARAGRAPH_CHARS = 30  # skips boilerplate like "Advertisement" or a lone caption

PAYWALL_INDICATORS = [
    "subscribe to continue", "subscribe to read", "this content is for subscribers",
    "paywall", "premium content", "sign in to access", "create an account",
    "you've reached your limit", "free articles remaining",
]

_SKIP_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe"]
_CONTENT_SELECTORS = [
    "article", "[itemprop='articleBody']", ".article-body", ".article-content",
    ".entry-content", ".post-content", ".story-body", "#article-body",
]


def get_full_text(url: str, force: bool = False) -> dict:
    """Cached full-article extraction. Returns {status: "ok"|"failed"|"paywalled"|
    "social_media"|"video", title, blocks: [...], platform, embed_url, cached: bool}."""
    if not force:
        cached = _get_cached(url)
        if cached:
            return {**cached, "cached": True}

    result = _extract(url)
    result.setdefault("platform", None)
    result.setdefault("embed_url", None)
    _save_cache(url, result)
    return {**result, "cached": False}


def _get_cached(url: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT status, title, blocks_json, error, platform, embed_url "
        "FROM research_article_fulltext WHERE url = ?", (url,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "status": row["status"], "title": row["title"],
        "blocks": json.loads(row["blocks_json"]) if row["blocks_json"] else [],
        "error": row["error"], "platform": row["platform"], "embed_url": row["embed_url"],
    }


def _save_cache(url: str, result: dict) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO research_article_fulltext "
        "(url, status, title, blocks_json, error, platform, embed_url, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(url) DO UPDATE SET status = excluded.status, title = excluded.title, "
        "blocks_json = excluded.blocks_json, error = excluded.error, "
        "platform = excluded.platform, embed_url = excluded.embed_url, fetched_at = excluded.fetched_at",
        (url, result["status"], result.get("title"), json.dumps(result.get("blocks", [])),
         result.get("error"), result.get("platform"), result.get("embed_url"), time.time()),
    )
    conn.commit()
    conn.close()


def _looks_blocked(status_code: int, html: str) -> bool:
    if status_code in (403, 429):
        return True
    lowered = html.lower()
    return len(html) < 2000 and ("enable javascript" in lowered or "access denied" in lowered)


def _fetch_html(url: str) -> tuple[int, str]:
    r = requests.get(url, timeout=FETCH_TIMEOUT_S, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
    return r.status_code, r.text


def _fetch_html_stealth(url: str) -> tuple[int, str]:
    from scrapling import StealthyFetcher
    resp = StealthyFetcher.fetch(url, headless=True, network_idle=True, timeout=30_000)
    body = resp.body.decode("utf-8", errors="ignore") if isinstance(resp.body, bytes) else str(resp.body)
    return resp.status, body


def _platform_result(url: str) -> dict | None:
    """None if `url` isn't a known social/video platform — caller proceeds with normal
    article extraction. Otherwise a terminal result: "video" (YouTube — embeddable, no
    auth needed) or "social_media" (Facebook/Instagram/Twitter/TikTok — not an article,
    and these block scrapers, so extraction is never even attempted)."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if host in _YOUTUBE_DOMAINS:
        m = _YOUTUBE_ID_RE.search(url)
        if m:
            video_id = m.group(1)
            embed_url = f"https://www.youtube.com/embed/{video_id}"
            return {"status": "video", "title": None, "blocks": [], "error": None,
                    "platform": "YouTube", "embed_url": embed_url}
        return None  # couldn't find a video id — fall through to generic extraction
    if host in _SOCIAL_PLATFORMS:
        return {"status": "social_media", "title": None, "blocks": [], "error": None,
                "platform": _SOCIAL_PLATFORMS[host], "embed_url": None}
    return None


def _extract(url: str) -> dict:
    platform_result = _platform_result(url)
    if platform_result is not None:
        return platform_result
    try:
        status_code, html = _fetch_html(url)
        if status_code != 200 or _looks_blocked(status_code, html):
            try:
                status_code, html = _fetch_html_stealth(url)
            except Exception:
                logger.warning("Stealth fallback fetch failed for %r", url, exc_info=True)
        if status_code != 200:
            return {"status": "failed", "title": None, "blocks": [],
                    "error": f"HTTP {status_code}"}
    except Exception as e:
        logger.warning("Full-text fetch failed for %r", url, exc_info=True)
        return {"status": "failed", "title": None, "blocks": [], "error": str(e)[:200]}

    if any(ind in html.lower() for ind in PAYWALL_INDICATORS):
        return {"status": "paywalled", "title": _extract_title(html), "blocks": [], "error": None}

    title, blocks = _parse_article(html, url)
    if not blocks:
        return {"status": "failed", "title": title, "blocks": [],
                "error": "No article content found"}
    return {"status": "ok", "title": title, "blocks": blocks, "error": None}


def _extract_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return None


def _find_content_container(soup: BeautifulSoup) -> Tag | None:
    for selector in _CONTENT_SELECTORS:
        found = soup.select_one(selector)
        if found and len(found.get_text(strip=True)) > 200:
            return found

    # Readability-style fallback: the element whose direct <p> children have the most
    # combined text — avoids picking a nav/sidebar that merely contains a few short <p>s.
    best, best_len = None, 0
    for candidate in soup.find_all(["div", "section", "main"]):
        paragraphs = candidate.find_all("p", recursive=False)
        total = sum(len(p.get_text(strip=True)) for p in paragraphs)
        if total > best_len:
            best, best_len = candidate, total
    return best if best_len > 200 else soup.body


def _parse_article(html: str, base_url: str) -> tuple[str | None, list[dict]]:
    soup = BeautifulSoup(html, "lxml")
    for tag_name in _SKIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    title = _extract_title(html)
    container = _find_content_container(soup)
    if container is None:
        return title, []

    blocks: list[dict] = []
    for el in container.find_all(["p", "h2", "h3", "img", "figure"]):
        if len(blocks) >= MAX_BLOCKS:
            break
        if el.name in ("h2", "h3"):
            text = el.get_text(" ", strip=True)
            if text:
                blocks.append({"type": "heading", "text": text})
        elif el.name == "p":
            text = el.get_text(" ", strip=True)
            if len(text) >= MIN_PARAGRAPH_CHARS:
                blocks.append({"type": "paragraph", "text": text})
        elif el.name in ("img", "figure"):
            img = el if el.name == "img" else el.find("img")
            if not img:
                continue
            src = img.get("src") or img.get("data-src") or ""
            if not src or src.startswith("data:"):
                continue
            width = img.get("width")
            height = img.get("height")
            if width and height and str(width).isdigit() and str(height).isdigit():
                if int(width) <= 2 or int(height) <= 2:
                    continue  # tracking pixel
            blocks.append({"type": "image", "src": urljoin(base_url, src),
                           "alt": img.get("alt", "")})

    return title, blocks
