"""What the deck's repair agent needs once the run has ended: each chart's facts, the articles behind each of its
categories (articles that answer the question first) and its candidate sources, and each question's best sources.
Saved beside the deck (repair_context.json), so the Fix button can repair a finished run without recomputing it."""
from __future__ import annotations

from . import evidence
from .engine_types import RQ, EngineRow, Section

ARTICLES_PER_SEGMENT = 6
CANDIDATES = 12
TEXT_CHARS = 600


def article(row: EngineRow, brands) -> dict:
    a = row.article
    return {"url": a.url, "title": a.title, "outlet": a.outlet, "date": a.date.isoformat() if a.date else "",
            "text": (a.text or "")[:TEXT_CHARS], "brands": evidence.row_brands(row, brands)}


def _section(s: Section, by_url: dict[str, EngineRow], relevant: set[str], brands) -> dict:
    segments = {}
    for seg, urls in (s.segment_urls or {}).items():
        mine = [u for u in urls if u in by_url]
        ordered = [u for u in mine if u in relevant] + [u for u in mine if u not in relevant]
        segments[str(seg)] = [article(by_url[u], brands) for u in ordered[:ARTICLES_PER_SEGMENT]]
    candidates = [u for u in s.candidate_urls if u in by_url][:CANDIDATES]
    return {"title": s.title, "facts": list(s.facts), "segments": segments,
            "candidates": [article(by_url[u], brands) for u in candidates]}


def build(rqs: list[RQ], sections_by_rq: dict[str, list[Section]], rows_by_rq: dict[str, list[EngineRow]],
          rows: list[EngineRow], brands, relevant_by_rq: dict[str, set[str]]) -> dict:
    by_url = {r.article.norm_url: r for r in rows}
    sections = {}
    for rq_id, secs in sections_by_rq.items():
        for s in secs:
            if not s.skipped:
                sections[s.id] = {**_section(s, by_url, relevant_by_rq.get(rq_id, set()), brands), "rq_id": rq_id}
    questions = {q.id: {"question": q.question,
                        "candidates": [article(r, brands)
                                       for r in evidence.rank(rows_by_rq.get(q.id, []), brands, [], "primary")[:CANDIDATES]]}
                 for q in rqs}
    return {"sections": sections, "questions": questions}
