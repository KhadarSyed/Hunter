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


def choose(chart: dict | None, question: str = "") -> dict | None:
    """The chart with the kind that fits its data and question, and the reason (shown in the run log)."""
    if not chart:
        return chart
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
        return {**chart, "kind": "kpi", "values": [share], "unit": "percent",
                "choice": f"{SINGLE}: only {chart['categories'][0]} is named, shown as its share"}
    else:
        why = "one figure" if rel == SINGLE else f"{len(chart['breakdown']['groups'])} groups"
    return {**chart, "kind": kind, "choice": f"{rel}: {why}"}
