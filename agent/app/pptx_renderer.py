"""PowerPoint Renderer — transforms an approved Presentation Model into a
branded .pptx file.

This module makes ZERO strategic or editorial decisions. All content decisions
were already made by the Presentation Composer (Stage 10). The renderer is
responsible ONLY for faithfully rendering the Presentation Model into slides.

Architecture mirrors deck_builder.py patterns but reads from the PC model
instead of the pipeline DeckPlan.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Optional

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt, Emu

from . import intelligence_store as store
from . import config

logger = logging.getLogger(__name__)

VALID_JOB_TYPES = {"full", "slide", "section"}
VALID_JOB_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}

# ── Brand colours (from Hunter PR reference decks) ───────────────────

VIOLET = RGBColor(0x5B, 0x2C, 0x9D)
BRAND_VIOLET = RGBColor(0x5E, 0x35, 0xB1)
RED = RGBColor(0xDE, 0x2A, 0x00)
BLUE = RGBColor(0xA6, 0xCA, 0xEC)
LT_PURPLE = RGBColor(0xD1, 0xC4, 0xE9)
GREEN = RGBColor(0x4E, 0xA7, 0x2E)
TEAL = RGBColor(0x15, 0x60, 0x82)
PINK = RGBColor(0xA0, 0x2B, 0x93)
DK_GREEN = RGBColor(0x19, 0x6B, 0x24)
BLACK = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x6E, 0x6E, 0x6E)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CARD_BG = RGBColor(0xF5, 0xF0, 0xFA)

SERIES_PALETTE = [BRAND_VIOLET, TEAL, PINK, GREEN, DK_GREEN, RED, BLUE, LT_PURPLE]

SLIDE_WIDTH_INCHES = 13.333
SLIDE_HEIGHT_INCHES = 7.5


# ── Theme resolution ────────────────────────────────────────────────

def _resolve_theme(theme_id: str = "hunter_default") -> dict:
    store.ensure_default_theme()
    theme = store.get_theme(theme_id)
    if not theme:
        theme = store.get_theme("hunter_default")
    if not theme:
        return {
            "primary_color": "#5B2C9D",
            "secondary_color": "#5E35B1",
            "accent_color": "#A6CAEC",
            "background_color": "#FFFFFF",
            "text_color": "#1A1A1A",
            "font_heading": "Calibri",
            "font_body": "Calibri",
            "font_size_title": 26,
            "font_size_body": 14,
            "font_size_caption": 9,
        }
    return theme


def _hex_to_rgb(hex_str: str) -> RGBColor:
    h = hex_str.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ── Layout engine ───────────────────────────────────────────────────

def _blank_layout(prs: Presentation):
    for layout in prs.slide_masters[0].slide_layouts:
        if layout.name.strip().lower() == "blank":
            return layout
    return prs.slide_masters[0].slide_layouts[-1]


REGION_COVER = {
    "title": (0.8, 2.0, 11.7, 1.5),
    "subtitle": (0.8, 3.6, 11.7, 0.8),
    "date": (0.8, 4.5, 5.0, 0.5),
}

REGION_CONTENT = {
    "eyebrow": (0.3, 0.15, 12.7, 0.22),
    "title": (0.3, 0.35, 7.0, 0.4),
    "takeaway": (7.6, 0.15, 5.5, 0.55),
    "body": (0.3, 0.85, 12.7, 5.8),
    "body_left": (0.3, 0.85, 6.0, 5.8),
    "body_right": (6.7, 0.85, 6.3, 5.8),
    "chart": (0.3, 0.85, 12.7, 5.8),
    "chart_left": (0.3, 0.85, 8.0, 5.8),
    "chart_right": (8.6, 0.85, 4.4, 5.8),
    "footer": (0.3, 7.0, 12.7, 0.3),
    "source": (0.3, 7.28, 12.7, 0.18),
    "slide_number": (12.3, 7.0, 0.7, 0.3),
}

REGION_DIVIDER = {
    "title": (0.8, 2.5, 11.7, 1.2),
    "subtitle": (0.8, 3.7, 11.7, 0.5),
}

# ── SOV archetype regions ──────────────────────────────────────────
# Slide: 13.333" × 7.5"  (widescreen)
# Layout: context label + title row, takeaway band, donut left + trend right,
#         competitor narrative columns across bottom, source footer

REGION_SOV = {
    "context_label": (0.3, 0.12, 12.7, 0.18),
    "title":         (0.3, 0.30, 7.0, 0.38),
    "takeaway":      (0.3, 0.72, 12.7, 0.65),
    "donut":         (0.3, 1.50, 5.5, 3.4),
    "trend":         (6.1, 1.50, 6.9, 3.4),
    "sample_size":   (10.5, 4.85, 2.5, 0.22),
    "narratives":    (0.3, 5.10, 12.7, 1.80),
    "source":        (0.3, 7.00, 12.7, 0.18),
    "slide_number":  (12.3, 7.00, 0.7, 0.3),
}

# ── Theme archetype regions ────────────────────────────────────────
# Layout: context label + entity title, takeaway right, bar chart left +
#         theme trend right, theme narrative columns across bottom

REGION_THEME = {
    "context_label":  (0.3, 0.12, 12.7, 0.18),
    "title":          (0.3, 0.30, 7.0, 0.38),
    "takeaway":       (7.6, 0.30, 5.4, 1.10),
    "bar_chart":      (0.3, 1.50, 5.5, 3.3),
    "theme_trend":    (6.1, 1.50, 6.9, 3.3),
    "sample_size":    (10.5, 4.75, 2.5, 0.22),
    "narratives":     (0.3, 5.00, 12.7, 1.90),
    "source":         (0.3, 7.00, 12.7, 0.18),
    "slide_number":   (12.3, 7.00, 0.7, 0.3),
}


def _get_region(region_name: str, layout_type: str = "content") -> tuple:
    if layout_type == "cover":
        return REGION_COVER.get(region_name, REGION_CONTENT.get(region_name, (0.3, 0.85, 12.7, 5.8)))
    if layout_type == "divider":
        return REGION_DIVIDER.get(region_name, REGION_CONTENT.get(region_name, (0.3, 0.85, 12.7, 5.8)))
    return REGION_CONTENT.get(region_name, (0.3, 0.85, 12.7, 5.8))


# ── Text engine ─────────────────────────────────────────────────────

def _add_textbox(slide, left, top, width, height, text, font_size=14,
                 bold=False, italic=False, color=None, alignment=None,
                 word_wrap=True):
    box = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = word_wrap
    p = tf.paragraphs[0]
    if alignment:
        p.alignment = alignment
    run = p.add_run()
    run.text = str(text)
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.italic = italic
    if color:
        run.font.color.rgb = color
    return box


def _add_eyebrow(slide, text: str, theme: dict):
    r = _get_region("eyebrow")
    _add_textbox(slide, *r, text.upper(),
                 font_size=theme.get("font_size_caption", 9),
                 bold=True, color=_hex_to_rgb(theme.get("primary_color", "#5B2C9D")))


def _add_slide_title(slide, text: str, theme: dict):
    r = _get_region("title")
    _add_textbox(slide, *r, text,
                 font_size=theme.get("font_size_title", 26) - 11,
                 bold=True, color=BLACK)


def _add_takeaway(slide, text: str):
    r = _get_region("takeaway")
    shape = slide.shapes.add_shape(
        5, Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]))
    shape.fill.solid()
    shape.fill.fore_color.rgb = CARD_BG
    shape.line.color.rgb = LT_PURPLE
    shape.line.width = Pt(0.5)
    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.12)
    tf.margin_right = Inches(0.12)
    tf.margin_top = Inches(0.06)
    tf.margin_bottom = Inches(0.06)
    run = tf.paragraphs[0].add_run()
    run.text = text
    run.font.size = Pt(9)
    run.font.color.rgb = BLACK


def _add_source_footer(slide, source_text: str, slide_number: int = 0):
    r = _get_region("source")
    _add_textbox(slide, *r, source_text,
                 font_size=7, italic=True, color=GREY,
                 alignment=PP_ALIGN.RIGHT)
    if slide_number > 0:
        nr = _get_region("slide_number")
        _add_textbox(slide, *nr, str(slide_number),
                     font_size=8, color=GREY, alignment=PP_ALIGN.RIGHT)


def _add_body_text(slide, paragraphs: list[str], region: str = "body",
                   font_size: int = 14, color=None):
    r = _get_region(region)
    box = slide.shapes.add_textbox(
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]))
    tf = box.text_frame
    tf.word_wrap = True
    for i, para_text in enumerate(paragraphs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text = str(para_text)
        run.font.size = Pt(font_size)
        run.font.color.rgb = color or BLACK
        p.space_after = Pt(8)
    return box


def _add_bullet_list(slide, items: list[str], region: str = "body",
                     font_size: int = 12):
    r = _get_region(region)
    box = slide.shapes.add_textbox(
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]))
    tf = box.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        prefix = "" if str(item).startswith("•") else "•  "
        run.text = f"{prefix}{item}"
        run.font.size = Pt(font_size)
        run.font.color.rgb = BLACK
        p.space_after = Pt(4)
    return box


def _add_speaker_notes(slide, notes_text: str):
    if not notes_text:
        return
    notes = notes_text
    # Strip LLM preamble artifacts
    for prefix in ["Certainly!", "Sure!", "Here's", "Here are", "Of course!"]:
        if notes.startswith(prefix):
            # Skip to next sentence
            idx = notes.find(". ", len(prefix))
            if idx > 0:
                notes = notes[idx + 2:]
            break
    # Remove meta-coaching phrases
    notes = notes.replace("For your audience on the", "On the")
    notes = notes.replace("you can start by highlighting", "highlight")
    notes = notes.replace("Great start! ", "")
    notes_slide = slide.notes_slide
    tf = notes_slide.notes_text_frame
    tf.text = notes


# ── Chart engine ────────────────────────────────────────────────────

def _render_bar_chart(slide, data: dict, region: str = "chart"):
    r = _get_region(region)
    chart_data = CategoryChartData()
    categories = data.get("categories", ["A", "B", "C"])
    chart_data.categories = categories
    for series in data.get("series", [{"name": "Value", "values": [1, 2, 3]}]):
        vals = series.get("values", [0] * len(categories))
        chart_data.add_series(series.get("name", "Series"), vals)
    chart_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
        chart_data)
    chart = chart_frame.chart
    chart.has_legend = len(data.get("series", [])) > 1
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(8)
    for i, series in enumerate(chart.series):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
    return chart_frame


def _render_stacked_bar(slide, data: dict, region: str = "chart"):
    r = _get_region(region)
    chart_data = CategoryChartData()
    categories = data.get("categories", ["A", "B", "C"])
    chart_data.categories = categories
    for series in data.get("series", [{"name": "V1", "values": [1, 2, 3]}]):
        vals = series.get("values", [0] * len(categories))
        chart_data.add_series(series.get("name", "Series"), vals)
    chart_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.BAR_STACKED,
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
        chart_data)
    chart = chart_frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    for i, series in enumerate(chart.series):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
    return chart_frame


def _render_line_chart(slide, data: dict, region: str = "chart"):
    r = _get_region(region)
    chart_data = CategoryChartData()
    categories = data.get("categories", ["Q1", "Q2", "Q3", "Q4"])
    chart_data.categories = categories
    for series in data.get("series", [{"name": "Trend", "values": [10, 20, 15, 25]}]):
        vals = series.get("values", [0] * len(categories))
        chart_data.add_series(series.get("name", "Series"), vals)
    chart_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.LINE_MARKERS,
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
        chart_data)
    chart = chart_frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    for i, series in enumerate(chart.series):
        series.format.line.color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
        series.format.line.width = Pt(2)
    return chart_frame


def _render_pie_chart(slide, data: dict, region: str = "chart"):
    r = _get_region(region)
    chart_data = CategoryChartData()
    categories = data.get("categories", ["A", "B", "C"])
    chart_data.categories = categories
    values = data.get("values", [40, 35, 25])
    chart_data.add_series("", values)
    chart_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.PIE,
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
        chart_data)
    chart = chart_frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.RIGHT
    chart.legend.include_in_layout = False
    plot = chart.plots[0]
    for i in range(len(categories)):
        point = plot.series[0].points[i]
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
    return chart_frame


def _render_donut_chart(slide, data: dict, region: str = "chart"):
    r = _get_region(region)
    chart_data = CategoryChartData()
    categories = data.get("categories", ["Positive", "Neutral", "Negative"])
    chart_data.categories = categories
    values = data.get("values", [45, 35, 20])
    chart_data.add_series("", values)
    chart_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.DOUGHNUT,
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
        chart_data)
    chart = chart_frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.RIGHT
    chart.legend.include_in_layout = False
    plot = chart.plots[0]
    for i in range(len(categories)):
        point = plot.series[0].points[i]
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
    return chart_frame


def _render_area_chart(slide, data: dict, region: str = "chart"):
    r = _get_region(region)
    chart_data = CategoryChartData()
    categories = data.get("categories", ["Jan", "Feb", "Mar", "Apr"])
    chart_data.categories = categories
    for series in data.get("series", [{"name": "Volume", "values": [100, 150, 120, 180]}]):
        vals = series.get("values", [0] * len(categories))
        chart_data.add_series(series.get("name", "Series"), vals)
    chart_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.AREA,
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
        chart_data)
    chart = chart_frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    for i, series in enumerate(chart.series):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
    return chart_frame


def _render_scatter_chart(slide, data: dict, region: str = "chart"):
    from pptx.chart.data import XyChartData
    r = _get_region(region)
    chart_data = XyChartData()
    for series in data.get("series", [{"name": "Data", "points": [(1, 2), (3, 4), (5, 3)]}]):
        s = chart_data.add_series(series.get("name", "Series"))
        for pt in series.get("points", []):
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                s.add_data_point(pt[0], pt[1])
    chart_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.XY_SCATTER,
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
        chart_data)
    return chart_frame


def _render_bubble_chart(slide, data: dict, region: str = "chart"):
    from pptx.chart.data import BubbleChartData
    r = _get_region(region)
    chart_data = BubbleChartData()
    for series in data.get("series", [{"name": "Data", "points": [(1, 2, 10), (3, 4, 20)]}]):
        s = chart_data.add_series(series.get("name", "Series"))
        for pt in series.get("points", []):
            if isinstance(pt, (list, tuple)) and len(pt) >= 3:
                s.add_data_point(pt[0], pt[1], pt[2])
    chart_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.BUBBLE,
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
        chart_data)
    return chart_frame


CHART_RENDERERS = {
    "bar_chart": _render_bar_chart,
    "stacked_bar": _render_stacked_bar,
    "grouped_bar": _render_bar_chart,
    "line_chart": _render_line_chart,
    "area": _render_area_chart,
    "scatter": _render_scatter_chart,
    "bubble": _render_bubble_chart,
    "pie": _render_pie_chart,
    "donut": _render_donut_chart,
}


def _render_chart(slide, visual_type: str, data: dict, region: str = "chart"):
    renderer = CHART_RENDERERS.get(visual_type)
    if renderer:
        return renderer(slide, data, region)
    return _render_bar_chart(slide, data, region)


# ── Table engine ────────────────────────────────────────────────────

def _render_table(slide, data: dict, region: str = "body"):
    r = _get_region(region)
    headers = data.get("headers", [])
    rows_data = data.get("rows", [])
    if not headers and not rows_data:
        return None

    n_rows = len(rows_data) + (1 if headers else 0)
    n_cols = len(headers) if headers else (len(rows_data[0]) if rows_data else 1)

    table_shape = slide.shapes.add_table(
        n_rows, n_cols,
        Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(min(r[3], n_rows * 0.45)))
    table = table_shape.table

    if headers:
        for ci, h in enumerate(headers):
            cell = table.cell(0, ci)
            cell.text = str(h)
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(10)
                    run.font.bold = True
                    run.font.color.rgb = WHITE
                p.alignment = PP_ALIGN.CENTER
            cell.fill.solid()
            cell.fill.fore_color.rgb = BRAND_VIOLET

    row_offset = 1 if headers else 0
    for ri, row in enumerate(rows_data):
        for ci, val in enumerate(row):
            if ci >= n_cols:
                break
            cell = table.cell(ri + row_offset, ci)
            cell.text = str(val)
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9)
                    run.font.color.rgb = BLACK
            if ri % 2 == 1:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(0xF8, 0xF6, 0xFB)

    return table_shape


# ── KPI cards engine ────────────────────────────────────────────────

def _render_kpi_cards(slide, items: list[dict], region: str = "body"):
    r = _get_region(region)
    n = len(items) if items else 0
    if n == 0:
        return

    tile_w = min(2.8, r[2] / n - 0.2)
    gap = 0.2
    total = n * tile_w + (n - 1) * gap
    start_x = r[0] + (r[2] - total) / 2
    tile_h = min(2.8, r[3])

    for i, item in enumerate(items):
        x = start_x + i * (tile_w + gap)
        shape = slide.shapes.add_shape(
            5, Inches(x), Inches(r[1]), Inches(tile_w), Inches(tile_h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = CARD_BG
        shape.line.color.rgb = LT_PURPLE
        shape.line.width = Pt(0.5)

        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.12)
        tf.margin_top = Inches(0.25)

        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        run = p.add_run()
        run.text = str(item.get("value", "--"))
        run.font.size = Pt(28)
        run.font.bold = True
        run.font.color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]

        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        run2 = p2.add_run()
        run2.text = str(item.get("label", ""))
        run2.font.size = Pt(10)
        run2.font.bold = True
        run2.font.color.rgb = BLACK


# ── Timeline engine ─────────────────────────────────────────────────

def _render_timeline(slide, items: list[dict], region: str = "body"):
    r = _get_region(region)
    n = len(items) if items else 0
    if n == 0:
        return

    line_y = r[1] + r[3] / 2
    slide.shapes.add_shape(
        1, Inches(r[0] + 0.3), Inches(line_y), Inches(r[2] - 0.6), Inches(0.02))

    spacing = (r[2] - 0.6) / max(n - 1, 1)
    for i, item in enumerate(items):
        x = r[0] + 0.3 + i * spacing
        dot = slide.shapes.add_shape(
            9, Inches(x - 0.1), Inches(line_y - 0.1), Inches(0.2), Inches(0.2))
        dot.fill.solid()
        dot.fill.fore_color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
        dot.line.fill.background()

        _add_textbox(slide, x - 0.6, line_y - 0.6, 1.2, 0.4,
                     str(item.get("date", "")),
                     font_size=8, bold=True, color=BLACK,
                     alignment=PP_ALIGN.CENTER)
        _add_textbox(slide, x - 0.8, line_y + 0.2, 1.6, 0.5,
                     str(item.get("label", "")),
                     font_size=8, color=GREY,
                     alignment=PP_ALIGN.CENTER)


# ── Matrix / comparison engine ──────────────────────────────────────

def _render_matrix(slide, data: dict, region: str = "body"):
    items = data.get("items", [])
    if not items:
        return _render_table(slide, data, region)
    table_data = {
        "headers": data.get("headers", ["Dimension", "Assessment", "Impact"]),
        "rows": [[it.get("dimension", ""), it.get("assessment", ""),
                   it.get("impact", "")] for it in items],
    }
    return _render_table(slide, table_data, region)


# ── Funnel engine ───────────────────────────────────────────────────

def _render_funnel(slide, stages: list[dict], region: str = "body"):
    r = _get_region(region)
    n = len(stages) if stages else 0
    if n == 0:
        return

    stage_h = min(r[3] / n, 0.8)
    max_w = r[2] - 1.0
    for i, stage in enumerate(stages):
        ratio = 1.0 - (i / max(n, 1)) * 0.6
        w = max_w * ratio
        x = r[0] + (r[2] - w) / 2
        y = r[1] + i * (stage_h + 0.1)

        shape = slide.shapes.add_shape(
            5, Inches(x), Inches(y), Inches(w), Inches(stage_h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
        shape.line.fill.background()

        tf = shape.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        run = p.add_run()
        label = stage.get("label", f"Stage {i + 1}")
        value = stage.get("value", "")
        run.text = f"{label}: {value}" if value else label
        run.font.size = Pt(11)
        run.font.bold = True
        run.font.color.rgb = WHITE


# ── Network diagram engine (simplified) ─────────────────────────────

def _render_network(slide, data: dict, region: str = "body"):
    nodes = data.get("nodes", [])
    r = _get_region(region)
    if not nodes:
        return

    n = len(nodes)
    import math
    cx, cy = r[0] + r[2] / 2, r[1] + r[3] / 2
    radius = min(r[2], r[3]) / 3
    positions = []
    for i in range(n):
        angle = 2 * math.pi * i / n - math.pi / 2
        px = cx + radius * math.cos(angle)
        py = cy + radius * math.sin(angle)
        positions.append((px, py))

    for i, node in enumerate(nodes):
        px, py = positions[i]
        shape = slide.shapes.add_shape(
            9, Inches(px - 0.35), Inches(py - 0.35),
            Inches(0.7), Inches(0.7))
        shape.fill.solid()
        shape.fill.fore_color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
        shape.line.fill.background()

        tf = shape.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        run = p.add_run()
        run.text = str(node.get("label", f"N{i + 1}"))[:12]
        run.font.size = Pt(7)
        run.font.bold = True
        run.font.color.rgb = WHITE


# ── Map placeholder ─────────────────────────────────────────────────

def _render_map_placeholder(slide, data: dict, region: str = "body"):
    r = _get_region(region)
    _add_textbox(slide, r[0] + 1, r[1] + 1, r[2] - 2, 1.5,
                 "[Geographic visualization — requires map image asset]",
                 font_size=14, italic=True, color=GREY,
                 alignment=PP_ALIGN.CENTER)
    regions = data.get("regions", [])
    if regions:
        items = [f"{rg.get('name', '')}: {rg.get('value', '')}" for rg in regions[:8]]
        _add_bullet_list(slide, items, region="body", font_size=11)


# ── Dashboard engine ────────────────────────────────────────────────

def _render_dashboard(slide, data: dict, theme: dict):
    kpis = data.get("kpis", [])
    if kpis:
        _render_kpi_cards(slide, kpis[:5], region="body")
    chart_data = data.get("chart")
    if chart_data:
        _render_bar_chart(slide, chart_data, region="chart_left")


# ── Visual dispatcher ───────────────────────────────────────────────

VISUAL_RENDERERS = {
    "bar_chart": lambda s, d, t: _render_bar_chart(s, d),
    "stacked_bar": lambda s, d, t: _render_stacked_bar(s, d),
    "line_chart": lambda s, d, t: _render_line_chart(s, d),
    "area": lambda s, d, t: _render_area_chart(s, d),
    "scatter": lambda s, d, t: _render_scatter_chart(s, d),
    "bubble": lambda s, d, t: _render_bubble_chart(s, d),
    "heatmap": lambda s, d, t: _render_matrix(s, d),
    "timeline": lambda s, d, t: _render_timeline(s, d.get("items", [])),
    "journey": lambda s, d, t: _render_timeline(s, d.get("items", [])),
    "matrix": lambda s, d, t: _render_matrix(s, d),
    "table": lambda s, d, t: _render_table(s, d),
    "network": lambda s, d, t: _render_network(s, d),
    "treemap": lambda s, d, t: _render_bar_chart(s, d),
    "sankey": lambda s, d, t: _render_stacked_bar(s, d),
    "quote": lambda s, d, t: None,
    "dashboard": lambda s, d, t: _render_dashboard(s, d, t),
    "kpi_cards": lambda s, d, t: _render_kpi_cards(s, d.get("items", [])),
    "funnel": lambda s, d, t: _render_funnel(s, d.get("stages", [])),
    "map": lambda s, d, t: _render_map_placeholder(s, d),
    "theme_cluster": lambda s, d, t: _render_network(s, d),
}


# ── Slide renderers by purpose ──────────────────────────────────────

def _render_cover_slide(prs, slide_data: dict, theme: dict, slide_num: int):
    slide = prs.slides.add_slide(_blank_layout(prs))
    r = _get_region("title", "cover")
    _add_textbox(slide, *r, slide_data.get("title", ""),
                 font_size=theme.get("font_size_title", 26),
                 bold=True, color=_hex_to_rgb(theme.get("primary_color", "#5B2C9D")),
                 alignment=PP_ALIGN.LEFT)
    subtitle = slide_data.get("subtitle") or slide_data.get("narrative", "")
    if subtitle:
        r2 = _get_region("subtitle", "cover")
        _add_textbox(slide, *r2, subtitle,
                     font_size=16, color=GREY)
    r3 = _get_region("date", "cover")
    _add_textbox(slide, *r3, date.today().strftime("%B %Y"),
                 font_size=12, italic=True, color=GREY)
    _add_speaker_notes(slide, slide_data.get("speaker_notes", ""))
    return slide


def _render_agenda_slide(prs, slide_data: dict, theme: dict, slide_num: int,
                         all_slides: list[dict]):
    slide = prs.slides.add_slide(_blank_layout(prs))
    _add_eyebrow(slide, "AGENDA", theme)
    _add_slide_title(slide, slide_data.get("title", "Agenda"), theme)

    agenda_items = []
    for s in all_slides:
        purpose = s.get("slide_purpose", "")
        if purpose not in ("cover", "agenda", "appendix"):
            agenda_items.append(s.get("title", ""))

    _add_bullet_list(slide, agenda_items[:15], region="body", font_size=13)
    _add_source_footer(slide, "", slide_num)
    _add_speaker_notes(slide, slide_data.get("speaker_notes", ""))
    return slide


def _render_divider_slide(prs, slide_data: dict, theme: dict, slide_num: int):
    slide = prs.slides.add_slide(_blank_layout(prs))
    r = _get_region("title", "divider")
    _add_textbox(slide, *r, slide_data.get("title", ""),
                 font_size=32, bold=True,
                 color=_hex_to_rgb(theme.get("primary_color", "#5B2C9D")),
                 alignment=PP_ALIGN.LEFT)
    subtitle = slide_data.get("subtitle", "")
    if subtitle:
        r2 = _get_region("subtitle", "divider")
        _add_textbox(slide, *r2, subtitle,
                     font_size=16, italic=True, color=GREY)
    _add_source_footer(slide, "", slide_num)
    _add_speaker_notes(slide, slide_data.get("speaker_notes", ""))
    return slide


def _render_conclusion_slide(prs, slide_data: dict, theme: dict, slide_num: int):
    slide = prs.slides.add_slide(_blank_layout(prs))
    _add_eyebrow(slide, "CONCLUSION", theme)
    _add_slide_title(slide, slide_data.get("title", "Conclusion & Next Steps"), theme)

    blocks = slide_data.get("content_blocks_json", [])
    if isinstance(blocks, str):
        try:
            blocks = json.loads(blocks)
        except (json.JSONDecodeError, TypeError):
            blocks = []

    rec_items = []
    narrative_parts = []
    for block in blocks:
        if isinstance(block, dict):
            btype = block.get("type", "")
            content = block.get("content", "")
            if btype == "recommendation":
                rec_items.append(content)
            elif content:
                narrative_parts.append(content)

    if narrative_parts:
        _add_body_text(slide, narrative_parts, region="body_left", font_size=13)
    if rec_items:
        _add_bullet_list(slide, rec_items, region="body_right", font_size=12)

    _add_source_footer(slide, "", slide_num)
    _add_speaker_notes(slide, slide_data.get("speaker_notes", ""))
    return slide


def _is_template_string(text: str) -> bool:
    """Detect internal template strings that should not appear on slides."""
    markers = [
        "Analysis of",
        "accepted evidence item(s)",
        "reveals findings relevant to:",
        "additional finding(s)",
        "supplementary context to the primary narrative",
        "Evidence base comprises",
        "Focus on your main objective",
    ]
    text_lower = text.lower()
    return any(m.lower() in text_lower for m in markers)


def _render_content_slide(prs, slide_data: dict, theme: dict, slide_num: int):
    slide = prs.slides.add_slide(_blank_layout(prs))

    purpose = slide_data.get("slide_purpose", "key_finding")
    eyebrow = purpose.replace("_", " ").upper()
    _add_eyebrow(slide, eyebrow, theme)
    _add_slide_title(slide, slide_data.get("title", ""), theme)

    key_message = slide_data.get("key_message", "")
    if key_message:
        _add_takeaway(slide, key_message)

    blocks = slide_data.get("content_blocks_json", [])
    if isinstance(blocks, str):
        try:
            blocks = json.loads(blocks)
        except (json.JSONDecodeError, TypeError):
            blocks = []

    visual = slide_data.get("recommended_visual", "")
    has_chart = visual in CHART_RENDERERS or visual in VISUAL_RENDERERS

    narrative_parts = []
    evidence_parts = []
    metric_parts = []
    quote_text = ""
    source_parts = []

    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        content = block.get("content", "")
        if not content:
            continue
        if btype in ("title", "subtitle"):
            continue
        elif btype == "quote" or btype == "verbatim":
            quote_text = content
        elif btype == "source" or btype == "footnote":
            source_parts.append(content)
        elif btype == "metrics":
            metric_parts.append(content)
        elif btype == "evidence_panel":
            evidence_parts.append(content)
        else:
            narrative_parts.append(content)

    # Filter out template/meta strings from all text content
    narrative_parts = [p for p in narrative_parts if not _is_template_string(p)]
    evidence_parts = [p for p in evidence_parts if not _is_template_string(p)]

    if has_chart:
        chart_data = _extract_chart_data(blocks, slide_data)
        if chart_data.get("categories"):
            renderer = VISUAL_RENDERERS.get(visual)
            if renderer:
                renderer(slide, chart_data, theme)
            if narrative_parts:
                _add_body_text(slide, narrative_parts[:3], region="chart_right", font_size=11)
        else:
            all_text = narrative_parts + evidence_parts
            if all_text:
                _add_body_text(slide, all_text, font_size=13)
    elif visual == "quote" and quote_text:
        _add_textbox(slide, 1.5, 2.0, 10.3, 3.0,
                     f'“{quote_text}”',
                     font_size=20, italic=True,
                     color=_hex_to_rgb(theme.get("primary_color", "#5B2C9D")),
                     alignment=PP_ALIGN.CENTER)
    elif visual == "table":
        table_data = _extract_table_data(blocks)
        if table_data:
            _render_table(slide, table_data)
        elif narrative_parts:
            _add_body_text(slide, narrative_parts, font_size=13)
    elif visual == "kpi_cards" and metric_parts:
        kpi_items = [{"value": m.split(":")[0].strip() if ":" in m else m,
                       "label": m.split(":", 1)[1].strip() if ":" in m else ""}
                      for m in metric_parts[:5]]
        _render_kpi_cards(slide, kpi_items)
    else:
        all_text = narrative_parts + evidence_parts
        if all_text:
            _add_body_text(slide, all_text, font_size=13)

    source_line = "; ".join(source_parts) if source_parts else ""
    _add_source_footer(slide, source_line, slide_num)
    _add_speaker_notes(slide, slide_data.get("speaker_notes", ""))
    return slide


def _extract_chart_data(blocks: list[dict], slide_data: dict) -> dict:
    data = {"categories": [], "series": [], "values": []}
    metric_values = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        content = block.get("content", "")
        if btype == "metrics" and content:
            metric_values.append(content)
        elif btype == "chart" and content:
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    data.update(parsed)
            except (json.JSONDecodeError, TypeError):
                pass

    if not data["categories"] and metric_values:
        cats = []
        vals = []
        for mv in metric_values:
            parts = mv.split(":")
            if len(parts) >= 2:
                cats.append(parts[0].strip())
                try:
                    vals.append(float(parts[1].strip().rstrip("%")))
                except ValueError:
                    vals.append(0)
        if cats:
            data["categories"] = cats
            data["series"] = [{"name": "Value", "values": vals}]

    if not data["categories"]:
        return {"categories": [], "series": [], "values": []}

    return data


def _extract_table_data(blocks: list[dict]) -> dict | None:
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "chart" and block.get("content"):
            try:
                parsed = json.loads(block["content"])
                if isinstance(parsed, dict) and "headers" in parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
    return None


# ── Appendix slide ──────────────────────────────────────────────────

def _render_appendix_slide(prs, slide_data: dict, theme: dict, slide_num: int):
    return _render_divider_slide(prs, slide_data, theme, slide_num)


# ── Horizontal bar chart (for theme slides) ──────────────────────────

def _render_horizontal_bar(slide, data: dict, region: tuple):
    """Horizontal bar chart showing ranked theme distribution."""
    chart_data = CategoryChartData()
    categories = data.get("categories", [])
    values = data.get("values", [])
    if not categories:
        return None
    chart_data.categories = categories
    chart_data.add_series("Share", values)
    chart_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.BAR_CLUSTERED,
        Inches(region[0]), Inches(region[1]),
        Inches(region[2]), Inches(region[3]),
        chart_data)
    chart = chart_frame.chart
    chart.has_legend = False
    plot = chart.plots[0]
    plot.gap_width = 80
    series = chart.series[0]
    for i in range(len(categories)):
        point = series.points[i]
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
    try:
        series.has_data_labels = True
        labels = series.data_labels
        labels.show_value = True
        labels.number_format = '0.0"%"'
        labels.font.size = Pt(9)
        labels.font.bold = True
    except Exception:
        pass
    return chart_frame


# ── Multi-column narrative blocks ─────────────────────────────────────

def _render_narrative_columns(slide, columns: list[dict], region: tuple,
                              theme: dict):
    """Render N side-by-side narrative blocks with heading + body text.

    Each column dict: {"heading": str, "body": str, "color_index": int}
    """
    n = len(columns)
    if n == 0:
        return
    gap = 0.15
    total_gap = gap * (n - 1)
    col_w = (region[2] - total_gap) / n
    col_h = region[3]

    for i, col in enumerate(columns):
        x = region[0] + i * (col_w + gap)
        y = region[1]
        color_idx = col.get("color_index", i)

        heading_h = 0.30
        shape = slide.shapes.add_shape(
            5, Inches(x), Inches(y), Inches(col_w), Inches(heading_h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = SERIES_PALETTE[color_idx % len(SERIES_PALETTE)]
        shape.line.fill.background()
        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.08)
        tf.margin_top = Inches(0.02)
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = col.get("heading", "")
        run.font.size = Pt(9)
        run.font.bold = True
        run.font.color.rgb = WHITE

        body_y = y + heading_h + 0.04
        body_h = col_h - heading_h - 0.04
        body_box = slide.shapes.add_textbox(
            Inches(x), Inches(body_y), Inches(col_w), Inches(body_h))
        btf = body_box.text_frame
        btf.word_wrap = True
        btf.margin_left = Inches(0.06)
        btf.margin_right = Inches(0.06)
        btf.margin_top = Inches(0.04)
        bp = btf.paragraphs[0]
        brun = bp.add_run()
        brun.text = col.get("body", "")
        brun.font.size = Pt(8)
        brun.font.color.rgb = BLACK
        bp.space_after = Pt(2)


# ── SOV archetype slide renderer ─────────────────────────────────────

def _render_sov_slide(prs, slide_data: dict, theme: dict, slide_num: int):
    """Render Competitive — Share of Voice & Trendline archetype slide.

    Expected content_blocks_json structure:
    {
        "archetype": "sov_competitive",
        "context_label": "MEN'S WEARHOUSE & COMPETITORS — EDITORIAL",
        "title": "Competitive — Share of Voice & Trendline",
        "executive_takeaway": "...",
        "sample_size": 2102,
        "donut": {"categories": [...], "values": [...]},
        "trend": {"categories": [...], "series": [...]},
        "narratives": [{"heading": "...", "body": "...", "color_index": 0}, ...],
        "source_footer": "SOURCE: MELTWATER | AUG 2025 – AUG 2026"
    }
    """
    slide = prs.slides.add_slide(_blank_layout(prs))
    R = REGION_SOV

    blocks = slide_data.get("content_blocks_json", {})
    if isinstance(blocks, str):
        try:
            blocks = json.loads(blocks)
        except (json.JSONDecodeError, TypeError):
            blocks = {}

    archetype_data = blocks if isinstance(blocks, dict) and blocks.get("archetype") == "sov_competitive" else {}
    if not archetype_data:
        for b in (blocks if isinstance(blocks, list) else []):
            if isinstance(b, dict) and b.get("type") == "chart" and b.get("content"):
                try:
                    parsed = json.loads(b["content"])
                    if isinstance(parsed, dict) and parsed.get("archetype") == "sov_competitive":
                        archetype_data = parsed
                        break
                except (json.JSONDecodeError, TypeError):
                    pass
    if not archetype_data:
        return _render_content_slide(prs, slide_data, theme, slide_num)

    ctx = archetype_data.get("context_label", "")
    if ctx:
        _add_textbox(slide, *R["context_label"], ctx.upper(),
                     font_size=8, bold=True,
                     color=_hex_to_rgb(theme.get("primary_color", "#5B2C9D")))

    title = archetype_data.get("title", slide_data.get("title", "Competitive — Share of Voice & Trendline"))
    _add_textbox(slide, *R["title"], title,
                 font_size=15, bold=True, color=BLACK)

    takeaway = archetype_data.get("executive_takeaway", "")
    if takeaway:
        r = R["takeaway"]
        shape = slide.shapes.add_shape(
            5, Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]))
        shape.fill.solid()
        shape.fill.fore_color.rgb = CARD_BG
        shape.line.color.rgb = LT_PURPLE
        shape.line.width = Pt(0.5)
        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.12)
        tf.margin_right = Inches(0.12)
        tf.margin_top = Inches(0.06)
        tf.margin_bottom = Inches(0.06)
        run = tf.paragraphs[0].add_run()
        run.text = takeaway
        run.font.size = Pt(9)
        run.font.color.rgb = BLACK

    donut_data = archetype_data.get("donut", {})
    if donut_data.get("categories"):
        r = R["donut"]
        chart_data_obj = CategoryChartData()
        chart_data_obj.categories = donut_data["categories"]
        chart_data_obj.add_series("SOV", donut_data.get("values", []))
        chart_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.DOUGHNUT,
            Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
            chart_data_obj)
        chart = chart_frame.chart
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(8)
        plot = chart.plots[0]
        for i in range(len(donut_data["categories"])):
            point = plot.series[0].points[i]
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
        try:
            plot.series[0].has_data_labels = True
            labels = plot.series[0].data_labels
            labels.show_value = True
            labels.show_category_name = False
            labels.number_format = '0.0"%"'
            labels.font.size = Pt(9)
            labels.font.bold = True
        except Exception:
            pass

    trend_data = archetype_data.get("trend", {})
    if trend_data.get("categories"):
        r = R["trend"]
        t_chart_data = CategoryChartData()
        t_chart_data.categories = trend_data["categories"]
        for series in trend_data.get("series", []):
            vals = series.get("values", [0] * len(trend_data["categories"]))
            t_chart_data.add_series(series.get("name", ""), vals)
        chart_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.LINE_MARKERS,
            Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
            t_chart_data)
        chart = chart_frame.chart
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(8)
        for i, series in enumerate(chart.series):
            series.format.line.color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
            series.format.line.width = Pt(2)

    n_val = archetype_data.get("sample_size")
    if n_val:
        r = R["sample_size"]
        _add_textbox(slide, *r, f"N = {n_val:,}",
                     font_size=8, bold=True, color=GREY,
                     alignment=PP_ALIGN.RIGHT)

    narratives = archetype_data.get("narratives", [])
    if narratives:
        _render_narrative_columns(slide, narratives, R["narratives"], theme)

    source_text = archetype_data.get("source_footer", "")
    _add_source_footer(slide, source_text, slide_num)
    _add_speaker_notes(slide, slide_data.get("speaker_notes", ""))
    return slide


# ── Theme archetype slide renderer ───────────────────────────────────

def _render_theme_slide(prs, slide_data: dict, theme: dict, slide_num: int):
    """Render [Entity] — Themes & Trends archetype slide.

    Expected content_blocks_json structure:
    {
        "archetype": "entity_themes",
        "context_label": "MEN'S WEARHOUSE & COMPETITORS — EDITORIAL",
        "title": "Brooks Brothers — Themes & Trends",
        "executive_takeaway": "...",
        "sample_size": 423,
        "bar_chart": {"categories": [...], "values": [...]},
        "theme_trend": {"categories": [...], "series": [...]},
        "narratives": [{"heading": "...", "body": "...", "color_index": 0}, ...],
        "source_footer": "SOURCE: MELTWATER | SEP 2025 – DEC 2025"
    }
    """
    slide = prs.slides.add_slide(_blank_layout(prs))
    R = REGION_THEME

    blocks = slide_data.get("content_blocks_json", {})
    if isinstance(blocks, str):
        try:
            blocks = json.loads(blocks)
        except (json.JSONDecodeError, TypeError):
            blocks = {}

    archetype_data = blocks if isinstance(blocks, dict) and blocks.get("archetype") == "entity_themes" else {}
    if not archetype_data:
        for b in (blocks if isinstance(blocks, list) else []):
            if isinstance(b, dict) and b.get("type") == "chart" and b.get("content"):
                try:
                    parsed = json.loads(b["content"])
                    if isinstance(parsed, dict) and parsed.get("archetype") == "entity_themes":
                        archetype_data = parsed
                        break
                except (json.JSONDecodeError, TypeError):
                    pass
    if not archetype_data:
        return _render_content_slide(prs, slide_data, theme, slide_num)

    ctx = archetype_data.get("context_label", "")
    if ctx:
        _add_textbox(slide, *R["context_label"], ctx.upper(),
                     font_size=8, bold=True,
                     color=_hex_to_rgb(theme.get("primary_color", "#5B2C9D")))

    title = archetype_data.get("title", slide_data.get("title", ""))
    _add_textbox(slide, *R["title"], title,
                 font_size=15, bold=True, color=BLACK)

    takeaway = archetype_data.get("executive_takeaway", "")
    if takeaway:
        r = R["takeaway"]
        shape = slide.shapes.add_shape(
            5, Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]))
        shape.fill.solid()
        shape.fill.fore_color.rgb = CARD_BG
        shape.line.color.rgb = LT_PURPLE
        shape.line.width = Pt(0.5)
        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.10)
        tf.margin_right = Inches(0.10)
        tf.margin_top = Inches(0.06)
        tf.margin_bottom = Inches(0.06)
        run = tf.paragraphs[0].add_run()
        run.text = takeaway
        run.font.size = Pt(8)
        run.font.color.rgb = BLACK

    bar_data = archetype_data.get("bar_chart", {})
    if bar_data.get("categories"):
        _render_horizontal_bar(slide, bar_data, R["bar_chart"])

    trend_data = archetype_data.get("theme_trend", {})
    if trend_data.get("categories"):
        r = R["theme_trend"]
        t_chart_data = CategoryChartData()
        t_chart_data.categories = trend_data["categories"]
        for series in trend_data.get("series", []):
            vals = series.get("values", [0] * len(trend_data["categories"]))
            t_chart_data.add_series(series.get("name", ""), vals)
        chart_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.LINE_MARKERS,
            Inches(r[0]), Inches(r[1]), Inches(r[2]), Inches(r[3]),
            t_chart_data)
        chart = chart_frame.chart
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(7)
        for i, series in enumerate(chart.series):
            series.format.line.color.rgb = SERIES_PALETTE[i % len(SERIES_PALETTE)]
            series.format.line.width = Pt(2)

    n_val = archetype_data.get("sample_size")
    if n_val:
        r = R["sample_size"]
        _add_textbox(slide, *r, f"N = {n_val:,}",
                     font_size=8, bold=True, color=GREY,
                     alignment=PP_ALIGN.RIGHT)

    narratives = archetype_data.get("narratives", [])
    if narratives:
        _render_narrative_columns(slide, narratives, R["narratives"], theme)

    source_text = archetype_data.get("source_footer", "")
    _add_source_footer(slide, source_text, slide_num)
    _add_speaker_notes(slide, slide_data.get("speaker_notes", ""))
    return slide


# ── Purpose-to-renderer dispatch ────────────────────────────────────

PURPOSE_RENDERERS = {
    "cover": _render_cover_slide,
    "agenda": None,
    "conclusion": _render_conclusion_slide,
    "appendix": _render_appendix_slide,
    "sov_competitive": _render_sov_slide,
    "entity_themes": _render_theme_slide,
}

SECTION_DIVIDER_PURPOSES = set()


# ── Main rendering pipeline ────────────────────────────────────────

def validate_for_render(pres_id: int) -> dict:
    pres = store.get_pc_presentation(pres_id)
    if not pres:
        return {"valid": False, "issues": ["Presentation not found"], "warnings": []}

    issues = []
    warnings = []

    if pres["status"] not in ("approved", "draft", "needs_review"):
        issues.append(f"Presentation status is '{pres['status']}' — expected approved")

    slides = store.list_pc_slides(pres_id)
    if not slides:
        issues.append("No slides found in presentation")

    has_cover = any(s["slide_purpose"] == "cover" for s in slides)
    if not has_cover:
        warnings.append("No cover slide found")

    rejected = [s for s in slides if s["status"] == "rejected"]
    if rejected:
        warnings.append(f"{len(rejected)} slide(s) have 'rejected' status")

    low_conf = [s for s in slides if s.get("overall_confidence", 1.0) < 0.4]
    if low_conf:
        warnings.append(f"{len(low_conf)} slide(s) have low confidence (<0.4)")

    return {"valid": len(issues) == 0, "issues": issues, "warnings": warnings}


def render_presentation(pres_id: int, theme_id: str = "hunter_default",
                        actor: str = "system") -> dict:
    validation = validate_for_render(pres_id)
    if not validation["valid"]:
        return {"error": "Presentation not valid for rendering",
                "issues": validation["issues"]}

    pres = store.get_pc_presentation(pres_id)
    slides = store.list_pc_slides(pres_id)
    theme = _resolve_theme(theme_id)

    job_id = str(uuid.uuid4())
    store.create_render_job(job_id, pres_id, job_type="full", theme_id=theme_id)
    store.update_render_job(job_id, status="running", started_at=time.time())
    store.add_render_history(pres_id, job_id, "render_started", actor=actor,
                            details={"theme_id": theme_id, "slide_count": len(slides)})

    start_time = time.time()
    warnings = []

    try:
        output_dir = Path(config.DATA_DIR) / "rendered"
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_"
                             for c in pres.get("title", "presentation")[:50])
        filename = f"{safe_title}_{job_id[:8]}.pptx"
        output_path = str(output_dir / filename)

        prs = Presentation()
        prs.slide_width = Inches(SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(SLIDE_HEIGHT_INCHES)

        for i, slide_data in enumerate(slides):
            slide_start = time.time()
            purpose = slide_data.get("slide_purpose", "key_finding")
            slide_num = i + 1

            store.update_render_job(
                job_id,
                progress_pct=int((i / max(len(slides), 1)) * 100),
                progress_message=f"Rendering slide {slide_num}/{len(slides)}: {purpose}")

            try:
                renderer = PURPOSE_RENDERERS.get(purpose)
                if renderer:
                    renderer(prs, slide_data, theme, slide_num)
                elif purpose == "agenda":
                    _render_agenda_slide(prs, slide_data, theme, slide_num, slides)
                else:
                    _render_content_slide(prs, slide_data, theme, slide_num)

                render_type = "special" if purpose in PURPOSE_RENDERERS else "content"
                store.add_render_metric(
                    job_id, slide_data["id"], i,
                    render_type,
                    duration_ms=int((time.time() - slide_start) * 1000))

            except Exception as e:
                logger.error("Error rendering slide %d (%s): %s", slide_num, purpose, e)
                warnings.append(f"Slide {slide_num} ({purpose}): {str(e)}")
                slide = prs.slides.add_slide(_blank_layout(prs))
                _add_textbox(slide, 1, 3, 11, 2,
                             f"[Render error on slide {slide_num}: {purpose}]",
                             font_size=16, italic=True, color=RED,
                             alignment=PP_ALIGN.CENTER)

        prs.save(output_path)
        duration_ms = int((time.time() - start_time) * 1000)
        file_size = os.path.getsize(output_path)

        version = len(store.list_rendered_presentations(pres_id)) + 1
        rp_id = store.create_rendered_presentation(
            job_id, pres_id, output_path,
            version=version,
            output_size_bytes=file_size,
            slide_count=len(slides),
            theme_id=theme_id,
            render_duration_ms=duration_ms,
            metadata={"warnings": warnings, "title": pres.get("title", "")})

        store.update_render_job(
            job_id, status="completed",
            progress_pct=100,
            progress_message="Render complete",
            output_path=output_path,
            output_size_bytes=file_size,
            warnings=warnings,
            finished_at=time.time())

        store.add_render_history(
            pres_id, job_id, "render_completed", actor=actor,
            details={"duration_ms": duration_ms, "file_size": file_size,
                     "slide_count": len(slides), "warnings_count": len(warnings),
                     "version": version})

        return {
            "job_id": job_id,
            "status": "completed",
            "output_path": output_path,
            "file_size_bytes": file_size,
            "slide_count": len(slides),
            "render_duration_ms": duration_ms,
            "warnings": warnings,
            "version": version,
            "rendered_presentation_id": rp_id,
        }

    except Exception as e:
        logger.error("Render failed for presentation %d: %s", pres_id, e)
        store.update_render_job(
            job_id, status="failed",
            error=str(e), finished_at=time.time())
        store.add_render_history(
            pres_id, job_id, "render_failed", actor=actor,
            details={"error": str(e)})
        return {"error": str(e), "job_id": job_id, "status": "failed"}


def render_slide(slide_id: int, theme_id: str = "hunter_default",
                 actor: str = "system") -> dict:
    slide_data = store.get_pc_slide(slide_id)
    if not slide_data:
        return {"error": "Slide not found"}

    pres_id = slide_data["presentation_id"]
    all_slides = store.list_pc_slides(pres_id)
    theme = _resolve_theme(theme_id)

    job_id = str(uuid.uuid4())
    store.create_render_job(job_id, pres_id, job_type="slide",
                            slide_ids=[slide_id], theme_id=theme_id)
    store.update_render_job(job_id, status="running", started_at=time.time())

    start_time = time.time()
    try:
        output_dir = Path(config.DATA_DIR) / "rendered"
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"slide_{slide_id}_{job_id[:8]}.pptx"
        output_path = str(output_dir / filename)

        prs = Presentation()
        prs.slide_width = Inches(SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(SLIDE_HEIGHT_INCHES)

        purpose = slide_data.get("slide_purpose", "key_finding")
        slide_num = slide_data.get("slide_number", 0) + 1

        renderer = PURPOSE_RENDERERS.get(purpose)
        if renderer:
            renderer(prs, slide_data, theme, slide_num)
        elif purpose == "agenda":
            _render_agenda_slide(prs, slide_data, theme, slide_num, all_slides)
        else:
            _render_content_slide(prs, slide_data, theme, slide_num)

        prs.save(output_path)
        duration_ms = int((time.time() - start_time) * 1000)
        file_size = os.path.getsize(output_path)

        store.update_render_job(
            job_id, status="completed", progress_pct=100,
            output_path=output_path, output_size_bytes=file_size,
            finished_at=time.time())

        store.add_render_metric(
            job_id, slide_id, slide_data.get("slide_number", 0),
            "single", duration_ms=duration_ms)

        return {
            "job_id": job_id,
            "status": "completed",
            "output_path": output_path,
            "file_size_bytes": file_size,
            "render_duration_ms": duration_ms,
        }

    except Exception as e:
        store.update_render_job(
            job_id, status="failed", error=str(e), finished_at=time.time())
        return {"error": str(e), "job_id": job_id, "status": "failed"}


def render_section(pres_id: int, purpose_filter: str,
                   theme_id: str = "hunter_default",
                   actor: str = "system") -> dict:
    slides = store.list_pc_slides(pres_id)
    matching = [s for s in slides if s.get("slide_purpose") == purpose_filter]
    if not matching:
        return {"error": f"No slides with purpose '{purpose_filter}' found"}

    theme = _resolve_theme(theme_id)
    job_id = str(uuid.uuid4())
    slide_ids = [s["id"] for s in matching]
    store.create_render_job(job_id, pres_id, job_type="section",
                            slide_ids=slide_ids, theme_id=theme_id)
    store.update_render_job(job_id, status="running", started_at=time.time())

    start_time = time.time()
    warnings = []
    try:
        output_dir = Path(config.DATA_DIR) / "rendered"
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"section_{purpose_filter}_{job_id[:8]}.pptx"
        output_path = str(output_dir / filename)

        prs = Presentation()
        prs.slide_width = Inches(SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(SLIDE_HEIGHT_INCHES)

        for slide_data in matching:
            slide_num = slide_data.get("slide_number", 0) + 1
            try:
                _render_content_slide(prs, slide_data, theme, slide_num)
            except Exception as e:
                warnings.append(f"Slide {slide_num}: {str(e)}")

        prs.save(output_path)
        duration_ms = int((time.time() - start_time) * 1000)
        file_size = os.path.getsize(output_path)

        store.update_render_job(
            job_id, status="completed", progress_pct=100,
            output_path=output_path, output_size_bytes=file_size,
            warnings=warnings, finished_at=time.time())

        return {
            "job_id": job_id,
            "status": "completed",
            "output_path": output_path,
            "slide_count": len(matching),
            "file_size_bytes": file_size,
            "render_duration_ms": duration_ms,
            "warnings": warnings,
        }

    except Exception as e:
        store.update_render_job(
            job_id, status="failed", error=str(e), finished_at=time.time())
        return {"error": str(e), "job_id": job_id, "status": "failed"}


def get_render_status(job_id: str) -> dict | None:
    return store.get_render_job(job_id)


def get_download_path(job_id: str) -> str | None:
    job = store.get_render_job(job_id)
    if not job:
        return None
    path = job.get("output_path")
    if path and os.path.exists(path):
        return path
    return None


def list_themes() -> list[dict]:
    store.ensure_default_theme()
    return store.list_themes()


def get_render_summary(pres_id: int) -> dict:
    jobs = store.list_render_jobs(pres_id)
    rendered = store.list_rendered_presentations(pres_id)
    history = store.get_render_history(pres_id)

    latest_job = jobs[0] if jobs else None
    latest_render = rendered[0] if rendered else None

    return {
        "total_renders": len(rendered),
        "total_jobs": len(jobs),
        "latest_job": latest_job,
        "latest_render": latest_render,
        "has_download": bool(latest_render and
                             latest_render.get("output_path") and
                             os.path.exists(latest_render["output_path"])),
        "history_count": len(history),
    }
