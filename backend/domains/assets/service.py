"""Logos, site icons, flags and slide photos shared by every organization. Lookup order for every fetcher:
the file already on this server's disk, then the intel_assets table, then the external API (Brandfetch, Google
favicons, Iconify, photo search) - whose answer is written to the table and the disk both. The disk is only a
per-process cache: a restarted server (Render wipes it) reads the table instead of paying for another API call.

A definite "this source has none" is stored too (empty content, meta {"missing": true}) and trusted for
MISSING_RETRY_S; a transient failure (network error) is never stored. The table is a cache: when the database cannot
be read or written the fetch simply goes ahead, so assets never fail a deck."""
from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import requests

from . import repository

logger = logging.getLogger(__name__)
KINDS = ("logo", "icon", "favicon", "flag", "photo")
MISSING_RETRY_S = 7 * 86_400       # a brand / site with no logo or icon is asked again after a week

# fetch() -> (bytes, content type, meta) | None (the source definitely has none); raising RequestException / OSError
# means "could not ask right now"
Fetch = Callable[[], "tuple[bytes, str, dict] | None"]


def get(kind: str, key: str) -> dict | None:
    try:
        return repository.get_asset(kind, key)
    except Exception as e:          # a cache that cannot be read costs one API call, never the asset
        logger.warning("asset %s/%s not read from the database: %s", kind, key[:80], type(e).__name__)
        return None


def put(kind: str, key: str, content: bytes, content_type: str = "", meta: dict | None = None) -> None:
    try:
        repository.put_asset(kind, key, content, content_type, meta or {})
    except Exception as e:
        logger.warning("asset %s/%s not saved to the database: %s", kind, key[:80], type(e).__name__)


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


def to_file(kind: str, key: str, out: Path, fetch: Fetch) -> Path | None:
    """The asset as a file at `out`: the disk copy, else the table's, else fetched."""
    if out.is_file():
        return out
    got = lookup(kind, key, fetch)
    return write_file(out, got[0]) if got else None
