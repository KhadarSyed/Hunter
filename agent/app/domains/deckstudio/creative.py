"""Per-slide LLM creative pass. The model may restyle a slide's HTML within the deck's tokens; the result
ships only if every guard passes, otherwise the template version does."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import guards
from .renderer import render_deck
from .spec import DeckSpec, DeckTokens, SlideSpec

logger = logging.getLogger(__name__)
_SECTION = re.compile(r"<section\b.*?</section>", re.S | re.I)
_BAD = [re.compile(p, re.S | re.I) for p in (r"<script\b.*?</script>", r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')",
                                               r"<iframe\b.*?</iframe>", r"<link\b[^>]*>")]
_REMOTE = re.compile(r"""\s(src|href)\s*=\s*["'](https?:)?//[^"']*["']""", re.I)
_PROMPT = ("You are a presentation designer. Improve this one slide's HTML (a 1920x1080 <section>) so it looks "
           "premium and on-brand. Keep the same data-id, every number and every word of the question exactly as "
           "given; never add numbers. Use only the CSS variables --primary, --accent, --text, --muted, --surface, "
           "--on-dark, --overlay, --title, --body and the existing assets/ images. No scripts, no external URLs, "
           "nothing outside the slide. Return only the <section>...</section>.")


def _sanitise(html: str) -> str:
    for bad in _BAD:
        html = bad.sub("", html)
    return _REMOTE.sub("", html)


def creative_slide(llm, slide_html: str, slide: SlideSpec, tokens: DeckTokens, reference: dict) -> str | None:
    try:
        reply = llm.chat([{"role": "system", "content": _PROMPT},
                          {"role": "user", "content": f"Reference layout: {reference or 'none'}\nSlide:\n{slide_html}"}])
    except Exception as e:      # the creative pass is optional
        logger.warning("creative pass skipped for %s: %s", slide.id, type(e).__name__)
        return None
    m = _SECTION.search(reply or "")
    if not m or f'data-id="{slide.id}"' not in m.group(0):
        return None
    return _sanitise(m.group(0))


def compose(spec: DeckSpec, out_dir: Path, llm, shingles: set, progress=None, workers: int = 4) -> tuple[Path, list[dict]]:
    template_path = render_deck(spec, out_dir)
    template_html = guards.slide_html_map(template_path.read_text(encoding="utf-8"))
    report = {s.id: {"slide_id": s.id, "source": "template", "reasons": []} for s in spec.slides}
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return template_path, list(report.values())
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
    for sid in candidates:
        report[sid]["source"] = "creative"
    return render_deck(spec, out_dir, candidates), list(report.values())
