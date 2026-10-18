"""Renders a DeckSpec into one HTML deck (frontend-slides-style viewport-safe base) with an assets folder."""
from __future__ import annotations

import re
import shutil
from dataclasses import replace
from html import unescape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from . import logo_prep, tables
from .art_director import fonts_href
from .charts import chart_svg
from .spec import DeckSpec, DeckTokens, SlideSpec

TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))


def _md_bold(text) -> Markup:
    """**phrase** as bold, everything else escaped (card text comes from the model)."""
    return Markup(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", str(escape(text or ""))))


_env.filters["md_bold"] = _md_bold
_TAG = re.compile(r"<[^>]+>")
FRONTEND_CSS = (Path(__file__).parent / "frontend_slides" / "viewport-base.css").read_text(encoding="utf-8")
CHART_SIZE = {"A": (1000, 540), "C": (1100, 600), "plain": (1600, 600), "full": (900, 420), "S": (620, 640)}
CHART_SIZE_WITH_CARDS = {"C": (1100, 370)}          # the photo-panel slide's summary cards sit under the chart


def _asset(path: str | None, out_dir: Path) -> str | None:
    if not path or not Path(path).exists():
        return None
    target = out_dir / "assets" / Path(path).name
    target.parent.mkdir(parents=True, exist_ok=True)
    if Path(path).resolve() != target.resolve():
        shutil.copyfile(path, target)
    return f"assets/{target.name}"


def render_slide(slide: SlideSpec, tokens: DeckTokens, n: int, total: int, base_n: int, period: str, source: str,
                 out_dir: Path, marks: dict | None = None) -> str:
    slide = replace(slide, cards=[{**c, **({"image": _asset(c["image"], out_dir)} if c.get("image") else {}),
                                   **({"thumb": _asset(c["thumb"], out_dir)} if c.get("thumb") else {})}
                                  for c in slide.cards])
    image = _asset(slide.image.get("path"), out_dir)
    # every mark beside a chart label or table cell is trimmed, and a white one is set on a dark chip (as on the cover)
    marked = {name: m for name, p in slide.logos.items() if (m := _mark(p, out_dir))}
    logos = {name: rel for name, (rel, _light) in marked.items()}
    light = {name for name, (_rel, is_light) in marked.items() if is_light}
    w, h = CHART_SIZE_WITH_CARDS["C"] if slide.treatment == "C" and slide.cards else CHART_SIZE.get(slide.treatment, (1000, 540))
    charts = [chart_svg(c, tokens, logos, w, h, light=light) for c in slide.charts]
    return _env.get_template("slide.html.j2").render(s=slide, t=tokens, n=n, total=total, base_n=base_n, period=period,
                                                     source=source, image=image, charts=charts, logos=logos,
                                                     light_logos=light, table_cap=tables.render_cap(slide),
                                                     marks=marks or {"brand": None, "name": "", "strip": [], "cites": {}})


MAX_STRIP_LOGOS = 6


DARK_CHIP_LUMA = 0.55        # a white logo needs a chip at least this dark to read


def _dark_enough(color: str, fallback: str) -> str:
    """The brand colour behind a white logo, or the deck's text colour when the brand colour is too pale."""
    try:
        r, g, b = (int(color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return fallback.lstrip("#")
    return color.lstrip("#") if 0.299 * r + 0.587 * g + 0.114 * b < DARK_CHIP_LUMA else fallback.lstrip("#")


def _mark(path: str | None, out_dir: Path) -> tuple[str, bool] | None:
    """A logo trimmed to its mark and copied into assets/, and whether it is light (set on a dark chip)."""
    prepared = logo_prep.prepare(path, out_dir)
    rel = _asset(prepared[0], out_dir) if prepared else None
    return (rel, prepared[1]) if rel else None


def _marks(spec: DeckSpec, out_dir: Path) -> dict:
    """The client's logo (cover and footers) and the competitive set (cover), copied into assets/."""
    # the client's logo already heads the cover: the strip shows the competitors, never the client a second time
    rivals = [(n, p) for n, p in spec.logo_strip.items() if not (spec.brand_logo and (n == spec.title or p == spec.brand_logo))]
    strip = [(name, *mark) for name, p in rivals[:MAX_STRIP_LOGOS] if (mark := _mark(p, out_dir))]
    cites = {n: {"outlet": m.get("outlet") or "", "icon": _asset(m.get("icon"), out_dir), "url": m.get("url") or ""}
             for n, m in (spec.citation_meta or {}).items()}
    brand = _mark(spec.brand_logo, out_dir)
    symbol = _mark(getattr(spec, "brand_symbol", ""), out_dir)
    tokens = spec.tokens or DeckTokens()
    return {"brand": brand[0] if brand else None, "brand_light": bool(brand and brand[1]),
            "symbol": symbol[0] if symbol else None,
            "chip_dark": f"#{_dark_enough(tokens.primary, tokens.text)}",
            "name": spec.title, "strip": strip, "cites": cites,
            "product": _asset(spec.product_image, out_dir), "product_name": spec.product_name}


def render_deck(spec: DeckSpec, out_dir: Path, slide_html: dict[str, str] | None = None, source: str = "Meltwater") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    tokens = spec.tokens or DeckTokens()
    marks = _marks(spec, out_dir)
    parts = [(slide_html or {}).get(s.id) or render_slide(s, tokens, n, len(spec.slides), spec.base_n, spec.period, source,
                                                          out_dir, marks)
             for n, s in enumerate(spec.slides, start=1)]
    html = _env.get_template("deck.html.j2").render(spec=spec, t=tokens, fonts=fonts_href(tokens), slides=parts,
                                                     frontend_css=FRONTEND_CSS)
    path = out_dir / "deck.html"
    path.write_text(html, encoding="utf-8")
    return path


_ASSET = re.compile(r"assets/[\w.\-]+")
_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp"}


def inline_assets(path: Path) -> Path:
    """The served deck runs sandboxed (no cookies, no network): its images travel inside the file."""
    import base64
    html = path.read_text(encoding="utf-8")

    def data_uri(m: re.Match) -> str:
        f = path.parent / m.group(0)
        if not f.is_file():
            return m.group(0)
        mime = _MIME.get(f.suffix.lower(), "application/octet-stream")
        return f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode("ascii")
    path.write_text(_ASSET.sub(data_uri, html), encoding="utf-8")
    return path


def slide_text(html: str) -> str:
    html = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", unescape(_TAG.sub(" ", html))).strip()
