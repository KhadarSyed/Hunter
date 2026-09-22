"""Background Brief Word Renderer — generates a premium Intelligence Brief
matching the InfoVision Executive Intelligence format.

Uses python-docx. Styled to match the Lettuce Outbreak Brief reference PDF:
spaced-caps section labels, numbered sections (SECTION · 01), KPI dashboard,
table of contents, descriptive section subtitles, and a professional closing page.

Output structure:
  Cover page → Table of Contents → Executive Summary → Brand Developments →
  Brand Narrative Assessment → Competitor Developments → Industry & Policy
  Context → Key Issues to Monitor → Source Register → Methodology → Closing
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn, nsdecls
from docx.shared import Inches, Pt, Cm, RGBColor, Emu

from . import intelligence_store as store
from . import config

logger = logging.getLogger(__name__)

BRAND_VIOLET = RGBColor(0x5B, 0x2C, 0x9D)
DARK_TEXT = RGBColor(0x1A, 0x1A, 0x2E)
BODY_TEXT = RGBColor(0x33, 0x33, 0x33)
LIGHT_TEXT = RGBColor(0x66, 0x66, 0x66)
MUTED_TEXT = RGBColor(0x99, 0x99, 0x99)
TAG_COLOR = RGBColor(0x7B, 0x4C, 0xBD)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ACCENT_BG = "F5F0FF"
VIOLET_BG = "5B2C9D"

SECTION_SUBTITLES = {
    "company_introduction": "The brand in context",
    "executive_summary": "The brief, distilled",
    "brand_developments": "What moved this cycle",
    "brand_narrative": "How the story is being told",
    "competitor_developments": "The competitive landscape",
    "industry_context": "Forces shaping the market",
    "key_issues": "What to watch next",
    "source_register": "Independently compiled references",
    "methodology": "How this brief was assembled",
}


def render_brief_docx(brief_id: int) -> str:
    brief_row = store.get_brief_by_id(brief_id)
    if not brief_row:
        raise ValueError(f"Brief {brief_id} not found")

    brief = brief_row["brief"]
    title = brief.get("title", "Competitive News Brief")
    subtitle = brief.get("subtitle", "ANALYST BRIEFING")
    subject = brief.get("research_subject", "")
    category = brief.get("category", "COMPETITIVE INTELLIGENCE")

    doc = Document()
    _setup_document(doc)
    _add_cover_page(doc, title, subtitle, subject, brief, category)

    section_order = brief.get("section_order", [])
    sections = brief.get("sections", {})

    content_sections = []
    for key in section_order:
        section = sections.get(key)
        if section and section.get("content", "").strip():
            content_sections.append((key, section))

    _add_table_of_contents(doc, content_sections)

    for idx, (key, section) in enumerate(content_sections):
        content = section.get("content", "")
        sec_title = section.get("title", key.replace("_", " ").title())
        sec_subtitle = SECTION_SUBTITLES.get(key, "")

        doc.add_page_break()
        _add_section_header(doc, idx, sec_title, sec_subtitle)

        if key == "source_register":
            _render_source_register(doc, content)
        elif key == "company_introduction":
            _render_rich_content(doc, content)
        elif key == "executive_summary":
            _render_executive_summary(doc, content)
        elif key in ("brand_developments", "competitor_developments"):
            _render_developments_section(doc, content)
        elif key == "brand_narrative":
            _render_narrative_section(doc, content)
        elif key == "key_issues":
            _render_key_issues(doc, content)
        elif key == "methodology":
            _render_methodology(doc, content)
        else:
            _render_rich_content(doc, content)

    _add_closing_page(doc, subject, brief)
    _add_header_footer(doc, title)

    output_dir = Path(config.DATA_DIR) / "briefs"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_subject = re.sub(r'[^\w\s-]', '', subject).strip().replace(' ', '_')[:50]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Intelligence_Brief_{safe_subject}_{timestamp}.docx"
    filepath = str(output_dir / filename)

    doc.save(filepath)
    store.update_brief_docx(brief_id, filepath)

    logger.info("Intelligence Brief DOCX rendered: %s", filepath)
    return filepath


# ── Document setup ──────────────────────────────────────────────────────

def _setup_document(doc: Document) -> None:
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(10.5)
    font.color.rgb = BODY_TEXT
    pf = style.paragraph_format
    pf.space_after = Pt(6)
    pf.line_spacing = 1.2

    for level in range(1, 4):
        style_name = f"Heading {level}"
        if style_name in doc.styles:
            hs = doc.styles[style_name]
            hs.font.name = "Calibri"
            hs.font.color.rgb = BRAND_VIOLET
            hs.font.bold = True
            if level == 1:
                hs.font.size = Pt(22)
                hs.paragraph_format.space_before = Pt(0)
                hs.paragraph_format.space_after = Pt(4)
            elif level == 2:
                hs.font.size = Pt(13)
                hs.paragraph_format.space_before = Pt(18)
                hs.paragraph_format.space_after = Pt(6)
            else:
                hs.font.size = Pt(11)
                hs.paragraph_format.space_before = Pt(14)
                hs.paragraph_format.space_after = Pt(4)

    section = doc.sections[0]
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.54)
    section.right_margin = Cm(2.54)


# ── Cover page ──────────────────────────────────────────────────────────

def _add_cover_page(doc: Document, title: str, subtitle: str,
                    subject: str, brief: dict, category: str) -> None:
    for _ in range(3):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run("E X E C U T I V E   I N T E L L I G E N C E")
    run.font.size = Pt(9)
    run.font.color.rgb = BRAND_VIOLET
    run.font.bold = True
    run.font.name = "Calibri"

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_after = Pt(2)
    date_str = brief.get("generated_at", datetime.now().strftime("%B %d, %Y"))
    run = p.add_run(f"D A T E :   {_space_text(date_str.upper())}")
    run.font.size = Pt(8)
    run.font.color.rgb = MUTED_TEXT
    run.font.name = "Calibri"

    if category:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(_space_text(category.upper()))
        run.font.size = Pt(8)
        run.font.color.rgb = MUTED_TEXT
        run.font.name = "Calibri"

    doc.add_paragraph()

    _add_violet_rule(doc)

    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(title)
    run.font.size = Pt(28)
    run.font.color.rgb = DARK_TEXT
    run.font.bold = True
    run.font.name = "Calibri"

    purpose = brief.get("purpose", "")
    if purpose:
        doc.add_paragraph()
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = p.add_run(purpose)
        run.font.size = Pt(11)
        run.font.color.rgb = LIGHT_TEXT
        run.font.name = "Calibri"
        run.font.italic = True

    doc.add_paragraph()
    doc.add_paragraph()

    competitors = brief.get("competitors", [])
    if competitors:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = p.add_run("BRANDS TRACKED")
        run.font.size = Pt(8)
        run.font.color.rgb = BRAND_VIOLET
        run.font.bold = True
        run.font.name = "Calibri"
        _add_letter_spacing(run, 100)

        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(12)
        run = p.add_run(", ".join(competitors))
        run.font.size = Pt(10)
        run.font.color.rgb = BODY_TEXT
        run.font.name = "Calibri"

    meta = brief.get("metadata", {})
    source_count = brief.get("source_count", 0)
    if source_count:
        p = doc.add_paragraph()
        run = p.add_run(f"{source_count} validated sources")
        run.font.size = Pt(10)
        run.font.color.rgb = LIGHT_TEXT
        run.font.name = "Calibri"
        tier1 = meta.get("tier_1_count", 0)
        if tier1:
            run = p.add_run(f"  ·  {tier1} tier-1 authoritative")
            run.font.size = Pt(10)
            run.font.color.rgb = LIGHT_TEXT
            run.font.name = "Calibri"

    doc.add_paragraph()
    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run("C O N F I D E N T I A L")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)
    run.font.bold = True
    run.font.name = "Calibri"


# ── Table of contents ───────────────────────────────────────────────────

def _add_table_of_contents(doc: Document, content_sections: list) -> None:
    doc.add_page_break()

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run("I N   T H I S   E D I T I O N")
    run.font.size = Pt(9)
    run.font.color.rgb = BRAND_VIOLET
    run.font.bold = True
    run.font.name = "Calibri"

    doc.add_paragraph()

    p = doc.add_paragraph()
    run = p.add_run("Contents")
    run.font.size = Pt(24)
    run.font.color.rgb = DARK_TEXT
    run.font.bold = True
    run.font.name = "Calibri"

    doc.add_paragraph()
    _add_violet_rule(doc)
    doc.add_paragraph()

    for idx, (key, section) in enumerate(content_sections):
        sec_title = section.get("title", key.replace("_", " ").title())
        sec_subtitle = SECTION_SUBTITLES.get(key, "")

        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(2)

        run = p.add_run(f"{idx:02d}")
        run.font.size = Pt(20)
        run.font.color.rgb = BRAND_VIOLET
        run.font.bold = True
        run.font.name = "Calibri"

        run = p.add_run(f"   {sec_title}")
        run.font.size = Pt(12)
        run.font.color.rgb = DARK_TEXT
        run.font.bold = True
        run.font.name = "Calibri"

        if sec_subtitle:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(8)
            run = p.add_run(f"     {sec_subtitle}")
            run.font.size = Pt(10)
            run.font.color.rgb = LIGHT_TEXT
            run.font.name = "Calibri"

        _add_thin_rule(doc)


# ── Section header (SECTION · XX) ──────────────────────────────────────

def _add_section_header(doc: Document, index: int, title: str,
                        subtitle: str = "") -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(f"S E C T I O N  ·  {index:02d}")
    run.font.size = Pt(9)
    run.font.color.rgb = BRAND_VIOLET
    run.font.bold = True
    run.font.name = "Calibri"

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(title)
    run.font.size = Pt(22)
    run.font.color.rgb = DARK_TEXT
    run.font.bold = True
    run.font.name = "Calibri"

    if subtitle:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(8)
        run = p.add_run(subtitle)
        run.font.size = Pt(11)
        run.font.color.rgb = LIGHT_TEXT
        run.font.name = "Calibri"
        run.font.italic = True

    _add_violet_rule(doc)
    doc.add_paragraph()


# ── Rules & visual elements ────────────────────────────────────────────

def _add_violet_rule(doc: Document) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    pPr = p._element.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "5B2C9D")
    pBdr.append(bottom)
    pPr.append(pBdr)


def _add_thin_rule(doc: Document) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    pPr = p._element.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "2")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "DDDDDD")
    pBdr.append(bottom)
    pPr.append(pBdr)


def _add_letter_spacing(run, spacing_twips: int) -> None:
    rPr = run._element.get_or_add_rPr()
    spacing_el = OxmlElement("w:spacing")
    spacing_el.set(qn("w:val"), str(spacing_twips))
    rPr.append(spacing_el)


def _space_text(text: str) -> str:
    """Add spaces between characters for tracked/spaced-caps effect."""
    return "  ".join(text)


def _set_paragraph_shading(paragraph, color_hex: str) -> None:
    pPr = paragraph._element.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color_hex)
    shd.set(qn("w:val"), "clear")
    pPr.append(shd)


# ── KPI block ──────────────────────────────────────────────────────────

def _add_kpi_row(doc: Document, kpis: list[dict]) -> None:
    """Render a row of KPI values with labels underneath."""
    if not kpis:
        return

    table = doc.add_table(rows=2, cols=len(kpis))
    table.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for i, kpi in enumerate(kpis):
        cell = table.cell(0, i)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(str(kpi.get("value", "")))
        run.font.size = Pt(24)
        run.font.color.rgb = BRAND_VIOLET
        run.font.bold = True
        run.font.name = "Calibri"

        cell = table.cell(1, i)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(kpi.get("label", "").upper())
        run.font.size = Pt(7)
        run.font.color.rgb = MUTED_TEXT
        run.font.bold = True
        run.font.name = "Calibri"
        _add_letter_spacing(run, 60)

    for row in table.rows:
        for cell in row.cells:
            tc = cell._element
            tcPr = tc.get_or_add_tcPr()
            borders = OxmlElement("w:tcBorders")
            for edge in ("top", "left", "bottom", "right"):
                el = OxmlElement(f"w:{edge}")
                el.set(qn("w:val"), "none")
                el.set(qn("w:sz"), "0")
                borders.append(el)
            tcPr.append(borders)

    doc.add_paragraph()


# ── Takeaway block ─────────────────────────────────────────────────────

def _add_takeaway(doc: Document, number: int, title: str, body: str) -> None:
    """Render a numbered strategic takeaway."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(2)
    _set_paragraph_shading(p, ACCENT_BG)

    run = p.add_run(f"TAKEAWAY {number:02d}")
    run.font.size = Pt(8)
    run.font.color.rgb = BRAND_VIOLET
    run.font.bold = True
    run.font.name = "Calibri"
    _add_letter_spacing(run, 80)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    _set_paragraph_shading(p, ACCENT_BG)
    run = p.add_run(title)
    run.font.size = Pt(14)
    run.font.color.rgb = DARK_TEXT
    run.font.bold = True
    run.font.name = "Calibri"

    if body:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(12)
        _set_paragraph_shading(p, ACCENT_BG)
        _add_rich_text(p, body, size=Pt(10))


# ── Section renderers ──────────────────────────────────────────────────

def _render_executive_summary(doc: Document, content: str) -> None:
    if not content:
        return

    lines = content.split("\n")
    takeaway_num = 0
    in_takeaway = False
    takeaway_title = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("## "):
            heading_text = stripped[3:]
            if "what this means" in heading_text.lower() or "takeaway" in heading_text.lower():
                continue
            doc.add_heading(heading_text, level=2)
            continue

        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=3)
            continue

        if stripped.startswith("- "):
            text = stripped[2:]
            if "**" in text and ":" in text:
                takeaway_num += 1
                bold_match = re.match(r'\*\*([^*]+)\*\*[:\s]*(.*)', text)
                if bold_match:
                    _add_takeaway(doc, takeaway_num, bold_match.group(1),
                                  bold_match.group(2))
                    continue
            p = doc.add_paragraph(style="List Bullet")
            _add_rich_text(p, text, size=Pt(10.5))
            continue

        p = doc.add_paragraph()
        _add_rich_text(p, stripped, size=Pt(10.5))


def _render_developments_section(doc: Document, content: str) -> None:
    if not content:
        return

    lines = content.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
            continue

        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=3)
            continue

        if stripped.startswith("Strategic tags:"):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(10)
            run = p.add_run("STRATEGIC TAGS")
            run.font.size = Pt(7)
            run.font.color.rgb = BRAND_VIOLET
            run.font.bold = True
            run.font.name = "Calibri"
            _add_letter_spacing(run, 60)

            tags = stripped.replace("Strategic tags:", "").strip()
            run = p.add_run(f"   {tags}")
            run.font.size = Pt(9)
            run.font.color.rgb = TAG_COLOR
            run.font.italic = True
            run.font.name = "Calibri"
            continue

        if stripped.startswith("- "):
            text = stripped[2:]
            p = doc.add_paragraph(style="List Bullet")
            _add_rich_text(p, text, size=Pt(10.5))
            continue

        p = doc.add_paragraph()
        _add_rich_text(p, stripped, size=Pt(10.5))


def _render_narrative_section(doc: Document, content: str) -> None:
    if not content:
        return

    lines = content.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
            continue

        if stripped.startswith("- **") and ":**" in stripped:
            label_match = re.match(r'^- \*\*([^*]+):\*\*\s*(.*)', stripped)
            if label_match:
                p = doc.add_paragraph(style="List Bullet")
                run = p.add_run(f"{label_match.group(1)}: ")
                run.bold = True
                run.font.size = Pt(10.5)
                run.font.color.rgb = BRAND_VIOLET
                run.font.name = "Calibri"
                _add_rich_text(p, label_match.group(2), size=Pt(10.5),
                               append=True)
                continue

        if stripped.startswith("- "):
            text = stripped[2:]
            p = doc.add_paragraph(style="List Bullet")
            _add_rich_text(p, text, size=Pt(10.5))
            continue

        p = doc.add_paragraph()
        _add_rich_text(p, stripped, size=Pt(10.5))


def _render_key_issues(doc: Document, content: str) -> None:
    if not content:
        return

    issue_num = 0
    lines = content.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
            continue

        if stripped.startswith("### "):
            issue_num += 1
            issue_title = stripped[4:]
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(4)
            run = p.add_run(f"ISSUE {issue_num:02d}")
            run.font.size = Pt(8)
            run.font.color.rgb = BRAND_VIOLET
            run.font.bold = True
            run.font.name = "Calibri"
            _add_letter_spacing(run, 60)

            run = p.add_run(f"   {issue_title}")
            run.font.size = Pt(12)
            run.font.color.rgb = DARK_TEXT
            run.font.bold = True
            run.font.name = "Calibri"
            continue

        if stripped.startswith("- "):
            text = stripped[2:]
            p = doc.add_paragraph(style="List Bullet")
            _add_rich_text(p, text, size=Pt(10.5))
            continue

        p = doc.add_paragraph()
        _add_rich_text(p, stripped, size=Pt(10.5))


def _render_methodology(doc: Document, content: str) -> None:
    if not content:
        return

    lines = content.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
            continue

        if stripped.startswith("- "):
            text = stripped[2:]
            p = doc.add_paragraph(style="List Bullet")
            _add_rich_text(p, text, size=Pt(9.5))
            continue

        p = doc.add_paragraph()
        _add_rich_text(p, stripped, size=Pt(9.5))


def _render_source_register(doc: Document, content: str) -> None:
    if not content:
        return

    lines = content.split("\n")
    source_num = 0
    first_line = True
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
            continue

        ref_match = re.match(r'^\[?(S\d+)\]?\s*\|?\s*(.*)', stripped)
        if ref_match and ref_match.group(1):
            source_num += 1
            ref = ref_match.group(1)
            rest = ref_match.group(2)

            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(2)

            run = p.add_run(f"{source_num:02d}")
            run.font.size = Pt(12)
            run.font.color.rgb = BRAND_VIOLET
            run.font.bold = True
            run.font.name = "Calibri"

            run = p.add_run(f"   ")
            run.font.size = Pt(9)

            _add_rich_text(p, rest, size=Pt(9), append=True)
            _add_thin_rule(doc)
            first_line = False
            continue

        if first_line:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(10)
            run = p.add_run(stripped)
            run.font.size = Pt(10)
            run.font.italic = True
            run.font.name = "Calibri"
            run.font.color.rgb = LIGHT_TEXT
            first_line = False
            continue

        p = doc.add_paragraph()
        run = p.add_run(stripped)
        run.font.size = Pt(9)
        run.font.name = "Calibri"


def _render_rich_content(doc: Document, content: str) -> None:
    if not content:
        return

    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
            continue

        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=3)
            continue

        if stripped.startswith("Strategic tags:"):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(6)
            run = p.add_run("STRATEGIC TAGS")
            run.font.size = Pt(7)
            run.font.color.rgb = BRAND_VIOLET
            run.font.bold = True
            run.font.name = "Calibri"
            _add_letter_spacing(run, 60)
            tags = stripped.replace("Strategic tags:", "").strip()
            run = p.add_run(f"   {tags}")
            run.font.size = Pt(9)
            run.font.color.rgb = TAG_COLOR
            run.font.italic = True
            run.font.name = "Calibri"
            continue

        if stripped.startswith("- "):
            text = stripped[2:]
            p = doc.add_paragraph(style="List Bullet")
            _add_rich_text(p, text, size=Pt(10.5))
            continue

        p = doc.add_paragraph()
        _add_rich_text(p, stripped, size=Pt(10.5))


# ── Rich text with inline formatting ───────────────────────────────────

def _add_rich_text(paragraph, text: str, size=None, append=False) -> None:
    sz = size or Pt(10.5)
    parts = re.split(r'(\*\*[^*]+\*\*|\[S\d+\])', text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
            run.font.size = sz
            run.font.name = "Calibri"
            run.font.color.rgb = DARK_TEXT
        elif re.match(r'^\[S\d+\]$', part):
            run = paragraph.add_run(part)
            run.font.size = Pt(8)
            run.font.color.rgb = BRAND_VIOLET
            run.font.bold = True
            run.font.name = "Calibri"
        else:
            run = paragraph.add_run(part)
            run.font.size = sz
            run.font.name = "Calibri"
            run.font.color.rgb = BODY_TEXT


# ── Closing page ───────────────────────────────────────────────────────

def _add_closing_page(doc: Document, subject: str, brief: dict) -> None:
    doc.add_page_break()

    for _ in range(6):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run("When the landscape shifts,\nso should your narrative.")
    run.font.size = Pt(22)
    run.font.color.rgb = DARK_TEXT
    run.font.bold = True
    run.font.name = "Calibri"

    doc.add_paragraph()
    _add_violet_rule(doc)
    doc.add_paragraph()

    p = doc.add_paragraph()
    run = p.add_run(
        "This brief was assembled from monitored coverage and validated "
        "sources. It captures a single cycle. In a fast-moving environment, "
        "the brand that responds effectively is the one that understood where "
        "the conversation was heading while there was still time to act. "
        "That is the work we do."
    )
    run.font.size = Pt(10)
    run.font.color.rgb = LIGHT_TEXT
    run.font.name = "Calibri"
    run.font.italic = True

    doc.add_paragraph()
    doc.add_paragraph()

    capabilities = [
        ("Brand-Risk & Attribution", "Who is carrying the coverage and where exposure sits"),
        ("Narrative Intelligence", "Which storylines are hardening and which are fading"),
        ("Competitive Monitoring", "What competitors are doing that changes your position"),
        ("Crisis Preparedness", "Early signals before they become headline risk"),
    ]

    for cap_title, cap_desc in capabilities:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(cap_title)
        run.font.size = Pt(10)
        run.font.color.rgb = BRAND_VIOLET
        run.font.bold = True
        run.font.name = "Calibri"

        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(10)
        run = p.add_run(cap_desc)
        run.font.size = Pt(9)
        run.font.color.rgb = LIGHT_TEXT
        run.font.name = "Calibri"

    doc.add_paragraph()
    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run("Hunter Intelligence  ·  InfoVision Inc.")
    run.font.size = Pt(9)
    run.font.color.rgb = MUTED_TEXT
    run.font.name = "Calibri"


# ── Header / footer ───────────────────────────────────────────────────

def _add_header_footer(doc: Document, title: str) -> None:
    section = doc.sections[0]
    section.different_first_page_header_footer = True

    header = section.header
    hp = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = hp.add_run(title.upper())
    run.font.size = Pt(7)
    run.font.color.rgb = MUTED_TEXT
    run.font.name = "Calibri"
    _add_letter_spacing(run, 40)

    footer = section.footer
    fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = fp.add_run("C O N F I D E N T I A L")
    run.font.size = Pt(6)
    run.font.color.rgb = MUTED_TEXT
    run.font.name = "Calibri"
    run = fp.add_run("   ·   Hunter Intelligence  ·  InfoVision Inc.")
    run.font.size = Pt(6)
    run.font.color.rgb = MUTED_TEXT
    run.font.name = "Calibri"
