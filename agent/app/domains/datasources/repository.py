"""SQLite access for org-managed data source credentials (Tavily, SerpAPI)."""
from __future__ import annotations

import time

from ...core.db import _conn

SOURCES = ("tavily", "serpapi")


def upsert_key(org_id: int, source: str, api_key: str, user_id: int) -> dict:
    """Admin sets/replaces the org's key for a source. Resets status to 'ok' —
    a freshly-entered key deserves a clean slate; the next real use re-validates it."""
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO org_data_sources (org_id, source, api_key, status, expired_at, last_error, "
        "updated_at, updated_by_user_id) VALUES (?, ?, ?, 'ok', NULL, NULL, ?, ?) "
        "ON CONFLICT(org_id, source) DO UPDATE SET "
        "api_key = excluded.api_key, status = 'ok', expired_at = NULL, last_error = NULL, "
        "updated_at = excluded.updated_at, updated_by_user_id = excluded.updated_by_user_id",
        (org_id, source, api_key, now, user_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM org_data_sources WHERE org_id = ? AND source = ?", (org_id, source)
    ).fetchone()
    conn.close()
    return dict(row)


def get_org_sources(org_id: int) -> list[dict]:
    """All configured sources for an org (raw api_key included — callers that expose this
    to the frontend must mask it; see schemas.py's DataSourceRecord)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM org_data_sources WHERE org_id = ?", (org_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_key(org_id: int, source: str) -> str | None:
    """Raw API key for internal use by the research pipeline (news_search.py). None if the
    org hasn't configured this source — callers fall back to the global env var key."""
    conn = _conn()
    row = conn.execute(
        "SELECT api_key FROM org_data_sources WHERE org_id = ? AND source = ?", (org_id, source)
    ).fetchone()
    conn.close()
    return row["api_key"] if row else None


def mark_status(org_id: int, source: str, status: str, error: str | None = None) -> None:
    """Reactively flip a configured source's status after a real call succeeds/fails.
    No-op if the org hasn't configured this source (nothing to update)."""
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


def list_expired(org_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM org_data_sources WHERE org_id = ? AND status = 'expired'", (org_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
