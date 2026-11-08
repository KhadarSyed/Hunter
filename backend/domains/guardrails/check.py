"""Guardrails check of a finished deck (Deliverables). Python first — free, exact, instant:
- prohibited words: every quoted term in a guardrail's "prohibited" section plus its listed variations, matched as
  whole words with their word family (a stem of 5+ letters also matches longer forms: "position" → "positioning");
- repetition: slide titles opening with the same words, and sentences repeated across slides.
The optional AI review asks the org's model to judge the meaning-level rules (factual, no speculation, human tone…)
against the full guardrail text, one call per deck."""
from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

from . import repository as repo

logger = logging.getLogger(__name__)
_QUOTED = re.compile(r'"([^"\n]{1,60})"')
_SECTION_END = re.compile(r"^\s*\d+\.\s+\S")
STEM_MIN = 5
MAX_SLIDE_TEXT = 4000


def prohibited_terms(org_id: int) -> list[str]:
    """Terms the org's active guardrails prohibit: quoted terms on lines after a 'prohibited vocabulary' heading, and
    the comma-separated words under an 'Examples of variations' heading, each block ending at 'This list is…' or the
    next numbered section. Lower-case, unique, longest first."""
    terms: set[str] = set()
    for g in repo.list_guardrails(org_id, active_only=True):
        mode = None
        for line in g["body"].splitlines():
            low = line.lower().strip()
            if low.startswith("this list is") or _SECTION_END.match(line):
                mode = None
                continue
            if low.startswith("prohibited vocabulary"):
                mode = "quoted"
            elif low.startswith("examples of variations"):
                mode = "variants"
                continue
            if mode == "quoted":
                terms.update(t.strip().lower() for t in _QUOTED.findall(line) if t.strip())
            elif mode == "variants" and "," in line:
                terms.update(w.strip(" .").lower() for w in line.split(",") if w.strip(" ."))
    return sorted(terms, key=lambda t: (-len(t), t))


def _pattern(term: str) -> re.Pattern:
    if not re.search(r"\w", term):                      # a symbol such as "%"
        return re.compile(re.escape(term))
    if len(term.split()) == 1 and len(term) >= STEM_MIN:   # the word family: positioned, positioning, …
        return re.compile(rf"(?<!\w){re.escape(term)}\w*", re.I)
    return re.compile(rf"(?<!\w){re.escape(term)}(?:s|es)?(?!\w)", re.I)


def deck_slides(pptx_path: str | Path) -> list[dict]:
    """[{n, title, text}] for every slide of a .pptx: titles, text boxes and table cells, in reading order."""
    from pptx import Presentation
    out = []
    for n, slide in enumerate(Presentation(str(pptx_path)).slides, start=1):
        title_shape = slide.shapes.title
        title = title_shape.text_frame.text.strip() if title_shape is not None and title_shape.has_text_frame else ""
        parts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False) and shape.has_table:
                parts += [c.text for row in shape.table.rows for c in row.cells]
        text = "\n".join(p for p in parts if p and p.strip())[:MAX_SLIDE_TEXT]
        out.append({"n": n, "title": title or text.split("\n", 1)[0][:120], "text": text})
    return out


def _snippet(text: str, start: int, end: int) -> str:
    a, b = max(0, start - 50), min(len(text), end + 50)
    return ("…" if a else "") + text[a:b].replace("\n", " ") + ("…" if b < len(text) else "")


def scan(slides: list[dict], terms: list[str]) -> list[dict]:
    """Rule-based findings: [{slide, rule, term, excerpt}]. Overlapping matches report the longest term once."""
    issues: list[dict] = []
    pats = [(t, _pattern(t)) for t in terms]           # longest first
    for s in slides:
        text, taken = s["text"], []
        for term, pat in pats:
            for m in pat.finditer(text):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                taken.append((m.start(), m.end()))
                issues.append({"slide": s["n"], "rule": "prohibited word", "term": m.group(0),
                               "excerpt": _snippet(text, m.start(), m.end())})
    openings = Counter(" ".join(s["title"].lower().split()[:3]) for s in slides if len(s["title"].split()) >= 4)
    for s in slides:
        key = " ".join(s["title"].lower().split()[:3])
        if len(s["title"].split()) >= 4 and openings.get(key, 0) > 1:
            issues.append({"slide": s["n"], "rule": "repeated title structure", "term": key, "excerpt": s["title"]})
    seen: dict[str, int] = {}
    for s in slides:
        for sentence in re.split(r"(?<=[.!?])\s+", s["text"]):
            norm = " ".join(sentence.lower().split())
            if len(norm) < 60:
                continue
            if norm in seen and seen[norm] != s["n"]:
                issues.append({"slide": s["n"], "rule": "repeated sentence", "term": f"also on slide {seen[norm]}",
                               "excerpt": sentence[:200]})
            seen.setdefault(norm, s["n"])
    return issues


class ReviewFailed(RuntimeError):
    """The AI review did not run: reported as an error, never as "no issues"."""


def ai_review(org_id: int, slides: list[dict], llm) -> list[dict]:
    """One call: the org's model judges the deck against the full guardrail text (meaning-level rules only — the
    word list is checked in Python). Returns [{slide, rule, excerpt, suggestion}]; [] on any failure."""
    from . import service
    text = service.text_for(org_id)
    if not text or llm is None:
        return []
    deck = "\n\n".join(f"[Slide {s['n']}] {s['title']}\n{s['text'][:1500]}" for s in slides)[:60000]
    messages = [
        {"role": "system", "content": "You review a client research deck for compliance with the organization's "
                                      "guardrails below. Report only clear violations of meaning-level rules (factual "
                                      "accuracy, speculation, exaggeration, generic AI-sounding wording, descriptive "
                                      "instead of analytical, overlapping findings). Do not report the prohibited word "
                                      "list (checked separately). Answer JSON only: {\"issues\": [{\"slide\": n, "
                                      "\"rule\": \"...\", \"excerpt\": \"exact words from the slide\", \"suggestion\": "
                                      "\"a compliant rewrite\"}]}\n\n" + text},
        {"role": "user", "content": deck}]
    try:
        from ...core.llm_provider import extract_json_object
        data = extract_json_object(llm.chat(messages, format_json=True)) or {}
        return [{"slide": int(i.get("slide") or 0), "rule": str(i.get("rule") or "guardrail")[:120],
                 "excerpt": str(i["excerpt"])[:400], "suggestion": str(i.get("suggestion") or "")[:600]}
                for i in data.get("issues") or [] if isinstance(i, dict) and i.get("excerpt")]
    except Exception as e:
        logger.warning("guardrails AI review failed: %s", type(e).__name__)
        raise ReviewFailed(f"The AI review could not run ({type(e).__name__}); the word check above still applies") from e


def check_deck(org_id: int, pptx_path: str | Path) -> dict:
    slides = deck_slides(pptx_path)
    terms = prohibited_terms(org_id)
    issues = scan(slides, terms)
    return {"slides": len(slides), "terms_checked": len(terms), "issues": issues,
            "passed": not any(i["rule"] == "prohibited word" for i in issues)}
