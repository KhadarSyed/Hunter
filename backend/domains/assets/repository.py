"""SQL for intel_assets: one row per (kind, key), shared by every organization."""
from __future__ import annotations

import json
import time

from ...core.db import _conn


def get_asset(kind: str, key: str) -> dict | None:
    """{content: bytes, content_type, meta, created_at} or None."""
    conn = _conn()
    try:
        row = conn.execute("SELECT content, content_type, meta_json, created_at FROM intel_assets "
                           "WHERE kind = ? AND key = ?", (kind, key)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"content": bytes(row[0]), "content_type": row[1], "meta": json.loads(row[2] or "{}"),
            "created_at": row[3]}


def put_asset(kind: str, key: str, content: bytes, content_type: str, meta: dict) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO intel_assets (kind, key, content, content_type, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (kind, key) DO UPDATE SET content = EXCLUDED.content, content_type = EXCLUDED.content_type, "
            "meta_json = EXCLUDED.meta_json, created_at = EXCLUDED.created_at RETURNING kind",
            (kind, key, content, content_type, json.dumps(meta, default=str), time.time()))
        conn.commit()
    finally:
        conn.close()


def delete_asset(kind: str, key: str) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM intel_assets WHERE kind = ? AND key = ?", (kind, key))
        conn.commit()
    finally:
        conn.close()
