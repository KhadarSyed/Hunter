"""Renders a DeckSpec into one HTML deck (frontend-slides-style viewport-safe base) with an assets folder."""
from __future__ import annotations

import re
import shutil
from dataclasses import replace
from html import unescape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .art_director import fonts_href
from .charts import chart_svg
from .spec import DeckSpec, DeckTokens, SlideSpec

TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))
_TAG = re.compile(r"<[^>]+>")
FRONTEND_CSS = (Path(__file__).parent / "frontend_slides" / "viewport-base.css").read_text(encoding="utf-8")
CHART_SIZE = {"A": (1000, 540), "C": (1100, 600), "plain": (1600, 600), "full": (900, 420)}


def _asset(path: str | None, out_dir: Path) -> str | None:
    if not path or not Path(path).exists():
        return None
    target = out_dir / "assets" / Path(path).name
    target.parent.mkdir(parents=True, exist_ok=True)
    if Path(path).resolve() != target.resolve():
        shutil.copyfile(path, target)
    return f"assets/{target.name}"


def render_slide(slide: SlideSpec, tokens: DeckTokens, n: int, total: int, base_n: int, period: str, source: str,
                 out_dir: Path) -> str:
    slide = replace(slide, cards=[{**c, **({"image": _asset(c["image"], out_dir)} if c.get("image") else {}),
                                   **({"thumb": _asset(c["thumb"], out_dir)} if c.get("thumb") else {})}
                                  for c in slide.cards])
    image = _asset(slide.image.get("path"), out_dir)
    logos = {name: rel for name, p in slide.logos.items() if (rel := _asset(p, out_dir))}
    w, h = CHART_SIZE.get(slide.treatment, (1000, 540))
    charts = [chart_svg(c, tokens, logos, w, h) for c in slide.charts]
    return _env.get_template("slide.html.j2").render(s=slide, t=tokens, n=n, total=total, base_n=base_n, period=period,
                                                     source=source, image=image, charts=charts)


def render_deck(spec: DeckSpec, out_dir: Path, slide_html: dict[str, str] | None = None, source: str = "Meltwater") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    tokens = spec.tokens or DeckTokens()
    parts = [(slide_html or {}).get(s.id) or render_slide(s, tokens, n, len(spec.slides), spec.base_n, spec.period, source, out_dir)
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
