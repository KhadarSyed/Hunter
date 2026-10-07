"""In-run repair of template slides that still fail layout QC: shorten text, drop a photo that makes text unreadable,
split a long table onto continuation slides. Up to MAX_ATTEMPTS re-renders; every fix is reported."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from . import guards
from .renderer import render_deck

MAX_ATTEMPTS = 2
SO_WHAT_MAX = 140
CARD_TEXT_MAX = 160
CARDS_MAX = 3
TABLE_ROWS_PER_SLIDE = 8
_ACTIONS = {"low_contrast": "drop_photo"}
_TABLE_KINDS = ("overflow", "off_slide")


def action_for(kind: str) -> str:
    return _ACTIONS.get(kind, "shorten")


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _shorten(slide) -> None:
    slide.so_what = _cut(slide.so_what, SO_WHAT_MAX)
    slide.cards = [{**c, "text": _cut(c.get("text", ""), CARD_TEXT_MAX)} for c in slide.cards[:CARDS_MAX]]


def _split(spec, slide) -> bool:
    rows = slide.tables[0]["rows"] if slide.tables else []
    if len(rows) <= TABLE_ROWS_PER_SLIDE:
        return False
    at = spec.slides.index(slide)
    chunks = [rows[i:i + TABLE_ROWS_PER_SLIDE] for i in range(0, len(rows), TABLE_ROWS_PER_SLIDE)]
    table = slide.tables[0]
    slide.tables = [{**table, "rows": chunks[0]}]
    for k, chunk in enumerate(chunks[1:], start=1):
        spec.slides.insert(at + k, replace(slide, id=f"{slide.id}-cont-{k}", title=f"{slide.title} (continued)",
                                           tables=[{**table, "rows": chunk}]))
    return True


def _apply(spec, slide, kind: str) -> str:
    if kind in _TABLE_KINDS and _split(spec, slide):
        return "split_table"
    if action_for(kind) == "drop_photo":
        slide.image = {**slide.image, "path": None}
        return "drop_photo"
    _shorten(slide)
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
