"""Deck validator: after the deck is built, every requirement of a client deck is checked and each gap named --
the client's logo and product on the cover, the brand vs competitor chapter, an answer, a chart, a cited summary
and verbatims for every question, every citation listed (with its icon) in Sources, and the brief's own asks.

Rows are {check, status: pass | warn | fail, detail}; a fail is something the client would notice is missing.
"""
from __future__ import annotations

from ..deliverable.engine_types import RQ
from .spec import DeckSpec, SlideSpec


def _row(check: str, ok: bool, detail: str = "", soft: bool = False) -> dict:
    return {"check": check, "status": "pass" if ok else ("warn" if soft else "fail"), "detail": "" if ok else detail}


def _cited(slides: list[SlideSpec]) -> set[str]:
    return {str(n) for s in slides for c in s.cards for n in c.get("citations") or []}


def _question(rq: RQ, slides: list[SlideSpec]) -> dict:
    mine = [s for s in slides if s.id.startswith(rq.id.lower() + "-")]
    divider = next((s for s in mine if s.type == "divider"), None)
    gaps = []
    if not divider or not (divider.so_what or "").strip():
        gaps.append("no answer")
    if not any(s.charts or s.tables for s in mine if s.type != "verbatim_wall"):
        gaps.append("no chart")
    if not _cited([s for s in mine if s.type != "verbatim_wall"]):
        gaps.append("no cited summary")
    if not any(s.type == "verbatim_wall" and s.cards for s in mine):
        gaps.append("no verbatims")
    return _row(rq.question, not gaps, ", ".join(gaps))


def validate_deck(spec: DeckSpec, rqs: list[RQ], checklist: list[dict], brand_products: list[str],
                  has_competitors: bool) -> list[dict]:
    slides = spec.slides
    rows = [_row("Client logo on the cover", bool(spec.brand_logo), "no logo for the client brand"),
            _row("Client product on the cover", bool(spec.product_image) or not brand_products,
                 f"no photo found for {', '.join(brand_products[:2])}", soft=True)]
    if has_competitors:
        rows.append(_row("Brand share of voice vs competitors", any(s.id.startswith("brand-sov") for s in slides),
                         "no share of voice slide"))
        rows.append(_row("Brand sentiment vs competitors", any(s.id.startswith("brand-sentiment") for s in slides),
                         "no sentiment slide"))
    rows += [_question(rq, slides) for rq in rqs]
    summary = next((s for s in slides if s.type == "executive_summary"), None)
    uncited = [c.get("headline") or "" for c in (summary.cards if summary else []) if not c.get("citations")]
    rows.append(_row("Executive summary cites its sources", bool(summary) and not uncited,
                     f"{len(uncited)} answer(s) without a source" if summary else "no executive summary", soft=True))
    listed = {str(r[0]) for s in slides if s.type == "citations" for t in s.tables for r in t.get("rows", []) if r}
    missing = sorted(_cited(slides) - listed, key=lambda n: int(n) if n.isdigit() else 0)
    rows.append(_row("Every citation is listed in Sources", not missing, "not in Sources: " + ", ".join(missing)))
    no_icon = sorted(n for n in _cited(slides) if not (spec.citation_meta.get(n) or {}).get("icon"))
    rows.append(_row("Citations show their source icon", not no_icon, f"{len(no_icon)} source(s) without an icon",
                     soft=True))
    rows += [_row(f"Brief: {r['ask']}", r["status"] == "covered", r.get("note") or r["status"],
                  soft=r["status"] == "partial")
             for r in checklist if r.get("kind") != "question"]
    return rows
