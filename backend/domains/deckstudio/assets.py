"""Slide photos: licensed (Pexels) and brand-owned first, SerpAPI Google Images as fallback, then SearXNG images
when SerpAPI finds nothing on-topic; every candidate passes the same relevance check against the brief's subjects;
never the same image twice; cropped to the slide treatment. Keys come from the environment and are never logged."""
from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
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
                 "height": p.get("height", 0), "title": p.get("alt") or ""} for p in photos]
    except (requests.RequestException, ValueError, KeyError, AttributeError, TypeError) as e:
        logger.warning("pexels search failed: %s", type(e).__name__)
        return []


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
            out.append({"url": f"{p['urls']['raw']}&w={UNSPLASH_WIDTH}&fm=jpg&q=85", "width": int(w * scale),
                        "height": int(h * scale), "title": p.get("alt_description") or p.get("description") or "",
                        "track": (p.get("links") or {}).get("download_location") or ""})
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
    return Photo(crop_to(raw, role, folder / f"{name}.jpg"), url, licence, why)


def _plan(query: str, subjects: Subjects | None, article_urls) -> Iterator[tuple[str, list[dict]]]:
    """Sources in order: the slide's own articles, then per query web images (SearXNG, else DuckDuckGo, else
    SerpAPI, which has a paid quota) and licensed stock -- web first when the slide names a brand (generic stock
    would spend its vision checks first), stock first otherwise. Lazy: each search runs only when find_photo
    reaches it, so a photo accepted early skips the searches it would never have used."""
    leads = [u for u in (article_image(a) for a in list(article_urls)[:MAX_ARTICLES]) if u]
    yield "article", [{"url": u, "width": 10 ** 6, "title": ""} for u in leads]
    for q in (brief_queries(subjects) if subjects else [query]):
        web = (("web", search) for search in (_searxng_images, _ddg_images, _serpapi))
        stock = (("licensed", search) for search in (_pexels, _unsplash))
        for licence, search in ((*web, *stock) if subjects and subjects.brands else (*stock, *web)):
            yield licence, search(q)


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
        ranked = sorted((c for c in results if c["url"] and c["url"] not in used and _maybe_usable(c, role)),
                        key=lambda c: -_relevance(query, c["title"]))
        for cand in ranked[:MAX_TRIES]:
            data = _download(cand["url"])
            if not data or is_duplicate(data, used):     # the same picture from another host is still a repeat
                continue
            title = cand["title"]
            if licence == "article" and subjects:      # routed to this slide's question: its subject by construction
                title = " ".join(subjects.brands + subjects.products + [subjects.category])
            ok, why, hd = _accept(data, role, title, subjects, judge)
            if why == UNVERIFIED:       # the slide's vision budget is spent: every later candidate fails the same way
                break
            if not ok:
                rejected += 1
                continue
            if not hd:
                backup = backup or {"data": data, "url": cand["url"], "licence": licence, "why": why, "cand": cand}
                continue
            return _keep(data, cand["url"], licence, why, role, folder, slug, used, cand)
        else:
            continue
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
    searches = ((q, search) for q in dict.fromkeys(t for t in terms if t) for search in (_serpapi, _searxng_images))
    for q, search in searches:      # lazy: SearXNG runs only when SerpAPI's results for this term all failed
        for cand in [c for c in search(q) if _maybe_usable(c, role)][:FALLBACK_TRIES]:
            for url in (cand["url"], "page"):
                if url == "page":
                    url = article_image(cand["page"]) if cand.get("page") else None
                if not url or url in used:
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
                        backup.update(data=data, url=url, licence="web", why=f"wider search: {why}", cand=None)
                    continue
                return _keep(data, url, "web", f"wider search: {why}", role, folder, slug, used)
    return None
