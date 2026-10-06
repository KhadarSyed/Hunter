"""LLM-drafted insights, accepted only if every number and citation checks out."""
from __future__ import annotations

import json
import logging
import re

from .citations import CitationRegistry
from .ingest import Article

logger = logging.getLogger(__name__)
_NUM = re.compile(r"\d+(?:\.\d+)?")
_YEARS = {"2024", "2025", "2026"}
MAX_CITES = 3


def allowed_numbers(facts: list[str]) -> set[str]:
    return {n for f in facts for n in _NUM.findall(f)} | _YEARS


_NUM_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(%|[A-Za-z]+)?")
_UNITS = {"%": "%", "article": "articles", "articles": "articles", "time": "times", "times": "times",
          "mention": "times", "mentions": "times", "expert": "experts", "experts": "experts"}


_X_OF_Y = re.compile(r"(\d+(?:\.\d+)?)\s+(?:of|out of)\s+(\d+(?:\.\d+)?)\s*([A-Za-z]+)")


def _pairs(text: str) -> set[tuple[str, str]]:
    out = {(n, _UNITS[u.lower()]) for n, u in _NUM_UNIT.findall(text)
           if u and u.lower() in _UNITS and n not in _YEARS}          # "July 2026 experts" is a date, not a count
    for x, y, u in _X_OF_Y.findall(text):                             # "18 of 778 articles": both are articles
        if u.lower() in _UNITS:
            out |= {(x, _UNITS[u.lower()]), (y, _UNITS[u.lower()])}
    return out


def allowed_pairs(facts: list[str]) -> set[tuple[str, str]]:
    """(number, unit) pairs stated in the facts, so '37 times' can't be restated as '37 articles'."""
    return {p for f in facts for p in _pairs(f)}


def validate_insight(text: str, cites: list[int], allowed: set[str], candidate_ids: set[int],
                     pairs: set[tuple[str, str]] | None = None) -> str | None:
    if not cites or not set(cites) <= candidate_ids:
        return "citation missing or outside candidate set"
    bad = [n for n in _NUM.findall(text) if n not in allowed]
    if bad:
        return f"number(s) not in facts: {bad}"
    if pairs is not None:
        wrong_unit = [f"{n} {u}" for n, u in _pairs(text) if (n, u) not in pairs]
        if wrong_unit:
            return f"number(s) with a unit the facts don't state: {wrong_unit}"
    return None


def _fallback(facts: list[str], candidates: list[Article], registry: CitationRegistry) -> list[dict]:
    return _backfill([], facts, candidates, registry, 1)


_PEAK = re.compile(r"^Peak (\d+):")
_LEADS = ("Top outlet", "Retailer", "Topic")


def _fact_headline(fact: str) -> str:
    peak = _PEAK.match(fact)
    if peak:
        return f"Peak month #{peak.group(1)}"
    if "sentiment:" in fact.lower():
        return "Sentiment split"
    lead = next((l for l in _LEADS if fact.startswith(l)), None)
    return lead or "Key finding"


def _backfill(kept: list[dict], facts: list[str], candidates: list[Article], registry: CitationRegistry,
              n: int) -> list[dict]:
    """Top a section up to n insights with deterministic fact cards (true by construction), skipping facts whose
    lead number an accepted insight already states. Cites the section's evidence articles."""
    if not candidates:
        return kept
    stated = " ".join(k["text"] for k in kept)
    out = list(kept)
    for fact in facts:
        if len(out) >= n:
            break
        lead = _NUM.search(fact)
        if lead and lead.group() in _NUM.findall(stated):
            continue
        headline = _fact_headline(fact)
        text = fact.rstrip(".") + "."
        out.append({"headline": headline, "text": text[:1].upper() + text[1:],
                    "citations": [registry.cite(a) for a in candidates[:2]]})   # register only when used
        stated += " " + fact
    return out


def draft_section(section: str, facts: list[str], candidates: list[Article], registry: CitationRegistry,
                  llm, n_insights: int = 3) -> list[dict]:
    """Candidates get local ids 1..k in the prompt; only articles an accepted insight actually cites are
    registered, so the appendix lists cited articles only."""
    if llm is None:
        return _backfill([], facts, candidates, registry, n_insights)
    allowed = allowed_numbers(facts)
    pairs = allowed_pairs(facts)
    local = {i: a for i, a in enumerate(candidates, start=1)}
    arts = [{"id": i, "outlet": a.outlet, "date": a.date.isoformat() if a.date else "", "title": a.title,
             "excerpt": a.text[:400]} for i, a in local.items()]
    messages = [
        {"role": "system", "content": "You write insights for a media-research deck. Use ONLY numbers that appear "
         "in FACTS. Every insight must cite the 1-3 article ids from ARTICLES that best support it. Return JSON only."},
        {"role": "user", "content": f"Section: {section}\nFACTS:\n" + "\n".join(f"- {f}" for f in facts) +
         f"\nARTICLES:\n{json.dumps(arts, ensure_ascii=False)}\nWrite {n_insights} insights as "
         '{"insights":[{"headline":"<=8 words","text":"<=45 words","citations":[ids]}]}'},
    ]
    try:
        parsed = json.loads(llm.chat(messages, format_json=True))
    except (json.JSONDecodeError, RuntimeError) as e:
        logger.warning("insight drafting for %s failed (%s); using fallback", section, e)
        return _fallback(facts, candidates, registry)
    valid = []
    for ins in parsed.get("insights", []):
        headline, text = str(ins.get("headline", "")).strip(), str(ins.get("text", "")).strip()
        raw = [int(c) for c in ins.get("citations", []) if str(c).isdigit()]
        cites = [c for c in dict.fromkeys(raw) if c in local][:MAX_CITES]   # drop unknown ids, cap
        reason = validate_insight(f"{headline} {text}", cites, allowed, set(local), pairs)
        if reason:
            logger.info("dropped insight in %s: %s", section, reason)
            continue
        valid.append((headline, text, cites))
    supported = _verify_claims(section, valid, facts, local, llm)
    kept = [{"headline": h, "text": t, "citations": sorted({registry.cite(local[c]) for c in cs})}
            for i, (h, t, cs) in enumerate(valid) if i in supported]
    return _backfill(kept, facts, candidates, registry, n_insights)


def _verify_claims(section: str, valid: list[tuple], facts: list[str], local: dict[int, Article], llm) -> set[int]:
    """Second pass: a judge checks every claim (numeric or not) against FACTS and its cited articles.
    Drops only explicit 'supported: false'; a missing/garbled verdict keeps the insight, which has already
    passed the number, unit and citation checks."""
    if not valid:
        return set()
    items = [{"index": i, "claim": f"{h}. {t}",
              "evidence": [{"title": local[c].title, "excerpt": local[c].text[:600]} for c in cs]}
             for i, (h, t, cs) in enumerate(valid)]
    messages = [
        {"role": "system", "content": "You fact-check insights for a media-research deck. Judge the factual content "
         "only — numbers, names, dates, events, rankings. Mark a claim unsupported only if a factual element is "
         "contradicted by, or absent from, FACTS and its own EVIDENCE articles. Reasonable interpretation that "
         "follows from supported facts (e.g. 'indicating strong interest') is allowed. Return JSON only."},
        {"role": "user", "content": f"Section: {section}\nFACTS:\n" + "\n".join(f"- {f}" for f in facts) +
         f"\nCLAIMS:\n{json.dumps(items, ensure_ascii=False)}\n"
         'Return {"verdicts":[{"index":0,"supported":true}]} with one verdict per claim.'},
    ]
    try:
        verdicts = json.loads(llm.chat(messages, format_json=True)).get("verdicts", [])
    except (json.JSONDecodeError, RuntimeError, AttributeError) as e:
        logger.warning("claim verification for %s failed (%s); keeping validated insights", section, e)
        return set(range(len(valid)))
    rejected = {v.get("index") for v in verdicts if isinstance(v, dict) and v.get("supported") is False}
    for i in sorted(rejected):
        if isinstance(i, int) and 0 <= i < len(valid):
            logger.info("dropped unsupported claim in %s: %s", section, valid[i][1][:80])
    return {i for i in range(len(valid)) if i not in rejected}
