"""Slide photos: licensed (Pexels) and brand-owned first, SerpAPI Google Images as fallback, then SearXNG images
when SerpAPI finds nothing on-topic; every candidate passes the same relevance check against the brief's subjects;
never the same image twice; cropped to the slide treatment. Keys come from the environment and are never logged."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path

import requests
from urllib.parse import urljoin, urlparse
from PIL import Image, ImageOps

from ...core import serp_keys
from ..assets import service as asset_store
from . import commons
from .image_brief import Subjects, queries as brief_queries, text_relevant
from .verbatims import is_public_http

logger = logging.getLogger(__name__)
TIMEOUT_S = 15
SIZES = {"background": (1920, 1080), "panel": (672, 1080)}
PEXELS_URL = "https://api.pexels.com/v1/search"
UNSPLASH_URL = "https://api.unsplash.com/search/photos"
UNSPLASH_WIDTH = 2400        # served resized from Unsplash's CDN: HD for a 1920 slide without a 6000px download
SERP_URL = "https://serpapi.com/search.json"
MAX_TRIES = 4
MAX_REDIRECTS = 3
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
CHUNK = 64 * 1024
ARTICLE_TIMEOUT_S = 10
MAX_ARTICLES = 4
MAX_VISION_CHECKS = 150
VISION_PER_SLIDE = 7          # the slide's own article images, then one look at every search source
ARTICLE_CHECKS = 2            # vision looks per source: the article images first, then each source's best match,
SOURCE_CHECKS = 1             # so a spent budget never ends the search before every source was tried
_WORD = re.compile(r"[a-z]{3,}")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


@dataclass
class Photo:
    path: Path | None
    source_url: str
    licence: str
    why: str = ""


# ─── licence policy (Instructions/image-licensing-legal-note.md) ──────────────────────────────────────────────────
# Client decks use licence-safe photos only, unless the organization turned on "editorial images" (Settings >
# Guardrails); IMAGE_SOURCE=legacy restores the earlier behaviour (article + web images allowed) as a rollback.
LICENSED = ("licensed", "brand")
OPENVERSE_URL = "https://api.openverse.org/v1/images/"
PIXABAY_URL = "https://pixabay.com/api/"
BREAKER_FAILS, BREAKER_PAUSE_S, SEARCH_CACHE_S = 3, 600, 24 * 3600
_breaker: dict[str, tuple[int, float]] = {}
_search_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def legacy_mode() -> bool:
    return os.environ.get("IMAGE_SOURCE", "multi_provider").strip().lower() == "legacy"


def editorial_allowed() -> bool:
    """Article / web-search images: only for an org that opted in (or in legacy mode). Read from the deck run's scope."""
    if legacy_mode():
        return True
    try:
        from ...core.db import _conn
        from ..exclusions.service import org_of_project
        from ..usage import service as usage
        org = org_of_project(usage.current().get("project_id") or 0)
        if not org:
            return False
        conn = _conn()
        try:
            row = conn.execute("SELECT allow_editorial_images FROM organizations WHERE id = ?", (org,)).fetchone()
        finally:
            conn.close()
        return bool(row and row[0])
    except Exception as e:
        logger.warning("editorial image setting unreadable (%s): licensed photos only", type(e).__name__)
        return False


def _guarded(name: str, search, query: str) -> list[dict]:
    """One provider search behind a 24 h (provider, query) cache and a circuit breaker: after BREAKER_FAILS failures
    in a row the provider is skipped for BREAKER_PAUSE_S. An adapter returns None on an error."""
    import time as _time
    now = _time.time()
    fails, until = _breaker.get(name, (0, 0.0))
    if until > now:
        return []
    hit = _search_cache.get((name, query))
    if hit and now - hit[0] < SEARCH_CACHE_S:
        return hit[1]
    try:
        found = search(query)
    except Exception as e:             # an adapter bug never stops the deck: the next source is tried
        logger.warning("%s image search raised: %s", name, type(e).__name__)
        found = None
    if found is None:
        fails += 1
        _breaker[name] = (fails, now + BREAKER_PAUSE_S if fails >= BREAKER_FAILS else 0.0)
        return []
    _breaker[name] = (0, 0.0)
    _search_cache[(name, query)] = (now, found)
    return found


def _stock_credit(title: str, author: str, licence: str, page: str) -> dict:
    return {"use": "credit", "name": licence, "author": author or "Unknown", "page": page, "title": title}


def _pexels(query: str) -> list[dict] | None:
    key = os.environ.get("PEXEL_API_KEY", "") or os.environ.get("PEXELS_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(PEXELS_URL, params={"query": query, "per_page": 10, "orientation": "landscape"},
                         headers={"Authorization": key}, timeout=TIMEOUT_S)
        r.raise_for_status()
        photos = r.json().get("photos") or []
        return [{"url": p["src"].get("original") or p["src"].get("large2x"), "width": p.get("width", 0),
                 "height": p.get("height", 0), "title": p.get("alt") or "",
                 "credit": _stock_credit(p.get("alt") or "Photo", f"{p.get('photographer') or ''} (Pexels)",
                                         "Pexels License", p.get("url") or "https://www.pexels.com")} for p in photos]
    except (requests.RequestException, ValueError, KeyError, AttributeError, TypeError) as e:
        logger.warning("pexels search failed: %s", type(e).__name__)
        return None


def _openverse(query: str) -> list[dict] | None:
    """Openverse (WordPress Foundation): CC-licensed and public-domain images from Wikimedia, Flickr and museums,
    filtered to licences that allow commercial use. No key needed. Each result carries its creator and licence."""
    try:
        r = requests.get(OPENVERSE_URL, params={"q": query, "license_type": "commercial", "page_size": 20,
                                                 "mature": "false", "aspect_ratio": "wide"},
                         headers={"User-Agent": "AlphaMetricx-decks/1.0"}, timeout=TIMEOUT_S)
        r.raise_for_status()
        out = []
        for i in r.json().get("results") or []:
            code = str(i.get("license") or "").lower()
            lic = {"cc0": "CC0", "pdm": "Public domain"}.get(code) or f"CC {code.upper()} {i.get('license_version') or ''}".strip()
            out.append({"url": i.get("url"), "width": i.get("width") or 0, "height": i.get("height") or 0,
                        "title": i.get("title") or "",
                        "credit": _stock_credit(i.get("title") or "Photo", i.get("creator") or "Unknown", lic,
                                                i.get("foreign_landing_url") or i.get("url") or "")})
        return out
    except (requests.RequestException, ValueError, KeyError, AttributeError, TypeError) as e:
        logger.warning("openverse search failed: %s", type(e).__name__)
        return None


def _pixabay(query: str) -> list[dict] | None:
    """Pixabay (PIXABAY_API_KEY): free for commercial use under the Pixabay Content License; images must be
    downloaded (not hot-linked), which the deck does anyway."""
    key = os.environ.get("PIXABAY_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(PIXABAY_URL, params={"key": key, "q": query[:100], "image_type": "photo",
                                              "orientation": "horizontal", "safesearch": "true", "per_page": 20},
                         timeout=TIMEOUT_S)
        r.raise_for_status()
        return [{"url": h.get("largeImageURL"), "width": h.get("imageWidth") or 0, "height": h.get("imageHeight") or 0,
                 "title": h.get("tags") or "",
                 "credit": _stock_credit(h.get("tags") or "Photo", f"{h.get('user') or ''} (Pixabay)",
                                         "Pixabay Content License", h.get("pageURL") or "https://pixabay.com")}
                for h in r.json().get("hits") or []]
    except (requests.RequestException, ValueError, KeyError, AttributeError, TypeError) as e:
        logger.warning("pixabay search failed: %s", type(e).__name__)
        return None


def _tavily_images(query: str) -> list[dict] | None:
    """Tavily search with include_images (editorial only: web images of unknown licence)."""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.post("https://api.tavily.com/search", json={"api_key": key, "query": query, "max_results": 5,
                                                                 "include_images": True,
                                                                 "include_image_descriptions": True},
                          timeout=TIMEOUT_S)
        r.raise_for_status()
        out = []
        for img in r.json().get("images") or []:
            url, desc = (img, "") if isinstance(img, str) else (img.get("url"), img.get("description") or "")
            if url:
                out.append({"url": url, "width": 0, "height": 0, "title": desc})
        return out
    except (requests.RequestException, ValueError, KeyError, AttributeError, TypeError) as e:
        logger.warning("tavily image search failed: %s", type(e).__name__)
        return None


def licensed_sources() -> list[tuple[str, object]]:
    """Licence-safe providers in order (IMAGE_LICENSED_PROVIDERS can reorder or drop them)."""
    table = {"openverse": _openverse, "pexels": _pexels, "unsplash": _unsplash, "pixabay": _pixabay}
    wanted = os.environ.get("IMAGE_LICENSED_PROVIDERS", "openverse,pexels,unsplash,pixabay").split(",")
    return [(p.strip(), table[p.strip()]) for p in wanted if p.strip() in table]


def _unsplash(query: str) -> list[dict]:
    """Licensed, high-resolution stock (UNSPLASH_ACCESS_KEY). `track` is the download ping Unsplash's API terms ask
    for when a photo is used."""
    key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(UNSPLASH_URL, params={"query": query, "per_page": 10, "orientation": "landscape"},
                         headers={"Authorization": f"Client-ID {key}"}, timeout=TIMEOUT_S)
        r.raise_for_status()
        out = []
        for p in r.json().get("results") or []:
            w, h = p.get("width") or 0, p.get("height") or 0
            scale = min(1.0, UNSPLASH_WIDTH / w) if w else 1.0
            user = p.get("user") or {}
            title = p.get("alt_description") or p.get("description") or ""
            out.append({"url": f"{p['urls']['raw']}&w={UNSPLASH_WIDTH}&fm=jpg&q=85", "width": int(w * scale),
                        "height": int(h * scale), "title": title,
                        "track": (p.get("links") or {}).get("download_location") or "",
                        "credit": _stock_credit(title or "Photo", f"Photo by {user.get('name') or 'Unknown'} on Unsplash",
                                                "Unsplash License", (p.get("links") or {}).get("html") or "https://unsplash.com")})
        return out
    except (requests.RequestException, ValueError, KeyError, AttributeError, TypeError) as e:
        logger.warning("unsplash search failed: %s", type(e).__name__)
        return []


def _track_use(cand: dict) -> None:
    if not cand.get("track"):
        return
    try:
        requests.get(cand["track"], headers={"Authorization": f"Client-ID {os.environ.get('UNSPLASH_ACCESS_KEY', '')}"},
                     timeout=TIMEOUT_S)
    except requests.RequestException:
        pass        # the ping is courtesy to Unsplash's stats; the photo is already chosen


def _serpapi(query: str) -> list[dict]:
    try:
        r = serp_keys.get(SERP_URL, {"engine": "google_images", "q": query, "safe": "active"}, TIMEOUT_S)
        if r is None:
            return []
        r.raise_for_status()
        results = r.json().get("images_results") or []
        return [{"url": i.get("original"), "width": i.get("original_width") or 0,
                 "height": i.get("original_height") or 0, "title": i.get("title") or "",
                 "page": i.get("link") or ""} for i in results if i.get("original")]
    except (requests.RequestException, ValueError, AttributeError, TypeError) as e:
        logger.warning("serpapi image search failed: %s", type(e).__name__)
        return []


_DIGITS = re.compile(r"\d+")


def _searxng_images(query: str) -> list[dict]:
    """SearXNG's image engines (self-hosted, SEARXNG_URL): when SerpAPI is out of searches or finds nothing usable.
    Its results carry the image, the page it sits on and a 'W×H' resolution."""
    base = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
    if not base:
        return []
    try:
        r = requests.get(f"{base}/search", params={"q": query, "categories": "images", "format": "json",
                                                    "language": "en", "safesearch": 1}, timeout=TIMEOUT_S)
        r.raise_for_status()
        results = r.json().get("results") or []
        logger.info("searxng image fallback: %s results for %r", len(results), query)
        out = []
        for i in results:
            if not i.get("img_src"):
                continue
            wh = [int(n) for n in _DIGITS.findall(i.get("resolution") or "")[:2]] + [0, 0]
            out.append({"url": i["img_src"], "title": i.get("title") or "", "page": i.get("url") or "",
                        "width": wh[0], "height": wh[1]})
        return out
    except (requests.RequestException, ValueError, KeyError, AttributeError, TypeError) as e:
        logger.warning("searxng image search failed: %s", type(e).__name__)
        return []


def _ddg_images(query: str) -> list[dict]:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as d:
            found = list(d.images(query, safesearch="moderate", size="Large", max_results=15))
        return [{"url": i.get("image"), "width": int(i.get("width") or 0), "height": int(i.get("height") or 0),
                 "title": i.get("title") or ""} for i in found]
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


def _download(url: str, browser: bool = True) -> bytes | None:
    """An image from a public host only (every redirect hop re-checked), at most MAX_DOWNLOAD_BYTES. `browser=False`
    takes a refusal as the answer instead of retrying through a browser."""
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
    if not browser:
        return None
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
    with Image.open(path) as src:
        w, h = SIZES[role]
        src.draft("RGB", (w * 2, h * 2))     # a JPEG decodes at reduced scale: a 24 MP photo no longer takes ~70 MB
        img = ImageOps.fit(src.convert("RGB"), SIZES[role], method=Image.LANCZOS, centering=(0.5, 0.45))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=86)
    return out


def _relevance(query: str, title: str) -> int:
    return len(set(_WORD.findall(query.lower())) & set(_WORD.findall(title.lower())))


GOOD_UPSCALE = 1.25     # a near-HD photo enlarged this much still looks sharp; run 77's blurry ones were 1.4-2x


def upscale(width: int, height: int, role: str) -> float:
    """How much the photo is enlarged to fill its slot (cover crop), in the tighter direction: a wide but short photo
    stretched to a tall panel is blurred even when its width looks ample."""
    w, h = SIZES[role]
    return max(w / max(width, 1), h / max(height, 1))


THUMB_PX = 240         # a click-through card's picture: shown about 110 px wide, sharp on a 2x screen
# Social networks sign their image links for a few days only: a deck opened later shows nothing unless it carries a copy
EXPIRING_IMAGE_HOSTS = ("fbcdn.net", "cdninstagram.com", "tiktokcdn")


def thumbnail_data_uri(url: str) -> str | None:
    """The post's picture from its export link, shrunk and inlined so the deck keeps it after the link expires;
    None when the link no longer loads (the card then shows the platform's icon)."""
    data = _download(url, browser=False)
    if not data:
        return None
    try:
        with Image.open(BytesIO(data)) as img:
            small = img.convert("RGB")
            small.thumbnail((THUMB_PX, THUMB_PX))
        out = BytesIO()
        small.save(out, "JPEG", quality=72)
    except (OSError, ValueError):       # not a picture after all
        return None
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def refit(path: Path, role: str, out: Path) -> Path | None:
    """Another slide's photo cropped again from its download for this slot, or None when that would blur it: a
    tall panel photo cannot fill a full-slide background."""
    raw = Path(path).with_suffix(".src")
    src = raw if raw.exists() else Path(path)
    with Image.open(src) as img:
        if upscale(*img.size, role) > GOOD_UPSCALE:
            return None
    return crop_to(src, role, out)


def is_hd(width: int, height: int, role: str) -> bool:
    return upscale(width, height, role) <= 1


def _maybe_usable(cand: dict, role: str) -> bool:
    """A search result that already says it is too small even for the near-HD backup is skipped before downloading
    (0 = size not given)."""
    w, h = SIZES[role]
    return not (0 < cand.get("width", 0) < w / GOOD_UPSCALE or 0 < cand.get("height", 0) < h / GOOD_UPSCALE)


UNVERIFIED = "not verified (vision budget used up)"


def _accept(data: bytes, role: str, title: str, subjects: Subjects | None, judge) -> tuple[bool, str, bool]:
    """(on-topic and sharp enough, why, HD). A near-HD photo can pass: the caller keeps it as a backup."""
    try:
        with Image.open(BytesIO(data)) as im:
            im.load()          # decodes every byte: a truncated or corrupt download is not an image
            size = (im.width, im.height)
    except Exception:
        return False, "not an image", False
    if upscale(*size, role) > GOOD_UPSCALE:
        return False, f"too small ({size[0]}x{size[1]})", False
    hd = is_hd(*size, role)
    if subjects is None:
        return True, "no subject check", hd
    verdict = judge(data) if judge else None
    if verdict is not None:
        return verdict, "vision: " + ("matches" if verdict else "off-topic"), hd
    if judge is not None:
        # vision is available but could not look (its budget is spent): a photo nobody checked against the brief's
        # product or category is not shown -- an off-topic or outdated image is worse than the brand gradient
        return False, UNVERIFIED, hd
    ok = text_relevant(title, subjects)
    return ok, "text: " + ("names the subject" if ok else "does not name the subject"), hd


DUPLICATE_BITS = 10        # dHash bits two copies of one picture (other host, size or crop) differ by at most
_HASH = "dhash:"           # a used picture's fingerprint, kept in `used` beside its URLs


def dhash(data: bytes) -> int | None:
    """64-bit difference hash of a picture: the same photo resized, recompressed or served by another host hashes
    within DUPLICATE_BITS. None when the bytes are not an image."""
    try:
        with Image.open(BytesIO(data)) as im:
            px = im.convert("L").resize((9, 8), Image.LANCZOS).tobytes()
    except Exception:
        return None
    return sum(1 << i for i, (row, col) in enumerate((r, c) for r in range(8) for c in range(8))
               if px[row * 9 + col] > px[row * 9 + col + 1])


def is_duplicate(data: bytes, used: set[str]) -> bool:
    """Whether this picture (by content, not URL) is already on another slide."""
    h = dhash(data)
    return h is not None and any(bin(h ^ int(u[len(_HASH):], 16)).count("1") <= DUPLICATE_BITS
                                 for u in list(used) if u.startswith(_HASH))   # list(): other slides add meanwhile


def mark_used(data: bytes, used: set[str]) -> None:
    h = dhash(data)
    if h is not None:
        used.add(f"{_HASH}{h:016x}")


SRC_MAX_WIDTH = 2400       # a kept original is capped to this width (HD for a 1920 slide) to keep the database small
SRC_QUALITY = 85


def photo_key(subject: str, role: str, query: str) -> str:
    """What decides a slide's picture: the brand it is about, the slide shape and the search. Shared by every project
    and organization, so the subject is part of it: a project about another brand never gets this photo."""
    return "|".join(" ".join(str(p).lower().split()) for p in (subject, role, query))


def _capped_jpeg(path: Path) -> bytes | None:
    try:
        with Image.open(path) as src:
            src.draft("RGB", (SRC_MAX_WIDTH, SRC_MAX_WIDTH))
            img = src.convert("RGB")
    except (OSError, ValueError):
        return None
    if img.width > SRC_MAX_WIDTH:
        img = img.resize((SRC_MAX_WIDTH, round(img.height * SRC_MAX_WIDTH / img.width)), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=SRC_QUALITY)
    return buf.getvalue()


def _photo_from_saved(key: str, saved: dict, folder: Path, used: set[str]) -> Photo | None:
    meta = saved["meta"]
    if meta.get("source_url") in used or is_duplicate(saved["content"], used):   # never one picture twice in a deck
        return None
    if meta.get("licence") in ("article", "web") and not editorial_allowed():
        return None             # an earlier run's web image is not reused in a licence-safe deck
    try:
        name = f"cached-{hashlib.sha1(key.encode()).hexdigest()[:16]}"
        src = asset_store.write_file(folder / f"{name}.src", saved["content"])
        out = crop_to(src, meta["role"], folder / f"{name}.jpg")
        used.add(meta["source_url"])
        mark_used(saved["content"], used)
        _write_credit(out, meta.get("credit"))
        return Photo(out, meta["source_url"], meta["licence"], f"{meta['why']} (reused from an earlier run)")
    except (OSError, ValueError, KeyError) as e:
        logger.warning("cached photo %s not usable: %s", key[:80], type(e).__name__)
        return None


def cached_photo(key: str, folder: Path, used: set[str]) -> Photo | None:
    """The photo an earlier run (of any project) chose for the same subject, slide shape and search, reused with no
    search and no vision check. None when there is none."""
    saved = asset_store.get("photo", key)
    if not saved or not saved["content"]:
        return None
    return _photo_from_saved(key, saved, folder, used)


def similar_photo(subject: str, role: str, query: str, folder: Path, used: set[str]) -> Photo | None:
    """A photo an earlier run kept for the same subject and slide role, under a near-identical search (score >= 0.9),
    reused before any web search. Never a picture this deck already shows, from any host."""
    saved = asset_store.similar("photo", f"{subject} {query}", brand=subject, role=role, min_score=0.9)
    if not saved or not saved["content"]:
        return None
    return _photo_from_saved(saved["key"], saved, folder, used)


def remember_photo(key: str, photo: Photo, role: str, subject: str = "", query: str = "") -> None:
    """Keep a found photo's original (capped) for every later run. A slide with no photo is not kept: it searches
    again."""
    if not photo.path:
        return
    raw = Path(photo.path).with_suffix(".src")
    data = _capped_jpeg(raw if raw.exists() else Path(photo.path))
    if data:
        asset_store.put("photo", key, data, "image/jpeg",
                        {"source_url": photo.source_url, "licence": photo.licence, "why": photo.why, "role": role,
                         "credit": credit_of(photo.path), "subject": subject, "brand": subject, "query": query})


def _keep(data: bytes, url: str, licence: str, why: str, role: str, folder: Path, slug: str, used: set[str],
          cand: dict | None = None) -> Photo:
    folder.mkdir(parents=True, exist_ok=True)
    # named after the picture too: slides that searched the same words used to share one file, so the last photo
    # written showed on all of them
    name = f"{slug}-{hashlib.sha1(url.encode()).hexdigest()[:8]}"
    raw = folder / f"{name}.src"
    raw.write_bytes(data)
    used.add(url)
    mark_used(data, used)
    if cand:
        _track_use(cand)
    out = crop_to(raw, role, folder / f"{name}.jpg")
    _write_credit(out, _credit_for(url, licence, cand))
    return Photo(out, url, licence, why)


def _credit_for(url: str, licence: str, cand: dict | None) -> dict | None:
    """Every deck photo is credited: the provider's photographer and licence (Pexels, Unsplash, Openverse, Pixabay),
    a Wikimedia file's author and licence, or for an editorial (article / web) image its source site."""
    if cand and cand.get("credit"):
        return cand["credit"]
    if commons.is_wikimedia(url):
        lic = commons.licence(url)
        return lic if lic.get("use") in ("credit", "free") else None
    if licence in ("article", "web"):
        host = (urlparse(cand.get("page") if cand and cand.get("page") else url).hostname or "").removeprefix("www.")
        return {"use": "credit", "name": "Editorial use — © the rights holder", "author": f"Image: {host}",
                "page": (cand or {}).get("page") or url, "title": (cand or {}).get("title") or host}
    return None


def _licence_ok(url: str) -> bool:
    """A Wikimedia photo only under a licence that allows commercial use; other hosts as before."""
    return not commons.is_wikimedia(url) or commons.licence(url)["use"] != "no"


def _public_domain(url: str) -> bool:
    return commons.is_wikimedia(url) and commons.licence(url)["use"] == "free"


def _credit_file(photo: Path) -> Path:
    return Path(photo).with_suffix(".credit.json")


def _write_credit(photo: Path, credit: dict | None) -> None:
    """The author and licence beside a photo that must be credited: the appendix lists it wherever the photo ends up."""
    if credit:
        _credit_file(photo).write_text(json.dumps(credit), encoding="utf-8")


def credit_of(photo) -> dict | None:
    try:
        return json.loads(_credit_file(photo).read_text(encoding="utf-8")) if photo else None
    except (OSError, ValueError):
        return None


def _plan(query: str, subjects: Subjects | None, article_urls) -> Iterator[tuple[str, list[dict]]]:
    """Sources in order: the slide's own articles, then per query web images (SearXNG, else DuckDuckGo, else
    SerpAPI, which has a paid quota) and licensed stock -- web first when the slide names a brand (generic stock
    would spend its vision checks first), stock first otherwise. Lazy: each search runs only when find_photo
    reaches it, so a photo accepted early skips the searches it would never have used."""
    queries = brief_queries(subjects) if subjects else [query]
    if legacy_mode():                                      # IMAGE_SOURCE=legacy: the behaviour before the licence policy
        leads = [u for u in (article_image(a) for a in list(article_urls)[:MAX_ARTICLES]) if u]
        yield "article", [{"url": u, "width": 10 ** 6, "title": "", "page": a} for u, a in zip(leads, article_urls)]
        for q in queries:
            web = (("web", search) for search in (_searxng_images, _ddg_images, _serpapi))
            stock = (("licensed", search) for search in (_pexels, _unsplash))
            for licence, search in ((*web, *stock) if subjects and subjects.brands else (*stock, *web)):
                yield licence, search(q) or []
        return
    editorial = editorial_allowed()
    if editorial:                                          # the org opted in: its own cited articles first (on-topic)
        pairs = [(a, article_image(a)) for a in list(article_urls)[:MAX_ARTICLES]]
        yield "article", [{"url": u, "width": 10 ** 6, "title": "", "page": a} for a, u in pairs if u]
    for q in queries:
        stock = [("licensed", name, search) for name, search in licensed_sources()]
        web = [("web", name, search) for name, search in (("serpapi", _serpapi), ("tavily", _tavily_images),
                                                          ("searxng", _searxng_images), ("duckduckgo", _ddg_images))]
        order = stock + web if editorial else stock       # licensed-only by default
        for licence, name, search in order:
            yield licence, _guarded(name, search, q)


def find_photo(query: str, role: str, folder: Path, used: set[str], brand_image: Path | None = None, *,
               subjects: Subjects | None = None, article_urls=(), judge=None, fallback: bool = True) -> Photo:
    """The first candidate that is HD and on-topic; failing that, the first on-topic near-HD one (at most GOOD_UPSCALE
    enlarged) met on the way; no photo rather than an off-topic or blurry one. `fallback=False` (a named product's
    shot) never widens to the category: a generic category image labelled as the product misleads."""
    slug = hashlib.sha1(f"{query}|{role}".encode()).hexdigest()[:12]
    if brand_image and brand_image.exists() and str(brand_image) not in used:
        with Image.open(brand_image) as im:
            big_enough = upscale(im.width, im.height, role) <= GOOD_UPSCALE
        if big_enough:
            used.add(str(brand_image))
            mark_used(brand_image.read_bytes(), used)
            return Photo(crop_to(brand_image, role, folder / f"{slug}.jpg"), str(brand_image), "brand", "brand imagery")
    rejected, backup, why = 0, {}, ""
    for licence, results in _plan(query, subjects, article_urls):
        # Public Domain / CC0 first; a Wikimedia photo whose licence forbids commercial use is never tried
        ranked = sorted((c for c in results if c["url"] and c["url"] not in used and _maybe_usable(c, role)
                         and _licence_ok(c["url"])),
                        key=lambda c: (not _public_domain(c["url"]), -_relevance(query, c["title"])))
        looks = ARTICLE_CHECKS if licence == "article" else SOURCE_CHECKS
        for cand in ranked[:MAX_TRIES]:
            if looks <= 0:              # this source had its look: the next source gets the budget
                break
            data = _download(cand["url"])
            if not data or is_duplicate(data, used):     # the same picture from another host is still a repeat
                continue
            title = cand["title"]
            if licence == "article" and subjects:      # routed to this slide's question: its subject by construction
                title = " ".join(subjects.brands + subjects.products + [subjects.category])
            ok, why, hd = _accept(data, role, title, subjects, judge)
            if why == UNVERIFIED:       # the slide's vision budget is spent: every later candidate fails the same way
                break
            if why.startswith("vision"):
                looks -= 1
            if not ok:
                rejected += 1
                continue
            if not hd:
                backup = backup or {"data": data, "url": cand["url"], "licence": licence, "why": why, "cand": cand}
                continue
            return _keep(data, cand["url"], licence, why, role, folder, slug, used, cand)
        if why == UNVERIFIED:
            break
    widen = fallback and why != UNVERIFIED
    found = _fallback(query, role, folder, used, subjects, judge, slug, backup) if widen else None
    if found:
        return found
    if backup and not is_duplicate(backup["data"], used):     # another slide may have taken it meanwhile
        return _keep(backup["data"], backup["url"], backup["licence"], f"{backup['why']}; near-HD (no HD photo found)",
                     role, folder, slug, used, backup["cand"])
    return Photo(None, "", "none", f"no relevant photo ({rejected} candidates rejected)")


def product_photo(brand: str, name: str, category: str, folder: Path, used: set[str], make_judge=None) -> Photo:
    """The client's product for the cover: the current model (the year and "new" steer the search away from vintage
    and earlier generations), never widened to the category. `make_judge(subjects)` gives the vision check."""
    subjects = Subjects([brand], [name], category, f"{name} product packshot")
    return find_photo(f"{brand} {name} {date.today().year} new", "panel", folder, used, subjects=subjects,
                      fallback=False, judge=make_judge(subjects) if make_judge else None)


def brand_photo(brand: str, category: str, folder: Path, used: set[str], make_judge=None) -> Photo:
    """The client's own brand in its setting (a location, a storefront, the service in use) for the cover when no brief
    product has a photo: a promotion or programme ("PERKSFEST") is not something a photo shows. Never widened to the
    category: an anonymous category scene beside the logo would pass for the brand."""
    subjects = Subjects([brand], [], category, f"{brand} {category} location".strip())
    return find_photo(f"{brand} {category}".strip(), "panel", folder, used, subjects=subjects, fallback=False,
                      judge=make_judge(subjects) if make_judge else None)


FALLBACK_TRIES = 8


def _fallback(query: str, role: str, folder: Path, used: set[str], subjects: Subjects | None, judge,
              slug: str, backup: dict) -> Photo | None:
    """No HD photo yet: a wider Google Images search at the category's level (not the slide's brands), taking each
    result's image or, when it cannot be downloaded (hot-link blocked), the lead image its page declares. A near-HD
    match fills `backup` when it is still empty."""
    loose = Subjects([], [], subjects.category, subjects.scene) if subjects else None
    terms = [f"{subjects.category} {subjects.scene}".strip(), subjects.category] if subjects else [query]
    if legacy_mode() or editorial_allowed():
        engines = [("web", _serpapi), ("web", _searxng_images)]
    else:                           # licence-safe: the wider search stays on licensed stock
        engines = [("licensed", search) for _name, search in licensed_sources()]
    searches = ((q, lic, search) for q in dict.fromkeys(t for t in terms if t) for lic, search in engines)
    for q, lic, search in searches:      # lazy: the next engine runs only when this one's results all failed
        for cand in [c for c in (search(q) or []) if _maybe_usable(c, role)][:FALLBACK_TRIES]:
            for url in (cand["url"], "page" if lic == "web" else None):
                if url is None:
                    continue
                if url == "page":
                    url = article_image(cand["page"]) if cand.get("page") else None
                if not url or url in used or not _licence_ok(url):
                    continue
                data = _download(url)
                if not data or is_duplicate(data, used):
                    continue
                ok, why, hd = _accept(data, role, cand["title"], loose, judge)
                if why == UNVERIFIED:
                    return None
                if not ok:
                    continue
                if not hd:
                    if not backup:
                        backup.update(data=data, url=url, licence=lic, why=f"wider search: {why}", cand=cand)
                    continue
                return _keep(data, url, lic, f"wider search: {why}", role, folder, slug, used, cand)
    return None
