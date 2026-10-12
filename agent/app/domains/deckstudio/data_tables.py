"""The supporting data tables behind the deck, as an Excel workbook: each question's answer, every chart's and
table's numbers, and the cited sources with their links. Written from the same computed sections as the slides."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .planner import BRAND_KEY, BRAND_KICKER, PlanInput

FILE_SUFFIX = " - Data.xlsx"
_BOLD = Font(bold=True)


def _heading(ws, text: str) -> None:
    ws.append([text])
    ws.cell(ws.max_row, 1).font = _BOLD


def _sections(ws, sections) -> None:
    for s in sections:
        if s.skipped or not (s.chart or s.table):
            continue
        _heading(ws, s.title)
        if s.chart and s.chart.get("kind") != "kpi":
            ws.append([s.chart.get("series_label") or "Category", "Value" + (" (%)" if s.chart.get("unit") == "percent" else "")])
            for category, value in zip(s.chart.get("categories") or [], s.chart.get("values") or []):
                ws.append([category, value])
        if s.table:
            ws.append(list(s.table.get("header") or []))
            for row in s.table.get("rows") or []:
                ws.append(list(row))
        for fact in s.facts:
            ws.append([fact])
        ws.append([])


def write_workbook(inp: PlanInput, folder: Path) -> Path:
    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary.append(["Question", "Answer", "Headline figure"])
    for a in inp.answers:
        summary.append([a.get("question"), a.get("answer"), a.get("value")])
    for k, rq in enumerate(inp.rqs, start=1):
        ws = wb.create_sheet(f"Q{k}")
        _heading(ws, rq.question)
        ws.append([])
        _sections(ws, inp.sections_by_rq.get(rq.id, []))
    if inp.sections_by_rq.get(BRAND_KEY):
        _sections(wb.create_sheet(BRAND_KICKER[:31]), inp.sections_by_rq[BRAND_KEY])
    sources = wb.create_sheet("Sources")
    sources.append(["#", "Outlet", "Headline", "Date", "Link"])
    for c in inp.citations:
        sources.append([c.get("n"), c.get("outlet") or c.get("domain"), c.get("title"), c.get("date"), c.get("url")])
    for ws in wb.worksheets:
        ws.column_dimensions["A"].width = 60
        ws.column_dimensions["B"].width = 40
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in inp.title if ch.isalnum() or ch in " -_").strip() or "Deck"
    out = folder / f"{safe}{FILE_SUFFIX}"
    wb.save(out)
    return out
