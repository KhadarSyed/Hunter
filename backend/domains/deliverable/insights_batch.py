"""Batched insight drafting (opt-in: HUNTER_BATCH_INSIGHTS=1). One GPT call drafts the cards of every chart section
of a question, one call repairs the rejected cards, one judge call checks every claim -- instead of 3-8 calls per
section, one section after another. Each section keeps its own FACTS, ARTICLES (ids local to it), segments and the
same checks as insights.draft_section: _screen, the judge's rules, the number-free rescue, the fact-card backfill."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from . import insights as ins
from .citations import CitationRegistry
from .ingest import Article

logger = logging.getLogger(__name__)

_BATCH_NOTE = (" Several SECTIONS follow. Each has its own FACTS, ARTICLES (article ids are local to that section), "
               "ALREADY_SAID and ASK: answer every section on its own, from its own FACTS and ARTICLES only, and never "
               "repeat a point or figure another section makes. Return "
               '{"sections":[{"id":"s0","insights":[...]}]} with one entry per section id.')
_REPAIR_NOTE = " Each section lists its REJECTED insights and why: write replacements that fix those problems."
_JUDGE_NOTE = (" CLAIMS come from several sections: judge each only against its own section's FACTS and its own "
               "EVIDENCE.")


def enabled() -> bool:
    return os.environ.get("HUNTER_BATCH_INSIGHTS", "").strip().lower() in ("1", "true", "yes")


@dataclass
class Job:
    """One section's drafting inputs (as draft_section takes them); the rest is worked out by _prepare."""
    section: str
    facts: list[str]
    candidates: list[Article]
    n: int = 1
    entities: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    segments: list[str] | None = None
    article_segments: dict[str, list[str]] | None = None
    related: set[str] | None = None
    local: dict[int, Article] = field(default_factory=dict)
    arts: list[dict] = field(default_factory=list)
    allowed: set[str] = field(default_factory=set)
    pairs: set = field(default_factory=set)
    owners: dict[str, set[int]] = field(default_factory=dict)
    shown: set[str] = field(default_factory=set)
    valid: list[tuple] = field(default_factory=list)


def _prepare(j: Job) -> None:
    if j.segments:
        j.n = len(j.segments)
    j.allowed, j.pairs = ins.allowed_numbers(j.facts), ins.allowed_pairs(j.facts)
    j.local = {i: a for i, a in enumerate(j.candidates, start=1)}
    j.arts = [{"id": i, "outlet": a.outlet, "date": a.date.isoformat() if a.date else "", "title": a.title,
               "excerpt": a.text[:400], **({"segments": j.article_segments[a.norm_url]}
                                           if j.article_segments and a.norm_url in j.article_segments else {})}
              for i, a in j.local.items()]
    j.owners = ins._segment_owners(j.local, j.article_segments)
    j.shown = ins._headline_figures(j.facts)


def _ask(j: Job, k: int) -> str:
    if j.segments:
        return ins._segment_ask(j.segments)
    return (f"Write {k} insights as "
            '{"insights":[{"headline":"<=10 words: the takeaway, not the headline figure","text":"<=35 words: '
            'the named drivers behind the finding, then the so-what for the client","citations":[ids]}]}')


def _block(i: int, j: Job, extra: dict | None = None) -> dict:
    return {"id": f"s{i}", "SECTION": j.section, "FACTS": j.facts, "ARTICLES": j.arts,
            "ALREADY_SAID": j.avoid, "ASK": _ask(j, j.n - len(j.valid)), **(extra or {})}


def _call(llm, system: str, payload: dict, key: str) -> list[dict]:
    reply = json.loads(llm.chat([{"role": "system", "content": system},
                                 {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                                format_json=True))
    return [x for x in reply.get(key, []) if isinstance(x, dict)]


def _section_index(sid, n: int) -> int | None:
    s = str(sid or "")
    return int(s[1:]) if s[:1] == "s" and s[1:].isdigit() and int(s[1:]) < n else None


def _screen(j: Job, parsed: dict) -> list[tuple[str, str]]:
    """Screen a section's drafted cards as draft_section does; the valid ones join j.valid (no repeats)."""
    taken = {f for h, t, _ in j.valid for f in ins._figures(f"{h} {t}")}
    found, rejected = ins._screen(j.section, parsed, j.allowed, j.pairs, j.local, j.entities, j.shown, taken,
                                  owners=j.owners, related=j.related)
    seen = {t for _, t, _ in j.valid}
    j.valid += [v for v in found if v[1] not in seen]
    return rejected


def _verify(jobs: list[Job], llm) -> list[set[int]]:
    """One judge call for every section's claims; a failed call keeps the claims (they passed _screen)."""
    keep = [set(range(len(j.valid))) for j in jobs]
    items = [{"index": f"s{i}:{k}", "section": f"s{i}", "claim": f"{h}. {t}",
              "evidence": [{"title": j.local[c].title, "excerpt": j.local[c].text[:600]} for c in cs]}
             for i, j in enumerate(jobs) for k, (h, t, cs) in enumerate(j.valid)]
    if not items:
        return keep
    payload = {"SECTIONS": [{"id": f"s{i}", "SECTION": j.section, "FACTS": j.facts} for i, j in enumerate(jobs)],
               "CLAIMS": items, "RETURN": '{"verdicts":[{"index":"s0:0","supported":true}]}, one per claim'}
    try:
        verdicts = _call(llm, ins._JUDGE_SYSTEM + _JUDGE_NOTE, payload, "verdicts")
    except (json.JSONDecodeError, RuntimeError, AttributeError) as e:
        logger.warning("batched claim verification failed (%s); keeping screened insights", e)
        return keep
    for v in verdicts:
        sec, _, k = str(v.get("index", "")).partition(":")
        i = _section_index(sec, len(jobs))
        if v.get("supported") is False and i is not None and k.isdigit() and int(k) in keep[i]:
            keep[i].discard(int(k))
            logger.info("dropped unsupported claim in %s: %s", jobs[i].section, jobs[i].valid[int(k)][1][:80])
    return keep


def draft_sections(jobs: list[Job], registry: CitationRegistry, llm) -> list[list[dict]]:
    """draft_section for several sections at once: the same cards, in far fewer GPT calls."""
    if llm is None or len(jobs) < 2:
        return _one_by_one(jobs, registry, llm)
    for j in jobs:
        _prepare(j)
    try:
        drafted = _call(llm, ins._DRAFT_SYSTEM + _BATCH_NOTE,
                        {"SECTIONS": [_block(i, j) for i, j in enumerate(jobs)]}, "sections")
    except (json.JSONDecodeError, RuntimeError) as e:
        logger.warning("batched insight drafting failed (%s); drafting section by section", e)
        return _one_by_one(jobs, registry, llm)
    by_id = {d.get("id"): d for d in drafted}
    rejected = {}
    for i, j in enumerate(jobs):
        r = _screen(j, by_id.get(f"s{i}", {}))
        if r and len(j.valid) < j.n:
            rejected[i] = r
    if rejected:                   # one repair round for every section short of cards: why each was rejected
        blocks = [_block(i, jobs[i], {"REJECTED": [f"\"{t}\" -- {why}" for t, why in r]}) for i, r in rejected.items()]
        try:
            for d in _call(llm, ins._DRAFT_SYSTEM + _BATCH_NOTE + _REPAIR_NOTE, {"SECTIONS": blocks}, "sections"):
                i = _section_index(d.get("id"), len(jobs))
                if i in rejected:
                    _screen(jobs[i], d)
        except (json.JSONDecodeError, RuntimeError) as e:
            logger.warning("batched insight repair failed (%s)", e)
    supported = _verify(jobs, llm)
    out = []
    for i, j in enumerate(jobs):
        shown = [v for k, v in enumerate(j.valid) if k in supported[i]][:j.n]
        if len(shown) < j.n:       # the number-free rescue stays per section: only the short ones need it
            shown += ins._rescue(j.section, j.facts, j.arts, j.local, llm, j.n - len(shown),
                                 j.avoid + [f"{h}: {t}" for h, t, _ in shown], j.entities, j.allowed, j.pairs, j.shown)
        kept = [{"headline": h, "text": t, "citations": sorted({registry.cite(j.local[c]) for c in cs})}
                for h, t, cs in shown]
        cards = ins._backfill(kept, j.facts, j.candidates, registry, j.n, skip=j.shown)
        out.append(cards or ins._backfill(kept, j.facts, j.candidates, registry, j.n))   # never an empty panel
    return out


def _one_by_one(jobs: list[Job], registry: CitationRegistry, llm) -> list[list[dict]]:
    return [ins.draft_section(j.section, j.facts, j.candidates, registry, llm, j.n, entities=j.entities,
                              avoid=j.avoid, segments=j.segments, article_segments=j.article_segments,
                              related_segments=j.related) for j in jobs]
