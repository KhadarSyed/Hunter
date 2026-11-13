"""Logos, site icons, flags and slide photos shared by every organization. Lookup order for every fetcher:
the file already on this server's disk, then the intel_assets table, then the external API (Brandfetch, Google
favicons, Iconify, photo search) - whose answer is written to the table and the disk both. The disk is only a
per-process cache: a restarted server (Render wipes it) reads the table instead of paying for another API call.

A definite "this source has none" is stored too (empty content, meta {"missing": true}) and trusted for
MISSING_RETRY_S; a transient failure (network error) is never stored. The table is a cache: when the database cannot
be read or written the fetch simply goes ahead, so assets never fail a deck."""
from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import requests

from ...core import object_store
from . import library, repository

logger = logging.getLogger(__name__)
KINDS = ("logo", "icon", "favicon", "flag", "photo", "svg_icon", "product_logo", "slide_image", "house_logo", "deck",
         "brand_data")
_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/gif": ".gif", "image/svg+xml": ".svg",
        "image/webp": ".webp", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico", "application/json": ".json"}
_LABELS = {"logo": "Brand logo", "product_logo": "Product logo", "icon": "Icon", "svg_icon": "SVG icon",
           "favicon": "Site icon", "flag": "Country flag", "photo": "Slide photo", "slide_image": "Slide image",
           "house_logo": "House logo", "deck": "Research deck",
           "brand_data": "Brandfetch brand data"}
_NOT_SEARCHED = ("brand_data",)     # cached API answers: never matched by similarity, so no embedding call
MISSING_RETRY_S = 7 * 86_400       # a brand / site with no logo or icon is asked again after a week

# fetch() -> (bytes, content type, meta) | None (the source definitely has none); raising RequestException / OSError
# means "could not ask right now"
Fetch = Callable[[], "tuple[bytes, str, dict] | None"]


def summary_for(kind: str, key: str, meta: dict) -> str:
    """One line on what the asset is and why a deck used it: what similarity search matches on."""
    subject = meta.get("brand") or meta.get("subject") or key.split("#")[0]
    why = meta.get("why") or ""
    query = meta.get("query") or ""     # kept beside why: similar() searches "subject query"
    parts = [f"{_LABELS.get(kind, kind)} for {subject}"] + ([f"search: {query}"] if query else []) + \
            ([f"used for: {why}"] if why else []) + \
            ([f"slide role: {meta['role']}"] if meta.get("role") else []) + \
            ([f"source: {meta['source_url']}"] if meta.get("source_url") else [])
    return "; ".join(parts)[:500]


def embed_text(text: str) -> list[float] | None:
    """Best-effort: None on any error (unconfigured, unreachable, bad model)."""
    try:
        from ...core.llm_provider import get_llm_client
        client = get_llm_client()
        return [float(x) for x in client.embed(text)] if client else None
    except Exception as e:
        logger.info("asset embedding skipped: %s", type(e).__name__)
        return None


def _legacy_get(kind: str, key: str) -> dict | None:
    try:
        return repository.get_asset(kind, key)
    except Exception as e:          # a cache that cannot be read costs one API call, never the asset
        logger.warning("asset %s/%s not read from the database: %s", kind, key[:80], type(e).__name__)
        return None


def _legacy_put(kind: str, key: str, content: bytes, content_type: str, meta: dict) -> None:
    try:
        repository.put_asset(kind, key, content, content_type, meta)
    except Exception as e:
        logger.warning("asset %s/%s not saved to the database: %s", kind, key[:80], type(e).__name__)


def get(kind: str, key: str) -> dict | None:
    if object_store.enabled():
        try:
            row = library.get(kind, key)
        except Exception as e:
            logger.warning("asset %s/%s library not read: %s", kind, key[:80], type(e).__name__)
            row = None
        if row and row["missing"]:
            return {"content": b"", "content_type": "", "meta": row["meta"], "created_at": row["created_at"]}
        if row and row["s3_key"]:
            data = object_store.get_bytes(row["s3_key"])
            if data is not None:
                try:
                    library.touch(row["id"])
                except Exception as e:
                    logger.info("asset touch failed: %s", type(e).__name__)
                return {"content": data, "content_type": row["content_type"], "meta": row["meta"],
                        "created_at": row["created_at"]}
    return _legacy_get(kind, key)


def put(kind: str, key: str, content: bytes, content_type: str = "", meta: dict | None = None) -> None:
    meta = meta or {}
    if not object_store.enabled():
        _legacy_put(kind, key, content, content_type, meta)
        return
    try:
        sha = hashlib.sha256(content).hexdigest()
        s3_key = None
        if content:
            ext = _EXT.get(content_type.split(";")[0].strip().lower(), ".bin")
            s3_key = object_store.put_bytes(f"assets/{kind}/{sha[:2]}/{sha}{ext}", content, content_type)
            if s3_key is None:      # S3 refused it: keep the asset in Postgres as before
                _legacy_put(kind, key, content, content_type, meta)
                return
        summary = summary_for(kind, key, meta)
        library.upsert(kind, key, s3_key=s3_key, content_type=content_type, sha256=sha, size=len(content),
                       brand=str(meta.get("brand") or ""), summary=summary, meta=meta,
                       embedding=embed_text(summary) if content and kind not in _NOT_SEARCHED else None,
                       missing=not content)
    except Exception as e:
        logger.warning("asset %s/%s not saved: %s", kind, key[:80], type(e).__name__)


def similar(kind: str, text: str, *, brand: str | None = None, role: str | None = None,
            min_score: float = 0.9) -> dict | None:
    """The best stored asset of this kind whose summary is at least min_score close to text, else None."""
    try:
        vec = embed_text(text) if object_store.enabled() else None
        if not vec:
            return None
        for r in library.nearest(kind, vec, brand=brand, role=role, limit=1):
            if r["score"] < min_score:
                continue
            data = object_store.get_bytes(r["s3_key"])
            if data:
                library.touch(r["id"])
                return {"content": data, "content_type": r["content_type"], "meta": r["meta"],
                        "created_at": r["created_at"], "key": r["key"], "summary": r["summary"], "score": r["score"]}
    except Exception as e:          # e.g. dimension mismatch after an embedding-model switch
        logger.info("asset similarity search failed: %s", type(e).__name__)
    return None


def lookup(kind: str, key: str, fetch: Fetch) -> tuple[bytes, dict] | None:
    """(bytes, meta) from the table, else from fetch() (and saved); None when there is none."""
    saved = get(kind, key)
    if saved:
        if saved["content"]:
            return saved["content"], saved["meta"]
        if time.time() - (saved["created_at"] or 0) < MISSING_RETRY_S:
            return None
    try:
        got = fetch()
    except (requests.RequestException, OSError) as e:
        logger.info("asset %s/%s unavailable right now: %s", kind, key[:80], type(e).__name__)
        return None
    if got is None:
        put(kind, key, b"", "", {"missing": True})
        return None
    data, ctype, meta = got
    put(kind, key, data, ctype, meta)
    return data, meta


def write_file(path: Path, data: bytes) -> Path:
    """Whole or not at all: a concurrent reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    partial.write_bytes(data)
    os.replace(partial, path)
    return path


LINK_TTL_S = 3600


def link(kind: str, key: str, fetch: Fetch) -> tuple[str, dict] | None:
    """(time-limited S3 link, stored meta) for the asset, fetched and stored first when new; None without S3, when
    the source has none, or when it could not be stored in S3 (the caller then serves the bytes from lookup())."""
    if not object_store.enabled():
        return None
    try:
        row = library.get(kind, key)
    except Exception as e:
        logger.warning("asset %s/%s library not read: %s", kind, key[:80], type(e).__name__)
        return None
    if not (row and row["s3_key"]):
        if lookup(kind, key, fetch) is None:
            return None
        row = library.get(kind, key)
    url = object_store.presigned_url(row["s3_key"], LINK_TTL_S) if row and row["s3_key"] else None
    return (url, row["meta"]) if url else None


def to_file(kind: str, key: str, out: Path, fetch: Fetch) -> Path | None:
    """The asset as a file at `out`: the disk copy, else the table's, else fetched."""
    if out.is_file():
        return out
    got = lookup(kind, key, fetch)
    return write_file(out, got[0]) if got else None
