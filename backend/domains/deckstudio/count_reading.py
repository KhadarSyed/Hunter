"""What a chart category's number says about the research question, when none of its sampled articles explains
what drives it: read from the chart's own numbers only (its share, its rank, the gap to the leader), never a cause."""
from __future__ import annotations

import logging
import re

from ...core.llm_provider import extract_json_object

logger = logging.getLogger(__name__)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
SMALL_SHARE = 5.0         # a category under this share of the chart is too small to set the answer's direction

_SYSTEM = ("You write one insight card per chart category for a research deck. No article explains these "
           "categories, so read them from the chart alone: what the category's size and place among the others mean "
           "for the research question, and what the client should do with that. Never give a cause, motive or "
           "driver; never name an outlet, post or person. Quote at most one or two numbers, copied exactly as given "
           "(a count, the total or a share); never compute a difference, gap, ratio or new percentage. Two short "
           "sentences per category, plain English, no list of numbers. Example: 'Editorial carries 38.8% of this "
           "coverage, second to Social: news and blog stories are a real but secondary channel for this topic, "
           "worth a supporting role in the plan.' Return JSON {\"cards\": {\"<category>\": \"<text>\"}}.")


def _shares(cats: list[str], values: list[float], percent: bool) -> tuple[float, dict[str, float]]:
    total = 100.0 if percent else float(sum(values)) or 1.0
    return total, {c: round(v if percent else 100 * v / total, 1) for c, v in zip(cats, values)}


def _num(v: float) -> str:
    return f"{v:g}"


def plain(g: str, cats: list[str], values: list[float], percent: bool) -> str:
    """The category's place in the chart, said from its numbers: the fallback when GPT cannot write the card."""
    total, share = _shares(cats, values, percent)
    ranked = sorted(zip(cats, values), key=lambda p: -p[1])
    v = dict(zip(cats, values))[g]
    rank = 1 + sum(1 for _, x in ranked if x > v)          # a tie shares its place
    unit = "%" if percent else ""
    size = f"{_num(v)}%" if percent else f"{_num(v)} of {_num(total)} articles ({_num(share[g])}%)"
    lead, lead_v = ranked[0]
    if rank == 1:
        rest = [(c, x) for c, x in ranked if c != g]
        where = (f"It leads this chart, ahead of {rest[0][0]} ({_num(rest[0][1])}{unit})." if rest
                 else "It is the whole of this chart.")
    elif share[g] < SMALL_SHARE:
        where = f"A small share next to {lead} ({_num(lead_v)}{unit}): too small to change the answer."
    else:
        where = f"Second only to {lead}." if rank == 2 else f"It ranks {rank} of {len(ranked)}, behind {lead}."
    return f"{size}. {where}"


def _allowed(cats: list[str], values: list[float], percent: bool) -> set[str]:
    total, share = _shares(cats, values, percent)
    return ({_num(v) for v in values} | {_num(total)} | {_num(s) for s in share.values()}
            | {str(round(s)) for s in share.values()} | {str(i) for i in range(1, len(cats) + 1)})


def readings(llm, question: str, title: str, cats: list[str], values: list[float], percent: bool,
             missing: list[str]) -> dict[str, str]:
    """{category: card text} for each of `missing`: GPT's reading where every number it uses is the chart's,
    else the plain one."""
    out = {g: plain(g, cats, values, percent) for g in missing}
    if llm is None:
        return out
    total, share = _shares(cats, values, percent)
    chart = "; ".join(f"{c}: {_num(v)}%" if percent else f"{c}: {_num(v)} of {_num(total)} ({_num(share[c])}%)"
                      for c, v in zip(cats, values))
    try:
        reply = llm.chat([{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": f"Research question: {question}\nChart: {title}\n"
                                                      f"Categories: {chart}\nWrite cards for: {', '.join(missing)}"}])
        cards = extract_json_object(reply or "").get("cards") or {}
    except Exception as e:          # the plain reading stands
        logger.warning("count reading failed: %s", e)
        return out
    allowed = _allowed(cats, values, percent)
    for g in missing:
        text = str(cards.get(g) or "").strip()
        if text and all(n in allowed for n in _NUMBER.findall(text)):
            out[g] = text
    return out
