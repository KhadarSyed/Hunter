"""Insights stage: cited, number-checked insight cards per RQ (draft_section does the validation)."""
from __future__ import annotations

from .citations import CitationRegistry
from .engine_types import RQ, EngineRow, Section
from .insights import draft_section

N_INSIGHTS = 3
CANDIDATES = 12


def _candidates(sections: list[Section], rows: list[EngineRow]):
    by_url = {r.article.norm_url: r.article for r in rows}
    ordered = [u for s in sections for u in s.candidate_urls if u in by_url] + [r.article.norm_url for r in rows]
    seen, out = set(), []
    for u in ordered:
        if u not in seen:
            seen.add(u)
            out.append(by_url[u])
    return out[:CANDIDATES]


def rq_insights(rq: RQ, sections: list[Section], rows: list[EngineRow], registry: CitationRegistry, llm) -> list[dict]:
    facts = [f for s in sections if not s.skipped for f in s.facts]
    if not facts or not rows:
        return []
    return draft_section(rq.question or rq.id, facts, _candidates(sections, rows), registry, llm, N_INSIGHTS)


def executive_answers(rqs: list[RQ], sections_by_rq: dict[str, list[Section]], base_n: int) -> list[dict]:
    answers = []
    for rq in rqs:
        kpi = next((s for s in sections_by_rq.get(rq.id, []) if s.module == "share_kpi" and not s.skipped), None)
        if kpi is None:
            answers.append({"rq_id": rq.id, "question": rq.question, "value": "n/a",
                            "answer": "No articles for this question"})
        else:
            answers.append({"rq_id": rq.id, "question": rq.question, "value": f"{kpi.chart['values'][0]}%",
                            "answer": kpi.facts[0].split(": ", 1)[1]})
    return answers
