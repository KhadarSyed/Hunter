"""org_guardrails through SQLAlchemy Core (models.py)."""
from __future__ import annotations

import time

from sqlalchemy import delete, func, insert, select, update

from ...core import sa
from .models import org_guardrails as g
from .models import organizations


def list_guardrails(org_id: int, active_only: bool = False) -> list[dict]:
    q = select(g).where(g.c.org_id == org_id).order_by(g.c.id)
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(q.where(g.c.active == 1) if active_only else q)]


def get_guardrail(gid: int) -> dict | None:
    with sa.begin() as conn:
        row = conn.execute(select(g).where(g.c.id == gid)).first()
    return dict(row._mapping) if row else None


def add_guardrail(org_id: int, title: str, body: str, active: bool, user_id: int | None) -> int:
    now = time.time()
    with sa.begin() as conn:
        return conn.execute(insert(g).values(org_id=org_id, title=title, body=body, active=int(active),
                                             updated_by=user_id, created_at=now, updated_at=now)
                            .returning(g.c.id)).scalar_one()


def update_guardrail(gid: int, title: str, body: str, active: bool, user_id: int | None) -> None:
    with sa.begin() as conn:
        conn.execute(update(g).where(g.c.id == gid).values(title=title, body=body, active=int(active),
                                                           updated_by=user_id, updated_at=time.time()))


def delete_guardrail(gid: int) -> None:
    with sa.begin() as conn:
        conn.execute(delete(g).where(g.c.id == gid))


def org_id_by_name(name: str) -> int | None:
    o = organizations
    with sa.begin() as conn:
        return conn.execute(select(o.c.id).where(func.lower(func.trim(o.c.name)) == func.lower(func.trim(name)))
                            .order_by(o.c.id).limit(1)).scalar()
