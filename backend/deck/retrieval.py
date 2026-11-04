"""Brute-force cosine-similarity retrieval over the slide index.

At the scale of a few thousand slides this is fast enough in plain numpy;
no vector database is needed.
"""
from __future__ import annotations

import numpy as np

from ..core.llm_provider import HybridLLMClient
from . import memory


def _to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def search(query_text: str, llm_client: HybridLLMClient, top_k: int = 8, exclude_deck: str | None = None) -> list[dict]:
    """Return up to top_k slides most similar to query_text, best first.

    Each result: {deck_path, slide_no, title, body_text, has_chart, has_picture,
    client_guess, score}
    """
    query_vec = llm_client.embed(query_text)
    q_norm = np.linalg.norm(query_vec)
    if q_norm == 0:
        return []

    rows = memory.all_slides()
    scored = []
    for row in rows:
        if exclude_deck and row["deck_path"] == exclude_deck:
            continue
        vec = _to_vec(row["embedding_blob"])
        v_norm = np.linalg.norm(vec)
        if v_norm == 0:
            continue
        score = float(np.dot(query_vec, vec) / (q_norm * v_norm))
        scored.append((score, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, row in scored[:top_k]:
        results.append({
            "deck_path": row["deck_path"],
            "slide_no": row["slide_no"],
            "title": row["title"],
            "body_text": row["body_text"],
            "has_chart": bool(row["has_chart"]),
            "has_picture": bool(row["has_picture"]),
            "client_guess": row["client_guess"],
            "score": score,
        })
    return results


