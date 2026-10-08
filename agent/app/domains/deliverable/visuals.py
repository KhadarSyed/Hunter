"""Logos for many brands, Iconify icons and country flags as PNG, and the category hero image."""
from __future__ import annotations

import colorsys
import html
import logging
import re
from pathlib import Path

import requests
from PIL import Image

from . import style

logger = logging.getLogger(__name__)
ICON_API = "https://api.iconify.design"
TIMEOUT_S = 15
LIGHTNESS = (0.80, 0.72, 0.86, 0.76)

ICONS = {
    "share_kpi": "lucide:pie-chart", "volume_trend": "lucide:trending-up", "sentiment_split": "lucide:smile",
    "outlet_ranking": "lucide:newspaper", "reach": "lucide:radio-tower", "theme_clusters": "lucide:layout-grid",
    "entities": "lucide:users", "brand_sov": "lucide:award", "top_articles": "lucide:file-text",
    "media_split": "lucide:share-2", "question_breakdown": "lucide:bar-chart-horizontal", "dimension_crosstab": "lucide:table-2",
    "takeaway": "lucide:lightbulb", "methodology": "lucide:database", "overview": "lucide:bar-chart-3",
}
_ISO = {"united states": "us", "usa": "us", "us": "us", "united kingdom": "gb", "uk": "gb", "canada": "ca",
        "india": "in", "australia": "au", "germany": "de", "france": "fr"}
_SVG_PAGE = "<html><body style=\"margin:0;background:transparent\">{svg}</body></html>"


def palette_from_logo(path: Path | None) -> list[str]:
    """Fallback palette when Brandfetch has no colours: light tints of the logo saturated hues."""
    if not path or not Path(path).exists():
        return list(style.PALETTE)
    img = Image.open(path).convert("RGB").resize((80, 80))
    hues = []
    for _, (r, g, b) in sorted(img.quantize(colors=6).convert("RGB").getcolors(80 * 80) or [], reverse=True):
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s > 0.25 and 0.12 < l < 0.9:
            hues.append((h, s))
    if not hues:
        return list(style.PALETTE)
    out = []
    for i, light in enumerate(LIGHTNESS):
        h, s = hues[i % len(hues)]
        h = (h + 0.08 * (i // len(hues))) % 1.0
        r, g, b = colorsys.hls_to_rgb(h, light, min(0.65, max(0.35, s)))
        out.append(f"{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}")
    return out


def logos(names: list[str], folder: Path, judge=None) -> dict[str, Path]:
    """Downloaded logos by brand; one the judge says belongs to another brand is left out (no logo beats a
    wrong one: a name lookup can land on a different company's site)."""
    from .cli import _download_logos
    folder.mkdir(parents=True, exist_ok=True)
    got = _download_logos([{"brand": n} for n in names if n], folder)
    return {name: path for name, path in got.items()
            if path and (judge is None or judge(path.read_bytes(), name) is not False)}


def _fetch_svg(icon_id: str, color: str) -> str | None:
    prefix, name = icon_id.split(":", 1)
    params = {"height": 96} if prefix == "circle-flags" else {"color": "#" + color, "height": 96}
    try:
        r = requests.get(f"{ICON_API}/{prefix}/{name}.svg", params=params, timeout=TIMEOUT_S)
        return r.text if r.ok and r.text.lstrip().startswith("<svg") else None
    except requests.RequestException as e:
        logger.warning("icon %s unavailable: %s", icon_id, e)
        return None


def icon_png(icon_id: str, folder: Path, color: str = style.VIOLET) -> Path | None:
    out = folder / (re.sub(r"[^a-z0-9]+", "_", f"{icon_id}_{color}".lower()) + ".png")
    if out.exists():
        return out
    svg = _fetch_svg(icon_id, color)
    if not svg:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    try:
        _svg_to_png(svg, out)
    except Exception as e:      # icons are decoration: a missing browser must not fail the run
        logger.warning("icon %s not rendered: %s", icon_id, e)
        return None
    return out


def _svg_to_png(svg: str, out: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 96, "height": 96})
        page.set_content(_SVG_PAGE.format(svg=svg))
        page.locator("svg").screenshot(path=str(out), omit_background=True)
        browser.close()


DEFAULT_MARK_ICON = "mdi:star-four-points"
_WORDMARK = """<html><body style="margin:0;background:transparent"><div id="wm" style="display:inline-flex;align-items:center;
gap:20px;padding:12px 8px;font:800 56px/1 Arial,Helvetica,sans-serif;color:#{color};white-space:nowrap">
<span style="display:inline-block;width:76px;height:76px">{svg}</span><span>{name}</span></div></body></html>"""


def _search_icon(query: str) -> str | None:
    """The first Material Design icon Iconify finds for a word (e.g. "baby" -> mdi:baby-face-outline)."""
    try:
        r = requests.get(f"{ICON_API}/search", params={"query": query, "prefix": "mdi", "limit": 5}, timeout=TIMEOUT_S)
        icons = r.json().get("icons") if r.ok else None
        return icons[0] if icons else None
    except (requests.RequestException, ValueError) as e:
        logger.warning("icon search for %r unavailable: %s", query, type(e).__name__)
        return None


def _html_to_png(html_text: str, out: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 200})
        page.set_content(html_text)
        page.locator("#wm").screenshot(path=str(out), omit_background=True)
        browser.close()


def wordmark_png(name: str, category: str, folder: Path, color: str = style.VIOLET) -> Path | None:
    """A logo for a client that has none: its name set beside an icon for its category."""
    stop = {"category", "the", "and", "for", "brand", "group", "company", "inc"}
    words = [w for w in dict.fromkeys(re.findall(r"[a-z]{3,}", f"{category} {name}".lower())) if w not in stop]
    icon_id = next((i for q in [category, *words] if q and (i := _search_icon(q))), None) or DEFAULT_MARK_ICON
    svg = _fetch_svg(icon_id, color) or ""
    out = folder / (re.sub(r"[^a-z0-9]+", "_", f"wordmark_{name}".lower()) + ".png")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        _html_to_png(_WORDMARK.format(svg=svg, name=html.escape(name), color=color), out)
    except Exception as e:      # the cover keeps its title without a mark
        logger.warning("wordmark for %s not rendered: %s", name, type(e).__name__)
        return None
    return out if out.exists() else None


FAVICON_API = "https://www.google.com/s2/favicons"
FAVICON_SIZE = 64


def favicon_png(domain: str, folder: Path) -> Path | None:
    """The site icon for a citation domain, cached on disk; None when the site has none."""
    if not domain:
        return None
    out = folder / (re.sub(r"[^a-z0-9]+", "_", domain.lower()) + ".png")
    if out.exists():
        return out
    try:
        r = requests.get(FAVICON_API, params={"domain": domain, "sz": FAVICON_SIZE}, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        logger.warning("favicon for %s unavailable: %s", domain, e)
        return None
    if not r.ok or not r.headers.get("content-type", "").startswith("image/"):
        return None
    folder.mkdir(parents=True, exist_ok=True)
    from .cli import save_logo_png
    return save_logo_png(r.content, out)


def country_code(country: str) -> str | None:
    """ISO 3166-1 alpha-2 (lowercase) for the circle-flags icon set."""
    return _ISO.get((country or "").strip().lower())


def country_flag_png(country: str, folder: Path) -> Path | None:
    code = country_code(country)
    return icon_png(f"circle-flags:{code}", folder) if code else None


def hero_image(query: str, folder: Path) -> tuple[Path | None, str]:
    from ..research.pexels import resolve_background_image
    info = resolve_background_image(query) or {}
    url = info.get("image_url")
    if not url:
        return None, ""
    try:
        r = requests.get(url, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        logger.warning("hero image unavailable: %s", e)
        return None, ""
    if not r.ok:
        return None, ""
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "hero.jpg"
    out.write_bytes(r.content)
    photographer = info.get("photographer") or "Pexels"
    return out, f"Photo: {photographer} / Pexels"


# Words in a chart label -> an Iconify icon (Material Design Icons). First match wins; labels with no match get none.
VALUE_ICONS = (
    (("soccer", "football", "futsal", "5-a-side", "five-a-side"), "mdi:soccer"),
    (("trail", "hiking", "hike"), "mdi:run"),
    (("running", "jogging", "run", "marathon", "track", "athletics", "sprint"), "mdi:run"),
    (("tennis",), "mdi:tennis"),
    (("pickleball", "padel", "badminton", "squash", "racquet"), "mdi:badminton"),
    (("basketball", "netball"), "mdi:basketball"),
    (("volleyball",), "mdi:volleyball"),
    (("hockey", "lacrosse"), "mdi:hockey-sticks"),
    (("rugby",), "mdi:rugby"),
    (("baseball", "softball"), "mdi:baseball"),
    (("golf",), "mdi:golf"),
    (("cycling", "bike", "biking"), "mdi:bike"),
    (("swim",), "mdi:swim"),
    (("gym", "fitness", "weight", "crossfit"), "mdi:dumbbell"),
    (("yoga",), "mdi:yoga"),
    (("ski", "snowboard"), "mdi:ski"),
    (("skate", "skating"), "mdi:skateboard"),
    (("cut", "scrape", "scratch", "blister", "graze", "wound", "burn", "injur"), "mdi:bandage"),
)


# A keyword matches itself and its inflections (cuts, runners, swimming, injuries), not any longer word
# that happens to start with it ("ski" is not "skin care", "cut" is not "cuticle").
_INFLECTION = r"(?:s|es|er|ers|ing|ed|y|ies|[bdgmnpt](?:ing|er|ers|ed))?"


def value_icon(label: str) -> str | None:
    words = re.findall(r"[a-z0-9-]+", (label or "").lower())
    for keys, icon in VALUE_ICONS:
        if any(re.fullmatch(re.escape(k) + _INFLECTION, w) for w in words for k in keys):
            return icon
    return None
