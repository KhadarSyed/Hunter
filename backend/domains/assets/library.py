"""SQL for intel_asset_library (migration 35): one row per shared asset, bytes in S3, summary + embedding here."""
from __future__ import annotations

import json
import time

from ...core.db import _conn

_COLS = "id, kind, key, s3_key, content_type, brand, summary, meta_json, missing, created_at"


def _vec(embedding: list[float] | None) -> str | None:
    return "[" + ",".join(f"{float(x):.6f}" for x in embedding) + "]" if embedding else None


def upsert(kind: str, key: str, *, s3_key: str | None, content_type: str, sha256: str, size: int, brand: str,
           summary: str, meta: dict, embedding: list[float] | None, missing: bool = False) -> int:
    conn = _conn()
    try:
        row = conn.execute(
            "INSERT INTO intel_asset_library (kind, key, s3_key, content_type, sha256, size, brand, summary, "
            "meta_json, embedding, missing, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS vector), ?, ?) "
            "ON CONFLICT (kind, key) DO UPDATE SET s3_key = EXCLUDED.s3_key, content_type = EXCLUDED.content_type, "
            "sha256 = EXCLUDED.sha256, size = EXCLUDED.size, brand = EXCLUDED.brand, summary = EXCLUDED.summary, "
            "meta_json = EXCLUDED.meta_json, embedding = COALESCE(EXCLUDED.embedding, intel_asset_library.embedding), "
            "missing = EXCLUDED.missing, created_at = EXCLUDED.created_at RETURNING id",
            (kind, key, s3_key, content_type, sha256, size, brand.lower(), summary, json.dumps(meta, default=str),
             _vec(embedding), int(missing), time.time())).fetchone()
        conn.commit()
        return int(row[0])
    finally:
        conn.close()


def _out(r) -> dict:
    return {"id": r["id"], "kind": r["kind"], "key": r["key"], "s3_key": r["s3_key"],
            "content_type": r["content_type"], "brand": r["brand"], "summary": r["summary"],
            "meta": json.loads(r["meta_json"] or "{}"), "missing": bool(r["missing"]), "created_at": r["created_at"]}


def get(kind: str, key: str) -> dict | None:
    conn = _conn()
    try:
        r = conn.execute(f"SELECT {_COLS} FROM intel_asset_library WHERE kind = ? AND key = ?", (kind, key)).fetchone()
    finally:
        conn.close()
    return _out(r) if r else None


def touch(asset_id: int) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE intel_asset_library SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                     (time.time(), asset_id))
        conn.commit()
    finally:
        conn.close()


def nearest(kind: str, embedding: list[float], *, brand: str | None = None, role: str | None = None,
            limit: int = 5) -> list[dict]:
    where, args = ["kind = ?", "missing = 0", "embedding IS NOT NULL", "s3_key IS NOT NULL"], [kind]
    if brand is not None:
        where.append("brand = ?")
        args.append(brand.lower())
    if role is not None:
        where.append("CAST(meta_json AS jsonb) ->> 'role' = ?")
        args.append(role)
    conn = _conn()
    try:
        rows = conn.execute(
            f"SELECT {_COLS}, 1 - (embedding <=> CAST(? AS vector)) AS score FROM intel_asset_library "
            f"WHERE {' AND '.join(where)} ORDER BY embedding <=> CAST(? AS vector) LIMIT ?",
            [_vec(embedding), *args, _vec(embedding), limit]).fetchall()
    finally:
        conn.close()
    return [{**_out(r), "score": float(r["score"])} for r in rows]
