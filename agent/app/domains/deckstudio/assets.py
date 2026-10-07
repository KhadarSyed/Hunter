"""Slide photos: licensed (Pexels) and brand-owned first, SerpAPI Google Images as fallback; never the same
image twice; cropped to the slide treatment. Keys come from the environment and are never logged."""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)
TIMEOUT_S = 15
MIN_WIDTH = {"background": 1600, "panel": 900}
SIZES = {"background": (1920, 1080), "panel": (672, 1080)}
PEXELS_URL = "https://api.pexels.com/v1/search"
SERP_URL = "https://serpapi.com/search.json"
MAX_TRIES = 4
_WORD = re.compile(r"[a-z]{3,}")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


@dataclass
class Photo:
    path: Path | None
    source_url: str
    licence: str


def _pexels(query: str) -> list[dict]:
    key = os.environ.get("PEXEL_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(PEXELS_URL, params={"query": query, "per_page": 10, "orientation": "landscape"},
                         headers={"Authorization": key}, timeout=TIMEOUT_S)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning("pexels search failed: %s", type(e).__name__)
        return []
    return [{"url": p["src"].get("original") or p["src"].get("large2x"), "width": p.get("width", 0), "title": p.get("alt") or ""}
            for p in r.json().get("photos") or []]


def _serpapi(query: str) -> list[dict]:
    key = os.environ.get("SERP_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(SERP_URL, params={"engine": "google_images", "q": query, "api_key": key, "safe": "active"},
                         timeout=TIMEOUT_S)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning("serpapi image search failed: %s", type(e).__name__)
        return []
    return [{"url": i.get("original"), "width": i.get("original_width") or 0, "title": i.get("title") or ""}
            for i in r.json().get("images_results") or [] if i.get("original")]


def _download(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT_S)
        if r.ok and r.headers.get("content-type", "image/").startswith("image/"):
            return r.content
    except requests.RequestException:
        pass
    try:      # some sites refuse plain requests; Scrapling fetches like a browser
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=TIMEOUT_S)
        return page.body if getattr(page, "status", 0) == 200 else None
    except Exception as e:
        logger.warning("image download failed: %s", type(e).__name__)
        return None


def crop_to(path: Path, role: str, out: Path) -> Path:
    img = ImageOps.fit(Image.open(path).convert("RGB"), SIZES[role], method=Image.LANCZOS, centering=(0.5, 0.45))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=86)
    return out


def _relevance(query: str, title: str) -> int:
    return len(set(_WORD.findall(query.lower())) & set(_WORD.findall(title.lower())))


def find_photo(query: str, role: str, folder: Path, used: set[str], brand_image: Path | None = None) -> Photo:
    slug = hashlib.sha1(f"{query}|{role}".encode()).hexdigest()[:12]
    if brand_image and brand_image.exists() and str(brand_image) not in used:
        with Image.open(brand_image) as im:
            wide_enough = im.width >= MIN_WIDTH[role]
        if wide_enough:
            used.add(str(brand_image))
            return Photo(crop_to(brand_image, role, folder / f"{slug}.jpg"), str(brand_image), "brand")
    for licence, results in (("licensed", _pexels(query)), ("web", _serpapi(query))):
        ranked = sorted((c for c in results if c["url"] and c["url"] not in used and c["width"] >= MIN_WIDTH[role]),
                        key=lambda c: -_relevance(query, c["title"]))
        for cand in ranked[:MAX_TRIES]:
            data = _download(cand["url"])
            if not data:
                continue
            try:
                with Image.open(BytesIO(data)) as im:
                    if im.width < MIN_WIDTH[role]:
                        continue
            except Exception:
                continue
            folder.mkdir(parents=True, exist_ok=True)
            raw = folder / f"{slug}.src"
            raw.write_bytes(data)
            used.add(cand["url"])
            return Photo(crop_to(raw, role, folder / f"{slug}.jpg"), cand["url"], licence)
    return Photo(None, "", "none")
