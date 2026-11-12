"""Analyst Orientation Briefs repository, through SQLAlchemy Core (models.py)."""

from __future__ import annotations

import json
import time
from typing import Optional

from sqlalchemy import func, insert, select, update

from ...core import sa
from .models import intel_background_briefs as briefs
from .models import intel_brief_section_edits as edits

# core/store.py star-imports this module: export only the repository functions
__all__ = ["save_background_brief", "get_latest_brief", "get_brief_by_id", "update_brief_section", "approve_brief",
           "reject_brief", "update_brief_docx", "list_brief_versions"]


def _with_brief(row) -> Optional[dict]:
    if not row:
        return None
    d = dict(row._mapping)
    d["brief"] = json.loads(d["brief_json"])
    return d


def save_background_brief(project_id: int, research_id: int, brief: dict) -> int:
    """The project's next brief version, as a draft (version read and row written in one transaction)."""
    now = time.time()
    with sa.begin() as conn:
        version = (conn.execute(select(func.max(briefs.c.version)).where(briefs.c.project_id == project_id))
                   .scalar() or 0) + 1
        return conn.execute(insert(briefs).values(
            project_id=project_id, research_id=research_id, version=version, brief_json=json.dumps(brief),
            status="draft", created_at=now, updated_at=now).returning(briefs.c.id)).scalar_one()


def get_latest_brief(project_id: int) -> Optional[dict]:
    with sa.begin() as conn:
        return _with_brief(conn.execute(select(briefs).where(briefs.c.project_id == project_id)
                                        .order_by(briefs.c.version.desc()).limit(1)).first())


def get_brief_by_id(brief_id: int) -> Optional[dict]:
    with sa.begin() as conn:
        return _with_brief(conn.execute(select(briefs).where(briefs.c.id == brief_id)).first())


def update_brief_section(brief_id: int, section_key: str, content: str, analyst_note: str = ""):
    """An analyst edit: the section's content changes (when the section exists) and the edit is logged."""
    now = time.time()
    with sa.begin() as conn:
        row = conn.execute(select(briefs.c.brief_json).where(briefs.c.id == brief_id)).first()
        if not row:
            return
        brief = json.loads(row.brief_json)
        if section_key in brief.get("sections", {}):
            brief["sections"][section_key]["content"] = content
            brief["sections"][section_key]["edited"] = True
            conn.execute(update(briefs).where(briefs.c.id == brief_id)
                         .values(brief_json=json.dumps(brief), updated_at=now))
        conn.execute(insert(edits).values(brief_id=brief_id, section_key=section_key, edited_content=content,
                                          analyst_note=analyst_note, created_at=now))


def approve_brief(brief_id: int, reviewer: str = "analyst") -> bool:
    now = time.time()
    with sa.begin() as conn:
        conn.execute(update(briefs).where(briefs.c.id == brief_id).values(
            approval_status="approved", approved_by=reviewer, approved_at=now, updated_at=now))
    return True


def reject_brief(brief_id: int, notes: str = "") -> bool:
    with sa.begin() as conn:
        conn.execute(update(briefs).where(briefs.c.id == brief_id).values(
            approval_status="revision_requested", notes=notes, updated_at=time.time()))
    return True


def update_brief_docx(brief_id: int, docx_path: str):
    now = time.time()
    with sa.begin() as conn:
        conn.execute(update(briefs).where(briefs.c.id == brief_id).values(
            docx_path=docx_path, docx_generated_at=now, updated_at=now))


def list_brief_versions(project_id: int) -> list[dict]:
    cols = (briefs.c.id, briefs.c.version, briefs.c.status, briefs.c.approval_status, briefs.c.docx_path,
            briefs.c.created_at, briefs.c.updated_at)
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(
            select(*cols).where(briefs.c.project_id == project_id).order_by(briefs.c.version.desc()))]
