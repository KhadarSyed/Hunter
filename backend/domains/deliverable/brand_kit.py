"""Brand kit from the Brandfetch Brand API: colours -> light chart tints and a heading accent, fonts (only when
they will render), banner image and logo. Any failure falls back to the house style; never raises."""
from __future__ import annotations

import colorsys
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests
from PIL import Image

from ..research import logo_files
from ..research.brandfetch import resolve_brand_domain
from . import style

logger = logging.getLogger(__name__)
BRAND_API = "https://api.brandfetch.io/v2/brands"
TIMEOUT_S = 15
MIN_HEADING_CONTRAST = 4.5        # WCAG AA for text on white
TINT_LIGHTNESS = (0.82, 0.74, 0.88, 0.78)
_COLOR_ORDER = {"brand": 0, "accent": 1, "dark": 2, "light": 3}
_NEAR_BLACK = {"000000", "111111"}
SAFE_FONTS = {"arial", "calibri", "segoe ui", "georgia", "verdana", "tahoma", "trebuchet ms", "helvetica"}


@dataclass
class BrandKit:
    name: str
    domain: str | None = None
    colors: list[str] = field(default_factory=list)
    title_font: str = style.FONT
    body_font: str = style.FONT
    logo: Path | None = None
    banner: Path | None = None
    palette: list[str] = field(default_factory=lambda: list(style.PALETTE))
    accent: str = style.VIOLET


def _brand_api(domain: str) -> dict:
    key = os.environ.get("BRANDFETCH_API_KEY", "")
    r = requests.get(f"{BRAND_API}/{domain}", timeout=TIMEOUT_S, headers={"Authorization": f"Bearer {key}"})
    r.raise_for_status()
    return r.json() or {}


def _luminance(hex_rgb: str) -> float:
    c = [int(hex_rgb[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def tints(hexes: list[str]) -> list[str]:
    """Four light tints of the brand hues (skipping near-greys), light enough for a white slide."""
    hues = []
    for h in hexes:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        hue, _light, sat = colorsys.rgb_to_hls(r, g, b)
        if sat > 0.2:
            hues.append((hue, sat))
    if not hues:
        return list(style.PALETTE)
    out = []
    for i, light in enumerate(TINT_LIGHTNESS):
        hue, sat = hues[i % len(hues)]
        hue = (hue + 0.07 * (i // len(hues))) % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, light, min(0.65, max(0.35, sat)))
        out.append(f"{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}")
    return out


def safe_font(name: str, origin: str | None) -> str:
    """Google fonts and common system fonts are used; custom brand fonts would be silently substituted on a
    viewer's machine, so they fall back to the house font."""
    if name and (origin == "google" or name.strip().lower() in SAFE_FONTS):
        return name.strip()
    return style.FONT


def _download_image(url: str, path: Path) -> Path | None:
    from .cli import save_logo_png
    try:
        r = requests.get(url, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        logger.warning("brand image unavailable: %s", type(e).__name__)
        return None
    if not r.ok or not r.headers.get("content-type", "image/").startswith("image/"):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    return save_logo_png(r.content, path)


def _first_src(entries: list[dict], types: tuple[str, ...]) -> str | None:
    for wanted in types:
        for e in entries or []:
            if e.get("type") == wanted:
                fmts = sorted(e.get("formats") or [], key=lambda f: f.get("format") not in ("png", "jpeg", "jpg"))
                if fmts and fmts[0].get("src"):
                    return fmts[0]["src"]
    return None


def fetch_kit(brand_name: str, folder: Path, judge=None) -> BrandKit:
    """`judge(image_bytes, brand) -> True/False/None` checks each logo candidate (see vision.is_logo_of)."""
    kit = BrandKit(name=brand_name)
    try:
        domain = resolve_brand_domain(brand_name)
        if not domain:
            return kit
        data = _brand_api(domain)
    except (requests.RequestException, ValueError) as e:
        logger.warning("brand kit for %r unavailable: %s", brand_name, type(e).__name__)
        return kit
    kit.domain = domain
    colors = sorted((c for c in data.get("colors") or [] if re.fullmatch(r"#?[0-9A-Fa-f]{6}", c.get("hex") or "")),
                    key=lambda c: _COLOR_ORDER.get(c.get("type"), 9))
    listed = [c["hex"].lstrip("#").upper() for c in colors]
    for f in data.get("fonts") or []:
        if f.get("type") == "title":
            kit.title_font = safe_font(f.get("name") or "", f.get("origin"))
        elif f.get("type") == "body":
            kit.body_font = safe_font(f.get("name") or "", f.get("origin"))
    slug = re.sub(r"[^a-z0-9]+", "_", brand_name.lower())
    banner = _first_src(data.get("images") or [], ("banner", "other"))
    if banner:
        kit.banner = _download_image(banner, folder / f"{slug}_banner.png")
    kit.logo = _verified_logo(data.get("logos") or [], brand_name, folder, slug, judge)
    # The brand's own hues come from its emblem first (Tesla's red T): Brandfetch's list can hold only a website
    # colour (tesla.com: a button blue, black, white), and the deck must wear the brand's identity
    emblem = logo_files.logo_file(brand_name)
    own = logo_colors(emblem[0] if emblem else None) or logo_colors(kit.logo)
    kit.colors = list(dict.fromkeys(own + [c for c in listed if not any(_near(c, o) for o in own)]))
    kit.palette = tints(kit.colors)
    kit.accent = next((c for c in kit.colors if c not in _NEAR_BLACK
                       and contrast_ratio(c, style.WHITE) >= MIN_HEADING_CONTRAST), style.VIOLET)
    return kit


def _near(a: str, b: str, tolerance: int = 40) -> bool:
    return sum(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (0, 2, 4)) <= tolerance


def logo_colors(path, limit: int = 2) -> list[str]:
    """The emblem's own brand hues, most-used first: exact colours of its saturated pixels (not white, grey, black
    or transparent background), near-duplicates merged."""
    if not path or not Path(path).exists():
        return []
    try:
        img = Image.open(path).convert("RGBA").resize((96, 96))
    except Exception:
        return []
    counts: dict[tuple, int] = {}
    for r, g, b, a in img.getdata():
        if a < 200:
            continue
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s > 0.35 and 0.15 < l < 0.85:
            key = (r // 16 * 16, g // 16 * 16, b // 16 * 16)
            counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    out: list[str] = []
    for (r, g, b), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if n < 0.05 * total:
            break
        hexed = f"{min(255, r + 8):02X}{min(255, g + 8):02X}{min(255, b + 8):02X}"
        if not any(_near(hexed, o, 60) for o in out):
            out.append(hexed)
        if len(out) >= limit:
            break
    return out


def _logo_srcs(entries: list[dict]) -> list[str]:
    """Every logo Brandfetch lists, logos before symbols before icons, raster formats first."""
    out = []
    for wanted in ("logo", "symbol", "icon"):
        for e in entries:
            if e.get("type") == wanted:
                fmts = sorted(e.get("formats") or [], key=lambda f: f.get("format") not in ("png", "jpeg", "jpg"))
                if fmts and fmts[0].get("src") and fmts[0]["src"] not in out:
                    out.append(fmts[0]["src"])
    return out


def _verified_logo(entries: list[dict], brand_name: str, folder: Path, slug: str, judge) -> Path | None:
    """The first logo the vision check confirms is this brand's: Brandfetch records can carry a sister brand's
    wordmark (band-aid.com lists Neosporin as its "logo"). No judge, or none it can judge: the first one."""
    unjudged = None
    for i, src in enumerate(_logo_srcs(entries)):
        path = _download_image(src, folder / f"{slug}_logo{'' if i == 0 else f'_{i}'}.png")
        if path is None:
            continue
        verdict = judge(path.read_bytes(), brand_name) if judge else None
        if verdict is True:
            return path
        if verdict is None and unjudged is None:
            unjudged = path
    return unjudged
