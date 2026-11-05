"""Data set upload: many export files -> normalised, split traditional/social, deduplicated by link, kept in S3."""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from ...core import config, object_store
from ..execution.service import _load_dataset
from . import normalize, repository as repo

logger = logging.getLogger(__name__)
ALLOWED_EXT = (".csv", ".xlsx", ".xls")
MAX_FILE_BYTES = 50 * 1024 * 1024


def _safe_name(name: str) -> str:
    base = re.split(r"[\/]", name or "")[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "upload"


def _read(name: str, data: bytes) -> list[dict]:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.UPLOAD_DIR / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
    try:
        tmp.write_bytes(data)
        return _load_dataset(str(tmp))
    finally:
        tmp.unlink(missing_ok=True)


def _one(project_id: int, name: str, data: bytes, user: str | None) -> dict:
    safe = _safe_name(name)
    out = {"file_name": name, "rows_read": 0, "added": 0, "duplicates": 0, "error": None}
    fid = None
    try:
        if Path(safe).suffix.lower() not in ALLOWED_EXT:
            out["error"] = "Unsupported file type (use .csv, .xlsx or .xls)"
        elif len(data) > MAX_FILE_BYTES:
            out["error"] = "File is larger than 50 MB"
        elif not data:
            out["error"] = "File is empty"
        key = None if out["error"] else object_store.put_bytes(
            f"datasets/project-{project_id}/{uuid.uuid4().hex[:8]}-{safe}", data)
        fid = repo.add_file(project_id, name, key, None if key or out["error"] else data, user)
        if not out["error"]:
            raw = _read(safe, data)
            recs, out["error"] = normalize.records(raw)
            out["rows_read"] = len(raw)
            if recs:
                unique = list({r["norm_url"]: r for r in reversed(recs)}.values())[::-1]     # first row per link wins
                out["added"], out["duplicates"] = repo.insert_articles(project_id, fid, unique)
                out["duplicates"] += len(recs) - len(unique)
    except Exception as e:                      # one bad file must not stop the others
        logger.warning("Upload of %s failed: %s", safe, e)
        out["error"] = out["error"] or f"Could not process the file: {type(e).__name__}"
    finally:
        if fid is not None:
            try:
                repo.finish_file(fid, out["rows_read"], out["added"], out["duplicates"], out["error"])
            except Exception as e:
                logger.warning("Could not record the result of %s: %s", safe, e)
    return out


def upload(project_id: int, files: list[tuple[str, bytes]], user: str | None) -> dict:
    results = [_one(project_id, name, data, user) for name, data in files]
    try:
        counts = repo.channel_counts(project_id)
    except Exception as e:                      # the per-file results are already saved; do not lose them
        logger.warning("Channel counts failed: %s", e)
        counts = {}
    return {"files": results, "added": sum(r["added"] for r in results),
            "duplicates": sum(r["duplicates"] for r in results),
            "traditional": counts.get("traditional", 0), "social": counts.get("social", 0)}


# ---- tagging (the job lives in tagging_job.py) ---------------------------------------------------------------------
from .tagging_job import TaggingBusy, is_tagging, start_tagging, tagging_state  # noqa: E402,F401
