"""Guards: a slide ships only if its numbers are in its facts, it fits 1920x1080, and it copies no
reference-deck text."""
from __future__ import annotations

import re
from pathlib import Path

from ...core.llm_synthesis import _figures
from ..deliverable.factcheck import _with_rounding
from .indexer import SHINGLE
from .renderer import slide_text

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_SLIDE_COUNT = re.compile(r"\b\d+\s*/\s*\d+\b")
_WORD = re.compile(r"[a-z0-9']+")
_BOOLEAN = {"or", "and", "not", "near"}
_SECTION = re.compile(r'(<section class="slide[^"]*" data-id="([^"]+)".*?</section>)', re.S)
_LAYOUT_JS = """() => {
  const out = [];
  const rgb = s => (s.match(/[\\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => [r, g, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
                                   .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = h => { h = h.trim().replace('#', ''); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };
  document.querySelectorAll('.slide').forEach(slide => {
    const id = slide.dataset.id, box = slide.getBoundingClientRect();
    const treatment = slide.dataset.treatment || 'plain';
    const primary = hex(getComputedStyle(slide).getPropertyValue('--primary') || '#3D1A6B');
    const bgRaw = rgb(getComputedStyle(slide).backgroundColor);
    const slideBg = bgRaw.length > 3 && bgRaw[3] === 0 ? [255, 255, 255] : bgRaw;
    const behind = el => {
      for (let a = el; a && a !== slide.parentElement; a = a.parentElement) {
        const c = rgb(getComputedStyle(a).backgroundColor);
        if (c.length >= 3 && (c.length < 4 || c[3] >= 0.5) && a !== slide) return c.slice(0, 3);
      }
      const r = el.getBoundingClientRect(), photoSide = treatment === 'C' ? (r.left + r.width / 2 - box.left) < 672 : true;
      return (treatment === 'full' || treatment === 'A' || (treatment === 'C' && photoSide)) ? primary : slideBg.slice(0, 3);
    };
    const labels = [...slide.querySelectorAll('svg text.xlab')].map(t => t.getBoundingClientRect());
    for (let i = 1; i < labels.length; i++)
      if (labels[i].left < labels[i - 1].right - 1 && labels[i].width && labels[i - 1].width)
        out.push({slide_id: id, kind: 'overlap', detail: 'axis labels ' + i});
    slide.querySelectorAll('*').forEach(el => {
      if (el.closest('svg')) return;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
      if (!own) return;
      if (r.right > box.right + 1 || r.bottom > box.bottom + 1 || r.left < box.left - 1 || r.top < box.top - 1)
        out.push({slide_id: id, kind: 'off_slide', detail: el.textContent.trim().slice(0, 60)});
      const cs = getComputedStyle(el), clamped = cs.webkitLineClamp && cs.webkitLineClamp !== 'none';
      const fg = rgb(cs.color), alpha = fg.length > 3 ? fg[3] : 1, op = parseFloat(cs.opacity || '1');
      if (alpha * op > 0.4 && ratio(fg.slice(0, 3), behind(el)) < 3)
        out.push({slide_id: id, kind: 'low_contrast', detail: el.textContent.trim().slice(0, 60)});
      if (!clamped && cs.overflow !== 'visible' && (el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2))
        out.push({slide_id: id, kind: 'overflow', detail: el.textContent.trim().slice(0, 60)});
    });
  });
  return out;
}"""


def number_issues(text: str, facts_allowed: list[str]) -> list[str]:
    facts_text = " ".join(facts_allowed)
    allowed = _with_rounding(_figures(facts_text))
    known_years = {m.group(0) for m in _YEAR.finditer(facts_text)}
    cleaned = _YEAR.sub(lambda m: " " if m.group(0) in known_years else m.group(0), _SLIDE_COUNT.sub(" ", text))
    return sorted(_figures(cleaned) - allowed)


def _is_wording(shingle: tuple[str, ...]) -> bool:
    """Template wording, not shared data: number runs (slide counters) and Boolean query fragments (the
    project's own search query can match a reference deck that used similar terms) do not count."""
    digits = sum(w.isdigit() for w in shingle)
    operators = sum(w in _BOOLEAN for w in shingle)
    return digits <= len(shingle) // 2 and operators < 2


def copied_text(text: str, shingles: set) -> list[str]:
    words = _WORD.findall(text.lower())
    return sorted({" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)
                   if tuple(words[i:i + SHINGLE]) in shingles and _is_wording(tuple(words[i:i + SHINGLE]))})


def layout_issues(html_path: Path) -> list[dict]:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(Path(html_path).resolve().as_uri() + "?export=1")
        page.wait_for_timeout(400)
        issues = page.evaluate(_LAYOUT_JS)
        browser.close()
    return issues


def slide_html_map(html: str) -> dict[str, str]:
    return {m.group(2): m.group(1) for m in _SECTION.finditer(html)}


def slide_visible_text(section_html: str) -> str:
    return slide_text(section_html)
