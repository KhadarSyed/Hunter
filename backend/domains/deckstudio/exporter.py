"""Exports of the HTML deck: each slide at 1920x1080 into a 16:9 PPTX and a PDF.

In the PPTX the slide's text is real, editable PowerPoint text (pptx_text): titles, kickers, card text, bullets, KPI
numbers and footers as text boxes where the deck draws them, in its fonts, sizes and colours, tables as native tables
and source links as text hyperlinks. Behind them is the slide picture taken without its text, and each amCharts chart
as a vector SVG picture (amCharts' own SVG export, PNG fallback). A slide is presented the way a presenter would build
it: each card (insight, verbatim) -- its picture and its text, grouped -- fades in on click; slides cross-fade. The
slide text also goes in the notes. The PDF is the deck printed
by Chromium with the same SVG charts, so text and charts stay vector (slide pictures only if printing fails).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches

from . import pptx_text
from .spec import DeckSpec

logger = logging.getLogger(__name__)

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
PX_W, PX_H = 1920, 1080
SETTLE_MS = 900
MAX_BUILDS = 9
FADE_MS = 500
BUILD_SELECTOR = ".build"
CHART_SELECTOR = ".amchart[data-ready]"          # a chart amCharts has drawn (see vendor/deckcharts.js)
EXPORTED_SELECTOR = ".amchart[data-exported]"
CHARTS_TIMEOUT_MS = 30_000
_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


@dataclass
class Shot:
    full: Path
    base: Path | None = None                          # the slide with its builds hidden
    # (png, (x, y, w, h) px, its index among the slide's builds): its text boxes carry the same index
    builds: list[tuple[Path, tuple[float, float, float, float], int]] = field(default_factory=list)
    links: list[tuple[str, tuple[float, float, float, float]]] = field(default_factory=list)     # (url, x, y, w, h px)
    # the amCharts charts as vector SVG (+ PNG fallback), left out of `base`: (svg, png, x, y, w, h px)
    charts: list[tuple[Path, Path, tuple[float, float, float, float]]] = field(default_factory=list)
    text: dict = field(default_factory=dict)          # {"blocks": [...], "tables": [...]} (pptx_text.READ_JS)


MIN_LINK_PX = 4
# links around pictures only (a verbatim's post): a link with text becomes a text hyperlink (pptx_text)
_LINKS_JS = """s => { const o = s.getBoundingClientRect();
  return [...s.querySelectorAll('a[href]')].filter(a => !a.innerText.trim()).map(a => { const r = a.getBoundingClientRect();
    return {href: a.href, x: r.x - o.x, y: r.y - o.y, w: r.width, h: r.height}; }); }"""


def _links(el) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Every article link on the slide (verbatim posts, source chips) and where it sits, clipped to the slide."""
    out = []
    for link in el.evaluate(_LINKS_JS) or []:
        href = str(link.get("href") or "")
        x, y = max(0.0, link["x"]), max(0.0, link["y"])
        w, h = min(link["w"], PX_W - x), min(link["h"], PX_H - y)
        if href.lower().startswith(("https://", "http://")) and w >= MIN_LINK_PX and h >= MIN_LINK_PX:
            out.append((href, (x, y, w, h)))
    return out


def _charts(el, origin: dict, slide_dir: Path, k: int) -> list[tuple[Path, Path, tuple[float, float, float, float]]]:
    """Each fully drawn amCharts chart on the slide exported as SVG, with its PNG for viewers without SVG."""
    out = []
    for j, chart in enumerate(el.query_selector_all(CHART_SELECTOR), start=1):
        box = chart.bounding_box()
        if not box or box["width"] < 4 or box["height"] < 4:
            continue
        svg, png = slide_dir / "charts" / f"slide_{k:02d}_chart_{j}.svg", slide_dir / "charts" / f"slide_{k:02d}_chart_{j}.png"
        svg.parent.mkdir(parents=True, exist_ok=True)
        try:
            svg.write_text(chart.evaluate("c => deckCharts.svg(Number(c.dataset.chartIndex))"), encoding="utf-8")
        except Exception as e:       # no SVG export: the chart stays in the slide picture
            logger.warning("chart %s on slide %s not exported as SVG: %s", j, k, e)
            continue
        chart.screenshot(path=str(png))
        chart.evaluate("c => c.dataset.exported = '1'")
        out.append((svg, png, (box["x"] - origin["x"], box["y"] - origin["y"], box["width"], box["height"])))
    return out


def _hidden(el, selector: str, hide: bool) -> None:
    el.evaluate(f"(s, h) => s.querySelectorAll('{selector}').forEach(b => b.style.visibility = h ? 'hidden' : '')", hide)


def _capture(el, slide_dir: Path, k: int) -> Shot:
    shot = Shot(full=slide_dir / f"slide_{k:02d}.png")
    el.screenshot(path=str(shot.full))
    shot.links = _links(el)
    origin = el.bounding_box()
    builds = el.query_selector_all(BUILD_SELECTOR)[:MAX_BUILDS]
    if not origin:
        return shot
    shot.charts = _charts(el, origin, slide_dir, k)
    try:                    # the slide's text, then hidden for the pictures (it comes back as PowerPoint text)
        shot.text = el.evaluate(pptx_text.READ_JS % {"max_builds": MAX_BUILDS}) or {}
    except Exception as e:  # the text stays in the pictures, as before
        logger.warning("slide %s text not read for editable PowerPoint text: %s", k, e)
    el.evaluate(pptx_text.HIDE_JS, bool(shot.text))
    for i, b in enumerate(builds, start=1):
        box = b.bounding_box()
        if not box or box["width"] < 4 or box["height"] < 4:
            continue
        path = slide_dir / "builds" / f"slide_{k:02d}_build_{i}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        b.screenshot(path=str(path))
        shot.builds.append((path, (box["x"] - origin["x"], box["y"] - origin["y"], box["width"], box["height"]), i - 1))
    if shot.builds or shot.charts or shot.text:
        hide = f"{BUILD_SELECTOR},{EXPORTED_SELECTOR}"
        _hidden(el, hide, True)
        shot.base = slide_dir / "builds" / f"slide_{k:02d}_base.png"
        shot.base.parent.mkdir(parents=True, exist_ok=True)
        el.screenshot(path=str(shot.base))
        _hidden(el, hide, False)
    el.evaluate(pptx_text.HIDE_JS, False)
    return shot


def _print_pdf(page, pdf: Path) -> bool:
    """The deck printed by Chromium, every amCharts chart swapped for its SVG export: text and charts stay vector."""
    try:
        page.evaluate("() => window.deckCharts && window.deckCharts.freeze()")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        page.emulate_media(media="screen")
        page.pdf(path=str(pdf), width=f"{PX_W}px", height=f"{PX_H}px", print_background=True, prefer_css_page_size=True,
                 margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        return True
    except Exception as e:      # the slide pictures make the PDF instead
        logger.warning("vector PDF failed, using slide pictures: %s", e)
        return False


def screenshot_slides(html_path: Path, out_dir: Path, pdf: Path | None = None) -> list[Shot]:
    """Every slide's pictures; with `pdf`, also the vector PDF (written only when it succeeds)."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": PX_W, "height": PX_H})
        page.goto(Path(html_path).resolve().as_uri() + "?export=1", wait_until="networkidle")
        try:      # every chart fully drawn (export mode draws without animation)
            page.wait_for_function("() => !window.deckCharts || window.deckCharts.ready", timeout=CHARTS_TIMEOUT_MS)
        except PlaywrightTimeout:
            logger.warning("amCharts charts not ready after %s ms; the SVG charts stand in", CHARTS_TIMEOUT_MS)
        page.wait_for_timeout(SETTLE_MS)          # web fonts and photos settle
        for k, el in enumerate(page.query_selector_all("section.slide"), start=1):
            shots.append(_capture(el, out_dir, k))
        if pdf is not None and not _print_pdf(page, pdf) and pdf.exists():
            pdf.unlink()
        browser.close()
    return shots


def _emu(px: float, total_px: int, total_emu: int) -> Emu:
    return Emu(int(round(px / total_px * total_emu)))


def _px(px: float, axis: str) -> Emu:
    """A slide pixel distance along x or y in EMU."""
    return _emu(px, PX_W, SLIDE_W) if axis == "x" else _emu(px, PX_H, SLIDE_H)


def _p(tag: str, **attrs) -> etree._Element:
    el = etree.Element(f"{{{_NS}}}{tag}")
    for k, v in attrs.items():
        el.set(k, str(v))
    return el


def _sub(parent, tag: str, **attrs) -> etree._Element:
    el = _p(tag, **attrs)
    parent.append(el)
    return el


def _click_fades(clicks: list[list[int]]) -> etree._Element:
    """<p:timing>: one click per list of shapes (a card's picture and its text boxes), all fading in together
    (PowerPoint's preset 10; the first on the click, the rest with it)."""
    ids = iter(range(1, 10_000))
    timing = _p("timing")
    root = _sub(_sub(_sub(timing, "tnLst"), "par"), "cTn", id=next(ids), dur="indefinite", restart="never",
                nodeType="tmRoot")
    seq = _sub(_sub(root, "childTnLst"), "seq", concurrent="1", nextAc="seek")
    main = _sub(seq, "cTn", id=next(ids), dur="indefinite", nodeType="mainSeq")
    clicks_lst = _sub(main, "childTnLst")
    for shape_ids in clicks:
        click = _sub(_sub(clicks_lst, "par"), "cTn", id=next(ids), fill="hold")
        _sub(_sub(click, "stCondLst"), "cond", delay="indefinite")
        step = _sub(_sub(_sub(click, "childTnLst"), "par"), "cTn", id=next(ids), fill="hold")
        _sub(_sub(step, "stCondLst"), "cond", delay="0")
        effects = _sub(step, "childTnLst")
        for n, spid in enumerate(shape_ids):
            _fade(effects, spid, ids, "clickEffect" if n == 0 else "withEffect")
    prev = _sub(_sub(seq, "prevCondLst"), "cond", evt="onPrev", delay="0")
    _sub(_sub(prev, "tgtEl"), "sldTgt")
    nxt = _sub(_sub(seq, "nextCondLst"), "cond", evt="onNext", delay="0")
    _sub(_sub(nxt, "tgtEl"), "sldTgt")
    return timing


def _fade(parent, spid: int, ids, node_type: str) -> None:
    effect = _sub(_sub(parent, "par"), "cTn", id=next(ids), presetID="10", presetClass="entr",
                  presetSubtype="0", fill="hold", grpId="0", nodeType=node_type)
    _sub(_sub(effect, "stCondLst"), "cond", delay="0")
    behaviours = _sub(effect, "childTnLst")
    show = _sub(behaviours, "set")
    bhvr = _sub(show, "cBhvr")
    flip = _sub(bhvr, "cTn", id=next(ids), dur="1", fill="hold")
    _sub(_sub(flip, "stCondLst"), "cond", delay="0")
    _sub(_sub(bhvr, "tgtEl"), "spTgt", spid=spid)
    _sub(_sub(bhvr, "attrNameLst"), "attrName").text = "style.visibility"
    _sub(_sub(show, "to"), "strVal", val="visible")
    fade = _sub(behaviours, "animEffect", transition="in", filter="fade")
    fbhvr = _sub(fade, "cBhvr")
    _sub(fbhvr, "cTn", id=next(ids), dur=FADE_MS)
    _sub(_sub(fbhvr, "tgtEl"), "spTgt", spid=spid)


def _animate(slide, shape_ids: list[list[int]]) -> None:
    """A fade transition into the slide, then each card (its picture and text) fading in one click at a time."""
    sld = slide._element
    for old in sld.findall(f"{{{_NS}}}transition") + sld.findall(f"{{{_NS}}}timing"):
        sld.remove(old)
    transition = _p("transition", spd="med")
    _sub(transition, "fade")
    ext = sld.find(f"{{{_NS}}}extLst")
    at = list(sld).index(ext) if ext is not None else len(sld)
    sld.insert(at, transition)
    if shape_ids:
        sld.insert(at + 1, _click_fades(shape_ids))


def _hotspot(slide, href: str, box: tuple[float, float, float, float]) -> None:
    """An invisible, clickable rectangle over a link in the slide picture. A no-fill shape lets clicks fall through
    in a slide show, so it gets a fully transparent fill instead; its theme style (outline, shadow) is dropped."""
    x, y, w, h = box
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, _emu(x, PX_W, SLIDE_W), _emu(y, PX_H, SLIDE_H),
                                   _emu(w, PX_W, SLIDE_W), _emu(h, PX_H, SLIDE_H))
    style = shape._element.find(qn("p:style"))
    if style is not None:
        shape._element.remove(style)
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    etree.SubElement(shape._element.spPr.find(qn("a:solidFill")).find(qn("a:srgbClr")), qn("a:alpha")).set("val", "0")
    shape.line.fill.background()
    shape.name = "Source link"
    shape._element.nvSpPr.cNvPr.set("descr", f"Open the original source: {href}")
    shape.click_action.hyperlink.address = href


SVG_EXT_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"       # PowerPoint's SVG-image extension (Office 2016+)
_ASVG = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"


def add_svg_picture(slide, svg: Path, png: Path, x, y, w, h):
    """A picture that PowerPoint draws from its SVG (vector, sharp at any zoom); an older viewer shows the PNG.
    python-pptx has no SVG support: the PNG picture's blip gets the asvg:svgBlip extension pointing at an SVG part."""
    pic = slide.shapes.add_picture(str(png), x, y, w, h)
    package = slide.part.package
    part = Part(package.next_partname("/ppt/media/image%d.svg"), "image/svg+xml", package, svg.read_bytes())
    rid = slide.part.relate_to(part, RT.IMAGE)
    blip = pic._element.blipFill.find(qn("a:blip"))
    ext = etree.SubElement(etree.SubElement(blip, qn("a:extLst")), qn("a:ext"), uri=SVG_EXT_URI)
    etree.SubElement(ext, f"{{{_ASVG}}}svgBlip", nsmap={"asvg": _ASVG}).set(qn("r:embed"), rid)
    pic.name = "Chart"
    return pic


def build_pptx(pngs: list[Path], spec: DeckSpec, out: Path, builds: list[Shot] | None = None) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    layout = prs.slide_layouts[5]          # "Title Only": the title stays searchable under the picture
    for k, (png, s) in enumerate(zip(pngs, spec.slides)):
        shot = builds[k] if builds and k < len(builds) else None
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = s.question or s.title or spec.title
        slide.shapes.add_picture(str(shot.base if shot and shot.base else png), Emu(0), Emu(0), SLIDE_W, SLIDE_H)
        for svg, chart_png, (x, y, w, h) in (shot.charts if shot and shot.base else []):
            add_svg_picture(slide, svg, chart_png, _emu(x, PX_W, SLIDE_W), _emu(y, PX_H, SLIDE_H),
                            _emu(w, PX_W, SLIDE_W), _emu(h, PX_H, SLIDE_H))
        text = (shot.text if shot and shot.base else None) or {}
        blocks = text.get("blocks") or []
        for t in text.get("tables") or []:
            pptx_text.add_table(slide.shapes, t, _px)
        for b in blocks:
            if b["build"] < 0 and not b["title"]:
                pptx_text.add_block(slide.shapes, b, _px)
        ids = []
        for path, (x, y, w, h), i in (shot.builds if shot and shot.base else []):
            # the card and its text appear together on its click; not grouped, so a click on the card's text edits it
            # (a group selects as a whole, its picture first: the text read as part of a picture)
            card = slide.shapes.add_picture(str(path), _emu(x, PX_W, SLIDE_W), _emu(y, PX_H, SLIDE_H),
                                            _emu(w, PX_W, SLIDE_W), _emu(h, PX_H, SLIDE_H))
            card.name = "Card"
            ids.append([card.shape_id] + [pptx_text.add_block(slide.shapes, b, _px).shape_id
                                          for b in blocks if b["build"] == i])
        title = next((b for b in blocks if b["title"] and b["build"] < 0), None)
        if title:              # the slide's own title placeholder carries the visible title, on top
            ph = slide.shapes.title
            pptx_text.add_block(slide.shapes, title, _px, shape=ph)
            ph._element.getparent().append(ph._element)
        for href, box in (shot.links if shot else []):
            _hotspot(slide, href, box)
        _animate(slide, ids)
        # card text marks its key phrases **bold** for the slide; speaker notes are plain text
        lines = [s.kicker, s.question or s.title, s.so_what] + [
            f"{c.get('headline', '')}: {c.get('text', '').replace('**', '')}" for c in s.cards] + [
            f"Why this chart: {c['choice']}" + (f" (also considered: {c['alternatives']})" if c.get("alternatives") else "")
            for c in s.charts if c.get("choice")]
        if s.type in ("verbatim_wall", "citations") and s.notes:
            lines.append(s.notes)
        slide.notes_slide.notes_text_frame.text = "\n".join(x for x in lines if x)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return out


def build_pdf(pngs: list[Path], out: Path) -> Path:
    images = [Image.open(p).convert("RGB") for p in pngs]
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out, "PDF", save_all=True, append_images=images[1:], resolution=144)
    return out


def export_all(html_path: Path, spec: DeckSpec, out_dir: Path, stem: str) -> dict:
    safe = "".join(ch for ch in stem if ch.isalnum() or ch in " -_").strip() or "Deck"
    pdf = out_dir / f"{safe} - Deck.pdf"
    shots = screenshot_slides(html_path, out_dir / "slides", pdf=pdf)
    if len(shots) != len(spec.slides):      # never pair titles and notes with the wrong pictures
        raise RuntimeError(f"rendered {len(shots)} slides for a {len(spec.slides)}-slide deck")
    pngs = [s.full for s in shots]
    return {"pngs": pngs, "pptx": build_pptx(pngs, spec, out_dir / f"{safe} - Deck.pptx", shots),
            "pdf": pdf if pdf.exists() else build_pdf(pngs, pdf)}
