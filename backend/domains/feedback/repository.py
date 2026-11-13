"""SQL for analyst corrections (intel_tag_feedback) through SQLAlchemy Core."""
from __future__ import annotations

import time

from sqlalchemy import func, insert, select

from ...core import sa
from .models import intel_tag_feedback as F

__all__ = ["save_feedback", "count_feedback", "nearest_feedback"]


def save_feedback(rows: list[dict]) -> int:
    """rows: dicts with the table's columns (embedding a list of floats or None). Returns how many were saved."""
    if not rows:
        return 0
    now = time.time()
    with sa.begin() as conn:
        conn.execute(insert(F), [{"created_at": now, **r} for r in rows])
    return len(rows)


def count_feedback(org_id: int | None, kinds: tuple[str, ...]) -> int:
    with sa.begin() as conn:
        return int(conn.execute(select(func.count()).select_from(F).where(
            F.c.org_id.is_not_distinct_from(org_id), F.c.kind.in_(kinds), F.c.embedding.isnot(None))).scalar())


def nearest_feedback(org_id: int | None, kinds: tuple[str, ...], embedding: list[float], model: str,
                     limit: int = 3) -> list[dict]:
    """The organization's corrections of these kinds closest to `embedding` (cosine), each with its score."""
    distance = F.c.embedding.cosine_distance([float(x) for x in embedding])
    q = (select(F.c.id, F.c.kind, F.c.rq_id, F.c.question, F.c.before_json, F.c.after_json, F.c.comment,
                F.c.article_text, (1 - distance).label("score"))
         .where(F.c.org_id.is_not_distinct_from(org_id), F.c.kind.in_(kinds), F.c.embedding.isnot(None),
                F.c.model == model)
         .order_by(distance).limit(limit))
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]
