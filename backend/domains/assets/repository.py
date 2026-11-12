"""intel_assets (one row per (kind, key), shared by every organization) through SQLAlchemy Core."""
from __future__ import annotations

import json
import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import sa
from .models import intel_assets as a


def get_asset(kind: str, key: str) -> dict | None:
    """{content: bytes, content_type, meta, created_at} or None."""
    with sa.begin() as conn:
        row = conn.execute(select(a.c.content, a.c.content_type, a.c.meta_json, a.c.created_at)
                           .where(a.c.kind == kind, a.c.key == key)).first()
    if row is None:
        return None
    return {"content": bytes(row.content), "content_type": row.content_type, "meta": json.loads(row.meta_json or "{}"),
            "created_at": row.created_at}


def put_asset(kind: str, key: str, content: bytes, content_type: str, meta: dict) -> None:
    stmt = pg_insert(a).values(kind=kind, key=key, content=content, content_type=content_type,
                               meta_json=json.dumps(meta, default=str), created_at=time.time())
    with sa.begin() as conn:      # no RETURNING: the row holds the file bytes
        conn.execute(stmt.on_conflict_do_update(index_elements=[a.c.kind, a.c.key], set_={
            c: stmt.excluded[c] for c in ("content", "content_type", "meta_json", "created_at")}))
