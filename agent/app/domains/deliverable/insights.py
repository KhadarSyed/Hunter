"""LLM-drafted insights, accepted only if every number and citation checks out."""
from __future__ import annotations

import json
import logging
import re
from decimal import ROUND_HALF_UP, Decimal

from .citations import CitationRegistry
from .ingest import Article

logger = logging.getLogger(__name__)
_NUM = re.compile(r"\d+(?:\.\d+)?")
_YEARS = {"2024", "2025", "2026"}
MAX_CITES = 3


def _half_up(n: str) -> str:
    """Conventional rounding (2.5 → 3); Python's round() would give 2."""
    return str(Decimal(n).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def allowed_numbers(facts: list[str]) -> set[str]:
    """Exact numbers only; rounded forms are licensed through allowed_pairs, i.e. only with their unit."""
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
    pairs = {p for f in facts for p in _pairs(f)}
    return pairs | {(_half_up(n), u) for n, u in pairs if "." in n}     # '60%' from 60.2%, never bare '60'


_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
          "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
_NUM_WORD = re.compile(r"\b(" + "|".join(_WORDS[2:]) + r")\b", re.IGNORECASE)   # 'one'/'zero' are prose


def _digits(text: str) -> str:
    """'Four articles' → '4 articles' so spelled-out counts get the same number and unit checks."""
    return _NUM_WORD.sub(lambda m: str(_WORDS.index(m.group(1).lower())), text)


def validate_insight(text: str, cites: list[int], allowed: set[str], candidate_ids: set[int],
                     pairs: set[tuple[str, str]] | None = None) -> str | None:
    text = _digits(text)
    if not cites or not set(cites) <= candidate_ids:
        return "citation missing or outside candidate set"
    unit_ok = {n for n, u in _pairs(text) if pairs is not None and (n, u) in pairs}
    bad = [n for n in _NUM.findall(text) if n not in allowed and n not in unit_ok]
    if bad:
        return f"number(s) not in facts: {bad}"
    if pairs is not None:
        wrong_unit = [f"{n} {u}" for n, u in _pairs(text) if (n, u) not in pairs]
        if wrong_unit:
            return f"number(s) with a unit the facts don't state: {wrong_unit}"
    return None


def _fallback(facts: list[str], candidates: list[Article], registry: CitationRegistry) -> list[dict]:
    return _backfill([], facts, candidates, registry, 1)


_PEAK = re.compile(r"^Peak (\d+)(?: for (.+?))?:")
_OUTLET = re.compile(r"^Top outlet for (.+?):")
_LEADS = ("Top outlet", "Retailer", "Topic")


def _fact_headline(fact: str) -> str:
    peak = _PEAK.match(fact)
    if peak:
        return f"{peak.group(2)} peak #{peak.group(1)}" if peak.group(2) else f"Peak month #{peak.group(1)}"
    outlet = _OUTLET.match(fact)
    if outlet:
        return f"Top outlet: {outlet.group(1)}"
    if "sentiment" in fact.lower() and ":" in fact:
        return "Sentiment split"
    for verb in (" mentioned in ", " featured in "):
        if verb in fact:
            return fact.split(verb)[0]
    lead = next((l for l in _LEADS if fact.startswith(l)), None)
    return lead or "Key finding"


_MONTH = re.compile(r":\s*([A-Z][a-z]{2}-\d{2})\b")
_OUTLET_NAME = re.compile(r"^Top outlet for .+?:\s*(.+?) with \d")


def _norm(s: str) -> str:
    return " ".join(s.replace("’", "'").casefold().split())


def _fact_evidence(fact: str, candidates: list[Article]) -> list[Article]:
    """Articles that actually illustrate this fact. Entity facts (peak month, outlet, brand/celebrity) only cite
    matching articles — none matching means no card; aggregate facts cite the section's example articles."""
    if _PEAK.match(fact):
        month = _MONTH.search(fact)
        return [a for a in candidates if month and a.date and a.date.strftime("%b-%y") == month.group(1)][:2]
    outlet = _OUTLET_NAME.match(fact)
    if outlet:
        return [a for a in candidates if _norm(a.outlet) == _norm(outlet.group(1))][:2]
    for verb in (" mentioned in ", " featured in "):
        if verb in fact:
            subject = _norm(fact.split(verb)[0])
            return [a for a in candidates if subject in _norm(f"{a.title} {a.text}")][:2]
    return candidates[:2]


def _lead_value(fact: str) -> set[str]:
    """The fact's headline number (first number carrying a unit), plus its rounded form."""
    lead = next((n for n, u in _NUM_UNIT.findall(fact) if u and u.lower() in _UNITS and n not in _YEARS), None)
    return {lead, _half_up(lead)} if lead else set()


def _backfill(kept: list[dict], facts: list[str], candidates: list[Article], registry: CitationRegistry,
              n: int, skip: set[str] | None = None) -> list[dict]:
    """Top a section up to n insights with deterministic fact cards (true by construction), skipping facts whose
    value an accepted insight already states (or the chart already shows, `skip`) and facts with no article that
    illustrates them."""
    out = list(kept)
    stated = set(_NUM.findall(_digits(" ".join(k["text"] for k in kept)))) | set(skip or ())
    for fact in facts:
        if len(out) >= n:
            break
        if _lead_value(fact) & stated:
            continue
        evidence = _fact_evidence(fact, candidates)
        if not evidence:
            continue
        text = fact.rstrip(".") + "."
        out.append({"headline": _fact_headline(fact), "text": text[:1].upper() + text[1:],
                    "citations": [registry.cite(a) for a in evidence]})   # register only when used
        stated |= set(_NUM.findall(fact))
    return out


def _entity_mismatch(text: str, cites: list[int], local: dict[int, Article], entities: list[str]) -> str | None:
    """If the insight names known entities, at least one cited article must mention one of them."""
    named = [e for e in entities if e and _norm(e) in _norm(text)]
    if not named:
        return None
    if any(_norm(e) in _norm(f"{local[c].title} {local[c].text} {local[c].outlet}") for c in cites for e in named):
        return None
    return f"cited articles don't mention {', '.join(named)}"


def draft_section(section: str, facts: list[str], candidates: list[Article], registry: CitationRegistry,
                  llm, n_insights: int = 3, entities: list[str] | None = None,
                  avoid: list[str] | None = None) -> list[dict]:
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
        {"role": "system", "content": "You write insights for a media-research deck, the way a senior media analyst "
         "does. The chart beside each insight already shows the shares and counts, so an insight never restates the "
         "headline figure; it explains WHY the pattern exists -- its drivers. Name the specific outlets, brands, products, people, "
         "events and months from the ARTICLES that drive it (e.g. 'The December peak came from holiday gift-guide "
         "round-ups in USA Today and Living Rich With Coupons, featuring Aveeno Baby and Tom's of Maine'), then end "
         "with the so-what for the client: the opportunity, risk or action it points to. Each insight covers a "
         "different driver; never repeat a point or a figure another insight makes. Never mention article ids in the "
         "text (no '(article 2)'); name the outlet instead -- the citations list carries the ids. Use at most one number per "
         "insight, and only as evidence for a driver. Each insight is a complete thought, never a bare 'X of Y "
         "articles'. Use ONLY numbers that appear "
         "in FACTS, with the same unit. Every insight must cite 1-3 article ids from ARTICLES: for a claim about "
         "specific coverage, cite the articles that state it; for a statistic from FACTS, cite articles that are "
         "examples of what is being counted. never leave citations empty. Comparisons ('more than', 'fewer than', "
         "'most', 'all', 'each') must hold exactly for every item named — e.g. never put a brand with 10 articles in "
         "a 'fewer than 10' list. Do not exaggerate: words like 'common', 'majority', 'dominates' must match the "
         "numbers (4 of 17 is about a quarter, not 'common'). Add no time qualifier the FACTS don't give "
         "(late/early, 'summer'); a month is just the month. Keep one figure per clause and never imply a monthly "
         "count equals an overall share. Return JSON only."},
        {"role": "user", "content": f"Section: {section}\nFACTS:\n" + "\n".join(f"- {f}" for f in facts) +
         f"\nARTICLES:\n{json.dumps(arts, ensure_ascii=False)}\n" +
         ("ALREADY SAID on this question (the reader has seen these; make a different point, do not restate "
          "them):\n" + "\n".join(f"- {a}" for a in avoid) + "\n" if avoid else "") +
         f"Write {n_insights} insights as "
         '{"insights":[{"headline":"<=10 words: the takeaway, not the headline figure","text":"<=35 words: '
         'the named drivers behind the finding, then the so-what for the client","citations":[ids]}]}'},
    ]
    headline_figs = _headline_figures(facts)
    try:
        reply = llm.chat(messages, format_json=True)
        valid, rejected = _screen(section, json.loads(reply), allowed, pairs, local, entities or [], headline_figs)
    except (json.JSONDecodeError, RuntimeError) as e:
        logger.warning("insight drafting for %s failed (%s); using fallback", section, e)
        return _fallback(facts, candidates, registry)
    if rejected and len(valid) < n_insights:
        # one repair round: show the model exactly why each insight failed and ask for replacements
        feedback = "\n".join(f"- \"{t}\" — rejected: {why}" for t, why in rejected)
        repair = messages + [{"role": "assistant", "content": reply},
                             {"role": "user", "content": f"These insights were rejected:\n{feedback}\nWrite "
                              f"{n_insights - len(valid)} replacement insights that fix these problems, same JSON "
                              "format and rules."}]
        try:
            more, _ = _screen(section, json.loads(llm.chat(repair, format_json=True)), allowed, pairs, local,
                              entities or [], headline_figs, {f for h, t, _ in valid for f in _figures(f"{h} {t}")})
            seen = {t for _, t, _ in valid}
            valid += [v for v in more if v[1] not in seen]          # the model may repeat an accepted insight
        except (json.JSONDecodeError, RuntimeError) as e:
            logger.warning("insight repair for %s failed (%s)", section, e)
    supported = _verify_claims(section, valid, facts, local, llm)
    shown = [v for i, v in enumerate(valid) if i in supported][:n_insights]   # cap before citing anything
    if len(shown) < n_insights:
        shown += _rescue(section, facts, arts, local, llm, n_insights - len(shown), (avoid or []) +
                         [f"{h}: {t}" for h, t, _ in shown], entities or [], allowed, pairs, headline_figs)
    kept = [{"headline": h, "text": t, "citations": sorted({registry.cite(local[c]) for c in cs})}
            for h, t, cs in shown]
    out = _backfill(kept, facts, candidates, registry, n_insights, skip=headline_figs)
    return out or _backfill(kept, facts, candidates, registry, n_insights)    # never an empty panel


_RESCUE_SYSTEM = (
    "You explain a media-research finding for a client, without numbers: the chart already shows them. Write no "
    "digits and no number words (say 'January', not 'Jan-26'). Explain WHY the pattern in FACTS exists -- name the "
    "outlets, brands, products, people, events and topics from ARTICLES that drive it -- then the so-what for the "
    "client. Every insight cites 1-3 article ids from ARTICLES; never mention ids in the text. Claim only what the "
    "ARTICLES show. Return JSON only.")


def _rescue(section: str, facts: list[str], arts: list[dict], local: dict[int, Article], llm, k: int,
            said: list[str], entities: list[str], allowed: set[str], pairs: set, shown_figs: set[str]) -> list[tuple]:
    """A last, number-free attempt before a fact card stands in: what drove the pattern, and the so-what."""
    messages = [
        {"role": "system", "content": _RESCUE_SYSTEM},
        {"role": "user", "content": f"Section: {section}\nFACTS:\n" + "\n".join(f"- {f}" for f in facts) +
         f"\nARTICLES:\n{json.dumps(arts, ensure_ascii=False)}\n" +
         ("ALREADY SAID (make a different point):\n" + "\n".join(f"- {s}" for s in said) + "\n" if said else "") +
         f'Write {k} insights as {{"insights":[{{"headline":"<=10 words","text":"<=35 words: the named drivers, '
         'then the so-what","citations":[ids]}]}'},
    ]
    try:                       # optional: any failure here leaves the fact card in place, never breaks the deck
        found, _ = _screen(section, json.loads(llm.chat(messages, format_json=True)), allowed, pairs, local,
                           entities, shown_figs)
        found = [v for v in found if not _NUM.search(_digits(_without_names(f"{v[0]} {v[1]}", local)))]
        supported = _verify_claims(section, found, facts, local, llm)
    except Exception as e:
        logger.warning("number-free rescue for %s failed (%s: %s)", section, type(e).__name__, e)
        return []
    return [v for i, v in enumerate(found) if i in supported][:k]


def _without_names(text: str, local: dict[int, Article]) -> str:
    """The text with candidate outlets' names taken out, so the digits of 'Law360' or '9to5Mac' are not read as a
    statistic the facts don't state."""
    for name in {a.outlet for a in local.values() if a.outlet and any(ch.isdigit() for ch in a.outlet)}:
        text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    return text


_TRIVIAL = {"0", "1"}
# The prompt's local article ids ("(articles 2 and 3)") mean nothing to a client; citations carry the sources
_ID_REF = re.compile(r"\s*\((?:e\.g\.,?\s*)?(?:articles?|ids?)\s*#?\d+(?:\s*(?:,|and|&)\s*#?\d+)*\)", re.I)


def _figures(text: str) -> set[str]:
    return {n for n in _NUM.findall(_digits(text)) if n not in _YEARS and n not in _TRIVIAL}


def _headline_figures(facts: list[str]) -> set[str]:
    """The figures the chart and the slide's answer already show (the section's first fact), rounded forms too.
    Off-limits only when the other facts give the insight something else to say."""
    figs = _figures(facts[0]) if facts else set()
    if not figs or not any(_figures(f) - figs for f in facts[1:]):
        return set()
    return figs | {_half_up(n) for n in figs if "." in n}


def _repeats(text: str, shown: set[str], taken: set[str]) -> str | None:
    figs = _figures(text)
    if figs & shown:
        return "restates the headline figure the chart already shows; explain what drives it instead"
    if figs & taken:
        return f"repeats a figure another insight already states: {sorted(figs & taken)}"
    return None


def _screen(section: str, parsed: dict, allowed: set[str], pairs: set, local: dict[int, Article],
            entities: list[str], shown: set[str] | None = None,
            taken: set[str] | None = None) -> tuple[list[tuple], list[tuple[str, str]]]:
    """Split drafted insights into valid (headline, text, local cites) and rejected (text, reason)."""
    valid, rejected = [], []
    taken = set(taken or ())
    for ins in parsed.get("insights", []):
        headline, text = str(ins.get("headline", "")).strip(), _ID_REF.sub("", str(ins.get("text", ""))).strip()
        raw = [int(c) for c in ins.get("citations", []) if str(c).isdigit()]
        cites = [c for c in dict.fromkeys(raw) if c in local][:MAX_CITES]   # drop unknown ids, cap
        checked = _without_names(f"{headline} {text}", local)
        reason = (validate_insight(checked, cites, allowed, set(local), pairs)
                  or _entity_mismatch(f"{headline} {text}", cites, local, entities)
                  or _repeats(checked, shown or set(), taken))
        if reason:
            logger.info("dropped insight in %s: %s", section, reason)
            rejected.append((text, reason))
        else:
            valid.append((headline, text, cites))
            taken |= _figures(f"{headline} {text}")
    return valid, rejected


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
         "follows from supported facts (e.g. 'indicating strong interest') is allowed. Check every comparison or "
         "quantifier ('fewer than 10', 'most', 'each', 'common', 'majority') against the exact FACTS numbers for "
         "every item it covers; one item that breaks it makes the claim unsupported. Check ratio words ('twice', "
         "'double', 'triple', 'x times') by arithmetic on the FACTS numbers (60.2% vs 28.9% is about twice, not "
         "triple). An interpretation must not contradict FACTS (a topic that FACTS rank first is not 'minimal'). "
         "Also judge whether its EVIDENCE articles are relevant to the claim's subject; if none of them is "
         "relevant, mark it unsupported. Return JSON only."},
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
