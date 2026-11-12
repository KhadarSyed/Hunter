"""The agentic memory store (memory_items, migration 32) through SQLAlchemy Core."""
from __future__ import annotations

import json
import time
from typing import Optional

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import sa
from .models import memory_items as m

# core/store.py star-imports this module: export only the repository functions, not SQLAlchemy helpers
__all__ = ["put_memory_item", "get_memory_item", "purge_expired_memory", "list_memory_items", "memory_stats"]


def _row(r) -> dict:
    d = dict(r._mapping)
    d["value"] = json.loads(d.pop("value_json"))
    return d


def _live(now: float):
    return or_(m.c.expires_at.is_(None), m.c.expires_at > now)


def put_memory_item(scope: str, scope_id: str, type_: str, key: str, value, ttl_seconds: Optional[float] = None) -> None:
    now = time.time()
    stmt = pg_insert(m).values(scope=scope, scope_id=scope_id, type=type_, key=key,
                               value_json=json.dumps(value, default=str), hits=0, created_at=now, updated_at=now,
                               expires_at=now + ttl_seconds if ttl_seconds else None)
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=[m.c.scope, m.c.scope_id, m.c.type, m.c.key], set_={
            c: stmt.excluded[c] for c in ("value_json", "updated_at", "expires_at")}))


def get_memory_item(scope: str, scope_id: str, type_: str, key: str) -> Optional[dict]:
    """The live (unexpired) item, counting the read as a hit."""
    with sa.begin() as conn:
        r = conn.execute(select(m).where(m.c.scope == scope, m.c.scope_id == scope_id, m.c.type == type_,
                                         m.c.key == key, _live(time.time()))).first()
        if r:
            conn.execute(update(m).where(m.c.id == r.id).values(hits=m.c.hits + 1))
    return _row(r) if r else None


def purge_expired_memory() -> int:
    """Delete expired items (reads already skip them; this keeps the table from growing). Returns the count."""
    with sa.begin() as conn:
        return conn.execute(delete(m).where(m.c.expires_at.is_not(None), m.c.expires_at < time.time())).rowcount


def list_memory_items(scope: str, scope_id: str, type_: str, limit: int = 50) -> list[dict]:
    """Live items, most recently updated first."""
    with sa.begin() as conn:
        rows = conn.execute(select(m).where(m.c.scope == scope, m.c.scope_id == scope_id, m.c.type == type_,
                                            _live(time.time())).order_by(m.c.updated_at.desc()).limit(limit)).all()
    return [_row(r) for r in rows]


def memory_stats() -> list[dict]:
    """Item and hit counts per scope and type, for the /api/intel/memory/stats view."""
    q = (select(m.c.scope, m.c.type, func.count().label("items"), func.coalesce(func.sum(m.c.hits), 0).label("hits"))
         .where(_live(time.time())).group_by(m.c.scope, m.c.type).order_by(m.c.scope, m.c.type))
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]
