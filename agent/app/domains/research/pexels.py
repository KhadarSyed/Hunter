"""Pexels background media resolution — dynamic, brand-related header imagery/video.

Lookup order for a query (typically a brand/project name):
  1. pexels_images table — every lookup is cached and served first
  2. Pexels Video Search API (PEXEL_API_KEY): first landscape-orientation video result
  3. Falls back to Pexels Photo Search API when no video result exists

Definite outcomes are saved, including "not found" (retried after NOT_FOUND_RETRY_S).
Transient failures (timeouts, 5xx, rate limits) are NOT saved, so a slow API never
blocks a query — mirrors domains/research/brandfetch.py's caching contract.

Pexels Photo Search API (developers.pexels.com/docs/#photos-search, 2026-09):
`GET https://api.pexels.com/v1/search?query={q}&per_page=1&orientation=landscape`
header `Authorization: {PEXEL_API_KEY}` → `{photos: [{src: {landscape, large2x, ...},
photographer, url}]}`.

Pexels Video Search API (developers.pexels.com/docs/#videos-search, 2026-09):
`GET https://api.pexels.com/videos/search?query={q}&per_page=1&orientation=landscape`
header `Authorization: {PEXEL_API_KEY}` → `{videos: [{image: <poster url>,
video_files: [{link, quality, file_type}], user: {name}, url}]}`. Picks the "sd"
quality mp4 file when available (keeps a looping header background lightweight),
falling back to "hd", then the first file present.

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
VIDEO_SEARCH_API_URL = "https://api.pexels.com/videos/search"
REQUEST_TIMEOUT_S = 10
NOT_FOUND_RETRY_S = 7 * 86_400  # re-check queries with no image after a week
_VIDEO_QUALITY_PREFERENCE = ("sd", "hd")


class LookupUnavailable(RuntimeError):
    """Pexels could not answer right now (timeout, 5xx, rate limit) — don't cache."""


def _env(name: str) -> str:
    return (os.getenv(name) or "").split("#")[0].strip().strip('"')


def is_reachable() -> bool:
    return bool(_env("PEXEL_API_KEY"))


def normalize_query(text: str) -> str:
    return " ".join(text.lower().split())


def _select_video_file(video_files: list[dict]) -> dict | None:
    """Prefer "sd" quality mp4 (lightweight, loops fine as a header background),
    then "hd", then whatever file is present."""
    if not video_files:
        return None
    mp4_files = [f for f in video_files if f.get("file_type") == "video/mp4"] or video_files
    for quality in _VIDEO_QUALITY_PREFERENCE:
        for f in mp4_files:
            if f.get("quality") == quality:
                return f
    return mp4_files[0]


def _search_photo(text: str) -> dict:
    """{image_url, photographer, source_url}, all None on no-match or a non-retryable
    HTTP error. Raises LookupUnavailable on timeouts, 5xx, or rate limiting."""
    empty = {"image_url": None, "photographer": None, "source_url": None}
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
        logger.warning("Pexels photo search failed for %r: HTTP %s", text, r.status_code)
        return empty

    try:
        photos = r.json().get("photos") or []
    except ValueError:
        return empty
    if not photos:
        return empty

    photo = photos[0]
    src = photo.get("src") or {}
    return {
        "image_url": src.get("landscape") or src.get("large2x") or src.get("large"),
        "photographer": photo.get("photographer"),
        "source_url": photo.get("url"),
    }


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

    photo = _search_photo(text)
    result.update(photo)
    repository.save_pexels_image(key, text, result["image_url"], result["photographer"], result["source_url"])
    return result


def resolve_background_video(query: str) -> dict:
    """{query, video_url, image_url, photographer, source_url, cached}: saved table
    first, then the Pexels Video Search API, falling back to the Photo Search API
    (via _search_photo) when no video result exists. Blocking (network) — call from
    a worker thread or FastAPI's threadpool."""
    text = query.strip()
    key = normalize_query(text)
    result = {"query": text, "video_url": None, "image_url": None, "photographer": None,
              "source_url": None, "cached": False}
    if not key:
        return result

    saved = repository.get_pexels_image(key)
    if saved and (saved["video_url"] or saved["image_url"] or time.time() - saved["fetched_at"] < NOT_FOUND_RETRY_S):
        return {**result, "video_url": saved["video_url"], "image_url": saved["image_url"],
                "photographer": saved["photographer"], "source_url": saved["source_url"], "cached": True}

    if not is_reachable():
        return result

    try:
        r = requests.get(
            VIDEO_SEARCH_API_URL, timeout=REQUEST_TIMEOUT_S,
            headers={"Authorization": _env("PEXEL_API_KEY")},
            params={"query": text, "per_page": 1, "orientation": "landscape"},
        )
    except requests.RequestException as e:
        raise LookupUnavailable(type(e).__name__) from e
    if r.status_code == 429 or r.status_code >= 500:
        raise LookupUnavailable(f"HTTP {r.status_code}")

    videos = []
    if r.status_code == 200:
        try:
            videos = r.json().get("videos") or []
        except ValueError:
            videos = []
    else:
        logger.warning("Pexels video search failed for %r: HTTP %s", text, r.status_code)

    if videos:
        video = videos[0]
        chosen = _select_video_file(video.get("video_files") or [])
        if chosen:
            result.update(
                video_url=chosen.get("link"),
                image_url=video.get("image"),
                photographer=(video.get("user") or {}).get("name"),
                source_url=video.get("url"),
            )

    if not result["video_url"]:
        photo = _search_photo(text)
        result.update(image_url=photo["image_url"], photographer=photo["photographer"],
                      source_url=photo["source_url"])

    repository.save_pexels_image(
        key, text, result["image_url"], result["photographer"], result["source_url"],
        video_url=result["video_url"],
    )
    return result
