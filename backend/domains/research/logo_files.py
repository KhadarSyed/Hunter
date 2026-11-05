"""Brand logos served from this app, not hotlinked: Brandfetch's CDN now redirects hotlinked images (and every
headless browser) to its guidelines page, which left the pages showing letter monograms. Each logo is fetched once
server-side, cached on disk and in the shared asset table (every organization reuses it), and served by /api/intel/brandfetch/logo/image; a white logo is flagged so the page
sets it on a dark chip."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from pathlib import Path
from urllib.parse import urljoin

import requests
from PIL import Image, UnidentifiedImageError

from ...core import config
from ..assets import service as assets
from ..deckstudio.logo_prep import is_light
from ..deckstudio.verbatims import is_public_http
from . import brandfetch as brandfetch_client

logger = logging.getLogger(__name__)

CACHE_DIR = config.DATA_DIR / "brand_logos"
CDN = "https://cdn.brandfetch.io"
TIMEOUT_S = 20
MAX_BYTES = 3_000_000
MAX_REDIRECTS = 3
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36", "Accept": "image/png,image/*"}
# Brandfetch answers a brand it does not know with a WEBP placeholder: from its CDN only a PNG is trusted
_IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")


def _paths(brand_name: str) -> tuple[Path, Path]:
    key = hashlib.sha1(brandfetch_client.normalize_brand(brand_name).encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"{key}.png", CACHE_DIR / f"{key}.json"


def _candidates(info: dict) -> list[str]:
    client = os.environ.get("BRANDFETCH_CLIENT_ID", "")
    domain = info.get("domain")
    # icon first: it is what the plain CDN URL served before logos were cached here, and a brand's "logo" asset can
    # belong to a sister brand (band-aid.com's "logo" is Neosporin's wordmark)
    cdn = [f"{CDN}/{domain}/w/400/h/400/{kind}.png?c={client}" for kind in ("icon", "logo")] if domain else []
    return cdn + ([info["logo_url"]] if info.get("logo_url") else [])


def _download(url: str) -> tuple[str, bytes] | None:
    """(content type, bytes) of an image at a public address; every redirect hop is checked too."""
    for _hop in range(MAX_REDIRECTS + 1):
        if not is_public_http(url):
            return None
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S, allow_redirects=False, stream=True)
        if r.is_redirect:
            url = urljoin(url, r.headers.get("location", ""))
            continue
        ctype = r.headers.get("content-type", "").split(";")[0].strip()
        data = r.raw.read(MAX_BYTES + 1, decode_content=True)
        return (ctype, data) if r.ok and len(data) <= MAX_BYTES else None
    return None


def _png(data: bytes) -> tuple[bytes, Image.Image] | None:
    """Any raster image as PNG bytes (and the image); None when it is not an image."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        return None
    img = img.convert("RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), img


def public_logo(brand_name: str, image_path: str) -> dict:
    """The brand's logo for the page: the cached PNG served by this app (image_path is its route), else a direct
    non-Brandfetch URL (an SVG from Google cannot become a PNG), else none. Brandfetch's CDN refuses hotlinks."""
    info = brandfetch_client.resolve_logo(brand_name)
    found = logo_file(brand_name)
    if found:
        return {**info, "logo_url": image_path, "is_light": found[1]}
    direct = info.get("logo_url") or ""
    hotlinkable = direct.startswith("https://") and not direct.startswith(CDN)
    return {**info, "logo_url": direct if hotlinkable else None, "is_light": False}


def _fetch(brand_name: str) -> tuple[bytes, str, dict] | None:
    """The brand's logo as PNG from its first usable candidate; None when every candidate answered and none was a
    logo (Brandfetch's placeholder WEBP included). Raises when a candidate could not be asked, so a network blip is
    never remembered as "no logo"."""
    failed: requests.RequestException | None = None
    for url in _candidates(brandfetch_client.resolve_logo(brand_name)):
        try:
            got = _download(url)
        except requests.RequestException as e:
            logger.info("logo download failed for %s: %s", brand_name, type(e).__name__)
            failed = e
            continue
        if not got:
            continue
        ctype, data = got
        if ctype not in _IMAGE_TYPES or (url.startswith(CDN) and ctype != "image/png"):
            continue
        png = _png(data)
        if png is None:
            continue
        return png[0], "image/png", {"brand": brand_name, "source": url.split("?")[0], "light": is_light(png[1])}
    if failed:
        raise failed
    return None


def logo_file(brand_name: str) -> tuple[Path, bool] | None:
    """(the cached PNG, white?) for a brand: this server's file, else the shared asset table, else fetched once (and
    saved to both); None when no usable logo exists."""
    png, meta = _paths(brand_name)
    if png.exists() and meta.exists():
        saved = json.loads(meta.read_text("utf-8"))
        source = saved.get("source") or ""
        # a Google image cached under the older, looser match rule is fetched again, not served
        if source.startswith(CDN) or brandfetch_client.is_plausible_logo(brand_name, source):
            return png, bool(saved.get("light"))
    key = brandfetch_client.normalize_brand(brand_name)
    if not key:
        return None
    got = assets.lookup("logo", key, lambda: _fetch(brand_name))
    if not got:
        return None
    data, info = got
    assets.write_file(png, data)
    meta.write_text(json.dumps(info), "utf-8")
    return png, bool(info.get("light"))
