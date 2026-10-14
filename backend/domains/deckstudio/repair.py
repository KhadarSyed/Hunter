"""In-run repair of template slides that still fail layout QC: shorten text, drop a photo that makes text unreadable,
split a long table onto continuation slides. Up to MAX_ATTEMPTS re-renders; every fix is reported."""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from . import guards, tables
from .renderer import render_deck

MAX_ATTEMPTS = 2
SO_WHAT_MAX = 140
CARD_TEXT_MAX = 160
CARDS_MAX = 2
WALL_QUESTION_MAX = 110          # a verbatim wall header: the question, cut at a sentence or word boundary
SEGMENT_TEXT_MAX = 480            # a segment card ("S" layout) keeps its why and so-what (cards run ~350-480 characters)
TABLE_ROWS_PER_SLIDE = 8
_ACTIONS = {"low_contrast": "drop_photo"}
_TABLE_KINDS = ("overflow", "off_slide")


def action_for(kind: str) -> str:
    return _ACTIONS.get(kind, "shorten")


_KEEP = ""                # stands in for the '!' of a name ('Yahoo! Life') while sentences are split


def _cut(text: str, limit: int, names: tuple[str, ...] = ()) -> str:
    """Whole sentences that fit; a mid-sentence cut (with …) only when not even the first sentence fits. `names`
    hold a '!' that does not end a sentence (outlets like 'Yahoo! Life')."""
    if len(text) <= limit:
        return text
    for name in names:
        text = text.replace(name, name.replace("!", _KEEP))
    sentences = [x.replace(_KEEP, "!") for x in re.split(r"(?<=[.!?])\s+", text)]
    text = text.replace(_KEEP, "!")
    kept = ""
    for s in sentences:
        if len(f"{kept} {s}".strip()) > limit:
            break
        kept = f"{kept} {s}".strip()
    return kept or text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _shorten(slide, names: tuple[str, ...] = ()) -> None:
    slide.so_what = _cut(slide.so_what, SO_WHAT_MAX, names)
    if slide.type == "verbatim_wall":
        # a wall's overflow is its header (a long research question); its screenshots are the content, so the
        # header is shortened and every post stays
        slide.question = _cut(slide.question or "", WALL_QUESTION_MAX)
        slide.title = _cut(slide.title or "", WALL_QUESTION_MAX)
        return
    if slide.treatment == "S":
        slide.cards = [{**c, "text": _cut(c.get("text", ""), SEGMENT_TEXT_MAX, names)} for c in slide.cards]
        return
    slide.cards = [{**c, "text": _cut(c.get("text", ""), CARD_TEXT_MAX, names)} for c in slide.cards[:CARDS_MAX]]


def _split(spec, slide) -> bool:
    rows = slide.tables[0]["rows"] if slide.tables else []
    if slide.type in tables.OWN_LAYOUT or slide.charts:
        cap = TABLE_ROWS_PER_SLIDE
    else:                       # evidence tables: what this layout holds, minus a row for safety
        cap = max(tables.MIN_ROWS, tables.rows_cap(slide) - 1)
    if len(rows) <= cap:
        return False
    at = spec.slides.index(slide)
    chunks = [rows[i:i + cap] for i in range(0, len(rows), cap)]
    table = slide.tables[0]
    links = table.get("links") or []
    slide.tables = [{**table, "rows": chunks[0], "links": links[:cap]}]
    for k, chunk in enumerate(chunks[1:], start=1):       # the insight cards stay with the table's first part
        spec.slides.insert(at + k, replace(slide, id=f"{slide.id}-cont-{k}", title=f"{slide.title} (continued)",
                                           cards=[], citations=[],
                                           tables=[{**table, "rows": chunk, "links": links[k * cap:(k + 1) * cap]}]))
    return True


def _apply(spec, slide, kind: str) -> str:
    if kind in _TABLE_KINDS and _split(spec, slide):
        return "split_table"
    if action_for(kind) == "drop_photo":
        slide.image = {**slide.image, "path": None}
        return "drop_photo"
    _shorten(slide, tuple(sorted({str(m.get("outlet") or "") for m in (spec.citation_meta or {}).values()
                                  if "!" in str(m.get("outlet") or "")}, key=len, reverse=True)))
    return "shorten"


def repair_deck(spec, out_dir: Path, candidates: dict[str, str], report: list[dict], on_fix=None,
                layout=guards.layout_issues, path: Path | None = None) -> tuple[Path, list[dict]]:
    by_id = {r["slide_id"]: r for r in report}
    flagged = {r["slide_id"]: r["qc"] for r in report if r["qc"] and r["slide_id"] not in candidates}
    for _attempt in range(MAX_ATTEMPTS):
        if not flagged:
            break
        for sid, flags in flagged.items():
            slide = next((s for s in spec.slides if s.id == sid), None)
            if slide is None:
                continue
            kind = flags[0].split(":", 1)[0]
            action = _apply(spec, slide, kind)
            by_id[sid].setdefault("repaired", []).append(action)
            if on_fix:
                on_fix(sid, action, kind)
        path = render_deck(spec, out_dir, candidates)
        still: dict[str, list[str]] = {}
        for issue in layout(path):
            if issue["slide_id"] in flagged:
                still.setdefault(issue["slide_id"], []).append(f"{issue['kind']}: {issue['detail']}")
        for sid in flagged:
            by_id[sid]["qc"] = still.get(sid, [])
        flagged = still
    rows = [by_id.get(s.id) or {"slide_id": s.id, "source": "template", "reasons": [], "qc": []} for s in spec.slides]
    return path or out_dir / "deck.html", rows
