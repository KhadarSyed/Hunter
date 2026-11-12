"""Research Plans repository, through SQLAlchemy Core (models.py)."""

from __future__ import annotations

import json
import time
from typing import Optional

from sqlalchemy import func, insert, select, update

from ...core import sa
from .models import intel_research_plans as plans

# core/store.py star-imports this module: export only the repository functions
__all__ = ["save_research_plan", "get_latest_plan", "approve_plan", "reject_plan", "get_plan_project_id"]


def save_research_plan(project_id: int, plan: dict, source: str = "llm") -> int:
    """The project's next plan version, as a draft (version read and row written in one transaction)."""
    with sa.begin() as conn:
        version = (conn.execute(select(func.max(plans.c.version)).where(plans.c.project_id == project_id))
                   .scalar() or 0) + 1
        return conn.execute(insert(plans).values(
            project_id=project_id, version=version, status="draft", plan_json=json.dumps(plan), source=source,
            created_at=time.time()).returning(plans.c.id)).scalar_one()


def get_latest_plan(project_id: int) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(select(plans).where(plans.c.project_id == project_id)
                           .order_by(plans.c.version.desc()).limit(1)).first()
    if not row:
        return None
    d = dict(row._mapping)
    d["plan"] = json.loads(d["plan_json"])
    return d


def approve_plan(plan_id: int, reviewer: str = "analyst") -> bool:
    with sa.begin() as conn:
        return conn.execute(update(plans).where(plans.c.id == plan_id).values(
            approval_status="approved", approved_by=reviewer, approved_at=time.time())).rowcount > 0


def reject_plan(plan_id: int, notes: str = "") -> bool:
    with sa.begin() as conn:
        return conn.execute(update(plans).where(plans.c.id == plan_id).values(
            approval_status="rejected", notes=notes)).rowcount > 0


def get_plan_project_id(plan_id: int) -> int | None:
    """The project owning a plan, for the access check; None when there is none."""
    with sa.begin() as conn:
        return conn.execute(select(plans.c.project_id).where(plans.c.id == plan_id)).scalar()
