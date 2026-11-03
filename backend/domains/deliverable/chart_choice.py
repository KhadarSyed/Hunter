"""Which chart a result is drawn as, decided from what its numbers are and what the question asks -- the
industry-standard chart choosers (FT Visual Vocabulary, Abela's chart chooser) applied to every analysis:

  change over time       -> a line (6+ points, peaks annotated), columns for a short series
  part-to-whole          -> a doughnut for 2-4 parts, sorted bars for 5-7, a treemap for 8+
                            (only when the parts are exclusive and add up to the whole)
  ranking / magnitude    -> sorted horizontal bars (an article can count in several categories, so the values are
                            not parts of one whole: a doughnut or treemap would mislead)
  composition per group  -> one 100% stacked bar per group
  a single figure        -> the figure itself (KPI or gauge)

A question that asks to compare or rank ("vs", "competitive", "top", "share of voice") gets bars even for parts of a
whole: position on a common axis is read more accurately than angles or areas (Cleveland & McGill)."""
from __future__ import annotations

import re

TIME, PART, RANK, GROUPS, SINGLE = "change over time", "part-to-whole", "ranking", "composition per group", "single figure"
LINE_MIN_POINTS = 6
DOUGHNUT_MAX_PARTS = 4
TREEMAP_MIN_PARTS = 8
PERCENT_WHOLE = (99.0, 101.0)        # rounded shares of one whole add up to 100 within rounding
_COMPARE = re.compile(r"\bcompar|\bvs\.?\b|versus|\brank|\btop\b|\bmost\b|\bleading\b|competit|benchmark|"
                      r"share of voice|\bsov\b|against", re.I)
# fixed splits of one whole: a question comparing brands does not make Positive / Neutral / Negative a ranking
_COMPOSITION = {"positive", "neutral", "negative", "mixed", "yes", "no", "unknown", "not stated", "social",
                "editorial", "independent", "brand-affiliated"}


def relation(chart: dict) -> str:
    """What the chart's numbers are, read from the numbers themselves (not from the chart kind a module proposed)."""
    kind = chart.get("kind")
    if (chart.get("breakdown") or {}).get("groups"):
        return GROUPS
    if kind in ("kpi", "gauge"):
        return SINGLE
    if kind in ("line_peaks", "column"):
        return TIME
    values = [float(v) for v in chart.get("values") or []]
    if len(values) < 2:
        return SINGLE
    total, unit = sum(values), chart.get("unit", "count")
    if unit == "percent" and PERCENT_WHOLE[0] <= total <= PERCENT_WHOLE[1]:
        return PART
    if unit == "count" and chart.get("n") and round(total) == int(chart["n"]):
        return PART                  # every article counted once: the categories split the whole
    if unit == "count" and _fixed_split(chart) and (not chart.get("n") or total <= int(chart["n"])):
        return PART                  # one label per article (sentiment): the labelled articles are the whole
    return RANK


def _fixed_split(chart: dict) -> bool:
    return all(str(c).strip().lower() in _COMPOSITION for c in chart.get("categories") or [])


_THEMES = re.compile(r"theme|topic", re.I)
_FLOW = re.compile(r"award|affiliat|endors|sponsor|partner|flow|lead(s)? to|result(s|ed)? in", re.I)
# what else fits each drawn kind, recorded beside the choice ("why this chart")
ALTERNATIVES = {"line_peaks": "columns (too many points to read as bars)", "column": "a line (too few points)",
                "doughnut": "sorted bars (fine too; a few parts read at a glance as a whole)",
                "treemap": "sorted bars (many parts: areas still show the whole)",
                "bar": "a doughnut or treemap (the values overlap, so they are not parts of one whole)",
                "stacked": "grouped bars (harder to compare each group's mix)", "kpi": "a one-bar chart (compares nothing)",
                "gauge": "a one-bar chart (compares nothing)",
                "us_map": "bars of the top states (lose where they are)",
                "bubble": "a treemap or sorted bars (no room for the tone of each theme)",
                "heatmap": "a heat table or grouped bars (one bar per cell is unreadable)",
                "sankey": "a heatmap (shows the cells, not the flow from one side to the other)",
                "multi_line": "one total line (hides which brand drives each peak)"}
SECOND_BRAND_SHARE = 0.1     # a second brand in a tenth of the articles: the rows carry several brands
MULTI_LINE_MIN_POINTS = 3


def _brand_trend(chart: dict, question: str) -> str | None:
    """Why the trend is drawn as a line per brand, or None: the question compares brands, or its rows carry several."""
    series = chart.get("brand_series") or []
    if len(series) < 2 or len(chart.get("categories") or []) < MULTI_LINE_MIN_POINTS:
        return None
    total = sum(chart.get("values") or []) or 1
    if _COMPARE.search(question or ""):
        return f"trend + comparison: one line per brand ({len(series)} brands), the client's peaks marked"
    if sum(series[1]["values"]) >= SECOND_BRAND_SHARE * total:
        return f"trend of several brands: {len(series)} brands each as a line, the client's peaks marked"
    return None


def _view(chart: dict, question: str, section_id: str) -> dict:
    """The deck's drawing of a chart chosen by the question's intent (themes -> bubbles); `kind` stays the plain
    chart the classic deck, the insight writer and the static fallback read."""
    parts = len(chart.get("categories") or [])
    if chart.get("kpis") and (chart.get("breakdown") or {}).get("groups"):     # share of voice (analytics.sov_split)
        by = chart["breakdown"]["by"]
        return {**chart, "choice": f"share of voice: the brands' mix per {by} as 100% bars, the client's share, rank "
                                   f"and change as KPI tiles above", "alternatives": ALTERNATIVES["stacked"]}
    if chart["kind"] in ("line_peaks", "column") and (why := _brand_trend(chart, question)):
        return {**chart, "view": "multi_line", "choice": why, "alternatives": ALTERNATIVES["multi_line"]}
    if chart["kind"] in ("bar", "treemap", "doughnut") and parts >= 3 and _THEMES.search(section_id) and not chart.get("breakdown"):
        toned = chart.get("tone") and any(t is not None for t in chart["tone"])
        why = f"themes: {parts} themes as bubbles sized by volume" + (", coloured by net sentiment" if toned else "")
        return {**chart, "view": "bubble", "choice": why, "alternatives": ALTERNATIVES["bubble"]}
    return {**chart, "alternatives": ALTERNATIVES.get(chart["kind"], "")}


def matrix_chart(matrix: dict, question: str, dims: tuple[str, str]) -> dict:
    """A cross-tab (rows x columns of article counts) as the deck draws it: a flow (brand -> award) as a Sankey,
    a fixed split (sentiment, social/editorial) as one 100% bar per row, anything else as a heatmap. Its kind is that
    drawing (not "bar"): a cross-tab's rows are not chart segments that each need their own insight card."""
    rows, cols, counts = matrix["rows"], matrix["cols"], matrix["counts"]
    base = {"categories": rows, "values": [sum(r) for r in counts], "unit": "count", "peaks": [],
            "series_label": "Articles", "matrix": matrix, **({"n": matrix["total"]} if matrix.get("total") else {})}
    label = f"{dims[1]} by {dims[0]}"
    if all(str(c).strip().lower() in _COMPOSITION for c in cols):
        groups = [{"name": r, "n": matrix["n"][i], "values": [round(100 * v / max(1, sum(counts[i])), 1) for v in counts[i]]}
                  for i, r in enumerate(rows)]
        return {**base, "kind": "stacked", "breakdown": {"by": dims[0], "stacks": cols, "groups": groups},
                "choice": f"{GROUPS}: {label}, a fixed split per {dims[0].lower()} as 100% bars",
                "alternatives": ALTERNATIVES["stacked"]}
    if _FLOW.search(question) or _FLOW.search(" ".join(dims)):
        return {**base, "kind": "sankey", "choice": f"flow: {label}, each band as wide as its articles",
                "alternatives": ALTERNATIVES["sankey"]}
    return {**base, "kind": "heatmap", "choice": f"two dimensions: {label}, each cell shaded by its share",
            "alternatives": ALTERNATIVES["heatmap"]}


def choose(chart: dict | None, question: str = "", section_id: str = "") -> dict | None:
    """The chart with the kind that fits its data and question, and the reason (shown in the run log)."""
    if not chart:
        return chart
    if chart.get("kind") == "us_map":      # a map was chosen for its geography (its own "choice")
        return {**chart, "alternatives": ALTERNATIVES["us_map"]}
    return _view(_kind(chart, question), question, section_id)


def _kind(chart: dict, question: str) -> dict:
    rel, parts = relation(chart), len(chart.get("categories") or [])
    kind = chart.get("kind")
    if rel == TIME:
        kind = "line_peaks" if parts >= LINE_MIN_POINTS else "column"
        why = f"{parts} time points"
    elif rel == PART and _COMPARE.search(question or "") and parts >= 3 and not _fixed_split(chart):
        kind, why = "bar", f"{parts} parts, and the question compares them"
    elif rel == PART:
        kind = "doughnut" if parts <= DOUGHNUT_MAX_PARTS else "treemap" if parts >= TREEMAP_MIN_PARTS else "bar"
        why = f"{parts} exclusive parts of one whole"
    elif rel == RANK:
        kind, why = "bar", f"{parts} categories that overlap (not one whole)"
    elif rel == SINGLE and kind not in ("kpi", "gauge") and parts == 1 and chart.get("n"):
        # a one-bar chart compares nothing: the figure itself, as a share of the question's articles
        share = round(100 * float(chart["values"][0]) / int(chart["n"]), 1)
        return {**chart, "kind": "kpi", "values": [share], "unit": "percent", "counts": chart["values"],
                "choice": f"{SINGLE}: only {chart['categories'][0]} is named, shown as its share"}
    else:
        why = "one figure" if rel == SINGLE else f"{len(chart['breakdown']['groups'])} groups"
    return {**chart, "kind": kind, "choice": f"{rel}: {why}"}
