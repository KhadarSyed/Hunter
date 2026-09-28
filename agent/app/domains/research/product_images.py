"""Best-effort product/brand image fetcher using Playwright (headless Chromium).

Navigates to a DuckDuckGo image-search results page for a product/brand query
and extracts the first usable image URL. Wired as an optional enrichment into
background_brief_service.compose_brief() — never blocks brief generation and
always degrades to None on any failure.

NOTE: images are scraped from search results without licensing checks. Fine
for internal analyst review; verify rights per image before any redistribution
or publication.

Requires: `playwright` Python package + `playwright install chromium` (one-time).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Cost/latency guard — headless browser startup + page load.
_FETCH_TIMEOUT_MS = 15_000


def fetch_product_image_url(query: str) -> str | None:
    """Return the first image URL from a DDG image search for `query`, or None.

    Never raises. Returns None when Playwright is unavailable, the page can't
    be loaded, or no image is found.
    """
    if not query or not query.strip():
        return None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug("playwright not installed — skipping product image fetch")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            ddg_url = f"https://duckduckgo.com/?q={query}&iax=images&ia=images"
            page.goto(ddg_url, timeout=_FETCH_TIMEOUT_MS, wait_until="domcontentloaded")
            # DDG images load as <img> inside tile links; wait for at least one.
            page.wait_for_selector("img[data-src], img.tile--img__img", timeout=_FETCH_TIMEOUT_MS)
            imgs = page.query_selector_all("img[data-src], img.tile--img__img")
            browser.close()

        for img in imgs:
            src = img.get_attribute("data-src") or img.get_attribute("src") or ""
            if src.startswith("http") and "duckduckgo" not in src:
                return src
        return None
    except Exception:
        logger.exception("Product image fetch failed for query=%r", query)
        return None


def enrich_brief_with_images(brief_data: dict, spec: dict) -> dict:
    """Best-effort: attach a 'product_images' list to brief_data metadata.

    Fetches one image per validated product entity (up to 4). Never raises —
    any failure just leaves product_images as []. Returns brief_data mutated
    in place (brief_data is a local dict built by compose_brief, not shared).
    """
    entities = spec.get("validated_entities", []) if isinstance(spec, dict) else []
    products = [
        e.get("name", "")
        for e in entities
        if isinstance(e, dict) and e.get("type") == "product" and e.get("name")
    ][:4]

    if not products:
        brief_data.setdefault("metadata", {})["product_images"] = []
        return brief_data

    images = []
    for product_name in products:
        url = fetch_product_image_url(f"{product_name} product")
        if url:
            images.append({"product": product_name, "image_url": url})

    brief_data.setdefault("metadata", {})["product_images"] = images
    return brief_data
