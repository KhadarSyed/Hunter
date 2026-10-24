"""Syndicated and similar articles among a project's research items, for the All Articles table.

  Syndicated: the same article published by a different publisher -- the same headline once the publisher's
              suffix is removed (" - Automotive News"), or near-identical text (embedding similarity >= 0.95).
  Similar:    a different article on the same theme, content, motive or context -- embedding similarity at or
              above SIMILAR_CROSS between different publishers, SIMILAR_SAME within one publisher (same-site
              pages share templates and boilerplate, which inflates their similarity).

Thresholds were set on a real project (724 items, nvidia/nemotron-3-embed-1b): cross-publisher pairs from 0.76
are same-story or same-theme (e.g. "Honda eyes Ohio plant" at Car and Driver and Automotive News), while
same-site pairs below ~0.86 are mostly template noise (one site's market pages, one company's job ads).
A social post's publisher is its account, not the platform.

Each item's vector is embedded once and stored (intel_research_item_vectors). Without an embedding provider,
a deterministic fallback matches titles: same headline = syndicated, heavy word overlap = similar.
"""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlparse

import numpy as np

from . import repository

logger = logging.getLogger(__name__)

SYNDICATED_MIN = 0.95
SIMILAR_CROSS = 0.76
SIMILAR_SAME = 0.86
LEXICAL_SIMILAR = 0.5  # title word overlap (Jaccard) for the no-embeddings fallback
EMBED_BATCH = 50
# New embeddings one table request may make (~5s per 100): research fetches embed as they save, so this only
# bounds an old project's first view; the rest are embedded on later views ("embeddings_partial" until then).
MAX_EMBED_PER_CALL = 1000
TEXT_CHARS = 600  # the opening of the content; further down is mostly site boilerplate

_SUFFIX = re.compile(r"\s+[-|–—:]\s+[^-|–—:]{2,40}$")
_WORD = re.compile(r"[a-z0-9]+")


def clean_title(title: str | None) -> str:
    """The headline without a trailing publisher name: "Ford bets $1B - Automotive News" -> "Ford bets $1B"."""
    return _SUFFIX.sub("", (title or "").strip())


def _title_key(title: str | None) -> str:
    return " ".join(_WORD.findall(clean_title(title).lower()))[:120]


def publisher_key(item: dict) -> str:
    """Who published it: the site, or for a social post the account on that platform."""
    host = (urlparse(item.get("url") or "").hostname or "").lower().removeprefix("www.")
    account = (item.get("author") or item.get("publication") or "").strip().lower()
    platform = (item.get("platform") or "").lower()
    # sources often store the platform's own name ("facebook") where the account should be: that says nothing
    if not platform or not account or account in (platform, host, host.split(".")[0]):
        return host
    return f"{host}/{account}"


def _embed_text(item: dict) -> str:
    return f"{clean_title(item.get('title'))}\n{(item.get('content') or '')[:TEXT_CHARS]}"


def _model() -> str:
    return os.environ.get("NVIDIA_EMBED_MODEL", "").strip()


def ensure_vectors(items: list[dict], llm, limit: int | None = None) -> dict[int, np.ndarray] | None:
    """Every item's stored vector, embedding (and storing) the ones not embedded yet -- at most `limit` new
    ones. None when no embedding provider works. Called after a research fetch, so the table rarely waits."""
    model = _model()
    if llm is None or not model:
        return None
    stored = {k: np.frombuffer(v, dtype=np.float32)
              for k, v in repository.get_item_vectors([i["id"] for i in items], model).items()}
    missing = [i for i in items if i["id"] not in stored][:limit]
    try:
        for start in range(0, len(missing), EMBED_BATCH):
            batch = missing[start:start + EMBED_BATCH]
            made = [np.asarray(v, dtype=np.float32) for v in llm.embed_batch([_embed_text(i) for i in batch])]
            if len(made) != len(batch):
                raise ValueError(f"{len(made)} vectors for {len(batch)} texts")
            repository.save_item_vectors({i["id"]: v.tobytes() for i, v in zip(batch, made)}, model, len(made[0]))
            stored.update({i["id"]: v for i, v in zip(batch, made)})
    except Exception as e:  # unconfigured, unreachable or rejected: fall back, never fail the table
        logger.warning("Research item embeddings unavailable (%s); using the title-matching fallback",
                       type(e).__name__)
        return None
    return stored


def _vectors(items: list[dict], llm) -> tuple[np.ndarray | None, bool]:
    """(unit vectors in item order, complete?). Items still unembedded past the per-call cap get a zero
    vector: they match nothing by meaning this time, only by headline, and are embedded on later calls."""
    stored = ensure_vectors(items, llm, limit=MAX_EMBED_PER_CALL)
    if not stored:
        return None, True
    if len({v.shape[0] for v in stored.values()}) > 1:
        logger.warning("Research item vectors have mixed sizes; using the title-matching fallback")
        return None, True
    zero = np.zeros(next(iter(stored.values())).shape[0], dtype=np.float32)
    matrix = np.stack([stored.get(i["id"], zero) for i in items])
    complete = all(i["id"] in stored for i in items)
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9), complete


def _title_overlap(items: list[dict]) -> np.ndarray:
    """Jaccard overlap of headline words, scored only for pairs sharing a word (an inverted index), so a
    large project doesn't pay for every pair."""
    words = [set(_title_key(i.get("title")).split()) for i in items]
    holders: dict[str, list[int]] = {}
    for n, ws in enumerate(words):
        for w in ws:
            holders.setdefault(w, []).append(n)
    scores = np.zeros((len(items), len(items)), dtype=np.float32)
    for a, ws in enumerate(words):
        for b in {m for w in ws for m in holders[w] if m > a}:
            scores[a, b] = scores[b, a] = len(ws & words[b]) / len(ws | words[b])
    return scores


def _codes(values: list[str]) -> np.ndarray:
    """Integer code per value; empty values never equal each other (or anything)."""
    index: dict[str, int] = {}
    return np.array([index.setdefault(v, len(index)) if v else -n - 1 for n, v in enumerate(values)])


def find_relations(items: list[dict], llm) -> tuple[dict[int, dict[str, list[int]]], str]:
    """{item id: {"syndicated": [ids], "similar": [ids]}} (each list closest first), and the method used:
    "embeddings" or "titles"."""
    if not items:
        return {}, "embeddings"
    pubs = _codes([publisher_key(i) for i in items])
    titles = _codes([_title_key(i.get("title")) for i in items])
    same_pub = pubs[:, None] == pubs[None, :]
    same_title = titles[:, None] == titles[None, :]

    vectors, complete = _vectors(items, llm)
    if vectors is not None:
        scores = vectors @ vectors.T
        method = "embeddings" if complete else "embeddings_partial"
        syndicated = ~same_pub & (same_title | (scores >= SYNDICATED_MIN))
        similar = ~syndicated & ~same_title & np.where(same_pub, scores >= SIMILAR_SAME, scores >= SIMILAR_CROSS)
    else:
        scores = _title_overlap(items)
        method = "titles"
        syndicated = ~same_pub & same_title
        similar = ~syndicated & ~same_title & (scores >= LEXICAL_SIMILAR)
    np.fill_diagonal(syndicated, False)
    np.fill_diagonal(similar, False)

    ids = [i["id"] for i in items]

    def ranked(mask_row: np.ndarray, score_row: np.ndarray) -> list[int]:
        hits = np.flatnonzero(mask_row)
        return [ids[k] for k in hits[np.argsort(-score_row[hits], kind="stable")]]

    return {ids[r]: {"syndicated": ranked(syndicated[r], scores[r]), "similar": ranked(similar[r], scores[r])}
            for r in range(len(items))}, method
