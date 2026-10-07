"""Per-slide LLM creative pass. The model may restyle a slide's HTML within the deck's tokens; the result
ships only if every guard passes, otherwise the template version does."""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

from . import guards, repair
from .renderer import render_deck
from .spec import DeckSpec, DeckTokens, SlideSpec

logger = logging.getLogger(__name__)
_SECTION = re.compile(r"<section\b.*?</section>", re.S | re.I)
_SVG = re.compile(r"<svg\b.*?</svg>", re.S | re.I)
# Creative HTML is untrusted: only these tags and attributes may appear, links only to the deck's own assets/
ALLOWED_TAGS = {"section", "div", "span", "p", "h1", "h2", "h3", "h4", "strong", "em", "b", "i", "br", "ul", "ol", "li",
                "img", "table", "thead", "tbody", "tr", "th", "td", "svg", "g", "rect", "path", "text", "tspan", "line",
                "polyline", "circle", "image"}
ALLOWED_ATTRS = {"class", "style", "data-id", "data-type", "data-treatment", "src", "href", "alt", "x", "y", "x1", "y1",
                 "x2", "y2", "cx", "cy", "r", "rx", "width", "height", "viewbox", "d", "points", "fill", "stroke",
                 "stroke-width", "stroke-opacity", "stroke-linejoin", "opacity", "text-anchor", "transform",
                 "preserveaspectratio", "xmlns", "font-size", "colspan", "rowspan"}
_BAD_STYLE = re.compile(r"url\s*\(|expression|@import|javascript|behavior|content\s*:|\\", re.I)
_PROMPT = ("You are a presentation designer. Improve this one slide's HTML (a 1920x1080 <section>) so it looks "
           "premium and on-brand. Keep the same data-id, every number and every word of the question exactly as "
           "given; never add numbers. Use only the CSS variables --primary, --accent, --text, --muted, --surface, "
           "--on-dark, --overlay, --title, --body and the existing assets/ images. Text over a photo or overlay must use "
           "var(--on-dark); every text must contrast clearly with what is behind it. No scripts, no external URLs, "
           "nothing outside the slide. Return only the <section>...</section>.")


class _Allowlist(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ok, self.sections = True, 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in ALLOWED_TAGS:
            self.ok = False
        if tag == "section":
            self.sections += 1
        for name, value in attrs:
            name, value = name.lower(), (value or "")
            if name not in ALLOWED_ATTRS:
                self.ok = False
            elif name in ("src", "href") and not value.startswith("assets/"):
                self.ok = False
            elif name == "style" and _BAD_STYLE.search(value):
                self.ok = False

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_comment(self, data):
        self.ok = False

    def handle_decl(self, decl):
        self.ok = False

    def unknown_decl(self, data):
        self.ok = False


def _safe(html: str) -> bool:
    """Exactly one slide section built only from allowed tags/attributes; anything else ships the template."""
    if html.lower().count("<section") != 1 or html.lower().count("</section>") != 1:
        return False
    parser = _Allowlist()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return False
    return parser.ok and parser.sections == 1


def _same_charts(template_html: str, candidate_html: str) -> bool:
    """Charts are computed data: a restyled slide must carry the template's SVG unchanged."""
    return _SVG.findall(template_html) == _SVG.findall(candidate_html)


def creative_slide(llm, slide_html: str, slide: SlideSpec, tokens: DeckTokens, reference: dict,
                   instructions: str = "") -> str | None:
    extra = f"\nUser instructions: {instructions}" if instructions else ""
    try:
        reply = llm.chat([{"role": "system", "content": _PROMPT},
                          {"role": "user", "content": f"Reference layout: {reference or 'none'}{extra}\nSlide:\n{slide_html}"}])
    except Exception as e:      # the creative pass is optional
        logger.warning("creative pass skipped for %s: %s", slide.id, type(e).__name__)
        return None
    m = _SECTION.search(reply or "")
    if not m or f'data-id="{slide.id}"' not in m.group(0):
        return None
    return m.group(0)


def compose(spec: DeckSpec, out_dir: Path, llm, shingles: set, progress=None, workers: int = 4,
            on_fix=None) -> tuple[Path, list[dict]]:
    template_path = render_deck(spec, out_dir)
    template_html = guards.slide_html_map(template_path.read_text(encoding="utf-8"))
    report = {s.id: {"slide_id": s.id, "source": "template", "reasons": [], "qc": []} for s in spec.slides}
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return _finish(template_path, spec, out_dir, {}, report, on_fix)
    tokens = spec.tokens or DeckTokens()
    candidates: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {s.id: pool.submit(creative_slide, llm, template_html.get(s.id, ""), s, tokens, s.reference)
                   for s in spec.slides}
        for k, s in enumerate(spec.slides, start=1):
            html = futures[s.id].result()
            if progress:
                progress(k, len(spec.slides), s.id)
            if not html:
                report[s.id]["reasons"].append("no usable creative version")
                continue
            if not _safe(html):
                report[s.id]["reasons"].append("unsafe or malformed html")
                continue
            if not _same_charts(template_html.get(s.id, ""), html):
                report[s.id]["reasons"].append("chart changed")
                continue
            text = guards.slide_visible_text(html)
            allowed = s.facts_allowed + [str(spec.base_n), s.question, s.kicker, s.title, spec.period]
            bad = guards.number_issues(text, allowed)
            copied = guards.copied_text(text, shingles)
            if bad or copied:
                report[s.id]["reasons"] += [f"number not in facts: {n}" for n in bad] + [f"copied: {c}" for c in copied]
                continue
            candidates[s.id] = html
    path = render_deck(spec, out_dir, candidates)
    for issue in guards.layout_issues(path):
        if candidates.pop(issue["slide_id"], None) is not None:
            report[issue["slide_id"]]["reasons"].append(f"layout: {issue['kind']} ({issue['detail']})")
    return _finish(render_deck(spec, out_dir, candidates), spec, out_dir, candidates, report, on_fix)


def _finish(path: Path, spec: DeckSpec, out_dir: Path, candidates: dict[str, str], report: dict, on_fix):
    """Final check, keep the creative HTML for later single-slide edits, then repair what still fails QC."""
    path, rows = _final_check(path, spec, out_dir, candidates, report)
    (out_dir / "creative.json").write_text(json.dumps(candidates), encoding="utf-8")
    return repair.repair_deck(spec, out_dir, candidates, rows, on_fix=on_fix, path=path)


def _final_check(path: Path, spec: DeckSpec, out_dir: Path, candidates: dict[str, str], report: dict) -> tuple[Path, list[dict]]:
    """The deck that ships is checked once more, template slides included: a creative slide that still causes a
    problem is dropped; a template slide's problem is flagged for QC."""
    issues = guards.layout_issues(path)
    if any(i["slide_id"] in candidates for i in issues):
        for i in issues:
            if candidates.pop(i["slide_id"], None) is not None:
                report[i["slide_id"]]["reasons"].append(f"layout: {i['kind']} ({i['detail']})")
        path = render_deck(spec, out_dir, candidates)
        issues = guards.layout_issues(path)
    for i in issues:
        if i["slide_id"] in report:
            report[i["slide_id"]]["qc"].append(f"{i['kind']}: {i['detail']}")
    for sid in candidates:
        report[sid]["source"] = "creative"
    return path, list(report.values())
