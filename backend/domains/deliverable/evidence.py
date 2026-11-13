"""Evidence: the articles a deck may cite, quote or screenshot.

An article counts as evidence for the primary brand only when it names the brand (or one of its products)
literally -- "now they need a band-aid, and quickly" is a figure of speech, not Band-Aid -- and it is ranked by how
much of the question's intent it carries (the sport, the injury type...). Competitor evidence is kept apart so the
deck can show it on its own slides. An enrichment flag (brand_mention = "figurative") overrides the keywords.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ...agents import question_dimensions as qd
from .analytics import _values_of
from .engine_types import EngineRow

logger = logging.getLogger(__name__)

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
    names = ([primary] if primary else []) + [c for c in competitors if _norm(c) != _norm(primary)]
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
    if primary:
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


def _fold(text: str) -> str:
    """Accents dropped, so 'EōS Fitness' in an article names the brand 'EoS Fitness'."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")


def mentions(text: str, brands: list[Brand]) -> list[str]:
    """Brands named literally in the text, in brand order (primary first)."""
    out = []
    text = _fold(text)
    for b in brands:
        if any(not _figurative(text, m.start(), m.end())
               for t in b.terms for m in _term_pattern(_fold(t)).finditer(text)):
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


_NOT_AN_ANSWER = {"", "no", "none", "unknown", "false", "n/a"}


def affirmative(value) -> bool:
    return any(str(v).strip().lower() not in _NOT_AN_ANSWER
               for v in (value if isinstance(value, list) else [value]) if v is not None)


def for_question(rows: list[EngineRow], brands: list[Brand], dims: list[qd.Dimension],
                 answer_tag: str = "") -> list[EngineRow]:
    """What a question's insights and verbatims may use: the brand's own evidence when the data has any; for a
    category study (or a brand the coverage never names) the articles that answer the question -- tagged yes on
    its answer tag first, then those naming a brand of the set, then the ones carrying more of its dimensions
    (judged ones by their tags), then reach."""
    primary = rank(rows, brands, dims, "primary")
    if primary:
        return primary

    def score(r: EngineRow) -> tuple:
        answered = bool(answer_tag) and affirmative((r.dynamic_tags or {}).get(answer_tag))
        matched = sum(1 for d in dims if affirmative(_values_of(r, d)))
        return answered, bool(row_brands(r, brands)), matched, r.article.reach

    return sorted((r for r in rows if getattr(r, "brand_mention", "") != "figurative"), key=score, reverse=True)


# ─── order by meaning too (stored article embeddings) ────────────────────────────────────────────────────────────
# The keyword order above misses an article that discusses the question in other words. Its rank is fused with how
# close the article's stored embedding is to the question (Reciprocal Rank Fusion: no score scales to tune). Only
# the order changes, never the set: a brand deck still cites only articles naming the brand, and every number an
# insight states is still checked against the computed facts. The vectors are the ones the Data set tagging job's
# relations phase stored (kind "article"); only the question is embedded (NVIDIA, no chat model).
RRF_K = 60      # the usual RRF constant: rank 1 and 5 differ a lot, rank 200 and 205 hardly


def _unit(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-9)


def fuse(rows: list[EngineRow], query: np.ndarray, vectors: dict[str, np.ndarray]) -> list[EngineRow]:
    """rows (keyword order) re-ordered by keyword rank fused with similarity rank. A row without a vector keeps only
    its keyword score."""
    q = _unit(np.asarray(query, dtype=np.float32))
    sims = {i: float(_unit(vectors[r.article.url]) @ q) for i, r in enumerate(rows)
            if r.article.url in vectors and vectors[r.article.url].shape == q.shape}
    if not sims:
        return rows
    by_meaning = {i: rank for rank, i in enumerate(sorted(sims, key=lambda i: -sims[i]), start=1)}
    score = {i: 1 / (RRF_K + i + 1) + (1 / (RRF_K + by_meaning[i]) if i in by_meaning else 0.0)
             for i in range(len(rows))}
    return [rows[i] for i in sorted(score, key=lambda i: (-score[i], i))]


def rerank_by_meaning(project_id: int, questions: dict[str, str], evidence_by_rq: dict[str, list[EngineRow]],
                      llm) -> tuple[dict[str, list[EngineRow]], int]:
    """(every question's evidence in fused order, article vectors used). Unchanged, with 0, when there are no stored
    vectors or the embedding provider fails. Never raises."""
    try:
        from ...core.nvidia_embed_client import embed_model_name
        from ..dataset import repository as dataset_repo
        model = embed_model_name()
        stored = dataset_repo.article_vectors(project_id, model) if model and llm is not None else {}
        if not stored:
            return evidence_by_rq, 0
        vectors = {url: np.frombuffer(b, dtype=np.float32) for url, b in stored.items()}
        return {rq_id: fuse(rows, llm.embed(questions[rq_id]), vectors) if rows and questions.get(rq_id) else rows
                for rq_id, rows in evidence_by_rq.items()}, len(vectors)
    except Exception as e:      # unconfigured or unreachable embeddings: the keyword order stands
        logger.warning("ordering citations by meaning skipped: %s", type(e).__name__)
        return evidence_by_rq, 0
