"""Copilot edits to a finished deck: restyle one slide with the user's instructions, or change design tokens. Every
change passes the same guards as the creative pass, then the deck is re-rendered and re-exported in place."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, fields, replace
from pathlib import Path

from . import art_director, creative, exporter, guards, renderer
from .spec import DeckSpec, DeckTokens

_HEX = re.compile(r"^[0-9A-Fa-f]{6}$")
_COLOR_FIELDS = {"background", "surface", "primary", "accent", "text", "muted", "on_dark"}
_FONT_FIELDS = {"title_font", "body_font"}


def load(deck_dir: Path) -> tuple[DeckSpec, dict[str, str]]:
    spec = DeckSpec.from_dict(json.loads((deck_dir / "spec.json").read_text(encoding="utf-8")))
    cpath = deck_dir / "creative.json"
    return spec, (json.loads(cpath.read_text(encoding="utf-8")) if cpath.exists() else {})


def _save(deck_dir: Path, spec: DeckSpec, candidates: dict[str, str]) -> None:
    (deck_dir / "spec.json").write_text(json.dumps(spec.to_dict(), default=str), encoding="utf-8")
    (deck_dir / "creative.json").write_text(json.dumps(candidates), encoding="utf-8")


def _export(spec: DeckSpec, html: Path, deck_dir: Path) -> dict:
    out = exporter.export_all(html, spec, deck_dir, spec.title)
    return {"pptx": str(out["pptx"]), "pdf": str(out["pdf"]), "html": str(html)}


def _slide(spec: DeckSpec, ref: str):
    if ref.isdigit() and 1 <= int(ref) <= len(spec.slides):
        return spec.slides[int(ref) - 1]
    found = next((s for s in spec.slides if s.id == ref), None)
    if not found:
        raise ValueError(f"no slide {ref!r}")
    return found


def _rejection(html: str | None, template: str, slide, spec: DeckSpec) -> str:
    if not html:
        return "the model returned no usable slide"
    if not creative._safe(html, template):
        return "unsafe or malformed html"
    if not creative._same_charts(template, html):
        return "the chart changed"
    allowed = slide.facts_allowed + [str(spec.base_n), slide.question, slide.kicker, slide.title, spec.period]
    bad = guards.number_issues(guards.slide_visible_text(html), allowed)
    return f"numbers not in the data: {', '.join(bad)}" if bad else ""


def revise_slide(deck_dir: Path, slide_ref: str, instructions: str, llm, check_layout: bool = True) -> dict:
    spec, candidates = load(deck_dir)
    slide = _slide(spec, str(slide_ref))
    template = guards.slide_html_map(renderer.render_deck(spec, deck_dir, {}).read_text(encoding="utf-8"))[slide.id]
    html = creative.creative_slide(llm, candidates.get(slide.id, template), slide, spec.tokens or DeckTokens(),
                                   slide.reference, instructions=instructions)
    reason = _rejection(html, template, slide, spec)
    if reason:
        return {"slide_id": slide.id, "applied": False, "reason": reason}
    candidates[slide.id] = html
    path = renderer.render_deck(spec, deck_dir, candidates)
    issues = [i for i in guards.layout_issues(path) if i["slide_id"] == slide.id] if check_layout else []
    if issues:
        return {"slide_id": slide.id, "applied": False, "reason": f"layout: {issues[0]['kind']}"}
    _save(deck_dir, spec, candidates)
    renderer.inline_assets(path)
    return {"slide_id": slide.id, "applied": True, "reason": "", **_export(spec, path, deck_dir)}


PREVIEW_HTML = "preview.html"
_ORIGINAL = "tokens_original.json"      # the deck's design as generated, so a colour change can be undone


def _recolor(tokens: DeckTokens, guarded: DeckTokens, applied: list[str]) -> DeckTokens:
    """The applied tokens, plus what derives from them: the photo overlay follows the primary, and charts re-tone from
    the new primary/accent (charts would otherwise keep the old palette)."""
    out = replace(tokens, **{k: getattr(guarded, k) for k in applied})
    if "primary" in applied:
        out.overlay = guarded.overlay
    if {"primary", "accent"} & set(applied):
        base = [out.primary, out.accent]
        out.series = art_director._series(art_director._brand_series(base) or base)
    return out


def design(deck_dir: Path, brand_name: str = "") -> dict:
    """The deck's current colours, swatches from its brand (the Brandfetch palette the banner shows, then the
    generated one) and whether there is a change to undo."""
    from ..deliverable import brand_kit
    spec, candidates = load(deck_dir)
    if not spec.brand_colors and brand_name:        # decks built before the spec kept the palette: look it up once
        spec.brand_colors = brand_kit.brand_colors(brand_name)
        if spec.brand_colors:
            _save(deck_dir, spec, candidates)
    t = spec.tokens or DeckTokens()
    swatches = spec.brand_colors + [t.primary, t.accent, *t.series]
    return {"primary": t.primary, "accent": t.accent, "swatches": list(dict.fromkeys(s.upper() for s in swatches)),
            "can_reset": (deck_dir / _ORIGINAL).exists()}


def reset_design(deck_dir: Path) -> dict:
    path = deck_dir / _ORIGINAL
    if not path.exists():
        raise ValueError("the deck still has its generated colours")
    spec, candidates = load(deck_dir)
    spec.tokens = DeckTokens(**json.loads(path.read_text(encoding="utf-8")))
    html = renderer.render_deck(spec, deck_dir, candidates)
    _save(deck_dir, spec, candidates)
    path.unlink()
    renderer.inline_assets(html)
    return {"applied": ["primary", "accent"], "rejected": {}, **_export(spec, html, deck_dir)}


def set_design(deck_dir: Path, changes: dict, preview: bool = False) -> dict:
    """Preview renders the recoloured deck to preview.html only (seconds, nothing saved); otherwise the change is
    saved and the PPTX/PDF re-exported."""
    spec, candidates = load(deck_dir)
    tokens = spec.tokens or DeckTokens()
    allowed = {f.name for f in fields(DeckTokens)} & (_COLOR_FIELDS | _FONT_FIELDS)
    rejected, updates = {}, {}
    for key, value in changes.items():
        if key not in allowed:
            rejected[key] = "not a design token"
        elif key in _COLOR_FIELDS and not _HEX.match(str(value)):
            rejected[key] = "colors are 6 hex digits"
        elif key in _FONT_FIELDS and str(value) not in art_director.GOOGLE_FONTS:
            rejected[key] = "font not available"
        else:
            updates[key] = str(value).upper() if key in _COLOR_FIELDS else str(value)
    guarded = art_director._guard(replace(tokens, **updates))
    applied = [k for k, v in updates.items() if getattr(guarded, k) == v]
    rejected.update({k: "fails the contrast guard" for k in updates if k not in applied})
    spec.tokens = _recolor(tokens, guarded, applied)
    if preview:
        path = renderer.render_deck(spec, deck_dir, candidates, name=PREVIEW_HTML)
        renderer.inline_assets(path)
        return {"applied": applied, "rejected": rejected, "html": PREVIEW_HTML}
    if applied and not (deck_dir / _ORIGINAL).exists():
        (deck_dir / _ORIGINAL).write_text(json.dumps(asdict(tokens)), encoding="utf-8")
    path = renderer.render_deck(spec, deck_dir, candidates)
    _save(deck_dir, spec, candidates)
    renderer.inline_assets(path)
    return {"applied": applied, "rejected": rejected, **_export(spec, path, deck_dir)}
