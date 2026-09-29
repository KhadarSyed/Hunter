"""Image asset fetching for the Intelligence Brief DOCX export — brand logos, country
flags, and industry/product-matched Pexels background images, downloaded and normalized
to raster bytes that python-docx's add_picture() can embed. python-docx recognizes only
PNG/JPEG/GIF/BMP/TIFF/WMF/EMF (no SVG, no WEBP), so results are converted where needed.

Every fetch is best-effort: a network failure, missing lookup, or unsupported format
returns None rather than raising, so a slow or unreachable image source never breaks
brief rendering — callers simply skip the picture for that slot.
"""
from __future__ import annotations

import logging
from io import BytesIO

import requests
from PIL import Image

from . import brandfetch, pexels
from .web_research import _country_to_iso_code

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 10

# Brandfetch's CDN content-negotiates on Accept/User-Agent — a plain requests.get()
# (generic Accept, no browser User-Agent) gets an HTML preview page back instead of
# the logo image; a browser-shaped request gets the actual image (commonly WEBP).
_BROWSER_HEADERS = {
    "Accept": "image/webp,image/png,image/*,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# flagcdn.com serves real PNG bytes directly by ISO 3166-1 alpha-2 code — unlike
# Iconify's api.iconify.design (used for the live web UI's circle-flags), which only
# ever serves SVG and has no server-side raster rendering endpoint.
FLAG_CDN_URL = "https://flagcdn.com/w160/{code}.png"


def _download(url: str | None, headers: dict | None = None) -> bytes | None:
    if not url:
        return None
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT_S, headers=headers)
        if r.status_code == 200 and r.content:
            return r.content
    except requests.RequestException:
        logger.warning("Image download failed for %r", url, exc_info=True)
    return None


def _to_docx_compatible_png(image_bytes: bytes) -> bytes | None:
    """Pass PNG/JPEG through unchanged; convert anything else (e.g. Brandfetch's WEBP)
    to PNG, since python-docx's image scanner doesn't recognize WEBP or SVG."""
    try:
        img = Image.open(BytesIO(image_bytes))
        if img.format in ("PNG", "JPEG"):
            return image_bytes
        buf = BytesIO()
        img.convert("RGBA").save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        logger.warning("Image format conversion failed", exc_info=True)
        return None


def get_brand_logo_bytes(brand_name: str) -> bytes | None:
    """Docx-embeddable logo bytes for a brand/competitor name, or None if unavailable."""
    if not brand_name or not brand_name.strip():
        return None
    raw = _download(brandfetch.get_brand_logo_url(brand_name), headers=_BROWSER_HEADERS)
    return _to_docx_compatible_png(raw) if raw else None


def get_country_flag_bytes(country: str) -> bytes | None:
    """Docx-embeddable flag PNG for a country name or ISO code, or None if unavailable."""
    if not country or not country.strip():
        return None
    code = _country_to_iso_code(country).lower()
    return _download(FLAG_CDN_URL.format(code=code))


def get_background_image_bytes(query: str) -> bytes | None:
    """Docx-embeddable background/banner JPEG for a Pexels photo search query (e.g.
    "Tesla electric vehicle"), or None if no match / unavailable. Callers build the
    query from the brand/competitor name plus its industry category so the image
    actually matches the product, not just the company name in isolation."""
    if not query or not query.strip():
        return None
    result = pexels.resolve_background_image(query)
    return _download(result.get("image_url"))
