"""Postgres access for org-managed data source credentials (Tavily, SerpAPI, Firecrawl).

Keys are encrypted at rest with the same Fernet box as the LLM provider keys (core/secret_box). Rows written before
encryption hold the plain key; `encrypt_legacy_keys()` (startup) converts them, and reads accept either form."""
from __future__ import annotations

import json
import logging
import time

from ...core import secret_box
from ...core.db import _conn

logger = logging.getLogger(__name__)
SOURCES = ("tavily", "serpapi", "firecrawl")
_FERNET_PREFIX = "gAAAA"          # every Fernet token starts with this (version byte + timestamp)


def _seal(api_key: str) -> str:
    return secret_box.encrypt(api_key)


def _open(stored: str | None) -> str | None:
    if not stored:
        return None
    if not stored.startswith(_FERNET_PREFIX):
        return stored                  # a row from before encryption; encrypt_legacy_keys() converts it
    try:
        return secret_box.decrypt(stored)
    except secret_box.SecretUnreadable:
        logger.warning("a data source key could not be decrypted (PROVIDER_SECRET_KEY changed?)")
        return None


def _plain(row) -> dict:
    out = dict(row)
    out["api_key"] = _open(out.get("api_key")) or ""
    try:
        out["settings"] = json.loads(out.get("settings_json") or "{}")
    except ValueError:
        out["settings"] = {}
    return out


def upsert_key(org_id: int, source: str, api_key: str, user_id: int, status: str = "ok",
               error: str | None = None, settings: dict | None = None) -> dict:
    """Admin sets/replaces the org's key for a source (stored encrypted). Settings, when given, replace the old ones."""
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO org_data_sources (org_id, source, api_key, status, expired_at, last_error, "
        "updated_at, updated_by_user_id, settings_json) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?) "
        "ON CONFLICT(org_id, source) DO UPDATE SET "
        "api_key = excluded.api_key, status = excluded.status, expired_at = NULL, last_error = excluded.last_error, "
        "updated_at = excluded.updated_at, updated_by_user_id = excluded.updated_by_user_id"
        + (", settings_json = excluded.settings_json" if settings is not None else ""),
        (org_id, source, _seal(api_key), status, error, now, user_id, json.dumps(settings or {})),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM org_data_sources WHERE org_id = ? AND source = ?", (org_id, source)).fetchone()
    conn.close()
    return _plain(row)


def update_settings(org_id: int, source: str, settings: dict) -> dict | None:
    conn = _conn()
    conn.execute("UPDATE org_data_sources SET settings_json = ?, updated_at = ? WHERE org_id = ? AND source = ?",
                 (json.dumps(settings), time.time(), org_id, source))
    conn.commit()
    row = conn.execute("SELECT * FROM org_data_sources WHERE org_id = ? AND source = ?", (org_id, source)).fetchone()
    conn.close()
    return _plain(row) if row else None


def delete_key(org_id: int, source: str) -> bool:
    conn = _conn()
    cur = conn.execute("DELETE FROM org_data_sources WHERE org_id = ? AND source = ?", (org_id, source))
    conn.commit()
    conn.close()
    return bool(cur.rowcount)


def get_org_sources(org_id: int) -> list[dict]:
    """All configured sources for an org, keys decrypted (callers exposing them must mask; see schemas.py)."""
    conn = _conn()
    rows = conn.execute("SELECT * FROM org_data_sources WHERE org_id = ?", (org_id,)).fetchall()
    conn.close()
    return [_plain(r) for r in rows]


def get_source(org_id: int, source: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM org_data_sources WHERE org_id = ? AND source = ?", (org_id, source)).fetchone()
    conn.close()
    return _plain(row) if row else None


def get_key(org_id: int, source: str) -> str | None:
    """The decrypted key for internal use by the research pipeline; None when the org has not configured it."""
    row = get_source(org_id, source)
    return (row["api_key"] or None) if row else None


def mark_status(org_id: int, source: str, status: str, error: str | None = None) -> None:
    """Reactively flip a configured source's status after a real call succeeds/fails (no-op when not configured)."""
    conn = _conn()
    now = time.time()
    expired_at = now if status == "expired" else None
    conn.execute(
        "UPDATE org_data_sources SET status = ?, expired_at = ?, last_error = ?, updated_at = ? "
        "WHERE org_id = ? AND source = ?",
        (status, expired_at, error, now, org_id, source),
    )
    conn.commit()
    conn.close()


def encrypt_legacy_keys() -> int:
    """Startup, idempotent: plain keys saved before encryption are encrypted in place. Returns how many."""
    conn = _conn()
    try:
        rows = conn.execute("SELECT id, api_key FROM org_data_sources").fetchall()
        n = 0
        for r in rows:
            if r["api_key"] and not r["api_key"].startswith(_FERNET_PREFIX):
                conn.execute("UPDATE org_data_sources SET api_key = ? WHERE id = ?", (_seal(r["api_key"]), r["id"]))
                n += 1
        conn.commit()
        return n
    finally:
        conn.close()
