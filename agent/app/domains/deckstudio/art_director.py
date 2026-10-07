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
    t.title_font = t.title_font if t.title_font in GOOGLE_FONTS else "Playfair Display"
    t.body_font = t.body_font if t.body_font in GOOGLE_FONTS else "Inter"
    r, g, b = (int(t.primary[i:i + 2], 16) for i in (0, 2, 4))
    t.overlay = f"linear-gradient(90deg, rgba({r},{g},{b},.88) 0%, rgba({r},{g},{b},.55) 55%, rgba({r},{g},{b},.15) 100%)"
    return t


def fallback_tokens(brand_colors: list[str]) -> DeckTokens:
    colors = [c for c in (_hex(c, "") for c in brand_colors) if c]
    t = DeckTokens()
    if colors:
        t.primary = colors[0]
        t.accent = colors[1] if len(colors) > 1 else t.accent
        t.series = _series(colors)
    return _guard(t)


def choose_tokens(llm, brand_colors: list[str], intent: str, rules: dict) -> tuple[DeckTokens, str]:
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
    t = DeckTokens(background=_hex(raw.get("background"), base.background), surface=_hex(raw.get("surface"), base.surface),
                   primary=_hex(raw.get("primary"), base.primary), accent=_hex(raw.get("accent"), base.accent),
                   text=_hex(raw.get("text"), base.text), muted=_hex(raw.get("muted"), base.muted),
                   series=_series([c for c in (_hex(c, "") for c in raw.get("series") or []) if c] or base.series),
                   title_font=str(raw.get("title_font") or ""), body_font=str(raw.get("body_font") or ""),
                   mood=[str(m) for m in raw.get("mood") or []][:5])
    return _guard(t), "llm"


def fonts_href(t: DeckTokens) -> str:
    fams = "&".join(f"family={quote_plus(f)}:wght@400;600;700" for f in dict.fromkeys([t.title_font, t.body_font]))
    return f"https://fonts.googleapis.com/css2?{fams}&display=swap"
