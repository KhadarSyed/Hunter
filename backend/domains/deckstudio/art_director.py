"""Brand-led design tokens: the LLM reads the brand colours and the project intent and proposes palette,
fonts and mood; guards keep text readable and fonts loadable; without an LLM the brand colours drive it."""
from __future__ import annotations

import colorsys
import json
import logging
import re
from urllib.parse import quote_plus

from ..deliverable.brand_kit import contrast_ratio
from .spec import DeckTokens

logger = logging.getLogger(__name__)
MIN_CONTRAST = 4.5
MIN_ACCENT_CONTRAST = 3.0
GOOGLE_FONTS = ("Inter", "Nunito Sans", "Source Sans 3", "Work Sans", "DM Sans", "Manrope", "Lato", "Montserrat",
                "Poppins", "Raleway", "Playfair Display", "Fraunces", "Lora", "Merriweather", "DM Serif Display",
                "Libre Baskerville", "Cormorant Garamond", "Space Grotesk", "Outfit", "Quicksand")
_HEX = re.compile(r"^[0-9A-Fa-f]{6}$")
_PROMPT = ("You are an art director. From the brand colours and the project intent, propose design tokens for a "
           "research presentation that feels like the brand. Return JSON with keys background, surface, primary, "
           "accent, text, muted, series (6 distinguishable chart colours), title_font, body_font, mood (3-5 words "
           "for photo search). Hex colours without '#'. Fonts must come from this list: {fonts}.")


def _hex(v, default: str) -> str:
    v = str(v or "").lstrip("#")
    return v.upper() if _HEX.match(v) else default


def _darken(h: str, bg: str, minimum: float) -> str:
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    while contrast_ratio(h, bg) < minimum and light > 0.05:
        light -= 0.05
        r, g, b = colorsys.hls_to_rgb(hue, light, sat)
        h = f"{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"
    return h if contrast_ratio(h, bg) >= minimum else "1F1F1F"


def _series(base: list[str]) -> list[str]:
    out = list(dict.fromkeys(base))
    return (out + [c for c in DeckTokens().series if c not in out])[:6]


def _guard(t: DeckTokens) -> DeckTokens:
    # Panels, cards and tables are light; a dark page background would leave their text unreadable
    if contrast_ratio(t.background, "000000") < contrast_ratio(t.background, "FFFFFF"):
        t.background = "FFFFFF"
    if contrast_ratio(t.surface, "000000") < 12:
        t.surface = DeckTokens().surface
    t.text = _darken(_darken(t.text, t.surface, MIN_CONTRAST), t.background, MIN_CONTRAST)
    t.muted = _darken(t.muted, t.background, MIN_CONTRAST)
    t.primary = _darken(t.primary, t.on_dark, MIN_CONTRAST)       # headers and overlays carry on-dark text
    t.accent = _darken(t.accent, t.background, MIN_ACCENT_CONTRAST)      # kickers are accent text on the background
    t.title_font = t.title_font if t.title_font in allowed_fonts() else "Playfair Display"
    t.body_font = t.body_font if t.body_font in allowed_fonts() else "Inter"
    t.chrome_font = t.chrome_font if t.chrome_font in allowed_fonts() else ""
    r, g, b = (int(t.primary[i:i + 2], 16) for i in (0, 2, 4))
    t.overlay = f"linear-gradient(90deg, rgba({r},{g},{b},.88) 0%, rgba({r},{g},{b},.55) 55%, rgba({r},{g},{b},.15) 100%)"
    return t


def _hls(h: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def _brand_hue(color: str, brand: list[str]) -> bool:
    """The colour is one of the brand's own hues (or a shade/tint of one): an art direction may darken or lighten the
    brand, never bring in a foreign hue (Tesla's deck got a teal accent no Tesla asset carries)."""
    if not color:
        return False
    h, l, s = _hls(color)
    for b in brand:
        bh, bl, bs = _hls(b)
        if bs < 0.15 or s < 0.15:                 # greys/black/white: only a near-identical neutral counts
            if abs(l - bl) < 0.15 and abs(s - bs) < 0.15:
                return True
            continue
        if min(abs(h - bh), 1 - abs(h - bh)) <= 0.04:
            return True
    return False


PAPER_SPREAD = 12          # a paper colour whose RGB channels differ by more than this is tinted (beige, mint)
NEUTRAL_SPREAD = 30        # below this a colour is a grey, black or white, not a brand hue
_TONES = (0.35, -0.3, 0.6, -0.5, 0.8, 0.15)    # lighter / darker steps for the brand's own chart colours


def _spread(c: str) -> int:
    rgb = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
    return max(rgb) - min(rgb)


def _tone(c: str, step: float) -> str:
    h, l, s = _hls(c)
    l = l + step * (1 - l) if step > 0 else l * (1 + step)
    return "".join(f"{round(v * 255):02X}" for v in colorsys.hls_to_rgb(h, l, s))


def _brand_series(brand: list[str]) -> list[str]:
    """Chart colours from the brand alone: its hues, then lighter and darker tones of them (never a hue the brand
    does not carry). Empty when the brand has no hue of its own (only black and white)."""
    hues = [c for c in brand if _spread(c) >= NEUTRAL_SPREAD]
    out = list(hues)
    for step in _TONES:
        out += [_tone(c, step) for c in hues]
    return list(dict.fromkeys(out))[:6]


def fallback_tokens(brand_colors: list[str]) -> DeckTokens:
    colors = [c for c in (_hex(c, "") for c in brand_colors) if c]
    t = DeckTokens()
    if colors:
        t.primary = colors[0]
        t.accent = colors[1] if len(colors) > 1 else t.accent
        t.series = _series(_brand_series(colors) or colors)
    return _guard(t)


HERO_MAX_PX = 120
HEADLINE_MAX_PX = 84
_PX = re.compile(r"(\d+(?:\.\d+)?)px")


def allowed_fonts() -> frozenset[str]:
    from .design_systems import pack_fonts
    return frozenset(GOOGLE_FONTS) | pack_fonts()


def _px(size) -> int:
    """84 / '84px' / 'clamp(56px, 6vw, 120px)' -> the largest pixel size named."""
    found = [float(x) for x in _PX.findall(str(size))] or ([float(size)] if isinstance(size, (int, float)) else [])
    return int(max(found)) if found else 0


def _role(typography: dict, *words: str) -> dict:
    """The largest type role whose name contains one of the words."""
    roles = [(k, v) for k, v in typography.items() if isinstance(v, dict) and any(w in k for w in words)]
    return max(roles, key=lambda kv: _px(kv[1].get("fontSize")), default=(None, {}))[1]


def _apply_design(t: DeckTokens, design: dict, brand_colors: list[str]) -> DeckTokens:
    """A frontend-slides design system shapes type and paper; the brand keeps primary and accent."""
    from .design_systems import first_family
    typo = design.get("typography") or {}
    hero, head = _role(typo, "display", "hero", "title"), _role(typo, "headline", "heading", "section")
    body = next((v for k, v in typo.items() if isinstance(v, dict) and k.startswith(("body", "lede", "paragraph"))), {})
    chrome = next((v for k, v in typo.items() if isinstance(v, dict) and (
        "mono" in str(v.get("fontFamily", "")).lower() or any(w in k for w in ("label", "caption", "eyebrow")))), {})
    t.title_font = first_family(str(hero.get("fontFamily", ""))) or t.title_font
    t.body_font = first_family(str(body.get("fontFamily", ""))) or t.body_font
    t.chrome_font = first_family(str(chrome.get("fontFamily", ""))) or ""
    t.type_scale = {"hero": min(_px(hero.get("fontSize")) or HERO_MAX_PX, HERO_MAX_PX),
                    "headline": min(_px(head.get("fontSize")) or HEADLINE_MAX_PX, HEADLINE_MAX_PX),
                    "weight": int(hero.get("fontWeight") or 700)}
    colors = [c for c in (_hex(str(v).lstrip("#"), "") for v in (design.get("colors") or {}).values()) if c]
    light = sorted(colors, key=lambda c: -contrast_ratio(c, "000000"))
    # the design system's paper only when it is a neutral: a tinted paper (beige, mint) is a colour the brand
    # does not carry; the brand's own hues carry the identity
    light = [c for c in light if _spread(c) <= PAPER_SPREAD or not brand_colors]
    if light and contrast_ratio(light[0], "000000") >= 12:
        t.background = light[0]
        t.surface = light[1] if len(light) > 1 and contrast_ratio(light[1], "000000") >= 12 else t.surface
    if not brand_colors:
        vivid = sorted(colors, key=lambda c: -colorsys.rgb_to_hsv(*(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)))[1])
        t.primary, t.accent = (vivid + [t.primary, t.accent])[:2]
    t.design_system = design.get("slug", "")
    return t


def choose_tokens(llm, brand_colors: list[str], intent: str, rules: dict, design: dict | None = None) -> tuple[DeckTokens, str]:
    t, source = _choose_base(llm, brand_colors, intent, rules)
    if design:
        t = _guard(_apply_design(t, design, brand_colors))
        source = f"{source} + design system"
    return t, source


def _choose_base(llm, brand_colors: list[str], intent: str, rules: dict) -> tuple[DeckTokens, str]:
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return fallback_tokens(brand_colors), "fallback"
    try:
        raw = json.loads(llm.chat([{"role": "system", "content": _PROMPT.format(fonts=", ".join(GOOGLE_FONTS))},
                                   {"role": "user", "content": json.dumps({"brand_colours": brand_colors, "intent": intent[:1500],
                                                                           "reference_fonts": [rules.get("title_font"), rules.get("body_font")]})}],
                                  format_json=True))
    except Exception as e:      # any LLM failure falls back to the brand colours
        logger.warning("art direction fell back: %s", type(e).__name__)
        return fallback_tokens(brand_colors), "fallback"
    if not isinstance(raw, dict):
        return fallback_tokens(brand_colors), "fallback"
    base = fallback_tokens(brand_colors)
    brand = [c for c in (_hex(c, "") for c in brand_colors) if c]
    primary, accent = _hex(raw.get("primary"), base.primary), _hex(raw.get("accent"), base.accent)
    if brand:                                     # primary and accent wear the brand's own hues
        primary = primary if _brand_hue(primary, brand) else base.primary
        accent = accent if _brand_hue(accent, brand) else base.accent
    series = _brand_series(brand) or [c for c in (_hex(c, "") for c in raw.get("series") or []) if c]
    background, surface = _hex(raw.get("background"), base.background), _hex(raw.get("surface"), base.surface)
    if brand:                                     # paper stays neutral: the brand's hues carry the identity
        background = background if _spread(background) <= PAPER_SPREAD else base.background
        surface = surface if _spread(surface) <= PAPER_SPREAD else base.surface
    t = DeckTokens(background=background, surface=surface,
                   primary=primary, accent=accent,
                   text=_hex(raw.get("text"), base.text), muted=_hex(raw.get("muted"), base.muted),
                   series=_series(series or base.series),
                   title_font=str(raw.get("title_font") or ""), body_font=str(raw.get("body_font") or ""),
                   mood=[str(m) for m in raw.get("mood") or []][:5])
    return _guard(t), "llm"


def fonts_href(t: DeckTokens) -> str:
    fams = "&".join(f"family={quote_plus(f)}:wght@400;600;700" for f in dict.fromkeys([t.title_font, t.body_font, t.chrome_font]) if f)
    return f"https://fonts.googleapis.com/css2?{fams}&display=swap"
