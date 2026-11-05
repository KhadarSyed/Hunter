"""The deck's charts as amCharts 5 configs: the same data, colours, logos and peaks as the SVG charts (charts.py),
drawn live in the HTML deck by vendor/deckcharts.js and exported to SVG for the PPTX and PDF. The SVG chart stays in
the slide as the fallback wherever amCharts does not draw."""
from __future__ import annotations

import base64
import json
from html import escape
from pathlib import Path

from .charts import _colors, _dark_chip, _neutral, _on
from .spec import DeckTokens

VENDOR = Path(__file__).parent / "vendor"
DRAWN = {"bar", "column", "line_peaks", "doughnut", "treemap", "us_map", "heatmap", "sankey", "sunburst"}  # a KPI stays the number
# a theme bubble's colour by its articles' net sentiment (-1..1): negative, mixed, positive (the deck's status colours)
_TONE_COLORS = {-1: "#C62828", 0: "#8A8A99", 1: "#2E7D32"}
TONE_SPLIT = 0.15


# rivals' lines when the deck's own hues are shades of one colour (Tableau 10, its blues left out)
RIVAL_HUES = ("E15759", "F28E2B", "59A14F", "B07AA1", "EDC948", "76B7B2", "9C755F")
MIN_HUE_DISTANCE = 70        # RGB distance two lines need to tell apart
MAX_LINE_LUMA = 0.8          # a paler line vanishes into the white chart


def _distinct(colors: list[str]) -> list[str]:
    """The colours in order, each kept only when it differs enough from the ones kept before it."""
    rgb = lambda c: tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    kept: list[str] = []
    for c in colors:
        if sum(w * v for w, v in zip((0.299, 0.587, 0.114), rgb(c))) / 255 > MAX_LINE_LUMA and kept:
            continue
        if all(sum((a - b) ** 2 for a, b in zip(rgb(c), rgb(k))) ** 0.5 >= MIN_HUE_DISTANCE for k in kept):
            kept.append(c)
    return kept


CHILD_TINT = 0.3      # a sunburst's outer ring: its parent's colour, this much toward white


def _tint(color: str) -> str:
    return "".join(f"{round(int(color[i:i + 2], 16) + (255 - int(color[i:i + 2], 16)) * CHILD_TINT):02X}" for i in (0, 2, 4))


def brand_colors(n: int, t: DeckTokens) -> list[str]:
    """One colour per brand, client first in the deck's brand colour, rivals in hues that tell apart from it."""
    palette = _distinct([t.primary] + [f for f in t.series if not _neutral(f)] + list(RIVAL_HUES))
    return [palette[0] if j == 0 else palette[1 + (j - 1) % (len(palette) - 1)] for j in range(n)]


def _badge(name: str, t: DeckTokens) -> str:
    """The SVG chart's round initial for a label without a logo, as a picture amCharts can place beside the label."""
    initial = escape(next((ch for ch in str(name) if ch.isalnum()), "?").upper())
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30"><circle cx="15" cy="15" r="15" '
           f'fill="#{t.primary}"/><text x="15" y="21" text-anchor="middle" font-family="Arial" font-weight="700" '
           f'font-size="17" fill="#fff">{initial}</text></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode("ascii")


def _marks(names: list[str], t: DeckTokens, logos: dict[str, str], light) -> list[dict]:
    """Each label's logo (a white one on the dark chip) or, when any label has one, its initial: never a few gaps."""
    marked = any(n in logos for n in names)
    return [{"logo": logos.get(n) or (_badge(n, t) if marked else ""), "chip": f"#{_dark_chip(t)}" if n in light else ""}
            for n in names]


def chart_config(chart: dict, t: DeckTokens, logos: dict[str, str] | None = None, light=frozenset()) -> dict | None:
    """The amCharts config of one deck chart, or None for a chart amCharts does not draw (a KPI)."""
    logos = logos or {}
    kind = chart.get("kind")
    groups = (chart.get("breakdown") or {}).get("groups")
    if kind not in DRAWN and not groups:
        return None
    cats = [str(c) for c in chart.get("categories") or []]
    vals = [float(v) for v in chart.get("values") or []]
    base = {"kind": kind, "unit": chart.get("unit", "count"), "font": t.chrome_font or t.body_font,
            "text": f"#{t.text}", "muted": f"#{t.muted}", "primary": f"#{t.primary}", "label": chart.get("series_label") or "",
            "reason": chart.get("choice") or "", "alternatives": chart.get("alternatives") or ""}
    if groups:
        stacks = [str(s) for s in chart["breakdown"]["stacks"]]
        # share of voice stacks brands (client first): brand colours, not shades of the deck's one hue
        fills = brand_colors(len(stacks), t) if chart.get("kpis") else _colors(stacks, t)
        names = [str(g["name"]) for g in groups]
        rows = [{"category": f"{n} ({g['n']})" if g.get("n") else n, "key": n, **m,
                 **{f"s{i}": float(v) for i, v in enumerate(g["values"])}}
                for n, g, m in zip(names, groups, _marks(names, t, logos, light))]
        return {**base, "kind": "stacked", "data": rows,
                "stacks": [{"name": s, "field": f"s{i}", "color": f"#{c}", **m}
                           for i, (s, c, m) in enumerate(zip(stacks, fills, _marks(stacks, t, logos, light)))],
                "ink": [f"#{_on(c)}" for c in fills]}
    if kind == "us_map":
        return {**base, "color": f"#{t.series[0]}", "states": chart.get("states") or [], "note": chart.get("unlocated") or "",
                "counties": chart.get("counties") or []}
    view = chart.get("view") or kind
    if view == "multi_line":        # one line per brand: the client in the brand colour, rivals in the deck's hues
        series = chart["brand_series"]
        colors = brand_colors(len(series), t)
        names = [s["name"] for s in series]
        rows = [{"category": c, **{f"s{j}": s["values"][i] for j, s in enumerate(series)},
                 **{f"p{j}": i in set(s.get("peaks") or []) for j, s in enumerate(series)}} for i, c in enumerate(cats)]
        return {**base, "kind": "multi_line", "data": rows,
                "lines": [{"name": s["name"], "field": f"s{j}", "peak": f"p{j}", "client": bool(s.get("client")),
                           "color": f"#{colors[j]}", **m}
                          for j, (s, m) in enumerate(zip(series, _marks(names, t, logos, light)))]}
    if view == "sunburst":         # rings: the parts, then what each is made of (its children a lighter shade)
        tree = chart["hierarchy"]
        fills = _colors([p["name"] for p in tree], t)
        nodes = [{"name": p["name"], "key": p["name"], "col": {"fill": f"#{f}"},
                  "children": [{"name": k["name"], "key": f"{p['name']}\t{k['name']}", "value": k["value"],
                                "col": {"fill": f"#{_tint(f)}"}} for k in p["children"]]}
                 for p, f in zip(tree, fills)]
        return {**base, "kind": "sunburst", "unit": "count", "data":[{"name": chart.get("series_label") or "All", "children": nodes}]}
    if view in ("heatmap", "sankey"):
        m = chart["matrix"]
        cells = [{"row": r, "col": c, "value": round(100 * v / max(1, m["n"][i]), 1), "count": v}
                 for i, r in enumerate(m["rows"]) for c, v in zip(m["cols"], m["counts"][i]) if view == "heatmap" or v]
        # a sankey's brand (or outlet) nodes carry their logos, as a bar chart's labels do: outside the node, on its side
        marks = {n: {"logo": logos[n], "chip": f"#{_dark_chip(t)}" if n in light else "", "side": side}
                 for side, names in (("left", m["rows"]), ("right", m["cols"])) for n in names
                 if view == "sankey" and n in logos}
        return {**base, "kind": view, "rows": m["rows"], "cols": m["cols"], "cells": cells, "dims": m["dims"],
                "colors": [f"#{c}" for c in _colors(m["rows"] + m["cols"], t)], "low": f"#{t.surface}",
                **({"marks": marks} if marks else {})}
    if view == "bubble":
        tone = chart.get("tone") or [None] * len(cats)
        fills = [f for f in t.series if not _neutral(f)] or list(t.series)
        data = [{"category": c, "value": v, "tone": tn,
                 "color": _TONE_COLORS[(tn > TONE_SPLIT) - (tn < -TONE_SPLIT)] if tn is not None else f"#{fills[i % len(fills)]}"}
                for i, (c, v, tn) in enumerate(zip(cats, vals, tone))]
        return {**base, "kind": "bubble", "data": [{**d, "ink": "#FFFFFF"} for d in data],
                "toned": any(tn is not None for tn in tone)}
    top = max(vals, default=0) or 1
    peaks = set(chart.get("peaks") or [])
    if kind == "bar":
        data = [{"category": c, "value": v, "color": f"#{t.series[0]}", "opacity": round(0.45 + 0.55 * v / top, 2), **m}
                for c, v, m in zip(cats, vals, _marks(cats, t, logos, light))]
    elif kind in ("column", "line_peaks"):
        data = [{"category": c, "value": v, "peak": i in peaks,
                 "color": f"#{t.primary if i in peaks and kind == 'column' else t.series[0]}"}
                for i, (c, v) in enumerate(zip(cats, vals))]
    elif kind == "doughnut":
        data = [{"category": c, "value": v, "color": f"#{col}"} for c, v, col in zip(cats, vals, _colors(cats, t))]
    else:        # treemap: the deck's hues only, as the SVG draws it (a white tile vanishes into the slide)
        fills = [f for f in t.series if not _neutral(f)] or list(t.series)
        pairs = sorted(((c, v) for c, v in zip(cats, vals) if v > 0), key=lambda p: -p[1])
        data = [{"category": c, "value": v, "color": f"#{fills[i % len(fills)]}", "ink": f"#{_on(fills[i % len(fills)])}"}
                for i, (c, v) in enumerate(pairs)]
    return {**base, "data": data, "accent": f"#{t.series[0]}"}


def deck_configs(slides, tokens: DeckTokens, logos_of) -> dict[str, list[dict | None]]:
    """{slide id: [config per chart]} for every slide with a chart; `logos_of(slide)` gives (logos, light)."""
    out = {}
    for s in slides:
        if s.charts:
            logos, light = logos_of(s)
            out[s.id] = [chart_config(c, tokens, logos, light) for c in s.charts]
    return out


def _inline(name: str) -> str:
    return (VENDOR / name).read_text(encoding="utf-8").replace("</script", "<\\/script")


def scripts(configs: dict, maps: bool) -> str:
    """The <script> blocks deck.html carries: the amCharts bundle (and the US geodata when a map needs it), the
    deck's chart configs and the code that draws them. '' when no chart is drawn by amCharts."""
    if not any(c for cs in configs.values() for c in cs):
        return ""
    files = ["amcharts5.bundle.js"] + (["amcharts5.usa.js"] if maps else []) + ["deckcharts.js"]
    data = json.dumps(configs).replace("</", "<\\/")
    blocks = [f'<script type="application/json" id="deck-charts">{data}</script>']
    blocks += [f"<script>{_inline(f)}</script>" for f in files]
    return "\n".join(blocks)
