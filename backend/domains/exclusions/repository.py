"""intel_exclusions (one row per excluded domain or keyword, scoped to an organization) through SQLAlchemy Core."""
from __future__ import annotations

import time

from sqlalchemy import delete, insert, select

from ...core import sa
from .models import intel_exclusions as x

# core/store.py star-imports this module: export only the repository functions, not SQLAlchemy helpers
__all__ = ["list_exclusions", "add_exclusion", "add_exclusions", "get_exclusion", "delete_exclusion"]


def list_exclusions(org_id: int | None) -> list[dict]:
    scope = x.c.org_id.is_(None) if org_id is None else x.c.org_id == org_id
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(select(x).where(scope).order_by(x.c.kind, x.c.value))]


def add_exclusion(org_id: int | None, kind: str, value: str, user_id: int) -> dict:
    with sa.begin() as conn:
        row = conn.execute(insert(x).values(org_id=org_id, kind=kind, value=value, created_by=user_id,
                                            created_at=time.time()).returning(*x.c)).one()
    return dict(row._mapping)


def add_exclusions(org_id: int | None, kind: str, values: list[str], user_id: int) -> int:
    """Many rules in one transaction (bulk import); returns how many were added."""
    if not values:
        return 0
    now = time.time()
    with sa.begin() as conn:
        conn.execute(insert(x), [{"org_id": org_id, "kind": kind, "value": v, "created_by": user_id,
                                  "created_at": now} for v in values])
    return len(values)


def get_exclusion(exclusion_id: int) -> dict | None:
    with sa.begin() as conn:
        row = conn.execute(select(x).where(x.c.id == exclusion_id)).first()
    return dict(row._mapping) if row else None


def delete_exclusion(exclusion_id: int) -> None:
    with sa.begin() as conn:
        conn.execute(delete(x).where(x.c.id == exclusion_id))
