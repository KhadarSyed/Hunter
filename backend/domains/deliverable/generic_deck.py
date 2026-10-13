"""Render stage: one visual deck for any project - cover with brand banner or category photo, executive answers,
overview, per-RQ chart slides with cited insight cards, tables, logos and icons, takeaways, methodology and a
citation appendix - in the brand heading font, accent and chart tints."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn
from pptx.util import Inches

from . import blocks, style
from .amcharts_png import render_treemap_png
from .deck import _add_logo, _move_to_end, keep_cover_and_closing, paginate
from .engine_types import RQ, Section
from .gauge import render_gauge_png
from .qc import estimate_overflow

logger = logging.getLogger(__name__)
CITES_PER_PAGE = 14
CHART_TOP = 1.5
FOOT_SOURCE = "SOURCE: MELTWATER"
EMU_PER_IN = 914400
COVER_IMAGE_TOP = 1.2
COVER_IMAGE_W = 4.2
COVER_IMAGE_MAX_H = 5.0
TITLE_BOX_W, TITLE_BOX_H = 5.7, 0.55     # blocks.add_header title box, one line at TITLE_PT
MAX_TILES = 5
KICKER_MAX_TOP = 0.4        # the header kicker sits at 0.15in
CONTACT_BAND = 0.8          # template pictures below this share of the slide height are contact icons
TITLE_FONT_FILE = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arialbd.ttf"
TITLE_PAD_IN = 0.2          # text box insets
QUESTION_CHARS = 95
CITE_TITLE_CHARS = 62     # one line in the 5in headline column


@dataclass
class DeckInput:
    title: str
    subtitle: str
    date_label: str
    period_label: str
    rqs: list[RQ]
    overview: Section
    sections_by_rq: dict[str, list[Section]]
    insights_by_rq: dict[str, list[dict]]
    answers: list[dict]
    takeaways: list[dict]
    methodology: list[str]
    citations: list[dict]
    base_n: int
    palette: list[str]
    accent: str
    title_font: str
    logos: dict[str, Path]
    icons: dict[str, Path]
    hero: Path | None
    hero_credit: str
    brand_image: Path | None
    flag: Path | None
    rq_titles: dict[str, str] = field(default_factory=dict)   # short slide titles from the analysis plan
    citation_icons: dict[int, Path] = field(default_factory=dict)
    brand_colors: list[str] = field(default_factory=list)      # Brandfetch colours, for the studio art director   # citation number -> source domain favicon


def _title_too_wide(text: str) -> bool:
    """Measured with the bold font when it is installed; the character estimate under-counts bold capitals."""
    if TITLE_FONT_FILE.exists():
        from PIL import ImageFont
        font = ImageFont.truetype(str(TITLE_FONT_FILE), style.TITLE_PT)
        return font.getlength(text + "…") / 72 > TITLE_BOX_W - TITLE_PAD_IN
    return estimate_overflow(text, TITLE_BOX_W, TITLE_BOX_H, style.TITLE_PT)


def _fit_title(text: str) -> str:
    """Trim at a word boundary until the title sits on one line of the header title box."""
    words = text.split()
    while len(words) > 1 and _title_too_wide(" ".join(words)):
        words = words[:-1]
    fitted = " ".join(words)
    return fitted if fitted == text.strip() else fitted.rstrip(",;:") + "…"


def _shorten(text: str, limit: int) -> str:
    """Cut at a word boundary with an ellipsis, never mid-word."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _slide(prs, inp: DeckInput, kicker: str, title: str, summary: str = "", icon: Path | None = None):
    s = blocks.new_content_slide(prs)
    blocks.add_header(s, kicker, _fit_title(title), summary, font=inp.title_font, accent=inp.accent)
    blocks.add_footer(s, f"{FOOT_SOURCE}  |  {inp.period_label}", inp.base_n)
    if icon and icon.exists():
        s.shapes.add_picture(str(icon), Inches(style.SLIDE_W - 0.95), Inches(0.3), height=Inches(0.5))
    return s


def _picture(slide, path: Path, x, y, w, h):
    slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))


def _draw_chart(slide, sec: Section, inp: DeckInput, work: Path, x, y, w, h):
    c = sec.chart
    kind, cats, vals = c["kind"], c.get("categories", []), c.get("values", [])
    if kind == "line_peaks":
        blocks.add_line_chart_with_peaks(slide, x, y, w, h, cats, vals, c.get("peaks", []))
    elif kind == "bar":
        fmt = blocks.PERCENT_FORMAT if c.get("unit") == "percent" else "0"
        blocks.add_bar_chart(slide, x, y, w, h, cats, vals, color=inp.palette[0], number_format=fmt)
    elif kind == "column":
        blocks.add_column_chart(slide, x, y, w, h, cats, vals, c.get("peaks", []))
    elif kind == "doughnut":
        blocks.add_doughnut(slide, x, y, w, h, cats, vals, colors=inp.palette)
    elif kind == "gauge":
        try:
            png = render_gauge_png(vals[0], cats[0] if cats else "", work / f"{sec.id}-gauge.png")
            _picture(slide, png, x, y, w, min(h, w * 0.62))
        except Exception as e:      # offline or no Chromium: the same figure as a native tile
            logger.warning("gauge render failed for %s, using a tile: %s", sec.id, e)
            blocks.add_kpi_tiles(slide, x, y, w, min(h, 2.2),
                                 [{"value": f"{vals[0]}%", "label": cats[0] if cats else "", "note": ""}])
    elif kind == "treemap":
        try:
            png = render_treemap_png(cats, vals, work / f"{sec.id}-treemap.png", palette=inp.palette)
            _picture(slide, png, x, y, w, min(h, w * 0.62))
        except Exception as e:      # offline or no Chromium: the same figures as a native bar chart
            logger.warning("treemap render failed for %s, using bars: %s", sec.id, e)
            blocks.add_bar_chart(slide, x, y, w, h, cats, vals, color=inp.palette[0], number_format="0")
    elif kind == "kpi":
        note = sec.facts[0].split(": ", 1)[-1] if sec.facts else ""
        blocks.add_kpi_tiles(slide, x, y, w, min(h, 2.2),
                             [{"value": f"{vals[0]}%", "label": cats[0] if cats else "", "note": note}])


def _strip_template_text(slide) -> None:
    """Template slides lend their styling (background art, logos, imagery), never their words."""
    for sh in list(slide.shapes):
        if sh.has_text_frame and sh.shape_type != MSO_SHAPE_TYPE.PICTURE:
            sh._element.getparent().remove(sh._element)


def _cover(prs, inp: DeckInput):
    cover = prs.slides[0]
    _strip_template_text(cover)
    blocks.add_text(cover, 0.6, 5.0, 7.6, 0.8, inp.title, 36, True, inp.accent, font=inp.title_font)
    blocks.add_text(cover, 0.6, 5.85, 7.6, 0.5, inp.subtitle, 20, False, style.BODY, font=inp.title_font)
    blocks.add_text(cover, 0.6, 6.5, 4.0, 0.35, inp.date_label, 12)
    use_brand = bool(inp.brand_image and inp.brand_image.exists())
    image = inp.brand_image if use_brand else inp.hero
    if image and image.exists():
        pic = cover.shapes.add_picture(str(image), Inches(style.SLIDE_W - 4.6), Inches(COVER_IMAGE_TOP),
                                       width=Inches(COVER_IMAGE_W))
        if pic.height > Inches(COVER_IMAGE_MAX_H):          # tall images: fit the height, keep the aspect ratio
            ratio = Inches(COVER_IMAGE_MAX_H) / pic.height
            pic.height, pic.width = Inches(COVER_IMAGE_MAX_H), int(pic.width * ratio)
    if inp.flag and inp.flag.exists():   # bottom right, clear of the template title block on the left
        cover.shapes.add_picture(str(inp.flag), Inches(style.SLIDE_W - 1.1), Inches(6.35), height=Inches(0.4))


def _exec_summary(prs, inp: DeckInput):
    s = _slide(prs, inp, "EXECUTIVE SUMMARY", "What the coverage says",
               f"Base: {inp.base_n} unique articles across {len(inp.rqs)} questions", inp.icons.get("overview"))
    tiles = [{"value": a["value"], "label": a["rq_id"], "note": a["answer"]} for a in inp.answers[:MAX_TILES]]
    blocks.add_kpi_tiles(s, style.MARGIN, CHART_TOP, style.SLIDE_W - 2 * style.MARGIN, 2.4, tiles)
    rows = [[a["rq_id"], _shorten(a["question"], QUESTION_CHARS), a["answer"]] for a in inp.answers]
    blocks.add_table(s, style.MARGIN, 4.1, style.SLIDE_W - 2 * style.MARGIN, 0.3 * (len(rows) + 1),
                     ["Question", "Asked", "Answer"], rows, [1.0, 6.0, 5.4])


def _overview(prs, inp: DeckInput, work: Path):
    s = _slide(prs, inp, "OVERVIEW", inp.overview.title, inp.overview.facts[0] if inp.overview.facts else "",
               inp.icons.get("overview"))
    _draw_chart(s, inp.overview, inp, work, style.MARGIN, CHART_TOP, 7.4, 4.6)
    blocks.add_text(s, 8.2, CHART_TOP, 4.6, 4.6, "\n".join(inp.overview.facts[1:8]), 10)


def _logo_row(slide, inp: DeckInput, names: list[str], x: float, y: float):
    for j, name in enumerate([n for n in names if n in inp.logos][:6]):
        _add_logo(slide, inp.logos[name], x + (j % 3) * 1.45, y + (j // 3) * 0.75, 0.55)


def _rq_slides(prs, inp: DeckInput, rq: RQ, work: Path):
    sections = inp.sections_by_rq.get(rq.id, [])
    drawable = [x for x in sections if not x.skipped and x.chart and x.chart["kind"] != "kpi"]
    kpi = next((x for x in sections if x.module == "share_kpi" and not x.skipped), None)
    insights = inp.insights_by_rq.get(rq.id, [])
    summary = kpi.facts[0].split(": ", 1)[-1] if kpi else "No articles for this question"
    title = inp.rq_titles.get(rq.id) or rq.question[:60]
    s = _slide(prs, inp, rq.id, title, summary, inp.icons.get("share_kpi"))
    if not kpi:
        blocks.add_text(s, style.MARGIN, CHART_TOP + 0.4, 12, 0.6, "No articles for this question", 18, True,
                        inp.accent, font=inp.title_font)
        return
    first = drawable[:2]
    width = (style.SLIDE_W - 2 * style.MARGIN - 0.3) / max(1, len(first))
    for i, sec in enumerate(first):
        x = style.MARGIN + i * (width + 0.3)
        blocks.add_text(s, x, CHART_TOP, width, 0.3, sec.title, 11, True, inp.accent, font=inp.title_font)
        _draw_chart(s, sec, inp, work, x, CHART_TOP + 0.3, width, 2.7)
        notes = [n for n in sec.notes if n != "logos"]
        if notes:
            blocks.add_text(s, x, CHART_TOP + 3.0, width, 0.25, "; ".join(notes), 8)
    if insights:
        blocks.add_insight_cards(s, style.MARGIN, CHART_TOP + 3.35, style.SLIDE_W - 2 * style.MARGIN, 2.0,
                                 insights[:3], cols=3, cite_icons=_cite_icons(inp))
    for sec in drawable[2:]:
        s2 = _slide(prs, inp, rq.id, sec.title, sec.facts[0] if sec.facts else "", inp.icons.get(sec.module))
        _draw_chart(s2, sec, inp, work, style.MARGIN, CHART_TOP, 7.6, 4.6)
        blocks.add_text(s2, 8.4, CHART_TOP, 4.4, 3.8, "\n".join(sec.facts[1:7]), 10)
        if any(c in inp.logos for c in sec.chart["categories"]):
            _logo_row(s2, inp, sec.chart["categories"], 8.4, 5.3)
    for sec in (x for x in sections if not x.skipped and x.table):
        s3 = _slide(prs, inp, rq.id, sec.title, sec.facts[0] if sec.facts else "", inp.icons.get(sec.module))
        rows = sec.table["rows"][:12]
        blocks.add_table(s3, style.MARGIN, CHART_TOP, style.SLIDE_W - 2 * style.MARGIN, 0.32 * (len(rows) + 1),
                         sec.table["header"], rows, sec.table["col_widths"])
    skipped = [x for x in sections if x.skipped and x.module != "share_kpi"]
    if skipped:
        blocks.add_text(s, style.MARGIN, 6.55, 12, 0.25,
                        "Not shown: " + "; ".join(f"{x.title} ({x.skipped})" for x in skipped), 8)


def _takeaways(prs, inp: DeckInput):
    s = _slide(prs, inp, "KEY TAKEAWAYS", "What to do next", "", inp.icons.get("takeaway"))
    blocks.add_insight_cards(s, style.MARGIN, CHART_TOP, style.SLIDE_W - 2 * style.MARGIN, 4.8, inp.takeaways[:6],
                             cols=3, cite_icons=_cite_icons(inp))


def _methodology(prs, inp: DeckInput):
    s = _slide(prs, inp, "APPENDIX", "Definitions & Methodology", "", inp.icons.get("methodology"))
    blocks.add_text(s, style.MARGIN, CHART_TOP, style.SLIDE_W - 2 * style.MARGIN, 4.8, "\n".join(inp.methodology), 10)


def _citations(prs, inp: DeckInput) -> list[int]:
    pages = paginate(inp.citations, CITES_PER_PAGE)
    numbers = []
    for i, page in enumerate(pages, start=1):
        s = _slide(prs, inp, "APPENDIX", f"Citations ({i}/{len(pages)})")
        rows = [["", str(c["n"]), c["outlet"] or c.get("domain", ""), _shorten(c["title"], CITE_TITLE_CHARS),
                 c["date"], c["url"][:55]] for c in page]
        blocks.add_table(s, style.MARGIN, CHART_TOP, style.SLIDE_W - 2 * style.MARGIN, 0.3 * (len(rows) + 1),
                         ["", "#", "Outlet", "Headline", "Date", "URL"], rows, [0.45, 0.45, 1.9, 5.0, 1.15, 3.45])
        for r, c in enumerate(page, start=1):   # the source domain icon sits in the first column
            icon = inp.citation_icons.get(c["n"])
            if icon and icon.exists():
                s.shapes.add_picture(str(icon), Inches(style.MARGIN + 0.12), Inches(CHART_TOP + 0.3 * r + 0.05),
                                     height=Inches(0.2))
        numbers.append(len(prs.slides))
    return numbers


_ICON_TYPES = (MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.GROUP, MSO_SHAPE_TYPE.FREEFORM, MSO_SHAPE_TYPE.AUTO_SHAPE)


def _drop_icons_below(shapes, band: int, to_slide=lambda y: y) -> None:
    """Removes icon shapes whose slide-space top is in the band, looking inside groups (whose children use
    their own coordinate space, mapped back through the group's offset and scale)."""
    for sh in list(shapes):
        if sh.shape_type not in _ICON_TYPES or (sh.has_text_frame and sh.text_frame.text.strip()):
            continue
        if to_slide(sh.top) >= band:
            sh._element.getparent().remove(sh._element)
        elif sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            xfrm = sh._element.grpSpPr.find(qn("a:xfrm"))
            off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
            ch_off, ch_ext = xfrm.find(qn("a:chOff")), xfrm.find(qn("a:chExt"))
            if None in (off, ext, ch_off, ch_ext) or not int(ch_ext.get("cy")):
                continue
            scale = int(ext.get("cy")) / int(ch_ext.get("cy"))
            top, ch_top = int(off.get("y")), int(ch_off.get("y"))
            _drop_icons_below(sh.shapes, band, lambda y, f=to_slide: f(top + (y - ch_top) * scale))


def _drop_contact_icons(slide) -> None:
    """The template's phone/mail/location icons label contact text we removed; alone they mean nothing."""
    _drop_icons_below(slide.shapes, Inches(style.SLIDE_H * CONTACT_BAND))


def _closing(prs, inp: DeckInput):
    closing = prs.slides[-1]
    _strip_template_text(closing)
    _drop_contact_icons(closing)
    blocks.add_text(closing, 0.8, 2.6, 8.0, 1.0, "Thank you", 44, True, inp.accent, font=inp.title_font)
    blocks.add_text(closing, 0.8, 3.7, 8.0, 0.5, f"{inp.title} – {inp.subtitle}", 18, False, style.BODY,
                    font=inp.title_font)
    blocks.add_text(closing, 0.8, 4.25, 8.0, 0.4, inp.date_label, 12)


def rq_first_slides(pptx_path: Path, rq_ids: list[str]) -> dict[str, int]:
    """1-based number of each RQ's first slide (the one whose kicker is the RQ id)."""
    first: dict[str, int] = {}
    for n, slide in enumerate(Presentation(str(pptx_path)).slides, start=1):
        for sh in slide.shapes:
            in_header = sh.top is not None and sh.top < Inches(KICKER_MAX_TOP)   # not the summary tiles
            if in_header and sh.has_text_frame and sh.text_frame.text in rq_ids and sh.text_frame.text not in first:
                first[sh.text_frame.text] = n
    return first


def _cite_icons(inp: DeckInput):
    if not inp.citation_icons:
        return None
    return lambda cites: [inp.citation_icons.get(n) for n in cites]


def build_generic_deck(inp: DeckInput, template: Path, work_dir: Path, out_path: Path) -> tuple[Path, list[int]]:
    work_dir.mkdir(parents=True, exist_ok=True)
    prs = Presentation(str(template))
    keep_cover_and_closing(prs)
    _cover(prs, inp)
    _exec_summary(prs, inp)
    _overview(prs, inp, work_dir)
    for rq in inp.rqs:
        _rq_slides(prs, inp, rq, work_dir)
    _takeaways(prs, inp)
    _methodology(prs, inp)
    appendix = _citations(prs, inp)
    _move_to_end(prs, 1)                  # the template closing slide goes last...
    _closing(prs, inp)
    appendix = [n - 1 for n in appendix]  # ...so every appendix slide moves up by one
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    # Not generated prose, so the fact check skips them: citation appendix, template cover and closing slide
    return out_path, sorted(set(appendix) | {1, len(prs.slides)})
