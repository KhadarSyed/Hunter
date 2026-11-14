"""Meltwater-style Boolean queries evaluated on an article's text, in Python (no model call).

Grammar, tightest first: a term ("phrase", word, word* wildcard, title:/headline: term) or a (bracketed group);
NOT (also binary: `A NOT B` is A AND NOT B); AND, NEAR/n (read as AND: the words only have to co-occur) and two terms
side by side (Meltwater's implicit AND); OR. Operators are upper case: "not" inside a phrase is a word.

Before this, matching OR'ed every term of a query and read every term after a NOT as an exclusion, so a brand name
alone matched an "AND celebrity chefs" question and `("Foxwoods" NOT (casino ...))` inside a NOT block excluded
Foxwoods itself (project 41)."""
from __future__ import annotations

import re
from functools import lru_cache

from ...agents.question_dimensions import keyword_hits

_TOKEN = re.compile(r'\s*(?:(\()|(\))|((?:title|headline):)?"([^"]*)"(?:~\d+)?|((?:title|headline):)?([^\s()"]+))')
_NEAR = re.compile(r"^NEAR(/\d+)?$")


def _tokens(query: str) -> list[tuple]:
    out, pos, query = [], 0, query.strip()
    while pos < len(query):
        m = _TOKEN.match(query, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot read the query at: {query[pos:pos + 30]!r}")
        pos = m.end()
        lp, rp, f1, phrase, f2, word = m.groups()
        if lp or rp:
            out.append(("(",) if lp else (")",))
        elif phrase is not None:
            if phrase.strip():
                out.append(("t", phrase.strip(), bool(f1)))
        elif word in ("AND", "OR", "NOT") or _NEAR.match(word):
            out.append(("op", "AND" if _NEAR.match(word) else word))
        else:
            out.append(("t", word, bool(f2)))
    return out


class _Parser:
    def __init__(self, tokens: list[tuple]):
        self.t, self.i = tokens, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        node = self.or_()
        if self.peek() is not None:
            raise ValueError("unexpected text after the end of the query")
        return node

    def or_(self):
        nodes = [self.and_()]
        while self.peek() == ("op", "OR"):
            self.take()
            nodes.append(self.and_())
        return nodes[0] if len(nodes) == 1 else ("or", nodes)

    def and_(self):
        nodes = [self.unary()]
        while (tok := self.peek()) is not None and tok != ("op", "OR") and tok != (")",):
            if tok == ("op", "AND"):
                self.take()
            nodes.append(self.unary())          # `A NOT B` lands here: unary() reads the NOT
        return nodes[0] if len(nodes) == 1 else ("and", nodes)

    def unary(self):
        if self.peek() == ("op", "NOT"):
            self.take()
            return ("not", self.unary())
        return self.atom()

    def atom(self):
        tok = self.take()
        if tok == ("(",):
            node = self.or_()
            if self.take() != (")",):
                raise ValueError("a bracket is not closed")
            return node
        if tok and tok[0] == "t":
            return tok
        raise ValueError(f"expected a term, got {tok!r}")


@lru_cache(maxsize=256)
def parse(query: str):
    """The query's tree, or None when it cannot be read (the caller falls back to plain term matching)."""
    try:
        return _Parser(_tokens(query or "")).parse() if (query or "").strip() else None
    except ValueError:
        return None


def matches(node, text: str, title: str = "") -> bool:
    kind = node[0]
    if kind == "t":
        return bool(keyword_hits(title if node[2] else text, [node[1]]))
    if kind == "not":
        return not matches(node[1], text, title)
    if kind == "and":
        return all(matches(n, text, title) for n in node[1])
    return any(matches(n, text, title) for n in node[1])
