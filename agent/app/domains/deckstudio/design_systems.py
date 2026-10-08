"""Design systems from the frontend-slides bold template pack (vendored, MIT): shortlist by the brief's intent, let
the LLM pick one, and read only that system's design.md front matter."""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
PACK = Path(__file__).parent / "frontend_slides" / "bold-template-pack"
INDEX_PATH = PACK / "selection-index.json"
ALLOWED_FORMALITY = ("medium", "medium-high", "high")
SHORTLIST = 5
_WORD = re.compile(r"[a-z]{4,}")
_FRONT = re.compile(r"^---\s*\n(.*?)\n---", re.S)
_PROMPT = ("Pick the design system that best fits this client research deck. Reply as JSON "
           '{"slug": "<one of the slugs>", "why": "<one sentence>"}.')


@lru_cache(maxsize=1)
def index() -> list[dict]:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))["templates"]


def _words(*parts) -> set[str]:
    return {w for p in parts for w in _WORD.findall((" ".join(p) if isinstance(p, list) else str(p or "")).lower())}


def _scored(intent: str, brand_mood: list[str]) -> list[tuple[int, str, dict]]:
    want = _words(intent, brand_mood)
    scored = []
    for t in index():
        if t["formality"] not in ALLOWED_FORMALITY:
            continue
        fit = len(want & _words(t["mood"], t["tone"], t["best_for"], t["tagline"]))
        clash = len(want & _words(t["avoid_for"]))
        scored.append((fit - 2 * clash, t["slug"], t))
    return sorted(scored, key=lambda x: (-x[0], x[1]))


def shortlist(intent: str, brand_mood: list[str], k: int = SHORTLIST) -> list[dict]:
    return [t for _s, _slug, t in _scored(intent, brand_mood)[:k]]


MIN_FIT = 2                       # words a library system shares with the brief before it counts as a match
GENERATED = "generated"
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_GEN_PROMPT = ("No design system in the library fits this client research deck. Design one for it. Reply as JSON "
               '{{"name": "<2-4 words>", "why": "<one sentence>", "colors": {{"<role>": "#RRGGBB", ...5 colours, one '
               'light paper colour, one dark ink colour}}, "typography": {{"display": {{"fontFamily": "<font>", '
               '"fontSize": "64px", "fontWeight": 700}}, "headline": {{...}}, "body": {{...}}, "label": {{...}}}}}}. '
               "Fonts only from: {fonts}.")


def _font(spec: dict, fallback: str) -> dict:
    family = first_family(str(spec.get("fontFamily", "")))
    family = family if family in pack_fonts() else fallback
    return {"fontFamily": f"'{family}', sans-serif", "fontSize": str(spec.get("fontSize") or "18px"),
            "fontWeight": int(spec.get("fontWeight") or 400)}


def generate(llm, intent: str, brand_mood: list[str]) -> dict | None:
    """A design system for this brief: its colours and type, fonts limited to ones the deck can load."""
    fonts = sorted(pack_fonts())
    try:
        reply = json.loads(llm.chat([{"role": "system", "content": _GEN_PROMPT.format(fonts=", ".join(fonts))},
                                     {"role": "user", "content": f"Brief: {intent}\nBrand mood: {', '.join(brand_mood)}"}],
                                    format_json=True) or "{}")
    except Exception as e:      # the closest library system stands in
        logger.warning("design system generation failed: %s", type(e).__name__)
        return None
    colors = {str(k): str(v) for k, v in (reply.get("colors") or {}).items() if _HEX.match(str(v))}
    typo = {str(k): v for k, v in (reply.get("typography") or {}).items() if isinstance(v, dict)}
    if len(colors) < 2 or not typo:
        return None
    display = "Playfair Display" if "Playfair Display" in fonts else fonts[0]
    body = "Inter" if "Inter" in fonts else fonts[0]
    design = {"name": str(reply.get("name") or "Custom design")[:60], "colors": colors,
              "typography": {k: _font(v, display if k in ("display", "headline", "hero") else body) for k, v in typo.items()}}
    return {"slug": GENERATED, "name": design["name"], "mood": brand_mood or ["custom"], "design": design,
            "why": str(reply.get("why") or "")[:200]}


def load(slug: str) -> dict:
    if slug not in {t["slug"] for t in index()}:
        raise ValueError(f"unknown design system {slug!r}")
    m = _FRONT.match((PACK / "templates" / slug / "design.md").read_text(encoding="utf-8"))
    return yaml.safe_load(m.group(1)) if m else {}


_SYSTEM_FONTS = frozenset({"MS Sans Serif", "Segoe UI", "Georgia", "Arial", "Helvetica", "Times New Roman"})
_FAMILY = re.compile(r"^\s*'?\"?([A-Za-z0-9 ]+?)'?\"?\s*(?:,|$)")


def first_family(css_family: str) -> str:
    """'Source Serif 4', Georgia, serif -> Source Serif 4."""
    m = _FAMILY.match(css_family or "")
    return m.group(1).strip() if m else ""


@lru_cache(maxsize=1)
def pack_fonts() -> frozenset[str]:
    """Every font family the vendored design systems name (all are Google Fonts)."""
    names = set()
    for t in index():
        for spec in (load(t["slug"]).get("typography") or {}).values():
            if isinstance(spec, dict) and (name := first_family(str(spec.get("fontFamily", "")))):
                names.add(name)
    return frozenset(names - _SYSTEM_FONTS)


def choose(llm, intent: str, brand_mood: list[str]) -> tuple[dict, str]:
    scored = _scored(intent, brand_mood)
    picks = [t for _s, _slug, t in scored[:SHORTLIST]]
    fallback = (picks[0], f"closest fit to the brief's tone ({', '.join(picks[0]['mood'][:3])})")
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return fallback
    if scored[0][0] < MIN_FIT and (own := generate(llm, intent, brand_mood)):
        return own, f"no library design fits the brief well (best match {scored[0][0]}); designed for this brief: {own['why']}"
    menu = "\n".join(f"- {t['slug']}: {t['tagline']} Best for: {t['best_for']}. Avoid for: {t['avoid_for']}." for t in picks)
    try:
        reply = json.loads(llm.chat([{"role": "system", "content": _PROMPT},
                                     {"role": "user", "content": f"Brief: {intent}\nBrand mood: {', '.join(brand_mood)}\n{menu}"}],
                                    format_json=True) or "{}")
        chosen = next((t for t in picks if t["slug"] == reply.get("slug")), None)
        if chosen:
            return chosen, str(reply.get("why") or "model choice")[:200]
    except Exception as e:      # the deterministic shortlist winner is a sound default
        logger.warning("design system choice fell back: %s", type(e).__name__)
    return fallback
