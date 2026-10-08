"""Question dimensions: what a research question asks to break conversation volume down by.

"Which sports generate the most injury conversations?" asks for a by-sport count; "the breakdown of injury types
by sport" asks for two dimensions and their cross-tab. The candidate values come from the question's own Meltwater
query (its OR groups, minus the brand group and NOT exclusions) and from lists written in the question text; the LLM
only labels the dimensions and groups synonyms ("football" and "5-a-side" are Soccer) -- it can never add a term that
is in neither, so every tag stays traceable to the brief. A question that asks for a categorisation no keyword list
expresses ("which experts are cited") gets a judged dimension instead: values the LLM names, tagged by the LLM per
article, never by keywords. Without an LLM the query groups are used as they are.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

MAX_DIMENSIONS = 3
MAX_VALUES = 15
MAX_TERMS = 12
MAX_TERM_CHARS = 40
_INNER_GROUP = re.compile(r"\(([^()]*)\)")
_TERM = re.compile(r'"([^"]+)"|([^\s()"]+)')
_OPERATORS = {"OR", "AND", "NOT", "NEAR"}
_QUESTION_PAREN = re.compile(r"\(([^()]*,[^()]*)\)")
# One bounded character class (no nested quantifiers): linear time on any question
_QUESTION_LIST = re.compile(r"\b(?:for|including|such as|like|across)\s+([^?.;:()]{3,240})", re.IGNORECASE)
_LIST_END = re.compile(r"\b(?:and|or)\s+[\w-]+", re.IGNORECASE)
MAX_QUESTION_CHARS = 600
_BREAKDOWN_ASK = re.compile(r"\bwhich\b|\bbreakdown\b|\bsplit\b|\bby\s+(?:sport|activit|injur|type|categor|product|"
                            r"channel|platform|region|country|retailer|occasion|author)|\bwhat\s+(?:sports?|types?|kinds?|"
                            r"activities|products?|categories)\b", re.IGNORECASE)
_NEAR = re.compile(r"^near/\d+$", re.IGNORECASE)
_SAFE_TERM = re.compile(r"^[\w\- ']+\*?$")


@dataclass(frozen=True)
class Value:
    name: str
    terms: tuple[str, ...]


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    values: tuple[Value, ...]
    judged: bool = False      # categories the LLM judges per article (expert type, purchase driver): no keywords


def _norm(term: str) -> str:
    return re.sub(r"[^a-z0-9]", "", term.lower())


def _base(term: str) -> str:
    return term.rstrip("*").strip().lower()


def _display(term: str) -> str:
    text = _base(term)
    return text[:1].upper() + text[1:]


def _group_terms(content: str) -> list[str] | None:
    """Terms of a pure OR group, or None when the group mixes in AND/NOT (it is a clause, not a list)."""
    terms, ops = [], []
    for m in _TERM.finditer(content):
        word = m.group(1) or m.group(2)
        if m.group(2) and (word.upper() in _OPERATORS or _NEAR.match(word)):
            ops.append(word.upper())
        else:
            terms.append(word.strip().lower())
    # every pair of terms joined by OR: NEAR/n, AND and adjacent terms (an implicit AND) are clauses, not lists
    if len(terms) < 2 or any(op != "OR" for op in ops) or len(ops) != len(terms) - 1:
        return None
    return terms


def _is_brand_group(terms: list[str], brands: list[str]) -> bool:
    keys = {_norm(b) for b in brands if _norm(b)}
    return any(_norm(t.rstrip("*")) in keys for t in terms)


def _negated_spans(query: str) -> list[tuple[int, int]]:
    """(start, end) of every parenthesised block that follows NOT, nested blocks included."""
    spans, stack = [], []
    for i, ch in enumerate(query):
        if ch == "(":
            stack.append((i, query[:i].rstrip().upper().endswith("NOT")))
        elif ch == ")" and stack:
            start, negated = stack.pop()
            if negated:
                spans.append((start, i))
    return spans


def query_groups(query: str, brands: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    query = query or ""
    negated = _negated_spans(query)
    for m in _INNER_GROUP.finditer(query):
        if any(a <= m.start() and m.end() - 1 <= b for a, b in negated):
            continue
        terms = _group_terms(m.group(1))
        if terms and not _is_brand_group(terms, brands) and set(terms) not in [set(g) for g in groups]:
            groups.append(terms)
    return groups


def _stem(word: str) -> str:
    word = word.strip().lower()
    if " " in word:
        return word
    if word.endswith(("ches", "shes", "xes", "sses")):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "is", "us")):
        word = word[:-1]
    return word + "*"


def _split_list(text: str) -> list[str]:
    items = re.split(r",|\band\b|\bor\b", text, flags=re.IGNORECASE)
    return [i.strip() for i in items if i.strip() and len(i.split()) <= 3]


def _question_groups(question: str) -> list[tuple[list[str], bool]]:
    """(terms, is_qualifier): a parenthetical list ("injuries (cuts, scrapes)") qualifies the question's scope;
    a "for a, b and c" list names what it asks about."""
    groups = []
    question = (question or "")[:MAX_QUESTION_CHARS]
    for pattern, qualifier in ((_QUESTION_PAREN, True), (_QUESTION_LIST, False)):
        for m in pattern.finditer(question):
            text = m.group(1)
            if pattern is _QUESTION_LIST:
                end = _LIST_END.search(text)           # a list ends at its "and/or x"
                if not end or "," not in text[:end.start()]:
                    continue
                text = text[:end.end()]
            items = [_stem(i) for i in _split_list(text)]
            if len(items) >= 2:
                groups.append((items, qualifier))
    return groups


def _merge(groups: list[list[str]], extra: list[tuple[list[str], bool]]) -> list[list[str]]:
    """A question list that overlaps a query group by half or more is the same dimension: union by base word.
    What the question asks about comes first; a dimension it only qualifies with (a parenthetical) comes last."""
    merged = [(list(g), False) for g in groups]
    for new, qualifier in extra:
        new_bases = {_base(t) for t in new}
        hit = next((i for i, (g, _) in enumerate(merged)
                    if len(new_bases & {_base(t) for t in g}) * 2 >= len(new_bases)), None)
        if hit is None:
            merged.append((new, qualifier))
            continue
        target, was = merged[hit]
        have = {_base(t) for t in target}
        merged[hit] = (target + [t for t in new if _base(t) not in have], was or qualifier)
    return [g for g, _ in sorted(merged, key=lambda gq: gq[1])]


def _fallback_dimension(i: int, terms: list[str]) -> Dimension:
    values = tuple(Value(name=_display(t), terms=(t,)) for t in terms[:MAX_VALUES])
    names = [v.name for v in values]
    label = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
    return Dimension(key=_slug(label, set()) if label else f"dim{i}", label=label, values=values)


def from_query_and_question(question: str, query: str, brands: list[str]) -> list[Dimension]:
    groups = _merge(query_groups(query, brands), _question_groups(question))
    return [_fallback_dimension(i, g) for i, g in enumerate(groups[:MAX_DIMENSIONS], start=1)]


def _slug(label: str, used: set[str]) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:30] or "dimension"
    while key in used:
        key += "_"
    used.add(key)
    return key


MIN_TERM_CHARS = 3


def _allowed(term, known: set[str], source_text: str) -> bool:
    if not (isinstance(term, str) and 0 < len(term) <= MAX_TERM_CHARS and _SAFE_TERM.match(term.strip())):
        return False
    base = _base(term)
    if base in known:
        return True
    tail = "" if term.strip().endswith("*") else r"(?![\w-])"
    return len(base) >= MIN_TERM_CHARS and re.search(rf"(?<![\w-]){re.escape(base)}{tail}", source_text) is not None


def _validate(data, base: list[Dimension], source_text: str) -> list[Dimension]:
    known = {_base(t) for d in base for v in d.values for t in v.terms}
    out, used = [], set()
    for raw in (data.get("dimensions") or [])[:MAX_DIMENSIONS] if isinstance(data, dict) else []:
        if not isinstance(raw, dict) or not str(raw.get("label") or "").strip():
            continue
        label = str(raw["label"]).strip()[:40]
        raw_values = [v for v in (raw.get("values") or [])[:MAX_VALUES] if isinstance(v, dict)]
        if raw_values and all(v.get("terms") == [] for v in raw_values):
            names = list(dict.fromkeys(str(v.get("name") or "").strip()[:40] for v in raw_values))
            values = tuple(Value(name=n, terms=()) for n in names if n)
            if values:
                out.append(Dimension(key=_slug(label, used), label=label, values=values, judged=True))
            continue
        values = []
        for v in (raw.get("values") or [])[:MAX_VALUES]:
            if not isinstance(v, dict) or not str(v.get("name") or "").strip():
                continue
            raw_terms = v.get("terms") if isinstance(v.get("terms"), list) else []
            terms = tuple(t.strip().lower() for t in raw_terms[:MAX_TERMS] if _allowed(t, known, source_text))
            if terms:
                values.append(Value(name=str(v["name"]).strip()[:40], terms=terms))
        if values:
            out.append(Dimension(key=_slug(label, used), label=label, values=tuple(values)))
    return out


def derive(llm, question: str, query: str, brands: list[str]) -> list[Dimension]:
    """Label and group the question's dimensions with the LLM; the query groups when it is unreachable or fails."""
    return derive_with_source(llm, question, query, brands)[0]


def derive_with_source(llm, question: str, query: str, brands: list[str]) -> tuple[list[Dimension], str]:
    """(dimensions, "llm" when the LLM answered -- even with none -- else "query")."""
    base = from_query_and_question(question, query, brands)
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return base, "query"
    messages = [
        {"role": "system", "content": "A media-research question asks to break conversation volume down by one or "
         "more dimensions (e.g. sport, injury type, product, retailer, author type). From the QUESTION and the "
         "CANDIDATE term groups taken from its search query, return the dimensions the question asks about, each "
         "with a short label and its values; a value groups synonym terms (\"football\" and \"5-a-side\" are one "
         "value, Soccer). Use only terms from the candidates or words written in the question. Drop generic "
         "catch-all terms. List first the dimension the question asks 'which/what' about; a parenthetical list that only "
         "qualifies its scope comes last. When the question asks for a categorisation no keyword list captures (who is cited, "
         "expert type, purchase driver, occasion), add a judged dimension: its values are the categories, each "
         "with \"terms\": [] -- they are tagged by reading each article. "
         f"At most {MAX_DIMENSIONS} dimensions, {MAX_VALUES} values each. Return JSON only: "
         "{\"dimensions\": [{\"label\": \"...\", \"values\": [{\"name\": \"...\", \"terms\": [\"...\"]}]}]}"},
        {"role": "user", "content": f"QUESTION: {question}\nCANDIDATES: "
         f"{json.dumps([[t for v in d.values for t in v.terms] for d in base])}"},
    ]
    try:
        dims = _validate(json.loads(llm.chat(messages, format_json=True)), base, f"{question}\n{query}".lower())
    except Exception as e:  # noqa: BLE001 -- any LLM failure means the deterministic dimensions
        logger.warning("question dimensions: LLM labelling failed (%s); using query groups", type(e).__name__)
        return base, "query"
    return (dims or base), "llm"


@lru_cache(maxsize=4096)
def _pattern(term: str) -> re.Pattern:
    wild = term.endswith("*")
    body = r"\s+".join(re.escape(part) for part in _base(term).split())
    return re.compile(rf"(?<![\w-]){body}" + (r"[\w-]*" if wild else r"(?![\w-])"), re.IGNORECASE)


def keyword_hits(text: str, terms: list[str]) -> list[str]:
    """The search terms the text actually contains, in the query's order (a trailing * matches word endings)."""
    return [t for t in dict.fromkeys(t for t in terms if t) if _pattern(t).search(text or "")]


def tag_text(text: str, dims: list[Dimension]) -> dict[str, list[str]]:
    """The values each dimension's terms name in the text; a longer match wins over a shorter one it contains
    ("trail running" is Trail running, not also Running)."""
    out: dict[str, list[str]] = {}
    for dim in dims:
        if dim.judged:
            out[dim.key] = []
            continue
        spans = []
        for vi, value in enumerate(dim.values):
            for term in value.terms:
                spans += [(m.start(), m.end(), vi) for m in _pattern(term).finditer(text or "")]
        taken: list[tuple[int, int]] = []
        hits: set[int] = set()
        for start, end, vi in sorted(spans, key=lambda s: -(s[1] - s[0])):
            if all(end <= a or start >= b for a, b in taken):
                taken.append((start, end))
                hits.add(vi)
        out[dim.key] = [dim.values[i].name for i in sorted(hits)]
    return out


def to_json(dims: list[Dimension]) -> list[dict]:
    return [{"key": d.key, "label": d.label, "judged": d.judged,
             "values": [{"name": v.name, "terms": list(v.terms)} for v in d.values]} for d in dims]


def from_json(data) -> list[Dimension]:
    return [Dimension(key=d["key"], label=d["label"], judged=bool(d.get("judged")),
                      values=tuple(Value(name=v["name"], terms=tuple(v["terms"])) for v in d["values"]))
            for d in data or []]


def asks_breakdown(question: str) -> bool:
    """Whether the question asks which value leads or how volume splits ("which sports", "breakdown by sport"),
    rather than a share or a tone."""
    return bool(_BREAKDOWN_ASK.search((question or "")[:MAX_QUESTION_CHARS]))


def valid_names(values, dim: Dimension) -> list[str] | None:
    """The tagged values that name one of the dimension's values; None when the tag is missing, malformed or
    stale (none of its names exist any more), so callers fall back to keywords."""
    if not isinstance(values, list):
        return None
    names = {v.name for v in dim.values}
    valid = [n for n in values if isinstance(n, str) and n in names]
    return valid if valid or not values else None
