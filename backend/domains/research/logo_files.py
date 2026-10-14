"""Brand logos served from this app, not hotlinked: Brandfetch's CDN now redirects hotlinked images (and every
headless browser) to its guidelines page, which left the pages showing letter monograms. Each logo is fetched once
server-side, cached on disk, and served by /api/intel/brandfetch/logo/image; a white logo is flagged so the page
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


def _save_png(data: bytes, path: Path) -> Image.Image | None:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        return None
    img = img.convert("RGBA")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return img


def logo_file(brand_name: str) -> tuple[Path, bool] | None:
    """(the cached PNG, white?) for a brand, fetched once; None when no usable logo exists."""
    png, meta = _paths(brand_name)
    if png.exists() and meta.exists():
        return png, bool(json.loads(meta.read_text("utf-8")).get("light"))
    info = brandfetch_client.resolve_logo(brand_name)
    for url in _candidates(info):
        try:
            got = _download(url)
        except requests.RequestException as e:
            logger.info("logo download failed for %s: %s", brand_name, type(e).__name__)
            continue
        if not got:
            continue
        ctype, data = got
        if ctype not in _IMAGE_TYPES or (url.startswith(CDN) and ctype != "image/png"):
            continue
        img = _save_png(data, png)
        if img is None:
            continue
        light = is_light(img)
        meta.write_text(json.dumps({"brand": brand_name, "source": url.split("?")[0], "light": light}), "utf-8")
        return png, light
    return None
