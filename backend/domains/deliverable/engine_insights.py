"""Insights stage: cited, number-checked insight cards per RQ (draft_section does the validation)."""
from __future__ import annotations

import re

from ...agents import question_dimensions as qd
from .citations import CitationRegistry
from .engine_types import RQ, EngineRow, Section
from .insights import draft_section
from .tag_insights import tag_answer

N_INSIGHTS = 3
CANDIDATES = 12


def _candidates(sections: list[Section], rows: list[EngineRow], evidence: list[EngineRow] | None = None):
    """Articles an insight may cite. With `evidence` (brand-relevant articles, best first), only those: a chart's
    top article that never names the brand is not a source for a brand deck."""
    if evidence is not None:
        rows = evidence
    by_url = {r.article.norm_url: r.article for r in rows}
    ordered = [u for s in sections for u in s.candidate_urls if u in by_url] + [r.article.norm_url for r in rows]
    seen, out = set(), []
    for u in ordered:
        if u not in seen:
            seen.add(u)
            out.append(by_url[u])
    return out[:CANDIDATES]


def rq_insights(rq: RQ, sections: list[Section], rows: list[EngineRow], registry: CitationRegistry, llm,
                evidence: list[EngineRow] | None = None) -> list[dict]:
    facts = [f for s in sections if not s.skipped for f in s.facts]
    if not facts or not rows:
        return []
    return draft_section(rq.question or rq.id, facts, _candidates(sections, rows, evidence), registry, llm, N_INSIGHTS)


def executive_answers(rqs: list[RQ], sections_by_rq: dict[str, list[Section]], base_n: int) -> list[dict]:
    answers = []
    for rq in rqs:
        tagged = next((s for s in sections_by_rq.get(rq.id, []) if s.module == "tag_share" and not s.skipped), None)
        if tagged is not None:              # the question's own tags answer it: the tagged share and what leads it
            answers.append(tag_answer(rq, tagged))
            continue
        kpi = next((s for s in sections_by_rq.get(rq.id, []) if s.module == "share_kpi" and not s.skipped), None)
        if kpi is None:
            answers.append({"rq_id": rq.id, "question": rq.question, "value": "n/a",
                            "answer": "No articles for this question"})
        else:
            answers.append(_breakdown_answer(rq, sections_by_rq.get(rq.id, [])) or
                           {"rq_id": rq.id, "question": rq.question, "value": f"{kpi.chart['values'][0]}%",
                            "answer": kpi.facts[0].split(": ", 1)[1]})
    return answers


def _breakdown_answer(rq: RQ, sections: list[Section]) -> dict | None:
    """'Which sport…?' is answered by the sport that leads its breakdown, not by the question's share of coverage."""
    s = next((s for s in sections if s.module == "question_breakdown" and not s.skipped and s.chart), None)
    if s is None or not qd.asks_breakdown(rq.question):
        return None
    cats, vals = s.chart["categories"], s.chart["values"]
    total = re.search(r" of (\d+) articles", s.facts[0])
    n = int(total.group(1)) if total else 0
    pct = round(100 * vals[0] / n, 1) if n else 0.0
    share = f" ({pct}%)" if n else ""
    rest = ", ".join(f"{c} ({v})" for c, v in zip(cats[1:4], vals[1:4]))
    text = f"{cats[0]} leads with {vals[0]} of {n} articles{share}" + (f", then {rest}" if rest else "")
    return {"rq_id": rq.id, "question": rq.question, "value": f"{pct}%", "answer": text}


def section_summaries(rq: RQ, sections: list[Section], rows: list[EngineRow], registry: CitationRegistry, llm,
                      evidence: list[EngineRow] | None = None, avoid: list[dict] | None = None,
                      relevant: set[str] | None = None) -> dict[str, list[dict]]:
    """One cited summary per drawn chart or table (not the KPI tile), so no evidence slide goes without its
    answer and its sources. Each is told what the question's insights and earlier summaries already said."""
    out = {}
    said = [f"{c.get('headline', '')}: {c.get('text', '')}" for c in avoid or []]
    for s in sections:
        if s.skipped or not (s.chart or s.table) or (s.chart or {}).get("kind") == "kpi" or not s.facts:
            continue
        segments = chart_segments(s)
        by_url = {r.article.norm_url: r.article for r in rows}
        # a category's card is written from its own articles that also answer the question (the evidence set):
        # a post matching a keyword in another sense ('cut deals with rivals') never becomes the example
        answering = relevant if relevant else ({r.article.norm_url for r in evidence} if evidence else set(by_url))
        owned: dict[str, list[str]] = {}          # article -> every category it is counted in
        for seg in segments:
            mine = [u for u in s.segment_urls.get(seg, []) if u in by_url]
            for u in ([u for u in mine if u in answering] or mine)[:SEGMENT_ARTICLES]:
                owned.setdefault(u, []).append(seg)
        cands = ([by_url[u] for u in dict.fromkeys(owned)] if owned else _candidates([s], rows, evidence))
        summary = draft_section(f"{rq.question} - {s.title}", s.facts, cands, registry, llm, 1,
                                avoid=said, segments=segments or None, article_segments=owned or None)
        cards = _segment_cards(summary, segments) if summary else []
        missing = [g for g in segments if g.lower() not in _by_headline(cards)]
        if cards and missing:            # one more try for the categories whose card was rejected
            more = draft_section(f"{rq.question} - {s.title}", s.facts, cands, registry, llm, 1,
                                 avoid=said + [f"{c['headline']}: {c['text']}" for c in cards],
                                 segments=missing, article_segments=owned or None)
            found = {**_by_headline(more or []), **_by_headline(cards)}
            cards = [found[g.lower()] for g in segments if g.lower() in found]     # back in the chart's order
        if summary and len(cards) < 2 and all(c.get("fact_only") for c in summary[:1]):
            # only a restated statistic came back: ask once more for what drives it, in the client's terms
            why = draft_section(f"{rq.question} - {s.title}: explain WHY the leading result looks this way and what "
                                "it means for the client", s.facts, cands, registry, llm, 1, avoid=said)
            summary = [c for c in why if not c.get("fact_only")][:1] or summary
        if summary:
            out[s.id] = (cards if len(cards) >= 2 else []) or summary[:1]
            said += [f"{c.get('headline', '')}: {c.get('text', '')}" for c in out[s.id]]
    return out


SEGMENT_MAX = 5
SEGMENT_ARTICLES = 3          # a category's own articles offered for its card
_NOT_SEGMENTS = {"unknown", "none", "other", "not stated", "n/a"}


def chart_segments(section: Section) -> list[str]:
    """A breakdown chart's categories, each explained on its own card: what the coverage in it says and why (a
    trend or a single-category chart is explained by one summary; 'Unknown' and the like never get a card)."""
    chart = section.chart or {}
    if chart.get("kind") not in ("bar", "treemap", "doughnut", "pie"):
        return []
    cats = [str(c) for c in chart.get("categories") or [] if str(c).strip().lower() not in _NOT_SEGMENTS]
    return cats[:SEGMENT_MAX] if len(cats) >= 2 else []


def _by_headline(cards: list[dict]) -> dict[str, dict]:
    return {str(c.get("headline", "")).strip().rstrip(":").lower(): c for c in cards}


def _segment_cards(cards: list[dict], segments: list[str]) -> list[dict]:
    """The cards that explain a segment, in the chart's order; fewer than two is not a breakdown explained, so the
    slide keeps its single summary instead."""
    by_name = {str(c.get("headline", "")).strip().rstrip(":").lower(): c for c in cards}
    kept = [by_name[s.lower()] for s in segments if s.lower() in by_name]
    return kept[:SEGMENT_MAX] if len(kept) >= 2 else []
