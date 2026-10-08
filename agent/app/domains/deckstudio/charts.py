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


def _fmt(v, unit: str) -> str:
    v = float(v)
    return f"{v:.1f}%" if unit == "percent" else (str(int(v)) if v.is_integer() else f"{v:.1f}")


def _bars(c, t, logos, w, h):
    cats, vals = c["categories"], [float(v) for v in c["values"]]
    top = max(vals) or 1
    row = min(56, (h - 10) / max(1, len(cats)))
    out = []
    for i, (cat, v) in enumerate(zip(cats, vals)):
        y = 5 + i * row
        bw = (w - LABEL_W - 110) * v / top
        label_x = LABEL_W - (LOGO_W + 14 if cat in logos else 8)
        out.append(f'<text class="ylab" style="font-size:22px" x="{label_x}" y="{y + row * .62:.1f}" text-anchor="end">{escape(_short(cat))}</text>')
        if cat in logos:
            out.append(f'<image href="{escape(logos[cat])}" x="{LABEL_W - LOGO_W - 4}" y="{y + row / 2 - LOGO_H / 2:.1f}" '
                       f'width="{LOGO_W}" height="{LOGO_H}" preserveAspectRatio="xMidYMid meet"/>')
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
    out = [f'<line x1="{pl}" y1="{h - pb}" x2="{w - 30}" y2="{h - pb}" stroke="#{t.muted}" stroke-opacity=".35"/>',
           f'<polyline points="{points}" fill="none" stroke="#{t.series[0]}" stroke-width="4" stroke-linejoin="round"/>']
    out += [f'<text class="xlab" style="font-size:18px" x="{xs[i]:.1f}" y="{h - pb + 28}" text-anchor="middle">{escape(_short(cats[i]))}</text>'
            for i in range(0, len(cats), step)]
    for p in c.get("peaks") or []:
        if 0 <= p < len(vals):
            out.append(f'<circle cx="{xs[p]:.1f}" cy="{ys[p]:.1f}" r="8" fill="#{t.primary}"/>')
            out.append(f'<text class="peak" style="font-size:21px" x="{xs[p]:.1f}" y="{ys[p] - 16:.1f}" text-anchor="middle">{_fmt(vals[p], "count")}</text>')
    return out


def _doughnut(c, t, w, h):
    cats, vals = c["categories"], [float(v) for v in c["values"]]
    total = sum(vals) or 1
    cx = cy = h / 2
    r = (h / 2 - 12) / 1.21          # the ring's stroke (0.42 r) reaches 1.21 r: keep the whole ring in the box
    out, a0 = [], -math.pi / 2
    for i, (cat, v) in enumerate(zip(cats, vals)):
        a1 = a0 + 2 * math.pi * v / total - 1e-4
        x0, y0, x1, y1 = cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1)
        out.append(f'<path d="M{x0:.1f},{y0:.1f} A{r:.1f},{r:.1f} 0 {1 if a1 - a0 > math.pi else 0} 1 {x1:.1f},{y1:.1f}" '
                   f'fill="none" stroke="#{t.series[i % 6]}" stroke-width="{r * .42:.1f}"/>')
        ly = 40 + i * 40
        out.append(f'<rect x="{h + 30}" y="{ly}" width="18" height="18" rx="4" fill="#{t.series[i % 6]}"/>')
        out.append(f'<text class="ylab" style="font-size:22px" x="{h + 58}" y="{ly + 16}">{escape(_short(cat))} · {_fmt(v, c.get("unit", "count"))}</text>')
        a0 = a1 + 1e-4
    return out


def _kpi(c, t, w, h):
    v = (c.get("values") or [0])[0]
    return [f'<text class="kpi" style="font-size:160px" x="{w / 2}" y="{h * .66:.1f}" text-anchor="middle" fill="#{t.primary}">'
            f'{_fmt(v, c.get("unit", "percent"))}</text>']


def chart_svg(chart: dict, tokens: DeckTokens, logos: dict[str, str], width: int, height: int) -> str:
    kind = chart.get("kind")
    if kind in ("bar", "treemap"):
        body = _bars(chart, tokens, logos, width, height)
    elif kind in ("line_peaks", "column"):
        body = _line(chart, tokens, width, height)
    elif kind == "doughnut":
        body = _doughnut(chart, tokens, width, height)
    else:
        body = _kpi(chart, tokens, width, height)
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" height="100%" '
            f'preserveAspectRatio="xMinYMin meet" xmlns="http://www.w3.org/2000/svg">{"".join(body)}</svg>')
