"""Image asset fetching for the Intelligence Brief DOCX export — brand logos, country
flags, and industry/product-matched Pexels background images, downloaded and normalized
to raster bytes that python-docx's add_picture() can embed (logos come as PNG from logo_files).

Every fetch is best-effort: a network failure, missing lookup, or unsupported format
returns None rather than raising, so a slow or unreachable image source never breaks
brief rendering — callers simply skip the picture for that slot.
"""
from __future__ import annotations

import logging

import requests

from ..assets import service as assets
from . import logo_files, pexels
from .web_research import _country_to_iso_code

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 10

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


def get_brand_logo_bytes(brand_name: str) -> bytes | None:
    """Docx-embeddable logo bytes (PNG) for a brand/competitor name, or None if unavailable: the same cached logo the
    decks use (shared asset table, public-address checks, Brandfetch's placeholder refused)."""
    if not brand_name or not brand_name.strip():
        return None
    found = logo_files.logo_file(brand_name)
    return found[0].read_bytes() if found else None


def get_country_flag_bytes(country: str) -> bytes | None:
    """Docx-embeddable flag PNG for a country name or ISO code, or None if unavailable (shared asset table first)."""
    if not country or not country.strip():
        return None
    code = _country_to_iso_code(country).lower()
    url = FLAG_CDN_URL.format(code=code)

    def fetch():
        r = requests.get(url, timeout=REQUEST_TIMEOUT_S)
        if r.status_code >= 500:            # the CDN is down: not remembered as "no flag"
            r.raise_for_status()
        return (r.content, "image/png", {"source": url}) if r.status_code == 200 and r.content else None
    got = assets.lookup("flag", f"flagcdn/{code}", fetch)
    return got[0] if got else None


def get_background_image_bytes(query: str) -> bytes | None:
    """Docx-embeddable background/banner JPEG for a Pexels photo search query (e.g.
    "Tesla electric vehicle"), or None if no match / unavailable. Callers build the
    query from the brand/competitor name plus its industry category so the image
    actually matches the product, not just the company name in isolation."""
    if not query or not query.strip():
        return None
    result = pexels.resolve_background_image(query)
    return _download(result.get("image_url"))
