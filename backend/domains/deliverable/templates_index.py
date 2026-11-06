"""Template stage: index the reference decks once and pick the one closest to the project's scope."""
from __future__ import annotations

import logging
import math
import re
import tempfile
import threading
from pathlib import Path

from pptx import Presentation

from ...core import config, object_store, store

logger = logging.getLogger(__name__)
DEFAULT_TEMPLATE = config.TEMPLATES_DIR / "Hunter PR Research_Johnson’s (Baby) Editorial _May 2026.pptx"
_WORD = re.compile(r"[a-z]{3,}")
MAX_TEXT = 4000
S3_PREFIX = "ppt-templates/"


def _s3_names() -> dict[str, str]:
    """{deck file name: S3 key} for the reference decks kept in S3 (empty without S3)."""
    return {k.rsplit("/", 1)[-1]: k for k, _ in object_store.list_keys(S3_PREFIX) if k.lower().endswith(".pptx")}


def ensure_local(path: Path) -> Path | None:
    """The deck on this disk: `path` itself, else its copy downloaded from S3 into DATA_DIR/ppt-templates (kept for
    the run). None when it is in neither place."""
    path = Path(path)
    if path.exists():
        return path
    target = config.DATA_DIR / "ppt-templates" / path.name
    if target.exists():
        return target
    return object_store.download(S3_PREFIX + path.name, target)


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


def _index_one(path: Path, key: str, llm, model: str, existing: dict) -> None:
    try:
        text = _deck_text(path)
    except OSError as e:     # a deck removed mid-run skips that deck, not the run
        logger.info("reference deck %s not read (%s)", path.name, type(e).__name__)
        return
    _save(key, text, llm, model, existing)


def _save(key: str, text: str, llm, model: str, existing: dict) -> None:
    vec = _embed(llm, text)
    if vec is None and key in existing:     # a failed embed never overwrites a deck's existing row
        return
    store.save_reference_deck(key, text, vec, model if vec is not None else "")


def index_templates(llm=None, stale_only: bool = False, from_s3: bool = False) -> int:
    """Embed the reference decks. `stale_only`: re-embed from the stored text those not embedded by the current model,
    once per process (no file is opened or downloaded). `from_s3`: with no local .pptx, index the decks in S3 that are
    not indexed yet, one at a time, each downloaded to its own temp folder and deleted after (the index keeps its
    text and embedding). Only the startup warm-up job passes `from_s3`: a deck run never downloads the set."""
    model = _embed_model(llm)
    folder = Path(config.TEMPLATES_DIR)
    existing = {d["path"]: d for d in store.list_reference_decks()}
    local = sorted(folder.glob("*.pptx")) if folder.exists() else []
    remote = _s3_names() if from_s3 and not local else {}
    count = 0
    for path in local or [folder / n for n in sorted(remote)]:
        key = str(path)
        if path.name.startswith("~$"):
            continue
        if stale_only:
            if (key, model) in _REINDEX_TRIED or existing.get(key, {}).get("model") == model:
                continue
            _REINDEX_TRIED.add((key, model))
            if key in existing:
                _save(key, existing[key]["text"], llm, model, existing)
                count += 1
                continue
        elif remote and key in existing:    # already indexed: do not download a large deck again
            count += 1
            continue
        if not remote:
            if is_usable(path):
                _index_one(path, key, llm, model, existing)
                count += 1
            continue
        with tempfile.TemporaryDirectory(prefix="ppt-index-") as tmp:
            fetched = object_store.download(remote[path.name], Path(tmp) / path.name)
            if fetched and is_usable(fetched):
                _index_one(fetched, key, llm, model, existing)
                count += 1
    return count


_warming = threading.Lock()


def _warm(llm) -> None:
    if _warming.acquire(blocking=False):
        try:
            logger.info("reference decks: %d indexed from S3", index_templates(llm, from_s3=True))
        except Exception as e:
            logger.warning("reference deck warm-up failed (%s: %s)", type(e).__name__, e)
        finally:
            _warming.release()


def warm_in_background() -> bool:
    """At startup: when S3 holds reference decks that are not indexed yet (and none are local), index them in a job so
    no deck run waits for the download. True when a job was started."""
    folder = Path(config.TEMPLATES_DIR)
    if not object_store.enabled() or (folder.exists() and any(folder.glob("*.pptx"))):
        return False
    indexed = {d["path"] for d in store.list_reference_decks()}
    if all(str(folder / n) in indexed for n in _s3_names()):
        return False
    from ...core import jobs
    from ...core.llm_provider import get_llm_client
    jobs.runner.submit(lambda: _warm(get_llm_client()), name="reference-deck-warmup")
    return True


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def choose_template_explained(scope_text: str, llm=None) -> tuple[Path, str]:
    """The template deck and a one-line reason a person can read in the run log."""
    path, score, count = _choose_scored(scope_text, llm)
    local = ensure_local(Path(path))
    path = local or path
    if not local and not Path(path).exists() and Path(path).name in _s3_names() and is_usable(config.TEMPLATE_PATH):
        return Path(config.TEMPLATE_PATH), "reference deck download failed, so the house template is used"
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
        decks = [d for d in store.list_reference_decks() if d["path"].startswith(folder)]
        remote = _s3_names() if any(not Path(d["path"]).exists() for d in decks) else {}
        return [d for d in decks if Path(d["path"]).exists() or Path(d["path"]).name in remote]

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
