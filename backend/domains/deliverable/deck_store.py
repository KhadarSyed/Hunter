"""A finished deck kept in Postgres, so a server whose disk is wiped on restart (Render free) still serves its
downloads, its deck page and its Fix button.

Stored per run (intel_deliverable_files, in CHUNK-sized parts, gzip'd where that saves GZ_MIN_SAVING): the downloads
(studio PPTX and PDF, the Deliverable PPTX, the Brief DOCX, the data XLSX), the slide thumbnails, the files Fix and a
re-render read (spec.json, repair_context.json, creative.json, tokens_original.json) and every file the spec points
at under DATA_DIR (photos, logos, site icons, verbatim screenshots). deck.html is not stored: it is ~100 MB of inlined
images, and is rendered again from the spec when missing (the same render + inline the Restyle page runs). Only each
project's latest persisted run is kept. Files are named by their path under DATA_DIR and restored to the same place."""
from __future__ import annotations

import gzip
import json
import logging
import os
import threading
import uuid
from pathlib import Path

from ...core import config, object_store, store

logger = logging.getLogger(__name__)
CHUNK = 8 * 1024 * 1024            # a part this size at most in memory: Render free has 512 MB
GZ_MIN_SAVING = 0.10               # compress a part only when it shrinks by at least this much
DECK_FILES = ("spec.json", "repair_context.json", "creative.json", "tokens_original.json")
DOWNLOADS = ("pptx_path", "docx_path", "pdf_path", "studio_pptx_path")
MAX_PATH_LEN = 400
_restore_lock = threading.Lock()   # one restore at a time: the deck page's many asset requests arrive together


def _name(path: Path) -> str | None:
    """The file's path under DATA_DIR (posix), or None for a file outside it (shipped templates)."""
    try:
        return path.resolve().relative_to(config.DATA_DIR.resolve()).as_posix()
    except ValueError:
        return None


def _referenced(spec_path: Path) -> list[Path]:
    """Every existing file the spec names by absolute path (photos, logos, icons, verbatim screenshots)."""
    found: set[str] = set()

    def walk(o) -> None:
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and len(o) < MAX_PATH_LEN and (o.startswith("/") or o[1:3] in (":\\", ":/")):
            found.add(o)
    try:
        walk(json.loads(spec_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []
    return [Path(p) for p in sorted(found) if Path(p).is_file()]


def files_to_keep(run: dict, deck_dir: Path) -> dict[str, Path]:
    """{name under DATA_DIR: file} for everything persist stores."""
    from ..deckstudio import data_tables
    paths = [deck_dir / n for n in DECK_FILES] + sorted(deck_dir.glob(f"*{data_tables.FILE_SUFFIX}"))
    paths += [Path(run[k]) for k in DOWNLOADS if run.get(k)]
    if run.get("thumbs_dir"):
        paths += sorted(Path(run["thumbs_dir"]).glob("*.png"))
    paths += _referenced(deck_dir / "spec.json")
    return {name: p for p in paths if p.is_file() and (name := _name(p))}


def _parts(files: dict[str, Path], s3_prefix: str | None = None):
    """Each file as one S3 row when S3 takes it, else as chunks (a failed upload falls back, the deck is never lost)."""
    for name, path in files.items():
        key = object_store.put_file(f"{s3_prefix}/{name}", path) if s3_prefix and object_store.enabled() else None
        if key:
            yield name, 0, 0, b"", key
            continue
        with path.open("rb") as f:
            part = 0
            while True:
                data = f.read(CHUNK)
                if not data and part:
                    break
                packed = gzip.compress(data, compresslevel=6)
                small = len(packed) <= len(data) * (1 - GZ_MIN_SAVING)
                yield name, part, int(small), packed if small else data
                part += 1
                if len(data) < CHUNK:
                    break


def persist(run_id: int, deck_dir: Path | str) -> int:
    """Store the run's files (see the module doc) and drop the project's older runs. Returns bytes stored, 0 when
    nothing was stored; never raises (the deck on disk is already finished)."""
    run = store.get_deliverable_run(run_id)
    if not run or not deck_dir:
        return 0
    try:
        files = files_to_keep(run, Path(deck_dir))
        prefix = f"decks/project-{run['project_id']}/run-{run_id}"
        total = store.save_deck_files(run_id, run["project_id"], _parts(files, prefix))
        _index_deck(run, files, prefix)
    except Exception as e:
        logger.error("run %s: deck not kept in the database (%s: %s)", run_id, type(e).__name__, e)
        return 0
    logger.info("run %s: %d files kept in the database (%.1f MB)", run_id, len(files), total / 1e6)
    return total


def _index_deck(run: dict, files: dict[str, Path], prefix: str) -> None:
    """A library row for the deck (no bytes copied) so a later brief can find it by similarity. Best effort."""
    try:
        pptx = next((n for k in ("studio_pptx_path", "pptx_path") if run.get(k) and (n := _name(Path(run[k])))
                     and n in files), None)
        if not pptx or not object_store.enabled():
            return
        from ..assets import library, service
        from . import rows
        project = store.get_project(run["project_id"]) or {}
        brand = ((project.get("spec") or {}).get("commissioning_brand") or {}).get("name") or project.get("brand") or ""
        summary = f"{brand} research deck: " + "; ".join(q.question for q in rows.approved_rqs(run["project_id"]))[:400]
        library.upsert("deck", f"run-{run['id']}", s3_key=f"{prefix}/{pptx}", content_type="", sha256="",
                       size=files[pptx].stat().st_size, brand=brand, summary=summary,
                       meta={"project_id": run["project_id"]}, embedding=service._embed(summary))
    except Exception as e:
        logger.info("run %s: deck not added to the asset library (%s: %s)", run.get("id"), type(e).__name__, e)


def _write(run_id: int, name: str) -> None:
    target = config.DATA_DIR / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if key := store.deck_file_s3_key(run_id, name):
        if not object_store.download(key, target):
            raise OSError(f"S3 download failed for {key}")
        return
    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
    with partial.open("wb") as f:
        for gz, content in store.deck_file_parts(run_id, name):
            f.write(gzip.decompress(content) if gz else content)
    os.replace(partial, target)


def _render_html(deck_dir: Path) -> None:
    from ..deckstudio import renderer, revise
    spec, candidates = revise.load(deck_dir)
    renderer.inline_assets(renderer.render_deck(spec, deck_dir, candidates))


def _complete(run: dict) -> bool:
    deck_dir = Path(run["deck_dir"]) if run.get("deck_dir") else None
    return bool(deck_dir and (deck_dir / "spec.json").is_file() and
                (not run.get("html_path") or Path(run["html_path"]).is_file()))


def restore(run: dict) -> bool:
    """Write back the run's stored files missing on this disk and render deck.html again when it is gone.
    True when anything was restored. Cheap when the deck is on disk (no database read)."""
    if not run or _complete(run):
        return False
    with _restore_lock:
        if _complete(run):                                  # restored by the request that held the lock
            return True
        try:
            missing = [n for n in store.deck_file_names(run["id"]) if not (config.DATA_DIR / n).is_file()]
            for name in missing:
                _write(run["id"], name)
            html = Path(run["html_path"]) if run.get("html_path") else None
            rendered = False
            if html and not html.is_file() and run.get("deck_dir") and (Path(run["deck_dir"]) / "spec.json").is_file():
                _render_html(Path(run["deck_dir"]))
                rendered = True
        except Exception as e:      # the route answers 404 as before
            logger.error("run %s: deck not restored from the database (%s: %s)", run.get("id"), type(e).__name__, e)
            return False
    if missing or rendered:
        logger.info("run %s: %d files restored from the database%s", run["id"], len(missing),
                    ", deck page rendered again" if rendered else "")
    return bool(missing or rendered)
