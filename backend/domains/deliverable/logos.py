"""Brand logos as PNG files for the decks: the Brandfetch PNG URL, a check that the answer is a real logo, and
normalising any raster image to PNG (python-pptx cannot embed webp/svg). Used by brand_kit, visuals and the
reference-deck CLI."""
from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image, UnidentifiedImageError

LOGO_TIMEOUT_S = 20
# Brandfetch's CDN serves an HTML page to non-browser clients; a browser UA gets the image.
LOGO_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept": "image/png,image/*"}


def logo_png_url(info: dict) -> str | None:
    """PowerPoint can't embed webp/svg; ask Brandfetch's CDN for a PNG explicitly."""
    if info.get("source") == "brandfetch" and info.get("domain"):
        return f"https://cdn.brandfetch.io/{info['domain']}/w/400/h/400/logo.png?c={os.environ.get('BRANDFETCH_CLIENT_ID', '')}"
    return info.get("logo_url")


def is_real_logo(content_type: str) -> bool:
    """We request logo.png; Brandfetch answers unknown brands with a WEBP placeholder instead."""
    return content_type.split(";")[0].strip() == "image/png"


def save_logo_png(data: bytes, path: Path) -> Path | None:
    """Normalise any raster logo (webp/jpeg/png) to PNG so python-pptx can embed it; None if not an image."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        return None
    img.convert("RGBA").save(path, format="PNG")
    return path
