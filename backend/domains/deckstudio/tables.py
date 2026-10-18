"""How many table rows a slide's table area holds, and long tables carried onto continuation slides, so a table is
never clipped by its panel. Cells hold at most two lines (table.html.j2 clamps them), so a row's height is known."""
from __future__ import annotations

from dataclasses import replace

from .spec import SlideSpec

ROW_PX = 66                 # two 17px lines at 1.35 line height, plus cell padding
HEADER_PX = 50
# usable table height (px) by layout: treatment, and whether insight cards share the slide
AREA_PX = {("A", False): 580, ("A", True): 580, ("C", False): 640, ("C", True): 360,
           ("S", False): 660, ("S", True): 660}
PLAIN_AREA_PX = 780
MIN_ROWS = 3
ORPHAN_ROWS = 2             # rows over the cap that stay on the slide instead of starting a continuation
# slides with their own pagination or a fixed layout (brief checklist, sources, query table, scope)
OWN_LAYOUT = ("checklist", "citations", "scorecard", "methodology", "objectives")


def rows_cap(slide: SlideSpec) -> int:
    area = AREA_PX.get((slide.treatment, bool(slide.cards)), PLAIN_AREA_PX)
    return max(MIN_ROWS, (area - HEADER_PX) // ROW_PX)


def render_cap(slide: SlideSpec) -> int:
    """Rows drawn: the cap, plus the orphan rows `paginate` kept on an evidence table's slide."""
    paginated = slide.tables and not slide.charts and slide.type not in OWN_LAYOUT
    return rows_cap(slide) + (ORPHAN_ROWS if paginated else 0)


def paginate(slides: list[SlideSpec]) -> list[SlideSpec]:
    """Each evidence table longer than its slide holds continues on the next slide (the insight cards stay with the
    first part, the rest carry the remaining rows); nothing is dropped and nothing is clipped."""
    out = []
    for s in slides:
        table = s.tables[0] if s.tables and not s.charts and s.type not in OWN_LAYOUT else None
        cap = rows_cap(s) if table else 0
        # one or two rows left over stay on the slide (the cap keeps a margin) rather than a near-empty continuation
        if not table or len(table.get("rows") or []) <= cap + ORPHAN_ROWS:
            out.append(s)
            continue
        rows, links = table["rows"], table.get("links") or []
        out.append(replace(s, tables=[{**table, "rows": rows[:cap], "links": links[:cap]}]))
        rest = replace(s, cards=[], citations=[])
        step = rows_cap(rest)
        for k, start in enumerate(range(cap, len(rows), step), start=1):
            out.append(replace(rest, id=f"{s.id}-cont-{k}", title=f"{s.title} (continued)",
                               tables=[{**table, "rows": rows[start:start + step],
                                        "links": links[start:start + step]}]))
    return out
