"""Logos for many brands, Iconify icons and country flags as PNG, and the category hero image."""
from __future__ import annotations

import colorsys
import html
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlparse

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


LOGO_TRIES = 6           # candidate images tried per brand before falling back to a letter badge
_CDN = "https://cdn.brandfetch.io"


def _cdn_pngs(domain: str) -> list[str]:
    """A domain's wordmark, then its square icon: some brands only have the icon as PNG (the wordmark comes back as
    WEBP, which is also Brandfetch's placeholder for an unknown brand, so it is never trusted)."""
    client = os.environ.get("BRANDFETCH_CLIENT_ID", "")
    return [f"{_CDN}/{domain}/w/400/h/400/{kind}.png?c={client}" for kind in ("logo", "icon")]


def _fetch_logo(url: str, path: Path) -> Path | None:
    from .cli import LOGO_HEADERS, LOGO_TIMEOUT_S, is_real_logo, save_logo_png
    try:
        r = requests.get(url, headers=LOGO_HEADERS, timeout=LOGO_TIMEOUT_S)
    except requests.RequestException as e:
        logger.warning("logo download failed for %s: %s", url.split("?")[0], type(e).__name__)
        return None
    ctype = r.headers.get("content-type", "").split(";")[0].strip()
    # Brandfetch answers an unknown brand with a WEBP placeholder, so its CDN must return PNG; any other host's
    # raster image is converted to PNG
    ok = is_real_logo(ctype) if url.startswith(_CDN) else ctype in ("image/png", "image/jpeg", "image/webp")
    return save_logo_png(r.content, path) if r.ok and ok else None


def logos(names: list[str], folder: Path, judge=None, hint: str = "") -> dict[str, Path]:
    """Downloaded logos by brand. Each candidate is checked by `judge` (no logo beats a wrong one: a name lookup can
    land on a different company's site); when one is rejected, the brand's other plausible matches, and matches for
    the name plus `hint`, are tried in turn."""
    from ..research.brandfetch import candidate_domains, google_logo_candidates, resolve_logo
    from .cli import logo_png_url
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for name in (n for n in names if n):
        stem = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        info = resolve_logo(name)
        first = [logo_png_url(info)] + (_cdn_pngs(info["domain"])[1:] if info.get("domain") else [])
        tried, k, chosen = set(), 0, {}

        def accepted(url: str, domain: str) -> Path | None:
            nonlocal k
            if not url or url in tried:
                return None
            tried.add(url)
            k += 1
            path = _fetch_logo(url, folder / f"{stem}_{k}.png")
            ok = path and (judge is None or judge(path.read_bytes(), name, domain) is not False)
            if ok:
                chosen.update(url=url, domain=domain)
            return path if ok else None

        found = next((p for p in (accepted(u, info.get("domain") or "") for u in first) if p), None)
        if found is None and judge is not None:
            for domain in candidate_domains(name, hint):
                if k >= LOGO_TRIES:
                    break
                found = next((p for p in (accepted(u, domain) for u in _cdn_pngs(domain)) if p), None)
                if found:
                    break
        if found is None and judge is not None:     # last: Google Images for the name plus the category
            for url in google_logo_candidates(name, hint):
                found = accepted(url, urlparse(url).netloc.removeprefix("www."))
                if found:
                    break
        if found:
            out[name] = found
            if chosen["url"] not in first:          # remember the approved logo: later decks start from it
                _remember(name, chosen["url"], chosen["domain"])
    return out


def _remember(name: str, url: str, domain: str) -> None:
    from ...core import store
    from ..research.brandfetch import normalize_brand
    on_cdn = url.startswith(_CDN)
    store.save_brand_logo(normalize_brand(name), name, url, domain if on_cdn else None,
                          "brandfetch" if on_cdn else "google")


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


BADGE_PX = 128
_BADGE_FONTS = ("arialbd.ttf", "DejaVuSans-Bold.ttf")


def letter_badge_png(name: str, folder: Path, color: str = style.VIOLET) -> Path | None:
    """A round badge with the outlet's initial, standing in for a site that has no icon."""
    from PIL import Image, ImageDraw, ImageFont
    initial = next((ch for ch in name or "" if ch.isalnum()), "")
    if not initial:
        return None
    out = folder / f"{BADGE_PREFIX}{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')[:40]}.png"
    if out.exists():
        return out
    img = Image.new("RGBA", (BADGE_PX, BADGE_PX), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, BADGE_PX - 1, BADGE_PX - 1), fill="#" + color.lstrip("#"))
    font = None
    for face in _BADGE_FONTS:
        try:
            font = ImageFont.truetype(face, 72)
            break
        except OSError:
            continue
    draw.text((BADGE_PX / 2, BADGE_PX / 2), initial.upper(), fill="white", anchor="mm",
              font=font or ImageFont.load_default(size=72))
    folder.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


def plain_name(name: str) -> str:
    """A brand name with typographic quotes made plain: "Johnson’s" and "Johnson's" are one brand."""
    return (name or "").translate(_QUOTES).strip()


def find_logo(name: str, logos: dict[str, Path]) -> Path | None:
    """The logo for a chart label: exact, then ignoring quotes and case, then the master brand's ("Aveeno" for
    "Aveeno Baby"), then the brand's own product line's ("Aquaphor Baby" for "Aquaphor")."""
    if name in logos:
        return logos[name]
    by_key = {plain_name(k).casefold(): v for k, v in logos.items() if v}
    key = plain_name(name).casefold()
    if key in by_key:
        return by_key[key]
    words = key.split()
    master = next((" ".join(words[:k]) for k in range(len(words) - 1, 0, -1) if " ".join(words[:k]) in by_key), None)
    if master:
        return by_key[master]
    line = sorted(k for k in by_key if k.startswith(key + " "))
    return by_key[line[0]] if line else None


BADGE_PREFIX = "badge_"
PAGE_LOGO_PX = 160         # logos embedded in the web page are shrunk to this height


def is_badge(path: Path | str) -> bool:
    """A letter-badge stand-in (see letter_badge_png), not a real logo."""
    return Path(path).name.startswith(BADGE_PREFIX)


def _full_opacity(img: Image.Image) -> Image.Image:
    from ..deckstudio.logo_prep import _full_opacity as solid     # one rule for the deck and the page
    return solid(img)


def logo_data_uri(path: Path) -> str | None:
    """A small PNG data URI of a logo for the web page, which cannot read the run's files directly."""
    import base64
    import io
    try:
        with Image.open(path) as im:
            im = _full_opacity(im.convert("RGBA"))       # a logo saved semi-transparent (BYD) shown solid
            im.thumbnail((PAGE_LOGO_PX * 4, PAGE_LOGO_PX))
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
    except OSError as e:
        logger.warning("logo %s unreadable: %s", Path(path).name, e)
        return None
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


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
