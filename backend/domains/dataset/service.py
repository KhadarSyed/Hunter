"""Data set upload: many export files -> normalised, split traditional/social, deduplicated by link, kept in S3."""
from __future__ import annotations

import logging
import os
import re
import time
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


# ---- query panel: per-RQ query preview, free re-match, needs-tagging counts and the re-tag estimate -----------------
PREVIEW_TITLES = 50
DROPPED_REASON = "No longer matches the edited query"


def _matching(query: str, arts: list[dict]) -> set[int]:
    from ...agents import rq_tagging
    return {a["id"] for a in arts if rq_tagging.keyword_hits(query, a["text"])}


def preview(project_id: int, current: str, edited: str) -> dict:
    """What the edited query would match against the current one. Reads only; writes nothing."""
    from ...agents.meltwater_query_builder import validate_boolean_syntax
    arts = repo.match_texts(project_id)
    old, new = _matching(current, arts), _matching(edited, arts)
    titles = {a["id"]: a["title"] for a in arts}

    def listed(ids: set[int]) -> list[dict]:
        return [{"id": i, "title": titles[i]} for i in sorted(ids)[:PREVIEW_TITLES]]
    errors = validate_boolean_syntax(edited)
    return {"valid": not errors, "errors": errors, "current": len(old), "edited": len(new),
            "added": listed(new - old), "dropped": listed(old - new)}


def rematch(project_id: int, rq_id: str, current: str, edited: str) -> None:
    """Free re-match after a query edit (keyword hits, no GPT); see repository.apply_rematch."""
    arts = repo.match_texts(project_id)
    old, new = _matching(current, arts), _matching(edited, arts)
    repo.apply_rematch(project_id, rq_id, sorted(new - old), sorted(old - new), DROPPED_REASON)


def rq_schemas(project_id: int) -> dict:
    from ..strategy import tag_schemas
    return tag_schemas.project_tag_schemas(project_id, None)


def rq_signature(rq, schemas: dict) -> str:
    from ...agents import rq_tagging
    return rq_tagging.signature(rq, schemas.get(rq.id))


def rq_counts(project_id: int, rq, schemas: dict) -> dict:
    return repo.rq_counts(project_id, rq.id, rq_signature(rq, schemas))


def estimate(project_id: int, rq) -> dict:
    """What "Re-tag this question" would send to GPT: the rows needing tagging, packed as the job packs them."""
    from ...agents import rq_tagging
    from ..usage import service as usage
    from . import batching
    from .tagging_job import ALL
    todo = repo.rq_rows_needing(project_id, rq.id, rq_signature(rq, rq_schemas(project_id)), ALL)
    batches = batching.pack(todo, rq_tagging._body, out_per_item=rq_tagging.OUT_PER_ARTICLE)
    inp = sum(batching.tokens(rq_tagging._body(a)) for a in todo)
    out = rq_tagging.OUT_PER_ARTICLE * len(todo)
    cost = usage.cost_usd("azure_openai", os.getenv("AZURE_OPENAI_MODEL", ""), usage.deployment_type("azure_openai"),
                          inp, 0, out, time.time())
    return {"articles": len(todo), "batches": len(batches), "input_tokens": inp, "output_tokens": out,
            "cost_usd": cost}
