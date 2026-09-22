"""Word Report Renderer — transforms an approved Presentation Model into a
professionally formatted Microsoft Word (.docx) report.

This module makes ZERO strategic or editorial decisions. All content decisions
were already made by the Presentation Composer (Stage 10). The renderer is
responsible ONLY for faithfully rendering the Presentation Model into a Word
document.

It never regenerates content, rewrites insights, modifies evidence, or
changes storyline. It is a pure rendering engine.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn, nsdecls
from docx.shared import Inches, Pt, Cm, RGBColor, Emu

from . import intelligence_store as store
from . import config

logger = logging.getLogger(__name__)

VALID_JOB_TYPES = {"full", "section"}
VALID_JOB_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}

SECTION_ORDER = [
    "cover", "confidentiality", "executive_summary", "methodology",
    "key_findings", "supporting_evidence", "business_impact",
    "recommendations", "conclusion", "appendix",
]

PURPOSE_TO_SECTION = {
    "cover": "cover",
    "agenda": "executive_summary",
    "executive_summary": "executive_summary",
    "methodology": "methodology",
    "key_finding": "key_findings",
    "trend": "key_findings",
    "consumer_insight": "key_findings",
    "sentiment": "key_findings",
    "competitive": "key_findings",
    "crisis": "key_findings",
    "opportunity": "business_impact",
    "risk": "business_impact",
    "recommendation": "recommendations",
    "conclusion": "conclusion",
    "appendix": "appendix",
    "divider": None,
    "content": "key_findings",
}


# ── Theme Engine ──────────────────────────────────────────────────────

def _resolve_theme(theme_id: str = "hunter_default") -> dict:
    store.ensure_default_theme()
    theme = store.get_theme(theme_id)
    if not theme:
        theme = store.get_theme("hunter_default")
    if not theme:
        theme = {
            "primary_color": "5B2C9D",
            "secondary_color": "5E35B1",
            "accent_color": "7C4DFF",
            "background_color": "FFFFFF",
            "text_color": "333333",
            "font_heading": "Calibri",
            "font_body": "Calibri",
            "font_size_title": 28,
            "font_size_body": 11,
            "font_size_caption": 9,
        }
    return theme


def _hex_to_rgb(hex_str: str) -> RGBColor:
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        hex_str = "333333"
    return RGBColor(int(hex_str[:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


# ── Document Layout Engine ────────────────────────────────────────────

def _setup_document(doc: Document, theme: dict) -> None:
    style = doc.styles["Normal"]
    font = style.font
    font.name = theme.get("font_body", "Calibri")
    font.size = Pt(int(theme.get("font_size_body", 11)))
    font.color.rgb = _hex_to_rgb(theme.get("text_color", "333333"))
    pf = style.paragraph_format
    pf.space_after = Pt(6)
    pf.line_spacing = 1.15

    for level in range(1, 7):
        style_name = f"Heading {level}"
        if style_name in doc.styles:
            hs = doc.styles[style_name]
            hs.font.name = theme.get("font_heading", "Calibri")
            hs.font.color.rgb = _hex_to_rgb(theme.get("primary_color", "5B2C9D"))
            hs.font.bold = True
            if level == 1:
                hs.font.size = Pt(24)
            elif level == 2:
                hs.font.size = Pt(18)
            elif level == 3:
                hs.font.size = Pt(14)
            else:
                hs.font.size = Pt(12)

    section = doc.sections[0]
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(2.54)
    section.right_margin = Cm(2.54)


def _add_header_footer(doc: Document, theme: dict, title: str) -> None:
    section = doc.sections[0]
    section.different_first_page_header_footer = True

    header = section.header
    hp = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    hp.text = title
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = hp.runs[0] if hp.runs else hp.add_run()
    run.font.size = Pt(8)
    run.font.color.rgb = _hex_to_rgb(theme.get("text_color", "999999"))
    run.font.name = theme.get("font_body", "Calibri")

    footer = section.footer
    fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp.text = "CONFIDENTIAL"
    run = fp.runs[0] if fp.runs else fp.add_run()
    run.font.size = Pt(7)
    run.font.color.rgb = _hex_to_rgb("999999")
    run.font.name = theme.get("font_body", "Calibri")


def _add_page_numbers(doc: Document) -> None:
    for section in doc.sections:
        footer = section.footer
        if not footer.paragraphs:
            footer.add_paragraph()
        p = footer.paragraphs[-1] if len(footer.paragraphs) > 1 else footer.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run = p.add_run()
        fldChar1 = OxmlElement("w:fldChar")
        fldChar1.set(qn("w:fldCharType"), "begin")
        run._r.append(fldChar1)
        instrText = OxmlElement("w:instrText")
        instrText.set(qn("xml:space"), "preserve")
        instrText.text = " PAGE "
        run._r.append(instrText)
        fldChar2 = OxmlElement("w:fldChar")
        fldChar2.set(qn("w:fldCharType"), "end")
        run._r.append(fldChar2)
        run.font.size = Pt(8)
        run.font.color.rgb = _hex_to_rgb("999999")


# ── Cover Page ────────────────────────────────────────────────────────

def _render_cover(doc: Document, theme: dict, pres: dict, slides: list[dict]) -> None:
    cover_slide = next((s for s in slides if s.get("slide_purpose") == "cover"), None)
    title = cover_slide.get("title") if cover_slide else pres.get("title", "Research Report")
    subtitle = cover_slide.get("subtitle", "") if cover_slide else ""

    for _ in range(6):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    run.font.size = Pt(int(theme.get("font_size_title", 28)))
    run.font.color.rgb = _hex_to_rgb(theme.get("primary_color", "5B2C9D"))
    run.font.name = theme.get("font_heading", "Calibri")
    run.font.bold = True

    if subtitle:
        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run2 = p2.add_run(subtitle)
        run2.font.size = Pt(16)
        run2.font.color.rgb = _hex_to_rgb(theme.get("secondary_color", "5E35B1"))
        run2.font.name = theme.get("font_heading", "Calibri")

    doc.add_paragraph()
    dp = doc.add_paragraph()
    dp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    dr = dp.add_run(date.today().strftime("%B %d, %Y"))
    dr.font.size = Pt(12)
    dr.font.color.rgb = _hex_to_rgb(theme.get("text_color", "666666"))

    p3 = doc.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r3 = p3.add_run("Prepared by Hunter Intelligence")
    r3.font.size = Pt(10)
    r3.font.color.rgb = _hex_to_rgb(theme.get("text_color", "999999"))

    doc.add_page_break()


# ── Confidentiality Notice ────────────────────────────────────────────

def _render_confidentiality(doc: Document, theme: dict, pres: dict) -> None:
    doc.add_heading("Confidentiality Notice", level=2)
    doc.add_paragraph(
        "This document contains confidential and proprietary information. "
        "It is intended solely for the use of the individual or entity to whom "
        "it is addressed. Any unauthorized review, use, disclosure, or distribution "
        "is prohibited. If you have received this document in error, please notify "
        "the sender immediately and destroy all copies."
    )
    doc.add_page_break()


# ── Executive Summary ─────────────────────────────────────────────────

def _render_executive_summary(doc: Document, theme: dict, pres: dict,
                               slides: list[dict]) -> int:
    doc.add_heading("Executive Summary", level=1)
    exec_summary = pres.get("executive_summary", "")
    if exec_summary:
        doc.add_paragraph(exec_summary)

    agenda_slides = [s for s in slides if s.get("slide_purpose") == "agenda"]
    for slide in agenda_slides:
        if slide.get("narrative"):
            doc.add_paragraph(slide["narrative"])

    exec_slides = [s for s in slides
                   if s.get("slide_purpose") == "executive_summary"]
    for slide in exec_slides:
        _render_slide_content(doc, theme, slide)

    doc.add_page_break()
    return 1 + len(agenda_slides) + len(exec_slides)


# ── Methodology ───────────────────────────────────────────────────────

def _render_methodology(doc: Document, theme: dict, pres: dict,
                         slides: list[dict]) -> int:
    doc.add_heading("Methodology", level=1)

    method_slides = [s for s in slides
                     if s.get("slide_purpose") == "methodology"]
    if method_slides:
        for slide in method_slides:
            _render_slide_content(doc, theme, slide)
    else:
        doc.add_paragraph(
            "This research was conducted using Hunter Intelligence's systematic "
            "methodology, combining multiple data sources and analytical methods "
            "to produce evidence-based findings."
        )

    doc.add_page_break()
    return max(1, len(method_slides))


# ── Key Findings ──────────────────────────────────────────────────────

def _render_key_findings(doc: Document, theme: dict, slides: list[dict],
                          footnotes: list[dict]) -> int:
    doc.add_heading("Key Findings", level=1)
    finding_purposes = {"key_finding", "trend", "consumer_insight",
                        "sentiment", "competitive", "crisis", "content"}
    finding_slides = [s for s in slides
                      if s.get("slide_purpose") in finding_purposes]
    if not finding_slides:
        doc.add_paragraph("No key findings available.")
        doc.add_page_break()
        return 0

    for i, slide in enumerate(finding_slides):
        if slide.get("title"):
            doc.add_heading(slide["title"], level=2)
        _render_slide_content(doc, theme, slide, footnotes=footnotes)
        if i < len(finding_slides) - 1:
            doc.add_paragraph()

    doc.add_page_break()
    return len(finding_slides)


# ── Supporting Evidence ───────────────────────────────────────────────

def _render_supporting_evidence(doc: Document, theme: dict,
                                 footnotes: list[dict]) -> int:
    if not footnotes:
        return 0
    doc.add_heading("Sources & Evidence", level=1)
    for i, fn in enumerate(footnotes, 1):
        p = doc.add_paragraph()
        run = p.add_run(f"[{i}] ")
        run.font.bold = True
        run.font.size = Pt(9)
        source_text = fn.get("source", fn.get("text", ""))
        sr = p.add_run(source_text)
        sr.font.size = Pt(9)
        sr.font.color.rgb = _hex_to_rgb("666666")
    doc.add_page_break()
    return len(footnotes)


# ── Business Impact ───────────────────────────────────────────────────

def _render_business_impact(doc: Document, theme: dict,
                             slides: list[dict]) -> int:
    impact_purposes = {"opportunity", "risk"}
    impact_slides = [s for s in slides
                     if s.get("slide_purpose") in impact_purposes]
    if not impact_slides:
        return 0
    doc.add_heading("Business Impact", level=1)
    for slide in impact_slides:
        if slide.get("title"):
            doc.add_heading(slide["title"], level=2)
        _render_slide_content(doc, theme, slide)
    doc.add_page_break()
    return len(impact_slides)


# ── Recommendations ───────────────────────────────────────────────────

def _render_recommendations(doc: Document, theme: dict,
                              slides: list[dict]) -> int:
    rec_slides = [s for s in slides
                  if s.get("slide_purpose") == "recommendation"]
    if not rec_slides:
        return 0
    doc.add_heading("Recommendations", level=1)
    for slide in rec_slides:
        if slide.get("title"):
            doc.add_heading(slide["title"], level=2)
        _render_slide_content(doc, theme, slide)
    doc.add_page_break()
    return len(rec_slides)


# ── Conclusion ────────────────────────────────────────────────────────

def _render_conclusion(doc: Document, theme: dict,
                        slides: list[dict]) -> int:
    conc_slides = [s for s in slides
                   if s.get("slide_purpose") == "conclusion"]
    if not conc_slides:
        return 0
    doc.add_heading("Conclusion", level=1)
    for slide in conc_slides:
        _render_slide_content(doc, theme, slide)
    doc.add_page_break()
    return len(conc_slides)


# ── Appendix ──────────────────────────────────────────────────────────

def _render_appendix(doc: Document, theme: dict,
                      slides: list[dict]) -> int:
    app_slides = [s for s in slides
                  if s.get("slide_purpose") == "appendix"]
    if not app_slides:
        return 0
    doc.add_heading("Appendix", level=1)
    for i, slide in enumerate(app_slides):
        label = slide.get("title", f"Appendix {chr(65 + i)}")
        doc.add_heading(label, level=2)
        _render_slide_content(doc, theme, slide)
    doc.add_page_break()
    return len(app_slides)


# ── Slide Content Renderer ────────────────────────────────────────────

def _render_slide_content(doc: Document, theme: dict, slide: dict,
                           footnotes: list[dict] | None = None) -> None:
    if slide.get("key_message"):
        _render_callout(doc, theme, slide["key_message"], style="key_message")

    if slide.get("narrative"):
        doc.add_paragraph(slide["narrative"])

    blocks = slide.get("content_blocks_json", [])
    if isinstance(blocks, str):
        try:
            blocks = json.loads(blocks)
        except (json.JSONDecodeError, TypeError):
            blocks = []

    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        content = block.get("content", "")
        label = block.get("label", "")

        if btype == "narrative" and content:
            doc.add_paragraph(content)
        elif btype == "quote" and content:
            _render_quote(doc, theme, content, label)
        elif btype == "metrics" and content:
            _render_metric_block(doc, theme, content, label)
        elif btype == "evidence_panel" and content:
            _render_evidence_panel(doc, theme, content, label, footnotes)
        elif btype == "source" and content:
            p = doc.add_paragraph()
            r = p.add_run(f"Source: {content}")
            r.font.size = Pt(int(theme.get("font_size_caption", 9)))
            r.font.italic = True
            r.font.color.rgb = _hex_to_rgb("999999")
        elif btype == "title" and content:
            doc.add_heading(content, level=3)
        elif btype == "subtitle" and content:
            p = doc.add_paragraph()
            r = p.add_run(content)
            r.font.size = Pt(13)
            r.font.color.rgb = _hex_to_rgb(theme.get("secondary_color", "5E35B1"))
        elif btype == "bullets" and content:
            _render_bullets(doc, content)
        elif btype == "chart" and content:
            _render_chart_block(doc, theme, content, label)
        elif btype == "table" and content:
            _render_table_block(doc, theme, content, label)

    visual_type = slide.get("recommended_visual", "")
    if visual_type and not any(
        b.get("type") in ("chart", "table") for b in blocks if isinstance(b, dict)
    ):
        chart_data = _extract_chart_data(blocks, slide)
        if chart_data.get("categories") or chart_data.get("values"):
            _render_chart_as_table(doc, theme, visual_type, chart_data, slide)


# ── Content Block Renderers ───────────────────────────────────────────

def _render_callout(doc: Document, theme: dict, text: str,
                     style: str = "info") -> None:
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.cell(0, 0)
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), theme.get("primary_color", "5B2C9D"))
    shading.set(qn("w:val"), "clear")
    cell._tc.get_or_add_tcPr().append(shading)
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.font.color.rgb = RGBColor(255, 255, 255)
    run.font.bold = True
    run.font.size = Pt(11)
    run.font.name = theme.get("font_heading", "Calibri")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _render_quote(doc: Document, theme: dict, text: str,
                   attribution: str = "") -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(1.5)
    p.paragraph_format.right_indent = Cm(1.5)
    run = p.add_run(f'"{text}"')
    run.font.italic = True
    run.font.size = Pt(11)
    run.font.color.rgb = _hex_to_rgb(theme.get("secondary_color", "5E35B1"))
    if attribution:
        ap = doc.add_paragraph()
        ap.paragraph_format.left_indent = Cm(1.5)
        ar = ap.add_run(f"— {attribution}")
        ar.font.size = Pt(9)
        ar.font.color.rgb = _hex_to_rgb("999999")


def _render_metric_block(doc: Document, theme: dict, content: str,
                          label: str = "") -> None:
    if label:
        p = doc.add_paragraph()
        r = p.add_run(label)
        r.font.bold = True
        r.font.size = Pt(10)
    p = doc.add_paragraph()
    r = p.add_run(str(content))
    r.font.size = Pt(18)
    r.font.bold = True
    r.font.color.rgb = _hex_to_rgb(theme.get("primary_color", "5B2C9D"))


def _render_evidence_panel(doc: Document, theme: dict, content: str,
                            label: str = "",
                            footnotes: list[dict] | None = None) -> None:
    if label:
        p = doc.add_paragraph()
        r = p.add_run(label)
        r.font.bold = True
        r.font.size = Pt(10)
    p = doc.add_paragraph()
    r = p.add_run(str(content))
    r.font.size = Pt(10)
    r.font.color.rgb = _hex_to_rgb("555555")
    if footnotes is not None:
        fn_idx = len(footnotes) + 1
        footnotes.append({"index": fn_idx, "source": str(content)[:120], "text": str(content)})
        sr = p.add_run(f" [{fn_idx}]")
        sr.font.size = Pt(8)
        sr.font.color.rgb = _hex_to_rgb(theme.get("accent_color", "7C4DFF"))
        sr.font.superscript = True


def _render_bullets(doc: Document, content: str) -> None:
    items = content.split("\n") if "\n" in content else [content]
    for item in items:
        item = item.strip().lstrip("•-* ")
        if item:
            doc.add_paragraph(item, style="List Bullet")


# ── Table Engine ──────────────────────────────────────────────────────

def _render_table_block(doc: Document, theme: dict, content: str,
                         label: str = "") -> None:
    if label:
        p = doc.add_paragraph()
        r = p.add_run(label)
        r.font.bold = True
        r.font.size = Pt(10)

    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (json.JSONDecodeError, TypeError):
        doc.add_paragraph(str(content))
        return

    if isinstance(data, dict):
        headers = data.get("headers", [])
        rows = data.get("rows", [])
    elif isinstance(data, list) and data:
        if isinstance(data[0], dict):
            headers = list(data[0].keys())
            rows = [list(r.values()) for r in data]
        elif isinstance(data[0], list):
            headers = [f"Column {i+1}" for i in range(len(data[0]))]
            rows = data
        else:
            headers = ["Value"]
            rows = [[str(v)] for v in data]
    else:
        doc.add_paragraph(str(content))
        return

    if not headers and not rows:
        return

    _create_styled_table(doc, theme, headers, rows)


def _create_styled_table(doc: Document, theme: dict,
                          headers: list[str], rows: list[list]) -> None:
    n_cols = len(headers) if headers else (len(rows[0]) if rows else 1)
    n_rows = (1 if headers else 0) + len(rows)
    table = doc.add_table(rows=n_rows, cols=n_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"

    if headers:
        for i, h in enumerate(headers[:n_cols]):
            cell = table.cell(0, i)
            cell.text = str(h)
            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), theme.get("primary_color", "5B2C9D"))
            shading.set(qn("w:val"), "clear")
            cell._tc.get_or_add_tcPr().append(shading)
            for run in cell.paragraphs[0].runs:
                run.font.color.rgb = RGBColor(255, 255, 255)
                run.font.bold = True
                run.font.size = Pt(9)
                run.font.name = theme.get("font_body", "Calibri")

    start_row = 1 if headers else 0
    for ri, row_data in enumerate(rows):
        for ci, val in enumerate(row_data[:n_cols]):
            cell = table.cell(start_row + ri, ci)
            cell.text = str(val) if val is not None else ""
            for run in cell.paragraphs[0].runs:
                run.font.size = Pt(9)
                run.font.name = theme.get("font_body", "Calibri")
            if ri % 2 == 1:
                shading = OxmlElement("w:shd")
                shading.set(qn("w:fill"), "F5F5F5")
                shading.set(qn("w:val"), "clear")
                cell._tc.get_or_add_tcPr().append(shading)

    doc.add_paragraph()


# ── Chart Engine ──────────────────────────────────────────────────────

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
                parsed = json.loads(content) if isinstance(content, str) else content
                if isinstance(parsed, dict):
                    data.update(parsed)
            except (json.JSONDecodeError, TypeError):
                pass

    if not data["categories"] and metric_values:
        for mv in metric_values:
            parts = str(mv).split(":")
            if len(parts) == 2:
                data["categories"].append(parts[0].strip())
                try:
                    data["values"].append(float(parts[1].strip().rstrip("%")))
                except ValueError:
                    data["values"].append(0)
    return data


def _render_chart_block(doc: Document, theme: dict, content: str,
                         label: str = "") -> None:
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (json.JSONDecodeError, TypeError):
        data = {}

    if not isinstance(data, dict):
        doc.add_paragraph(str(content))
        return

    chart_type = data.get("chart_type", data.get("type", "bar"))
    categories = data.get("categories", [])
    values = data.get("values", [])
    series = data.get("series", [])

    if label:
        p = doc.add_paragraph()
        r = p.add_run(label)
        r.font.bold = True

    if categories and (values or series):
        headers = ["Category"] + ([s.get("name", f"Series {i+1}") for i, s in enumerate(series)]
                                  if series else ["Value"])
        rows = []
        for i, cat in enumerate(categories):
            row = [str(cat)]
            if series:
                for s in series:
                    s_vals = s.get("values", [])
                    row.append(str(s_vals[i]) if i < len(s_vals) else "")
                rows.append(row)
            else:
                row.append(str(values[i]) if i < len(values) else "")
                rows.append(row)

        cap = doc.add_paragraph()
        cr = cap.add_run(f"Figure: {label or chart_type.replace('_', ' ').title()} Chart")
        cr.font.italic = True
        cr.font.size = Pt(9)
        cr.font.color.rgb = _hex_to_rgb("666666")

        _create_styled_table(doc, theme, headers, rows)
    else:
        p = doc.add_paragraph()
        r = p.add_run(f"[{chart_type.replace('_', ' ').title()} Chart]")
        r.font.italic = True
        r.font.color.rgb = _hex_to_rgb("999999")


def _render_chart_as_table(doc: Document, theme: dict, visual_type: str,
                            chart_data: dict, slide: dict) -> None:
    categories = chart_data.get("categories", [])
    values = chart_data.get("values", [])
    series = chart_data.get("series", [])

    if not categories:
        return

    title = slide.get("title", visual_type.replace("_", " ").title())
    cap = doc.add_paragraph()
    cr = cap.add_run(f"Figure: {title}")
    cr.font.italic = True
    cr.font.size = Pt(9)
    cr.font.color.rgb = _hex_to_rgb("666666")

    if series:
        headers = ["Category"] + [s.get("name", f"Series {i+1}")
                                   for i, s in enumerate(series)]
        rows = []
        for i, cat in enumerate(categories):
            row = [str(cat)]
            for s in series:
                s_vals = s.get("values", [])
                row.append(str(s_vals[i]) if i < len(s_vals) else "")
            rows.append(row)
    else:
        headers = ["Category", "Value"]
        rows = [[str(categories[i]),
                 str(values[i]) if i < len(values) else ""]
                for i in range(len(categories))]

    _create_styled_table(doc, theme, headers, rows)


# ── Citation Manager ──────────────────────────────────────────────────

def _collect_evidence_refs(slides: list[dict]) -> list[dict]:
    refs = []
    seen = set()
    for slide in slides:
        evidence_ids = slide.get("evidence_ids_json", [])
        if isinstance(evidence_ids, str):
            try:
                evidence_ids = json.loads(evidence_ids)
            except (json.JSONDecodeError, TypeError):
                evidence_ids = []
        for eid in evidence_ids:
            if eid not in seen:
                seen.add(eid)
                refs.append({"evidence_id": eid, "source": f"Evidence #{eid}",
                             "text": f"Evidence record {eid}"})
    return refs


# ── TOC ───────────────────────────────────────────────────────────────

def _add_toc(doc: Document) -> None:
    p = doc.add_paragraph()
    run = p.add_run("Table of Contents")
    run.font.size = Pt(20)
    run.font.bold = True
    doc.add_paragraph()

    fldChar1 = OxmlElement("w:fldChar")
    fldChar1.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = ' TOC \\o "1-3" \\h \\z \\u '
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "separate")
    fldChar3 = OxmlElement("w:fldChar")
    fldChar3.set(qn("w:fldCharType"), "end")

    p2 = doc.add_paragraph()
    r = p2.add_run()
    r._r.append(fldChar1)
    r._r.append(instrText)
    r._r.append(fldChar2)
    toc_text = p2.add_run("(Update field in Word to generate table of contents)")
    toc_text.font.italic = True
    toc_text.font.color.rgb = _hex_to_rgb("999999")
    toc_text.font.size = Pt(10)
    r2 = p2.add_run()
    r2._r.append(fldChar3)

    doc.add_page_break()


# ── Document Metadata ─────────────────────────────────────────────────

def _set_metadata(doc: Document, pres: dict) -> None:
    props = doc.core_properties
    props.author = "Hunter Intelligence"
    props.title = pres.get("title", "Research Report")
    props.subject = "Intelligence Research Report"
    props.keywords = "research, intelligence, hunter"
    props.category = "Report"
    props.comments = f"Generated by Hunter Intelligence on {date.today().isoformat()}"


# ── Validation ────────────────────────────────────────────────────────

def validate_for_render(pres_id: int) -> dict:
    pres = store.get_pc_presentation(pres_id)
    if not pres:
        return {"valid": False, "issues": ["Presentation not found"], "warnings": []}

    issues = []
    warnings = []

    status = pres.get("status", "draft")
    if status not in ("approved", "draft", "needs_review"):
        issues.append(f"Presentation status is '{status}' — must be approved/draft/needs_review")

    slides = store.list_pc_slides(pres_id)
    if not slides:
        issues.append("No slides found in presentation")
    else:
        has_cover = any(s.get("slide_purpose") == "cover" for s in slides)
        if not has_cover:
            warnings.append("No cover slide found — report will use presentation title")

        has_conclusion = any(s.get("slide_purpose") == "conclusion" for s in slides)
        if not has_conclusion:
            warnings.append("No conclusion slide found — section will be omitted")

        rejected = [s for s in slides if s.get("status") == "rejected"]
        if rejected:
            warnings.append(f"{len(rejected)} rejected slide(s) will be excluded")

        low_conf = [s for s in slides
                    if (s.get("overall_confidence") or 0) < 0.3
                    and s.get("status") != "rejected"]
        if low_conf:
            warnings.append(f"{len(low_conf)} slide(s) have low confidence (<30%)")

    return {"valid": len(issues) == 0, "issues": issues, "warnings": warnings}


# ── Main Render Pipeline ─────────────────────────────────────────────

def render_report(pres_id: int, theme_id: str = "hunter_default",
                  actor: str = "system") -> dict:
    validation = validate_for_render(pres_id)
    if not validation["valid"]:
        return {"error": "Validation failed", "issues": validation["issues"]}

    pres = store.get_pc_presentation(pres_id)
    slides = store.list_pc_slides(pres_id)
    slides = [s for s in slides if s.get("status") != "rejected"]
    slides.sort(key=lambda s: s.get("slide_number", 0))

    theme = _resolve_theme(theme_id)
    job_id = str(uuid.uuid4())
    store.create_word_job(job_id, pres_id, job_type="full", theme_id=theme_id)
    store.update_word_job(job_id, status="running", started_at=time.time())
    store.add_word_history(pres_id, job_id, "render_started",
                           actor=actor,
                           details={"theme_id": theme_id,
                                    "slide_count": len(slides)})

    warnings = list(validation.get("warnings", []))
    start_time = time.time()

    try:
        doc = Document()
        _setup_document(doc, theme)
        _set_metadata(doc, pres)
        _add_header_footer(doc, theme, pres.get("title", "Research Report"))
        _add_page_numbers(doc)

        footnotes: list[dict] = []
        section_stats = {}

        sec_start = time.time()
        _render_cover(doc, theme, pres, slides)
        section_stats["cover"] = time.time() - sec_start
        store.add_word_metric(job_id, "cover", 0, duration_ms=int(section_stats["cover"] * 1000))

        sec_start = time.time()
        _render_confidentiality(doc, theme, pres)
        section_stats["confidentiality"] = time.time() - sec_start
        store.add_word_metric(job_id, "confidentiality", 1,
                              duration_ms=int(section_stats["confidentiality"] * 1000))

        sec_start = time.time()
        _add_toc(doc)
        section_stats["toc"] = time.time() - sec_start
        store.add_word_metric(job_id, "table_of_contents", 2,
                              duration_ms=int(section_stats["toc"] * 1000))

        sec_start = time.time()
        exec_elems = _render_executive_summary(doc, theme, pres, slides)
        section_stats["executive_summary"] = time.time() - sec_start
        store.add_word_metric(job_id, "executive_summary", 3,
                              element_count=exec_elems,
                              duration_ms=int(section_stats["executive_summary"] * 1000))

        sec_start = time.time()
        meth_elems = _render_methodology(doc, theme, pres, slides)
        section_stats["methodology"] = time.time() - sec_start
        store.add_word_metric(job_id, "methodology", 4,
                              element_count=meth_elems,
                              duration_ms=int(section_stats["methodology"] * 1000))

        sec_start = time.time()
        kf_elems = _render_key_findings(doc, theme, slides, footnotes)
        section_stats["key_findings"] = time.time() - sec_start
        store.add_word_metric(job_id, "key_findings", 5,
                              element_count=kf_elems,
                              duration_ms=int(section_stats["key_findings"] * 1000))

        sec_start = time.time()
        ev_elems = _render_supporting_evidence(doc, theme, footnotes)
        section_stats["supporting_evidence"] = time.time() - sec_start
        store.add_word_metric(job_id, "supporting_evidence", 6,
                              element_count=ev_elems,
                              duration_ms=int(section_stats["supporting_evidence"] * 1000))

        sec_start = time.time()
        bi_elems = _render_business_impact(doc, theme, slides)
        section_stats["business_impact"] = time.time() - sec_start
        store.add_word_metric(job_id, "business_impact", 7,
                              element_count=bi_elems,
                              duration_ms=int(section_stats["business_impact"] * 1000))

        sec_start = time.time()
        rec_elems = _render_recommendations(doc, theme, slides)
        section_stats["recommendations"] = time.time() - sec_start
        store.add_word_metric(job_id, "recommendations", 8,
                              element_count=rec_elems,
                              duration_ms=int(section_stats["recommendations"] * 1000))

        sec_start = time.time()
        conc_elems = _render_conclusion(doc, theme, slides)
        section_stats["conclusion"] = time.time() - sec_start
        store.add_word_metric(job_id, "conclusion", 9,
                              element_count=conc_elems,
                              duration_ms=int(section_stats["conclusion"] * 1000))

        sec_start = time.time()
        app_elems = _render_appendix(doc, theme, slides)
        section_stats["appendix"] = time.time() - sec_start
        store.add_word_metric(job_id, "appendix", 10,
                              element_count=app_elems,
                              duration_ms=int(section_stats["appendix"] * 1000))

        output_dir = Path(config.DATA_DIR) / "rendered"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_filename = f"report_{pres_id}_{job_id[:8]}.docx"
        output_path = str(output_dir / output_filename)
        doc.save(output_path)

        file_size = os.path.getsize(output_path)
        elapsed_ms = int((time.time() - start_time) * 1000)

        total_text = []
        for p in doc.paragraphs:
            total_text.append(p.text)
        word_count = sum(len(t.split()) for t in total_text if t)

        existing_docs = store.list_word_documents(pres_id)
        version = len(existing_docs) + 1

        section_count = sum(1 for v in section_stats.values() if v > 0)

        doc_id = store.create_word_document(
            job_id, pres_id, output_path,
            version=version,
            output_size_bytes=file_size,
            section_count=section_count,
            word_count=word_count,
            theme_id=theme_id,
            render_duration_ms=elapsed_ms,
            metadata={"footnotes": len(footnotes)},
        )

        store.update_word_job(
            job_id,
            status="completed",
            output_path=output_path,
            output_size_bytes=file_size,
            warnings=warnings,
            finished_at=time.time(),
            progress_pct=100,
            progress_message="Report complete",
        )

        store.add_word_history(pres_id, job_id, "render_completed",
                               actor=actor,
                               details={"output_path": output_path,
                                        "file_size": file_size,
                                        "sections": section_count,
                                        "word_count": word_count,
                                        "duration_ms": elapsed_ms})

        return {
            "job_id": job_id,
            "status": "completed",
            "output_path": output_path,
            "file_size_bytes": file_size,
            "section_count": section_count,
            "word_count": word_count,
            "render_duration_ms": elapsed_ms,
            "warnings": warnings,
            "version": version,
            "document_id": doc_id,
        }

    except Exception as exc:
        elapsed_ms = int((time.time() - start_time) * 1000)
        error_msg = str(exc)
        store.update_word_job(
            job_id, status="failed", error=error_msg,
            finished_at=time.time(),
        )
        store.add_word_history(pres_id, job_id, "render_failed",
                               actor=actor,
                               details={"error": error_msg,
                                        "duration_ms": elapsed_ms})
        logger.exception("Word render failed")
        return {"error": error_msg, "job_id": job_id, "status": "failed"}


def render_section(pres_id: int, section_name: str,
                   theme_id: str = "hunter_default",
                   actor: str = "system") -> dict:
    if section_name not in SECTION_ORDER:
        return {"error": f"Unknown section: {section_name}"}

    validation = validate_for_render(pres_id)
    if not validation["valid"]:
        return {"error": "Validation failed", "issues": validation["issues"]}

    pres = store.get_pc_presentation(pres_id)
    slides = store.list_pc_slides(pres_id)
    slides = [s for s in slides if s.get("status") != "rejected"]
    theme = _resolve_theme(theme_id)

    job_id = str(uuid.uuid4())
    store.create_word_job(job_id, pres_id, job_type="section", theme_id=theme_id)
    store.update_word_job(job_id, status="running", started_at=time.time())

    start_time = time.time()
    try:
        doc = Document()
        _setup_document(doc, theme)
        footnotes: list[dict] = []

        renderers = {
            "cover": lambda: _render_cover(doc, theme, pres, slides),
            "confidentiality": lambda: _render_confidentiality(doc, theme, pres),
            "executive_summary": lambda: _render_executive_summary(doc, theme, pres, slides),
            "methodology": lambda: _render_methodology(doc, theme, pres, slides),
            "key_findings": lambda: _render_key_findings(doc, theme, slides, footnotes),
            "supporting_evidence": lambda: _render_supporting_evidence(doc, theme, footnotes),
            "business_impact": lambda: _render_business_impact(doc, theme, slides),
            "recommendations": lambda: _render_recommendations(doc, theme, slides),
            "conclusion": lambda: _render_conclusion(doc, theme, slides),
            "appendix": lambda: _render_appendix(doc, theme, slides),
        }

        renderer_fn = renderers.get(section_name)
        if renderer_fn:
            renderer_fn()

        output_dir = Path(config.DATA_DIR) / "rendered"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_filename = f"section_{section_name}_{pres_id}_{job_id[:8]}.docx"
        output_path = str(output_dir / output_filename)
        doc.save(output_path)

        file_size = os.path.getsize(output_path)
        elapsed_ms = int((time.time() - start_time) * 1000)

        store.update_word_job(
            job_id, status="completed", output_path=output_path,
            output_size_bytes=file_size, finished_at=time.time(),
            progress_pct=100,
        )

        return {
            "job_id": job_id,
            "status": "completed",
            "section": section_name,
            "output_path": output_path,
            "file_size_bytes": file_size,
            "render_duration_ms": elapsed_ms,
        }

    except Exception as exc:
        store.update_word_job(job_id, status="failed", error=str(exc),
                              finished_at=time.time())
        return {"error": str(exc), "job_id": job_id, "status": "failed"}


# ── Status & Reporting ────────────────────────────────────────────────

def get_render_status(job_id: str) -> dict | None:
    return store.get_word_job(job_id)


def get_download_path(job_id: str) -> str | None:
    job = store.get_word_job(job_id)
    if not job:
        return None
    path = job.get("output_path")
    if path and os.path.isfile(path):
        return path
    return None


def list_themes() -> list[dict]:
    return store.list_themes()


def get_render_summary(pres_id: int) -> dict:
    jobs = store.list_word_jobs(pres_id)
    docs = store.list_word_documents(pres_id)
    history = store.get_word_history(pres_id)
    latest_job = jobs[0] if jobs else None
    latest_doc = docs[0] if docs else None
    return {
        "total_renders": len(docs),
        "total_jobs": len(jobs),
        "latest_job": latest_job,
        "latest_document": latest_doc,
        "has_download": bool(latest_doc and latest_doc.get("output_path")
                             and os.path.isfile(latest_doc["output_path"])),
        "history_count": len(history),
    }
