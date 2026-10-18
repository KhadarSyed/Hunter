"""Inline SVG charts for the HTML deck: deterministic, offline, screenshot-safe; logos beside labels,
skipped axis labels on long series, annotated peaks."""
from __future__ import annotations

import math
from html import escape

from .spec import DeckTokens

MAX_X_LABELS = 8
LABEL_W = 300
LOGO_W, LOGO_H = 64, 30     # wordmarks are wide; the box keeps their aspect ratio
MAX_LABEL_CHARS = 24


def _short(s) -> str:
    s = str(s)
    return s if len(s) <= MAX_LABEL_CHARS else s[:MAX_LABEL_CHARS - 1] + "…"


LABEL_PT = 22
GLYPH_EM = 0.53            # average glyph width of the label font, for fitting a label to its room
BADGE_R = 15


def _fit(s, room_px: float, size: int = LABEL_PT) -> str:
    """The label shortened (with an ellipsis) to the room left of the bar, so a long name never runs off the chart."""
    s = str(s)
    chars = max(4, int(room_px / (size * GLYPH_EM)))
    return s if len(s) <= chars else s[:chars - 1].rstrip() + "…"


def _badge(cat, cx: float, cy: float, t) -> list[str]:
    """A round initial standing in for a missing logo or icon, so every label in a marked chart has a mark."""
    initial = next((ch for ch in str(cat) if ch.isalnum()), "?").upper()
    return [f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{BADGE_R}" fill="#{t.primary}"/>',
            f'<text x="{cx:.1f}" y="{cy + 6:.1f}" text-anchor="middle" style="font:700 17px var(--chrome);fill:#fff">'
            f'{escape(initial)}</text>']


def _fmt(v, unit: str) -> str:
    v = float(v)
    return f"{v:.1f}%" if unit == "percent" else (str(int(v)) if v.is_integer() else f"{v:.1f}")


DARK_CHIP_LUMA = 0.55


def _dark_chip(t) -> str:
    """The brand colour when it is dark enough to carry a white logo, else the deck's text colour."""
    try:
        r, g, b = (int(t.primary[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return t.text
    return t.primary if 0.299 * r + 0.587 * g + 0.114 * b < DARK_CHIP_LUMA else t.text


def _bars(c, t, logos, w, h, light=frozenset()):
    cats, vals = c["categories"], [float(v) for v in c["values"]]
    top = max(vals) or 1
    row = min(56, (h - 10) / max(1, len(cats)))
    out = []
    marked = any(cat in logos for cat in cats)       # one mark per label, or none: never a few logos and gaps
    for i, (cat, v) in enumerate(zip(cats, vals)):
        y = 5 + i * row
        bw = (w - LABEL_W - 110) * v / top
        label_x = LABEL_W - (LOGO_W + 14 if marked else 8)
        out.append(f'<text class="ylab" style="font-size:{LABEL_PT}px" x="{label_x}" y="{y + row * .62:.1f}" '
                   f'text-anchor="end">{escape(_fit(cat, label_x - 6))}</text>')
        if cat in logos:
            if cat in light:            # a white logo on its dark chip, or it vanishes into the white chart
                out.append(f'<rect x="{LABEL_W - LOGO_W - 6}" y="{y + row / 2 - LOGO_H / 2 - 2:.1f}" width="{LOGO_W + 4}" '
                           f'height="{LOGO_H + 4}" rx="6" fill="#{_dark_chip(t)}"/>')
            out.append(f'<image href="{escape(logos[cat])}" x="{LABEL_W - LOGO_W - 4}" y="{y + row / 2 - LOGO_H / 2:.1f}" '
                       f'width="{LOGO_W}" height="{LOGO_H}" preserveAspectRatio="xMidYMid meet"/>')
        elif marked:
            out += _badge(cat, LABEL_W - 4 - LOGO_W / 2, y + row / 2, t)
        out.append(f'<rect x="{LABEL_W + 6}" y="{y + row * .18:.1f}" width="{max(bw, 3):.1f}" height="{row * .64:.1f}" rx="4" '
                   f'fill="#{t.series[0]}" opacity="{0.45 + 0.55 * v / top:.2f}"/>')
        out.append(f'<text class="val" style="font-size:21px" x="{LABEL_W + 14 + bw:.1f}" y="{y + row * .62:.1f}">{_fmt(v, c.get("unit", "count"))}</text>')
    return out


def _line(c, t, w, h):
    cats, vals = c["categories"], [float(v) for v in c["values"]]
    top, n = (max(vals) or 1), max(1, len(vals) - 1)
    pl, pb, pt = 60, 46, 40
    xs = [pl + (w - pl - 30) * i / n for i in range(len(vals))]
    ys = [pt + (h - pt - pb) * (1 - v / top) for v in vals]
    step = max(1, -(-len(cats) // MAX_X_LABELS))
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{h - pb} {points} {xs[-1]:.1f},{h - pb}"
    out = [f'<line x1="{pl}" y1="{h - pb}" x2="{w - 30}" y2="{h - pb}" stroke="#{t.muted}" stroke-opacity=".35"/>',
           f'<polygon points="{area}" fill="#{t.series[0]}" fill-opacity=".12"/>',
           f'<polyline points="{points}" fill="none" stroke="#{t.series[0]}" stroke-width="4" stroke-linejoin="round"/>']
    out += [f'<text class="xlab" style="font-size:18px" x="{xs[i]:.1f}" y="{h - pb + 28}" text-anchor="middle">{escape(_short(cats[i]))}</text>'
            for i in range(0, len(cats), step)]
    for p in c.get("peaks") or []:
        if 0 <= p < len(vals):
            out.append(f'<circle cx="{xs[p]:.1f}" cy="{ys[p]:.1f}" r="8" fill="#{t.primary}"/>')
            out.append(f'<text class="peak" style="font-size:21px" x="{xs[p]:.1f}" y="{ys[p] - 16:.1f}" text-anchor="middle">{_fmt(vals[p], "count")}</text>')
    return out


# sentiment reads as green / grey / red whatever the brand's colours are (a red brand must not colour "Positive")
SENTIMENT_COLORS = {"positive": "2E9E5B", "neutral": "9AA0A6", "mixed": "C9A227", "negative": "D64545"}


def _colors(cats, t) -> list[str]:
    if cats and all(str(c).strip().lower() in SENTIMENT_COLORS for c in cats):
        return [SENTIMENT_COLORS[str(c).strip().lower()] for c in cats]
    return [t.series[i % len(t.series)] for i in range(len(cats))]


def _on(color: str) -> str:
    """White or near-black text, whichever reads on the fill."""
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return "1A1A1A" if 0.299 * r + 0.587 * g + 0.114 * b > 0.62 else "FFFFFF"


def _worst(row: list[float], short: float) -> float:
    s = sum(row)
    return max(max(a * short * short / (s * s), s * s / (short * short * a)) for a in row if a > 0) if s else 1.0


def _squarify(vals: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Rectangles with areas proportional to `vals` (sorted descending), each as close to square as the
    strip it sits in allows (the squarified treemap of Bruls, Huizing and van Wijk)."""
    total = sum(vals) or 1
    scaled = [v * w * h / total for v in vals]
    rects, i = [], 0
    while i < len(scaled):
        short = min(w, h)
        row, j = [scaled[i]], i + 1
        while j < len(scaled) and _worst(row + [scaled[j]], short) <= _worst(row, short):
            row.append(scaled[j])
            j += 1
        s = sum(row)
        if w >= h:                       # the strip is a column on the left
            cw, cy = (s / h if h else 0), y
            for a in row:
                rects.append((x, cy, cw, a / cw if cw else 0))
                cy += a / cw if cw else 0
            x, w = x + cw, w - cw
        else:                            # the strip is a row along the top
            rh, cx = (s / w if w else 0), x
            for a in row:
                rects.append((cx, y, a / rh if rh else 0, rh))
                cx += a / rh if rh else 0
            y, h = y + rh, h - rh
        i = j
    return rects


TREEMAP_GAP = 4


def _neutral(color: str) -> bool:
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return max(r, g, b) - min(r, g, b) < 30


def _treemap(c, t, w, h):
    pairs = sorted(((str(cat), float(v)) for cat, v in zip(c["categories"], c["values"]) if float(v) > 0),
                   key=lambda p: -p[1])
    out, unit = [], c.get("unit", "count")
    # tiles in the deck's hues only: a white tile vanishes into the slide and a black one reads as a hole
    fills = [f for f in t.series if not _neutral(f)] or list(t.series)
    for i, ((cat, v), (x, y, rw, rh)) in enumerate(zip(pairs, _squarify([v for _, v in pairs], 0, 0, w, h))):
        fill = fills[i % len(fills)]
        out.append(f'<rect x="{x + TREEMAP_GAP / 2:.1f}" y="{y + TREEMAP_GAP / 2:.1f}" width="{max(rw - TREEMAP_GAP, 1):.1f}" '
                   f'height="{max(rh - TREEMAP_GAP, 1):.1f}" rx="6" fill="#{fill}" fill-opacity="{0.95 - 0.06 * min(i, 8):.2f}"/>')
        if rw < 90 or rh < 48:           # too small to label legibly: the cards and the data table carry it
            continue
        size = 24 if rw > 260 and rh > 110 else 19
        ink = _on(fill)
        out.append(f'<text x="{x + 14:.1f}" y="{y + 14 + size:.1f}" style="font:600 {size}px var(--chrome);fill:#{ink}">'
                   f'{escape(_fit(cat, rw - 28, size))}</text>')
        out.append(f'<text x="{x + 14:.1f}" y="{y + 22 + size * 2:.1f}" style="font:400 {size - 3}px var(--chrome);fill:#{ink};opacity:.9">'
                   f'{_fmt(v, unit)}</text>')
    return out


STACK_LABEL_W = 300
STACK_LABEL_SHARE = 0.4
STACK_MIN_LABEL_PX = 64      # a segment narrower than this carries no number of its own (the table has it)


def _stacked(c, t, w, h, logos, light=frozenset()):
    """100% bars, one per group (a brand), split into the breakdown's stacks (positive / neutral / negative): the
    whole split per brand, where a single bar could show only one share of it."""
    cats = c["breakdown"]["stacks"]
    colors = _colors(cats, t)
    rows = [(g["name"], [float(v) for v in g["values"]], g.get("n")) for g in c["breakdown"]["groups"]]
    marked = any(name in logos for name, _, _ in rows)
    col_w = min(STACK_LABEL_W, int(w * STACK_LABEL_SHARE))      # a narrow panel keeps most of its width for the bars
    label_w = col_w - (LOGO_W + 14 if marked else 0)
    legend_w = sum(46 + int(len(str(cat)) * 20 * GLYPH_EM) for cat in cats)
    legend_h = 44
    row = min(80, (h - legend_h - 10) / max(1, len(rows)))
    out, lx = [], max(0, min(col_w + 6, w - legend_w))
    for cat, col in zip(cats, colors):
        out.append(f'<rect x="{lx}" y="6" width="18" height="18" rx="4" fill="#{col}"/>')
        out.append(f'<text class="ylab" style="font-size:20px" x="{lx + 26}" y="22">{escape(_short(cat))}</text>')
        lx += 46 + int(len(str(cat)) * 20 * GLYPH_EM)
    bar_w = w - col_w - 20
    for r, (name, vals, n) in enumerate(rows):
        y = legend_h + r * row
        label = f"{name} (n={n})" if n else name
        out.append(f'<text class="ylab" style="font-size:20px" x="{label_w - 8}" y="{y + row * .6:.1f}" '
                   f'text-anchor="end">{escape(_fit(label, label_w - 14, 20))}</text>')
        if name in logos:
            lx0, ly0 = col_w - LOGO_W - 4, y + row / 2 - LOGO_H / 2
            if name in light:
                out.append(f'<rect x="{lx0 - 2}" y="{ly0 - 2:.1f}" width="{LOGO_W + 4}" height="{LOGO_H + 4}" rx="6" '
                           f'fill="#{_dark_chip(t)}"/>')
            out.append(f'<image href="{escape(logos[name])}" x="{lx0}" y="{ly0:.1f}" width="{LOGO_W}" height="{LOGO_H}" '
                       f'preserveAspectRatio="xMidYMid meet"/>')
        elif marked:
            out += _badge(name, col_w - 4 - LOGO_W / 2, y + row / 2, t)
        total, x = sum(vals) or 1, col_w + 6
        for v, col in zip(vals, colors):
            seg = bar_w * v / total
            if seg <= 0:
                continue
            out.append(f'<rect x="{x:.1f}" y="{y + row * .16:.1f}" width="{seg:.1f}" height="{row * .68:.1f}" fill="#{col}"/>')
            if seg >= STACK_MIN_LABEL_PX:      # a number only where it fits inside its segment
                out.append(f'<text x="{x + seg / 2:.1f}" y="{y + row * .6:.1f}" text-anchor="middle" '
                           f'style="font:600 18px var(--chrome);fill:#{_on(col)}">{_fmt(100 * v / total, "percent")}</text>')
            x += seg
    return out


LEGEND_W = 260          # room a side legend needs; a narrower chart puts the legend under the ring
LEGEND_ROW = 40


def _doughnut(c, t, w, h):
    cats, vals = c["categories"], [float(v) for v in c["values"]]
    total = sum(vals) or 1
    side = w >= h + LEGEND_W
    size = h if side else min(w, h - LEGEND_ROW * len(cats) - 20)
    cx, cy = (size / 2, size / 2) if side else (w / 2, size / 2)
    r = (size / 2 - 12) / 1.21       # the ring's stroke (0.42 r) reaches 1.21 r: keep the whole ring in the box
    out, a0, colors = [], -math.pi / 2, _colors(cats, t)
    for i, (cat, v) in enumerate(zip(cats, vals)):
        a1 = a0 + 2 * math.pi * v / total - 1e-4
        x0, y0, x1, y1 = cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1)
        out.append(f'<path d="M{x0:.1f},{y0:.1f} A{r:.1f},{r:.1f} 0 {1 if a1 - a0 > math.pi else 0} 1 {x1:.1f},{y1:.1f}" '
                   f'fill="none" stroke="#{colors[i]}" stroke-width="{r * .42:.1f}"/>')
        lx, ly = (size + 30, 40 + i * LEGEND_ROW) if side else (max(20, w / 2 - 120), size + 20 + i * LEGEND_ROW)
        out.append(f'<rect x="{lx:.0f}" y="{ly:.0f}" width="18" height="18" rx="4" fill="#{colors[i]}"/>')
        out.append(f'<text class="ylab" style="font-size:22px" x="{lx + 28:.0f}" y="{ly + 16:.0f}">{escape(_short(cat))} · '
                   f'{_fmt(v, c.get("unit", "count"))}</text>')
        a0 = a1 + 1e-4
    return out


def _kpi(c, t, w, h):
    v = (c.get("values") or [0])[0]
    return [f'<text class="kpi" style="font-size:160px" x="{w / 2}" y="{h * .66:.1f}" text-anchor="middle" fill="#{t.primary}">'
            f'{_fmt(v, c.get("unit", "percent"))}</text>']


def chart_svg(chart: dict, tokens: DeckTokens, logos: dict[str, str], width: int, height: int,
              light: set[str] = frozenset()) -> str:
    """`light`: labels whose logo is white (drawn on a dark chip)."""
    kind = chart.get("kind")
    if (chart.get("breakdown") or {}).get("groups"):
        body = _stacked(chart, tokens, width, height, logos, light)
    elif kind == "treemap":
        body = _treemap(chart, tokens, width, height)
    elif kind == "bar":
        body = _bars(chart, tokens, logos, width, height, light)
    elif kind in ("line_peaks", "column"):
        body = _line(chart, tokens, width, height)
    elif kind == "doughnut":
        body = _doughnut(chart, tokens, width, height)
    else:
        body = _kpi(chart, tokens, width, height)
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" height="100%" '
            f'preserveAspectRatio="xMinYMin meet" xmlns="http://www.w3.org/2000/svg">{"".join(body)}</svg>')
