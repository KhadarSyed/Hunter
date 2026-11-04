"""SQL for the agentic memory store (memory_items, migration 32)."""
from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn


def _row(r) -> dict:
    d = dict(r)
    d["value"] = json.loads(d.pop("value_json"))
    return d


def put_memory_item(scope: str, scope_id: str, type_: str, key: str, value, ttl_seconds: Optional[float] = None) -> None:
    now = time.time()
    expires = now + ttl_seconds if ttl_seconds else None
    conn = _conn()
    conn.execute("INSERT INTO memory_items (scope, scope_id, type, key, value_json, hits, created_at, updated_at, "
                 "expires_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?) ON CONFLICT(scope, scope_id, type, key) DO UPDATE SET "
                 "value_json = excluded.value_json, updated_at = excluded.updated_at, expires_at = excluded.expires_at",
                 (scope, scope_id, type_, key, json.dumps(value, default=str), now, now, expires))
    conn.commit()
    conn.close()


def get_memory_item(scope: str, scope_id: str, type_: str, key: str) -> Optional[dict]:
    """The live (unexpired) item, counting the read as a hit."""
    conn = _conn()
    r = conn.execute("SELECT * FROM memory_items WHERE scope = ? AND scope_id = ? AND type = ? AND key = ? "
                     "AND (expires_at IS NULL OR expires_at > ?)", (scope, scope_id, type_, key, time.time())).fetchone()
    if r:
        conn.execute("UPDATE memory_items SET hits = hits + 1 WHERE id = ?", (r["id"],))
        conn.commit()
    conn.close()
    return _row(r) if r else None


def list_memory_items(scope: str, scope_id: str, type_: str, limit: int = 50) -> list[dict]:
    """Live items, most recently updated first."""
    conn = _conn()
    rows = conn.execute("SELECT * FROM memory_items WHERE scope = ? AND scope_id = ? AND type = ? "
                        "AND (expires_at IS NULL OR expires_at > ?) ORDER BY updated_at DESC LIMIT ?",
                        (scope, scope_id, type_, time.time(), limit)).fetchall()
    conn.close()
    return [_row(r) for r in rows]


def memory_stats() -> list[dict]:
    """Item and hit counts per scope and type, for the /api/intel/memory/stats view."""
    conn = _conn()
    rows = conn.execute("SELECT scope, type, COUNT(*) AS items, COALESCE(SUM(hits), 0) AS hits FROM memory_items "
                        "WHERE expires_at IS NULL OR expires_at > ? GROUP BY scope, type ORDER BY scope, type",
                        (time.time(),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
