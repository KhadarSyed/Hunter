"""Editable PowerPoint text: every text element of a rendered slide (titles, kickers, card text, bullets, KPI numbers,
footers) read from the browser -- its box, font, size, colour, weight and alignment -- then hidden for the background
picture and re-added as a native text box at the same place; tables become native PowerPoint tables over their
(text-free) picture. Charts are not read here: they are their own vector pictures (see exporter)."""
from __future__ import annotations

import re

from lxml import etree
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

PT_PER_PX = 0.5                 # a 1920 px slide is 13.333 in = 960 pt wide
WIDTH_SLACK = 0.03              # PowerPoint's text metrics differ slightly: a little room so a line never wraps early
NO_STYLE_TABLE = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"      # PowerPoint's "No Style, No Grid"
HLINK_COLOR_EXT = "{A12FA001-AC4F-418D-AE19-62706E023703}"     # a hyperlink keeps its run's colour (Office 2019+)
_AHYP = "http://schemas.microsoft.com/office/drawing/2018/hyperlinkcolor"
_RGBA = re.compile(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)")
_ALIGN = {"center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT, "end": PP_ALIGN.RIGHT, "justify": PP_ALIGN.JUSTIFY}

# Runs in the browser on one slide: the text blocks (an element whose own text and inline children make one box) and
# the tables. Each block's text box is its text's own extent; a clamped block keeps only its visible lines.
READ_JS = r"""s => {
  s.scrollIntoView();                          // caretRangeFromPoint (clamped text) reads the viewport only
  const o = s.getBoundingClientRect();
  const SKIP = 'svg, .amchart, .amchart-svg, .chart-why, script, style, noscript, template';
  const builds = [...s.querySelectorAll('.build')].slice(0, %(max_builds)d);
  const inline = el => getComputedStyle(el).display === 'inline';
  function alpha(el) { let a = 1; for (let e = el; e && e !== s.parentNode; e = e.parentElement) a *= +getComputedStyle(e).opacity; return a; }
  function style(el) {
    const c = getComputedStyle(el), a = el.closest('a[href]');
    return {font: c.fontFamily.split(',')[0].replace(/["']/g, '').trim(), size: parseFloat(c.fontSize), weight: +c.fontWeight || 400,
            italic: c.fontStyle === 'italic', color: c.color, transform: c.textTransform, spacing: parseFloat(c.letterSpacing) || 0,
            underline: c.textDecorationLine.includes('underline'), href: a && /^https?:/i.test(a.href) ? a.href : ''};
  }
  function runs(el, deep, out, nodes) {          // deep: block children too (a table cell), a line break between them
    for (const n of el.childNodes) {
      if (n.nodeType === 3) { if (n.textContent.replace(/\s+/g, '')) { out.push({text: n.textContent.replace(/\s+/g, ' '), ...style(el)}); nodes.push(n); }
                              else if (n.textContent && out.length) out.push({text: ' ', ...style(el)}); }
      else if (n.nodeType === 1 && !n.matches(SKIP)) {
        if (n.tagName === 'BR') out.push({text: '\n', ...style(el)});
        else if (inline(n)) runs(n, deep, out, nodes);
        else if (deep) { if (out.length) out.push({text: '\n', ...style(el)}); runs(n, deep, out, nodes); }
      }
    }
    return out;
  }
  function visible(el) {
    const c = getComputedStyle(el);
    return c.visibility !== 'hidden' && c.display !== 'none' && alpha(el) > 0.02 && el.getClientRects().length;
  }
  function clip(el, rs, nodes) {                // a -webkit-line-clamp block: its text up to the last visible character
    const cs = getComputedStyle(el);
    if ((!cs.webkitLineClamp || cs.webkitLineClamp === 'none') && cs.overflowY !== 'hidden') return rs;
    if (el.scrollHeight <= el.clientHeight + 4) return rs;
    const r = el.getBoundingClientRect(), lh = parseFloat(cs.lineHeight) || 20;
    const pos = document.caretRangeFromPoint(r.right - 4, r.top + el.clientHeight - lh / 2);
    if (!pos || !nodes.includes(pos.startContainer)) return rs;
    const last = nodes[nodes.length - 1];
    if (pos.startContainer === last && pos.startOffset >= last.textContent.trimEnd().length - 1) return rs;   // all shown
    const cut = nodes.indexOf(pos.startContainer), out = [];
    let k = -1;
    for (const run of rs) {
      if (run.text.trim() && run.text !== '\n') k++;
      if (k < cut) { out.push(run); continue; }
      const t = pos.startContainer.textContent.slice(0, pos.startOffset).replace(/\s+/g, ' ');
      out.push({...run, text: t.trimEnd() + '…'});
      break;
    }
    return out;
  }
  function box(r) { return {x: r.left - o.left, y: r.top - o.top, w: r.width, h: r.height}; }
  const blocks = [], titleSel = '.title, .question, .vtitle';
  let titled = false;
  for (const el of s.querySelectorAll('*')) {
    if (el.matches(SKIP) || el.closest(SKIP) || el.closest('table') || inline(el) || !visible(el)) continue;
    const nodes = [], rs = runs(el, false, [], nodes);
    if (!rs.some(r => r.text.trim())) continue;
    const range = document.createRange();
    range.setStartBefore(nodes[0]); range.setEndAfter(nodes[nodes.length - 1]);
    const t = range.getBoundingClientRect(), e = el.getBoundingClientRect(), c = getComputedStyle(el);
    if (t.width < 1 || t.bottom < o.top || t.top > o.bottom) continue;
    const padL = parseFloat(c.paddingLeft) + parseFloat(c.borderLeftWidth), padR = parseFloat(c.paddingRight) + parseFloat(c.borderRightWidth);
    const left = e.left + padL, right = e.right - padR, align = c.textAlign;
    // left-aligned text starts where its first character does (after an icon) and may grow to the content's right
    // edge, so PowerPoint wraps where Chrome did; centred and right-aligned text keep the content box
    const lead = ['left', 'start', 'justify'].includes(align) ? t.left : left;
    const b = {x: lead, y: t.top, w: right - lead, h: Math.min(t.height, e.bottom - t.top)};
    const isTitle = !titled && el.matches(titleSel);
    titled = titled || isTitle;
    el.dataset.pptxText = '1';
    el.style.setProperty('--pptx-m', c.color);
    el.querySelectorAll('*').forEach(k => { if (inline(k)) k.dataset.pptxText = '1'; });
    blocks.push({...box(new DOMRect(b.x, b.y, b.w, b.h)), runs: clip(el, rs, nodes), align, title: isTitle,
                 line: parseFloat(c.lineHeight) || 1.2 * parseFloat(c.fontSize), alpha: alpha(el),
                 lines: Math.round(t.height / (parseFloat(c.lineHeight) || 1.2 * parseFloat(c.fontSize))),
                 build: builds.findIndex(k => k.contains(el))});
  }
  const tables = [];
  for (const tb of s.querySelectorAll('table')) {
    if (tb.closest(SKIP) || !visible(tb)) continue;
    const rows = [...tb.rows].filter(tr => visible(tr)).map(tr => ({h: tr.getBoundingClientRect().height, cells: [...tr.cells].map(td => {
      const nodes = [], rs = runs(td, true, [], nodes), r = td.getBoundingClientRect(), c = getComputedStyle(td);
      let tl = r.left + parseFloat(c.paddingLeft), tt = r.top + parseFloat(c.paddingTop);
      if (nodes.length) { const g = document.createRange(); g.setStartBefore(nodes[0]); g.setEndAfter(nodes[nodes.length - 1]);
                          const q = g.getBoundingClientRect(); tl = q.left; tt = q.top; }
      const inner = td.querySelector('.cell') || td;
      return {w: r.width, runs: clip(inner, rs, nodes), align: c.textAlign, valign: c.verticalAlign,
              line: parseFloat(c.lineHeight) || 1.2 * parseFloat(c.fontSize),
              ml: tl - r.left, mt: tt - r.top, mr: parseFloat(c.paddingRight), mb: parseFloat(c.paddingBottom)};
    })})).filter(r => r.cells.length);
    if (!rows.length) continue;
    tb.querySelectorAll('*').forEach(k => k.dataset.pptxText = '1');
    tables.push({...box(tb.getBoundingClientRect()), rows});
  }
  return {blocks, tables};
}"""

# applied while the background and build pictures are taken: the text read above turns transparent (its layout, the
# backgrounds, borders and list markers stay), then shows again
HIDE_JS = """(s, hide) => {
  let st = document.getElementById('pptx-hide');
  if (hide && !st) { st = document.createElement('style'); st.id = 'pptx-hide';
    st.textContent = '[data-pptx-text]{color:transparent!important;text-shadow:none!important;' +
      'text-decoration-color:transparent!important}[data-pptx-text]::marker{color:var(--pptx-m)!important}';
    document.head.appendChild(st); }
  if (!hide && st) st.remove();
}"""


def _rgba(css: str) -> tuple[RGBColor, float] | None:
    m = _RGBA.match(css or "")
    if not m:
        return None
    r, g, b = (int(float(m.group(i))) for i in (1, 2, 3))
    return RGBColor(r, g, b), float(m.group(4)) if m.group(4) is not None else 1.0


def _color(run, css: str, alpha: float) -> None:
    found = _rgba(css)
    if not found:
        return
    rgb, a = found
    run.font.color.rgb = rgb
    if a * alpha < 0.995:
        clr = run.font._rPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
        etree.SubElement(clr, qn("a:alpha")).set("val", str(int(round(a * alpha * 100_000))))


def _text(run: dict) -> str:
    t = run["text"]
    return t.upper() if run.get("transform") == "uppercase" else t.lower() if run.get("transform") == "lowercase" else t


def fill(tf, runs: list[dict], align: str, line_px: float, alpha: float = 1.0) -> None:
    """A text frame's paragraphs (one per line break) and runs, styled as the browser drew them."""
    paras: list[list[dict]] = [[]]
    for r in runs:
        parts = r["text"].split("\n")
        for i, part in enumerate(parts):
            if i:
                paras.append([])
            if part:
                paras[-1].append({**r, "text": part})
    paras = [p for p in paras if any(r["text"].strip() for r in p)] or [[]]
    for k, pr in enumerate(paras):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = _ALIGN.get(align, PP_ALIGN.LEFT)      # set always: a title placeholder centres by default
        p.line_spacing = Pt(line_px * PT_PER_PX)
        for i, r in enumerate(pr):
            text = _text(r)
            if i == 0:
                text = text.lstrip()
            if i == len(pr) - 1:
                text = text.rstrip()
            if not text:
                continue
            run = p.add_run()
            run.text = text
            f = run.font
            f.name, f.size = r["font"], Pt(round(r["size"] * PT_PER_PX * 2) / 2)
            f.bold, f.italic = r["weight"] >= 600, r["italic"]
            f.underline = bool(r.get("underline"))
            if r.get("spacing"):
                f._rPr.set("spc", str(int(round(r["spacing"] * PT_PER_PX * 100))))
            _color(run, r["color"], alpha)
            if r.get("href"):
                run.hyperlink.address = r["href"]
                click = f._rPr.find(qn("a:hlinkClick"))
                ext = etree.SubElement(etree.SubElement(click, qn("a:extLst")), qn("a:ext"), uri=HLINK_COLOR_EXT)
                etree.SubElement(ext, f"{{{_AHYP}}}hlinkClr", nsmap={"ahyp": _AHYP}).set("val", "tx")


def _frame(tf, wrap: bool = True) -> None:
    tf.word_wrap = wrap
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Emu(0)
    tf.vertical_anchor = MSO_ANCHOR.TOP


def add_block(shapes, block: dict, emu, shape=None):
    """One text block as a text box (or into `shape`, the slide's title placeholder) at its place on the slide."""
    slack = block["w"] * WIDTH_SLACK
    x = block["x"] - (slack if block["align"] in ("right", "end") else slack / 2 if block["align"] == "center" else 0)
    box = (emu(x, "x"), emu(block["y"], "y"), emu(block["w"] + slack, "x"), emu(block["h"], "y"))
    if shape is None:
        shape = shapes.add_textbox(*box)
    else:
        shape.left, shape.top, shape.width, shape.height = box
        shape.text_frame.clear()
    # one line in the browser stays one line (a substituted font may be wider): only a paragraph wraps
    _frame(shape.text_frame, block.get("lines", 2) > 1)
    fill(shape.text_frame, block["runs"], block["align"], block["line"], block.get("alpha", 1.0))
    shape.name = "Title" if block.get("title") else "Text"
    return shape


def add_table(shapes, table: dict, emu):
    """A native table at the table's place, its text in the browser's styles over the table's picture (no fills,
    no grid: the picture keeps the heat colours, logos and rules)."""
    rows = table["rows"]
    n_cols = max(len(r["cells"]) for r in rows)
    widths = next(r for r in rows if len(r["cells"]) == n_cols)["cells"]
    frame = shapes.add_table(len(rows), n_cols, emu(table["x"], "x"), emu(table["y"], "y"), emu(table["w"], "x"),
                             emu(table["h"], "y"))
    tbl = frame.table
    tbl.first_row = tbl.horz_banding = False
    tbl._tbl.tblPr.find(qn("a:tableStyleId")).text = NO_STYLE_TABLE
    for j, cell in enumerate(widths):
        tbl.columns[j].width = emu(cell["w"], "x")
    for i, row in enumerate(rows):
        tbl.rows[i].height = emu(row["h"], "y")
        for j, cell in enumerate(row["cells"][:n_cols]):
            c = tbl.cell(i, j)
            c.fill.background()
            c.margin_left, c.margin_top = emu(cell["ml"], "x"), emu(cell["mt"], "y")
            c.margin_right, c.margin_bottom = emu(cell["mr"], "x"), Emu(0)
            c.vertical_anchor = MSO_ANCHOR.TOP
            c.text_frame.word_wrap = True
            fill(c.text_frame, cell["runs"], cell["align"], cell["line"])
    frame.name = "Table"
    return frame
