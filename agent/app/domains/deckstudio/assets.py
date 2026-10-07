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
from urllib.parse import urljoin
from PIL import Image, ImageOps

from ...core import serp_keys
from .image_brief import Subjects, queries as brief_queries, text_relevant
from .verbatims import is_public_http

logger = logging.getLogger(__name__)
TIMEOUT_S = 15
MIN_WIDTH = {"background": 1600, "panel": 900}
SIZES = {"background": (1920, 1080), "panel": (672, 1080)}
PEXELS_URL = "https://api.pexels.com/v1/search"
SERP_URL = "https://serpapi.com/search.json"
MAX_TRIES = 4
MAX_REDIRECTS = 3
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
CHUNK = 64 * 1024
ARTICLE_TIMEOUT_S = 10
MAX_ARTICLES = 4
MAX_VISION_CHECKS = 150
VISION_PER_SLIDE = 6
_WORD = re.compile(r"[a-z]{3,}")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


@dataclass
class Photo:
    path: Path | None
    source_url: str
    licence: str
    why: str = ""


def _pexels(query: str) -> list[dict]:
    key = os.environ.get("PEXEL_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(PEXELS_URL, params={"query": query, "per_page": 10, "orientation": "landscape"},
                         headers={"Authorization": key}, timeout=TIMEOUT_S)
        r.raise_for_status()
        photos = r.json().get("photos") or []
        return [{"url": p["src"].get("original") or p["src"].get("large2x"), "width": p.get("width", 0),
                 "title": p.get("alt") or ""} for p in photos]
    except (requests.RequestException, ValueError, KeyError, AttributeError, TypeError) as e:
        logger.warning("pexels search failed: %s", type(e).__name__)
        return []


def _serpapi(query: str) -> list[dict]:
    try:
        r = serp_keys.get(SERP_URL, {"engine": "google_images", "q": query, "safe": "active"}, TIMEOUT_S)
        if r is None:
            return []
        r.raise_for_status()
        results = r.json().get("images_results") or []
        return [{"url": i.get("original"), "width": i.get("original_width") or 0, "title": i.get("title") or ""}
                for i in results if i.get("original")]
    except (requests.RequestException, ValueError, AttributeError, TypeError) as e:
        logger.warning("serpapi image search failed: %s", type(e).__name__)
        return []


def _ddg_images(query: str) -> list[dict]:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as d:
            found = list(d.images(query, safesearch="moderate", size="Large", max_results=15))
        return [{"url": i.get("image"), "width": int(i.get("width") or 0), "title": i.get("title") or ""} for i in found]
    except Exception as e:      # rate limits and network errors: the next source is tried
        logger.warning("duckduckgo image search failed: %s", type(e).__name__)
        return []


_OG = re.compile(r"""<meta[^>]+(?:property|name)=["'](?:og:image|twitter:image)["'][^>]+content=["']([^"']+)""", re.I)


def article_image(url: str) -> str | None:
    """The lead image an article declares for sharing: on-topic by construction."""
    try:
        for _ in range(MAX_REDIRECTS + 1):         # each hop is checked: a public page may redirect into the network
            if not is_public_http(url):
                return None
            r = requests.get(url, timeout=ARTICLE_TIMEOUT_S, headers=UA, allow_redirects=False)
            if 300 <= r.status_code < 400 and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                return None
            m = _OG.search(r.text[:200000])
            found = m.group(1) if m else None
            return found if found and is_public_http(found) else None
    except requests.RequestException:
        return None
    return None


def _read_capped(r) -> bytes | None:
    data = bytearray()
    for chunk in r.iter_content(CHUNK):
        data.extend(chunk)
        if len(data) > MAX_DOWNLOAD_BYTES:
            return None
    return bytes(data)


class _TooBig(Exception):
    pass


def _download(url: str) -> bytes | None:
    """An image from a public host only (every redirect hop re-checked), at most MAX_DOWNLOAD_BYTES."""
    start = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not is_public_http(url):
                return None
            r = requests.get(url, headers=UA, timeout=TIMEOUT_S, stream=True, allow_redirects=False)
            try:
                if 300 <= r.status_code < 400 and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code == 200 and r.headers.get("content-type", "image/").startswith("image/"):
                    data = _read_capped(r)
                    if data is None:
                        raise _TooBig()
                    return data
                break
            finally:
                r.close()
    except _TooBig:
        return None
    except requests.RequestException:
        pass
    try:      # some sites refuse plain requests; Scrapling fetches like a browser
        return _scrapling_download(start)
    except Exception as e:
        logger.warning("image download failed: %s", type(e).__name__)
        return None


def _scrapling_download(url: str) -> bytes | None:
    """The browser-like fallback, with redirects walked one hop at a time so a private host is never requested."""
    from scrapling.fetchers import Fetcher
    for _ in range(MAX_REDIRECTS + 1):
        if not is_public_http(url):
            return None
        page = Fetcher.get(url, timeout=TIMEOUT_S, follow_redirects=False)
        status = getattr(page, "status", 0)
        headers = getattr(page, "headers", None) or {}
        location = headers.get("location") or headers.get("Location")
        if 300 <= status < 400 and location:
            url = urljoin(url, location)
            continue
        body = page.body if status == 200 else None
        return body if body and len(body) <= MAX_DOWNLOAD_BYTES else None
    return None


def crop_to(path: Path, role: str, out: Path) -> Path:
    img = ImageOps.fit(Image.open(path).convert("RGB"), SIZES[role], method=Image.LANCZOS, centering=(0.5, 0.45))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=86)
    return out


def _relevance(query: str, title: str) -> int:
    return len(set(_WORD.findall(query.lower())) & set(_WORD.findall(title.lower())))


def _accept(data: bytes, role: str, title: str, subjects: Subjects | None, judge) -> tuple[bool, str]:
    try:
        with Image.open(BytesIO(data)) as im:
            if im.width < MIN_WIDTH[role]:
                return False, "too small"
    except Exception:
        return False, "not an image"
    if subjects is None:
        return True, "no subject check"
    verdict = judge(data) if judge else None
    if verdict is not None:
        return verdict, "vision: " + ("matches" if verdict else "off-topic")
    ok = text_relevant(title, subjects)
    return ok, "text: " + ("names the subject" if ok else "does not name the subject")


def _plan(query: str, subjects: Subjects | None, article_urls) -> list[tuple[str, list[dict]]]:
    """Sources in order: the slide's own articles, then per query brand/product shots, licensed stock, Google."""
    leads = [u for u in (article_image(a) for a in list(article_urls)[:MAX_ARTICLES]) if u]
    plan = [("article", [{"url": u, "width": 10 ** 6, "title": ""} for u in leads])]
    for q in (brief_queries(subjects) if subjects else [query]):
        brand_shots = _ddg_images(q) if subjects and subjects.brands else []
        plan += [("web", brand_shots), ("licensed", _pexels(q)), ("web", _serpapi(q))]
    return plan


def find_photo(query: str, role: str, folder: Path, used: set[str], brand_image: Path | None = None, *,
               subjects: Subjects | None = None, article_urls=(), judge=None) -> Photo:
    """The first candidate that is big enough and on-topic; no photo rather than an off-topic one."""
    slug = hashlib.sha1(f"{query}|{role}".encode()).hexdigest()[:12]
    if brand_image and brand_image.exists() and str(brand_image) not in used:
        with Image.open(brand_image) as im:
            wide_enough = im.width >= MIN_WIDTH[role]
        if wide_enough:
            used.add(str(brand_image))
            return Photo(crop_to(brand_image, role, folder / f"{slug}.jpg"), str(brand_image), "brand", "brand imagery")
    rejected = 0
    for licence, results in _plan(query, subjects, article_urls):
        ranked = sorted((c for c in results if c["url"] and c["url"] not in used),
                        key=lambda c: -_relevance(query, c["title"]))
        for cand in ranked[:MAX_TRIES]:
            data = _download(cand["url"])
            if not data:
                continue
            title = cand["title"]
            if licence == "article" and subjects:      # routed to this slide's question: its subject by construction
                title = " ".join(subjects.brands + subjects.products + [subjects.category])
            ok, why = _accept(data, role, title, subjects, judge)
            if not ok:
                rejected += 1
                continue
            folder.mkdir(parents=True, exist_ok=True)
            raw = folder / f"{slug}.src"
            raw.write_bytes(data)
            used.add(cand["url"])
            return Photo(crop_to(raw, role, folder / f"{slug}.jpg"), cand["url"], licence, why)
    return Photo(None, "", "none", f"no relevant photo ({rejected} candidates rejected)")
