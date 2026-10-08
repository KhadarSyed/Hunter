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
                      evidence: list[EngineRow] | None = None) -> dict[str, list[dict]]:
    """One cited summary per drawn chart or table (not the KPI tile), so no evidence slide goes without its
    answer and its sources."""
    out = {}
    for s in sections:
        if s.skipped or not (s.chart or s.table) or (s.chart or {}).get("kind") == "kpi" or not s.facts:
            continue
        summary = draft_section(f"{rq.question} - {s.title}", s.facts, _candidates([s], rows, evidence), registry, llm, 1)
        if summary:
            out[s.id] = summary[:1]
    return out
