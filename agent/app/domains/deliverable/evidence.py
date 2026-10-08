"""Evidence: the articles a deck may cite, quote or screenshot.

An article counts as evidence for the primary brand only when it names the brand (or one of its products)
literally -- "now they need a band-aid, and quickly" is a figure of speech, not Band-Aid -- and it is ranked by how
much of the question's intent it carries (the sport, the injury type...). Competitor evidence is kept apart so the
deck can show it on its own slides. An enrichment flag (brand_mention = "figurative") overrides the keywords.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ...agents import question_dimensions as qd
from .analytics import _values_of
from .engine_types import EngineRow

WINDOW = 40          # characters around a match read for an idiom
_IDIOM_BEFORE = re.compile(r"(?:rip|ripping|ripped|tear|tearing|pull|pulling)\s+(?:it\s+)?(?:off\s+)?(?:the|a)\s+$|"
                           r"(?:need|needs|needed|just|only|merely|temporary|quick|another|like|than)\s+(?:a\s+)?$",
                           re.IGNORECASE)
_IDIOM_AFTER = re.compile(r"^\s*(?:off\b|solutions?\b|fix(?:es)?\b|approach(?:es)?\b|measures?\b|responses?\b|"
                          r"polic(?:y|ies)\b|remed(?:y|ies)\b|jobs?\b|on\s+(?:a|the)\s+(?:problem|issue|economy|wound))",
                          re.IGNORECASE)
_LITERAL_AFTER = re.compile(r"^\s*(?:®|brand\b|bandages?\b|plasters?\b)", re.IGNORECASE)


@dataclass(frozen=True)
class Brand:
    name: str
    terms: tuple[str, ...]
    primary: bool = False


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _original_case(term: str, query: str) -> str:
    m = re.search(re.escape(term), query, re.IGNORECASE)
    return m.group(0) if m else term.title()


def brand_set(primary: str, competitors: list[str], queries: list[str], products: list[str] = ()) -> list[Brand]:
    """The primary brand (all its spellings and products) and every competitor named in the brief or in the
    queries' brand clause."""
    names = [primary] + [c for c in competitors if _norm(c) != _norm(primary)]
    terms: dict[str, list[str]] = {n: [n.lower()] for n in names}
    keys = {_norm(n): n for n in names}
    for query in queries:
        for group in qd.query_groups(query, []):
            if not any(_norm(t.rstrip("*")) in keys for t in group):
                continue                     # not the brand clause
            for t in group:
                t = t.rstrip("*")
                owner = keys.get(_norm(t))
                if owner is None:
                    owner = _original_case(t, query)
                    keys[_norm(t)] = owner
                    terms[owner] = [owner.lower()]
                if t not in terms[owner]:
                    terms[owner].append(t)
    terms[primary] += [p.lower() for p in products if p and p.lower() not in terms[primary]]
    return [Brand(name=n, terms=tuple(ts), primary=(n == primary)) for n, ts in terms.items()]


@lru_cache(maxsize=1024)
def _term_pattern(term: str) -> re.Pattern:
    parts = [re.escape(p) for p in re.split(r"[\s-]+", term) if p]
    return re.compile(r"(?<![\w-])" + r"[\s-]?".join(parts) + r"(?![\w-])", re.IGNORECASE)


def _figurative(text: str, start: int, end: int) -> bool:
    before, after = text[max(0, start - WINDOW):start], text[end:end + WINDOW]
    if _LITERAL_AFTER.match(after):
        return False
    return bool(_IDIOM_BEFORE.search(before) or _IDIOM_AFTER.match(after))


def mentions(text: str, brands: list[Brand]) -> list[str]:
    """Brands named literally in the text, in brand order (primary first)."""
    out = []
    for b in brands:
        if any(not _figurative(text, m.start(), m.end())
               for t in b.terms for m in _term_pattern(t).finditer(text or "")):
            out.append(b.name)
    return out


def row_brands(row: EngineRow, brands: list[Brand]) -> list[str]:
    if getattr(row, "brand_mention", "") == "figurative":
        return []
    return mentions(f"{row.article.title}\n{row.article.text}", brands)


def rank(rows: list[EngineRow], brands: list[Brand], dims: list[qd.Dimension], who: str = "primary") -> list[EngineRow]:
    """Rows that name the primary brand (who="primary") or a competitor (who="competitor"), the ones carrying
    more of the question's dimensions first, then by reach."""
    primary = next((b.name for b in brands if b.primary), "")
    keep = []
    for row in rows:
        named = row_brands(row, brands)
        if (who == "primary" and primary in named) or (who == "competitor" and any(n != primary for n in named)):
            matched = sum(1 for d in dims if not d.judged and _values_of(row, d))
            keep.append((matched, row.article.reach, row))
    keep.sort(key=lambda k: (-k[0], -k[1]))
    return [row for _, _, row in keep]


def for_question(rows: list[EngineRow], brands: list[Brand], dims: list[qd.Dimension]) -> list[EngineRow]:
    """What a question's insights and verbatims may use: the brand's own evidence when the data has any; for a
    category study (or a brand the coverage never names) the articles that best carry the question's intent."""
    primary = rank(rows, brands, dims, "primary")
    if primary:
        return primary
    scored = [(sum(1 for d in dims if not d.judged and _values_of(r, d)), r.article.reach, r) for r in rows
              if getattr(r, "brand_mention", "") != "figurative"]
    scored.sort(key=lambda k: (-k[0], -k[1]))
    return [r for _, _, r in scored]
