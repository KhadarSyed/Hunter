"""Pexels background image resolution — dynamic, brand-related header imagery.

Lookup order for a query (typically a brand/project name):
  1. pexels_images table — every lookup is cached and served first
  2. Pexels Search API (PEXEL_API_KEY): first landscape-orientation photo result

Definite outcomes are saved, including "not found" (retried after NOT_FOUND_RETRY_S).
Transient failures (timeouts, 5xx, rate limits) are NOT saved, so a slow API never
blocks a query — mirrors domains/research/brandfetch.py's caching contract.

Pexels Search API (developers.pexels.com/docs/#photos-search, 2026-09):
`GET https://api.pexels.com/v1/search?query={q}&per_page=1&orientation=landscape`
header `Authorization: {PEXEL_API_KEY}` → `{photos: [{src: {landscape, large2x, ...},
photographer, url}]}`.

PEXEL_API_KEY is a secret: never log, cache, or return it.
"""
from __future__ import annotations

import logging
import os
import time

import requests

from . import repository

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://api.pexels.com/v1/search"
REQUEST_TIMEOUT_S = 10
NOT_FOUND_RETRY_S = 7 * 86_400  # re-check queries with no image after a week


class LookupUnavailable(RuntimeError):
    """Pexels could not answer right now (timeout, 5xx, rate limit) — don't cache."""


def _env(name: str) -> str:
    return (os.getenv(name) or "").split("#")[0].strip().strip('"')


def is_reachable() -> bool:
    return bool(_env("PEXEL_API_KEY"))


def normalize_query(text: str) -> str:
    return " ".join(text.lower().split())


def resolve_background_image(query: str) -> dict:
    """{query, image_url, photographer, source_url, cached}: saved table first, then
    Pexels. Blocking (network) — call from a worker thread or FastAPI's threadpool."""
    text = query.strip()
    key = normalize_query(text)
    result = {"query": text, "image_url": None, "photographer": None, "source_url": None, "cached": False}
    if not key:
        return result

    saved = repository.get_pexels_image(key)
    if saved and (saved["image_url"] or time.time() - saved["fetched_at"] < NOT_FOUND_RETRY_S):
        return {**result, "image_url": saved["image_url"], "photographer": saved["photographer"],
                "source_url": saved["source_url"], "cached": True}

    if not is_reachable():
        return result

    try:
        r = requests.get(
            SEARCH_API_URL, timeout=REQUEST_TIMEOUT_S,
            headers={"Authorization": _env("PEXEL_API_KEY")},
            params={"query": text, "per_page": 1, "orientation": "landscape"},
        )
    except requests.RequestException as e:
        raise LookupUnavailable(type(e).__name__) from e
    if r.status_code == 429 or r.status_code >= 500:
        raise LookupUnavailable(f"HTTP {r.status_code}")
    if r.status_code != 200:
        logger.warning("Pexels search failed for %r: HTTP %s", text, r.status_code)
        repository.save_pexels_image(key, text, None, None, None)
        return result

    try:
        photos = r.json().get("photos") or []
    except ValueError:
        return result

    if photos:
        photo = photos[0]
        src = photo.get("src") or {}
        result.update(
            image_url=src.get("landscape") or src.get("large2x") or src.get("large"),
            photographer=photo.get("photographer"),
            source_url=photo.get("url"),
        )

    repository.save_pexels_image(key, text, result["image_url"], result["photographer"], result["source_url"])
    return result
