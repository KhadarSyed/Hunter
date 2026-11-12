"""SQL for intel_asset_library (migration 35) through SQLAlchemy Core: one row per shared asset, bytes in S3, summary
+ embedding (pgvector) here."""
from __future__ import annotations

import json
import time

from sqlalchemy import cast, delete as sql_delete, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert

from ...core import sa
from .models import intel_asset_library as L

_COLS = (L.c.id, L.c.kind, L.c.key, L.c.s3_key, L.c.content_type, L.c.brand, L.c.summary, L.c.meta_json, L.c.missing,
         L.c.created_at)


def upsert(kind: str, key: str, *, s3_key: str | None, content_type: str, sha256: str, size: int, brand: str,
           summary: str, meta: dict, embedding: list[float] | None, missing: bool = False) -> int:
    """Insert or replace the (kind, key) row; a new row without an embedding keeps the stored one."""
    stmt = pg_insert(L).values(kind=kind, key=key, s3_key=s3_key, content_type=content_type, sha256=sha256, size=size,
                               brand=brand.lower(), summary=summary, meta_json=json.dumps(meta, default=str),
                               embedding=[float(x) for x in embedding] if embedding else None, missing=int(missing),
                               created_at=time.time())
    new = stmt.excluded
    with sa.begin() as conn:
        return int(conn.execute(stmt.on_conflict_do_update(index_elements=[L.c.kind, L.c.key], set_={
            "s3_key": new.s3_key, "content_type": new.content_type, "sha256": new.sha256, "size": new.size,
            "brand": new.brand, "summary": new.summary, "meta_json": new.meta_json,
            "embedding": func.coalesce(new.embedding, L.c.embedding, type_=L.c.embedding.type), "missing": new.missing,
            "created_at": new.created_at}).returning(L.c.id)).scalar_one())


def delete(kind: str, key: str) -> None:
    with sa.begin() as conn:
        conn.execute(sql_delete(L).where(L.c.kind == kind, L.c.key == key))


def _out(r) -> dict:
    return {"id": r["id"], "kind": r["kind"], "key": r["key"], "s3_key": r["s3_key"],
            "content_type": r["content_type"], "brand": r["brand"], "summary": r["summary"],
            "meta": json.loads(r["meta_json"] or "{}"), "missing": bool(r["missing"]), "created_at": r["created_at"]}


def get(kind: str, key: str) -> dict | None:
    with sa.begin() as conn:
        r = conn.execute(select(*_COLS).where(L.c.kind == kind, L.c.key == key)).first()
    return _out(r._mapping) if r else None


def touch(asset_id: int) -> None:
    with sa.begin() as conn:
        conn.execute(update(L).where(L.c.id == asset_id).values(use_count=L.c.use_count + 1, last_used_at=time.time()))


def nearest(kind: str, embedding: list[float], *, brand: str | None = None, role: str | None = None,
            limit: int = 5) -> list[dict]:
    """The stored assets of this kind closest to `embedding` (cosine), each with its score (1 = identical)."""
    distance = L.c.embedding.cosine_distance([float(x) for x in embedding])
    q = select(*_COLS, (1 - distance).label("score")).where(
        L.c.kind == kind, L.c.missing == 0, L.c.embedding.isnot(None), L.c.s3_key.isnot(None))
    if brand is not None:
        q = q.where(L.c.brand == brand.lower())
    if role is not None:
        q = q.where(cast(L.c.meta_json, JSONB)["role"].astext == role)
    with sa.begin() as conn:
        rows = conn.execute(q.order_by(distance).limit(limit)).all()
    return [{**_out(r._mapping), "score": float(r._mapping["score"])} for r in rows]
