"""Template stage: index the reference decks once and pick the one closest to the project's scope."""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path

from pptx import Presentation

from ...core import config, store

logger = logging.getLogger(__name__)
DEFAULT_TEMPLATE = config.TEMPLATES_DIR / "Hunter PR Research_Johnson’s (Baby) Editorial _May 2026.pptx"
_WORD = re.compile(r"[a-z]{3,}")
MAX_TEXT = 4000


def is_usable(path: Path) -> bool:
    try:
        prs = Presentation(str(path))
    except Exception:
        return False
    return len(prs.slides) >= 2 and any(l.name == "Blank" for l in prs.slide_layouts)


def _deck_text(path: Path) -> str:
    prs = Presentation(str(path))
    parts = [path.stem] + [sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame]
    return " ".join(parts)[:MAX_TEXT]


def _embed(llm, text: str):
    try:
        vec = llm.embed(text) if llm is not None and hasattr(llm, "embed") else None
        return [float(x) for x in vec] if vec is not None else None   # embed clients may return numpy arrays
    except Exception as e:   # embeddings are optional: token overlap still works
        logger.info("template embedding unavailable (%s)", e)
        return None


def _embed_model(llm) -> str:
    return getattr(getattr(llm, "_embed_backend", None), "model", "") or ""


_REINDEX_TRIED: set[tuple[str, str]] = set()   # (path, model) already re-indexed this process: a failed embed is not retried


def index_templates(llm=None, stale_only: bool = False) -> int:
    """Embed the reference decks. `stale_only`: just those not embedded by the current model, once per process.
    A failed embed never overwrites a deck's existing row."""
    model = _embed_model(llm)
    folder = Path(config.TEMPLATES_DIR)
    existing = {d["path"]: d for d in store.list_reference_decks()}
    count = 0
    for path in sorted(folder.glob("*.pptx")) if folder.exists() else []:
        key = str(path)
        if path.name.startswith("~$") or not is_usable(path):
            continue
        if stale_only:
            if (key, model) in _REINDEX_TRIED or existing.get(key, {}).get("model") == model:
                continue
            _REINDEX_TRIED.add((key, model))
        text = _deck_text(path)
        vec = _embed(llm, text)
        if vec is None and key in existing:
            count += 1
            continue
        store.save_reference_deck(key, text, vec, model if vec is not None else "")
        count += 1
    return count


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def choose_template_explained(scope_text: str, llm=None) -> tuple[Path, str]:
    """The template deck and a one-line reason a person can read in the run log."""
    path, score, count = _choose_scored(scope_text, llm)
    if not Path(path).exists() and is_usable(config.TEMPLATE_PATH):
        # a deployed server ships without the reference decks (client work); the house template travels in the image
        return Path(config.TEMPLATE_PATH), "no reference decks on this server, so the house template is used"
    if not Path(path).exists():
        raise FileNotFoundError(f"No usable PowerPoint template: add a .pptx to {config.TEMPLATES_DIR}")
    if score <= 0:
        return Path(path), f"no close match among {count} reference decks, so the house default is used"
    return Path(path), f"closest of {count} reference decks to this project's scope (similarity {score:.2f})"


def _choose_scored(scope_text: str, llm=None) -> tuple[Path, float, int]:
    folder = str(Path(config.TEMPLATES_DIR))

    def current():
        return [d for d in store.list_reference_decks() if d["path"].startswith(folder) and Path(d["path"]).exists()]

    model = _embed_model(llm)
    decks = current()
    # decks embedded by another model (or none recorded) are stale: re-index once when embeddings are available
    if not decks:
        if index_templates(llm):
            decks = current()
    elif model and any(d["model"] != model and (d["path"], model) not in _REINDEX_TRIED for d in decks):
        index_templates(llm, stale_only=True)
        decks = current()
    if not decks:
        return DEFAULT_TEMPLATE, 0.0, 0
    # vectors from different models are not comparable: only the current model's embeddings count
    if model:
        decks = [{**d, "embedding": d["embedding"] if d["model"] == model else None} for d in decks]
    query_vec = _embed(llm, scope_text) if any(d["embedding"] for d in decks) else None
    query_tokens = _tokens(scope_text)

    def score(d):
        if query_vec and d["embedding"]:
            return _cosine(query_vec, d["embedding"])
        return len(query_tokens & _tokens(d["text"])) / (len(query_tokens) or 1)

    best = max(decks, key=score)
    best_score = score(best)
    return (Path(best["path"]) if best_score > 0 else DEFAULT_TEMPLATE), best_score, len(decks)
