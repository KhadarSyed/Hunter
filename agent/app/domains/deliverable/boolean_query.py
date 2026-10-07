"""Local evaluation of Meltwater Boolean queries: AND / OR / NOT, quoted phrases, parentheses, `*` wildcards
and NEAR/n (co-occurrence within n words). Adjacent terms are an implicit AND. A malformed query matches
nothing rather than raising."""
from __future__ import annotations

import re

_TOKEN = re.compile(r'"[^"]*"|\(|\)|NEAR/\d+|AND|OR|NOT|[^\s()"]+')
_WORD = re.compile(r"[\w']+")     # Unicode letters and digits: L'Oréal, Ésika; "-" and "&" split words
_RIGHT_QUOTE = "’"


class _Malformed(ValueError):
    pass


def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower().replace(_RIGHT_QUOTE, "'"))


def _term_parts(term: str) -> list[str]:
    """Tokenised exactly like the text, so skin-care, J&J and K-beauty become phrases that match it; a trailing
    `*` stays on the last word as a wildcard."""
    parts = []
    for chunk in term.strip('"').split():
        words = _words(chunk.rstrip("*"))
        if chunk.endswith("*") and words:
            words[-1] += "*"
        parts += words
    return parts


def _hit(word: str, part: str) -> bool:
    if part.endswith("*"):
        return word.startswith(part[:-1])
    return word == part


def _term_positions(term: str, words: list[str]) -> list[int]:
    parts = _term_parts(term)
    if not parts:
        return []
    return [i for i in range(len(words) - len(parts) + 1)
            if all(_hit(words[i + k], parts[k]) for k in range(len(parts)))]


class _Parser:
    def __init__(self, tokens: list[str], words: list[str]):
        self.t, self.i, self.words = tokens, 0, words

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise _Malformed("unexpected end")
        self.i += 1
        return tok

    def parse_or(self):
        left = self.parse_and()
        while self.peek() == "OR":
            self.take()
            right = self.parse_and()
            left = left or right
        return left

    def parse_and(self):
        left = self.parse_unary()
        while self.peek() not in (None, "OR", ")"):
            if self.peek() == "AND":
                self.take()
            right = self.parse_unary()
            left = left and right
        return left

    def parse_unary(self):
        if self.peek() == "NOT":
            self.take()
            return not self.parse_unary()
        return self.parse_atom()

    def parse_atom(self):
        tok = self.peek()
        if tok == "(":
            self.take()
            value = self.parse_or()
            if self.take() != ")":
                raise _Malformed("missing )")
            return value
        if tok in (None, ")", "AND", "OR") or tok.startswith("NEAR/"):
            raise _Malformed(f"unexpected {tok}")
        term = self.take()
        positions = _term_positions(term, self.words)
        if (self.peek() or "").startswith("NEAR/"):
            n = int(self.take().split("/")[1])
            other = self.take()
            if other in ("(", ")", "AND", "OR", "NOT") or other.startswith("NEAR/"):
                raise _Malformed("NEAR needs a term")
            others = _term_positions(other, self.words)
            return any(abs(a - b) <= n for a in positions for b in others)
        return bool(positions)


def matches(query: str, text: str) -> bool:
    query = (query or "").strip()
    if not query or query.count('"') % 2:
        return False
    try:
        parser = _Parser(_TOKEN.findall(query), _words(text))
        result = parser.parse_or()
        if parser.peek() is not None:
            raise _Malformed("trailing tokens")
        return bool(result)
    except (_Malformed, ValueError, IndexError):
        return False
