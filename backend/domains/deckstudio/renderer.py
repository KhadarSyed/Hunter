"""Renders a DeckSpec into one HTML deck (frontend-slides-style viewport-safe base) with an assets folder."""
from __future__ import annotations

import base64
import json
import re
import shutil
from dataclasses import replace
from html import unescape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from ...core.config import PARTNER_LOGO
from ..deliverable import visuals
from ..deliverable.analytics import PLATFORM_DOMAINS
from . import amcharts, logo_prep, tables
from .art_director import fonts_href
from .charts import chart_svg
from .spec import DeckSpec, DeckTokens, SlideSpec

TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))


def _md_bold(text) -> Markup:
    """**phrase** as bold, everything else escaped (card text comes from the model)."""
    return Markup(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", str(escape(text or ""))))


_env.filters["md_bold"] = _md_bold


def _luminance(hex6: str, share: float = 1.0) -> float:
    """WCAG relative luminance of `hex6` laid at `share` opacity over white."""
    lin = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (share * int(hex6[i:i + 2], 16) / 255 + 1 - share for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _dark_heat(primary: str, share: float, text: str) -> bool:
    """Whether white text reads better than the deck's text colour on a heat cell (`share` of the brand colour)."""
    bg = _luminance(primary, share)
    return 1.05 / (bg + 0.05) > (bg + 0.05) / (_luminance(text) + 0.05)


_env.filters["dark_heat"] = _dark_heat
_TAG = re.compile(r"<[^>]+>")
FRONTEND_CSS = (Path(__file__).parent / "frontend_slides" / "viewport-base.css").read_text(encoding="utf-8")
CHART_SIZE = {"A": (1000, 540), "C": (1100, 600), "plain": (1600, 600), "full": (900, 420), "S": (620, 640)}
CHART_SIZE_WITH_CARDS = {"C": (1100, 370)}         # the photo-panel slide's summary cards sit under the chart
KPI_ROW_H = 130                                     # the KPI tiles above a chart take this much of its height
LIVE_CHART_SIZES = [(870, 400), (1780, 300), (870, 400)]  # the last-7-days dashboard: brands | outlets over the daily line


def _asset(path: str | None, out_dir: Path) -> str | None:
    if not path or not Path(path).exists():
        return None
    target = out_dir / "assets" / Path(path).name
    target.parent.mkdir(parents=True, exist_ok=True)
    if Path(path).resolve() != target.resolve():
        shutil.copyfile(path, target)
    return f"assets/{target.name}"


def _slide_logos(slide: SlideSpec, out_dir: Path) -> tuple[dict[str, str], set[str]]:
    """Every mark beside a chart label or table cell, trimmed, and which are white (set on a dark chip, as on the
    cover)."""
    marked = {name: m for name, p in slide.logos.items() if (m := _mark(p, out_dir))}
    return ({name: rel for name, (rel, _light) in marked.items()},
            {name for name, (_rel, is_light) in marked.items() if is_light})


def _inline_logos(logos: dict[str, str], out_dir: Path) -> dict[str, str]:
    """The chart's logos as data URIs: amCharts loads a picture with CORS, which a deck opened from disk (and the
    exporter) refuses for a file, and its SVG export links pictures by address, which a PPTX can not follow."""
    out = {}
    for name, rel in logos.items():
        path = out_dir / rel
        if path.exists():
            kind = "svg+xml" if path.suffix.lower() == ".svg" else path.suffix.lower().lstrip(".").replace("jpg", "jpeg")
            out[name] = f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    return out


def _channel_icons(slide: SlideSpec, out_dir: Path) -> dict[str, str]:
    """A US map's channels (X, Facebook, ...) with their site icons, for its tooltip: {channel: data URI}."""
    names = {c.rsplit(" ", 1)[0] for ch in slide.charts if ch.get("kind") == "us_map"
             for st in ch.get("states") or [] for c in str(st.get("channels") or "").split(" · ") if c}
    rels = {n: str(p.relative_to(out_dir)) for n in sorted(names) if n in PLATFORM_DOMAINS
            and (p := visuals.favicon_png(PLATFORM_DOMAINS[n], out_dir / "favicons"))}
    return _inline_logos(rels, out_dir)


def render_slide(slide: SlideSpec, tokens: DeckTokens, n: int, total: int, base_n: int, period: str, source: str,
                 out_dir: Path, marks: dict | None = None) -> str:
    slide = replace(slide, cards=[{**c, **({"image": _asset(c["image"], out_dir)} if c.get("image") else {}),
                                   **({"thumb": _asset(c["thumb"], out_dir)} if c.get("thumb") else {})}
                                  for c in slide.cards])
    image = _asset(slide.image.get("path"), out_dir)
    logos, light = _slide_logos(slide, out_dir)
    w, h = CHART_SIZE_WITH_CARDS["C"] if slide.treatment == "C" and slide.cards else CHART_SIZE.get(slide.treatment, (1000, 540))
    if slide.charts and slide.charts[0].get("kpis"):
        h -= KPI_ROW_H
    sizes = LIVE_CHART_SIZES if slide.type == "latest24h_dashboard" else [(w, h)] * len(slide.charts)
    charts = [chart_svg(c, tokens, logos, cw, ch, light=light) for c, (cw, ch) in zip(slide.charts, sizes)]
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


def _house_badge(part: str, out_dir: Path) -> str:
    """AlphaMetricx's wordmark, top right on every slide (restyled ones too). No InfoVision name or logo on decks."""
    rel = _asset(str(PARTNER_LOGO) if PARTNER_LOGO else None, out_dir)
    if not rel or 'class="house"' in part or "</section>" not in part:
        return part
    badge = f'<div class="house"><img class="house-partner" src="{escape(rel)}" alt="AlphaMetricx"></div>'
    head, _, tail = part.rpartition("</section>")
    return f"{head}{badge}</section>{tail}"


def render_deck(spec: DeckSpec, out_dir: Path, slide_html: dict[str, str] | None = None, source: str = "Meltwater",
                name: str = "deck.html") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    tokens = spec.tokens or DeckTokens()
    marks = _marks(spec, out_dir)
    parts = [_house_badge((slide_html or {}).get(s.id) or render_slide(s, tokens, n, len(spec.slides), spec.base_n,
                                                                       spec.period, source, out_dir, marks), out_dir)
             for n, s in enumerate(spec.slides, start=1)]
    # the charts are drawn live by amCharts from these configs (built from the spec, so a re-tone reaches them even on
    # a restyled slide); each slide's SVG chart stays as the fallback
    def chart_logos(s):
        logos, light = _slide_logos(s, out_dir)
        return {**_inline_logos(logos, out_dir), **_channel_icons(s, out_dir)}, light
    configs = amcharts.deck_configs(spec.slides, tokens, chart_logos)
    maps = any(c and c["kind"] == "us_map" for cs in configs.values() for c in cs)
    drill = _drill_data(spec, out_dir, configs)            # before the configs are written into the page
    scripts = amcharts.scripts(configs, maps)
    if drill:                                               # a click on a chart element or table row lists its articles
        scripts = (f'<script type="application/json" id="deck-articles">{drill}</script>\n'
                   f"<script>{amcharts._inline('drill.js')}</script>\n" + scripts)
    if any(s.type == "latest24h" for s in spec.slides):    # the live slides' text and their Refresh button
        scripts += f"\n<script>{amcharts._inline('live24h.js')}</script>"
    html = _env.get_template("deck.html.j2").render(spec=spec, t=tokens, fonts=fonts_href(tokens), slides=parts,
                                                     frontend_css=FRONTEND_CSS, chart_scripts=scripts)
    path = out_dir / name
    path.write_text(html, encoding="utf-8")
    return path


ARTICLE_FIELDS = ("t", "u", "d", "dt", "a", "c", "o", "i", "s")    # title, url, domain, date, author, channel, outlet,
                                                                    # image, summary (+ "f": the site icon's index)


def _drill_data(spec: DeckSpec, out_dir: Path, configs: dict) -> str:
    """The deck's articles once, as compact rows, with each chart element's and table row's article ids written
    into its chart config / table map. '' when nothing in the deck can be clicked through."""
    index: dict[str, int] = {}
    rows: list[list] = []
    icons: dict[str, int] = {}

    def ids(urls) -> list[int]:
        out = []
        for u in urls:
            a = spec.articles.get(u)
            if a is None:
                continue
            if u not in index:
                rel = _asset(spec.article_icons.get(a.get("d", "")), out_dir)
                index[u] = len(rows)
                rows.append([a.get(k, "") for k in ARTICLE_FIELDS] + [icons.setdefault(rel, len(icons)) if rel else -1])
            out.append(index[u])
        return out

    tables = {}
    for s in spec.slides:
        live = s.type == "latest24h_dashboard"           # the 24h charts list the refresh's own articles (by n)
        for c, cfg in zip(s.charts, configs.get(s.id) or []):
            if cfg and c.get("drill"):
                cfg["drill"] = dict(c["drill"]) if live else {k: v for k, urls in c["drill"].items() if (v := ids(urls))}
                cfg["live"] = live
        for t in s.tables:
            keys = {str(r[0]) for r in t.get("rows") or [] if r}
            found = {k: v for k, urls in (t.get("drill") or {}).items() if k in keys and (v := ids(urls))}
            if found:
                tables.setdefault(s.id, {}).update(found)
    if not rows and not any(c and c.get("live") for cs in configs.values() for c in cs):
        return ""
    data = {"fields": list(ARTICLE_FIELDS) + ["f"], "rows": rows, "icons": list(icons), "tables": tables}
    return json.dumps(data, separators=(",", ":")).replace("</", "<\\/")


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
