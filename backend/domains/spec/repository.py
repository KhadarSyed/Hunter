"""Research Specifications repository through SQLAlchemy Core (models.py): spec versions, section approvals, the
audit trail, clarifications and the readiness engine. Every multi-statement change runs in one transaction."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from sqlalchemy import func, insert, select, update

from ...core import sa
from ..projects.repository import get_project, update_project
from .models import intel_research_specifications as specs
from .models import intel_spec_audit as audit
from .models import intel_spec_clarifications as clarifications
from .models import intel_spec_section_approvals as approvals

# core/store.py star-imports this module: export only the repository functions and the section constants
__all__ = ["FORM_FIELDS", "SPEC_SECTION_ORDER", "MANDATORY_SECTIONS", "update_project_spec", "save_research_spec",
           "get_latest_spec", "get_spec_by_id", "update_spec", "update_spec_section", "update_spec_industry",
           "approve_spec_section", "lock_spec_section", "unlock_spec_section", "approve_full_spec", "reject_spec",
           "update_spec_docx", "list_spec_versions", "get_spec_audit", "add_clarification", "resolve_clarification",
           "remove_clarifications_except", "get_clarifications", "get_spec_readiness", "get_clarification_project_id"]

# ─── Project Spec Update ──────────────────────────────────────────────────────

# Fields entered on the New Project form. The Brief & Scope LLM spec does not carry
# them, so they are kept from the current spec when the analysis saves its result.
FORM_FIELDS = ("raw_brief", "brief_source", "client", "geography", "research_type", "time_period")


def update_project_spec(project_id: int, spec: dict) -> bool:
    """Save the Brief & Scope spec, preserving the form fields (name and brand unchanged)."""
    current = (get_project(project_id) or {}).get("spec") or {}
    kept = {k: current[k] for k in FORM_FIELDS if current.get(k) and not spec.get(k)}
    return update_project(project_id, spec={**spec, **kept})


# ─── Research Specifications ──────────────────────────────────────────────────

SPEC_SECTION_ORDER = [
    "project_understanding",
    "business_objective",
    "research_objectives",
    "research_questions",
    "scope_dimensions",
    "entities",
    "audiences",
    "inclusions",
    "exclusions",
    "methodology",
    "question_method_mapping",
    "data_requirements",
    "metrics",
    "deliverables",
    "assumptions",
    "clarifications",
    "risks",
    "dependencies",
    "success_criteria",
    "approval_status",
]


def _audit(conn, spec_id: int, action: str, actor: str, now: float, *, section_key: str | None = None,
           old_value: str | None = None, new_value: str | None = None) -> None:
    conn.execute(insert(audit).values(spec_id=spec_id, action=action, section_key=section_key, old_value=old_value,
                                      new_value=new_value, actor=actor, created_at=now))


def _as_text(content: Any) -> str:
    return content if isinstance(content, str) else json.dumps(content)


def _readiness_values(spec: dict) -> dict:
    readiness = _compute_readiness(spec)
    return {"readiness_status": readiness["status"], "readiness_json": json.dumps(readiness)}


def save_research_spec(
    project_id: int,
    spec: dict,
    raw_brief_text: str = "",
    generation_source: str = "manual",
    llm_model: str = "",
) -> int:
    """The project's next spec version, as a draft, with a draft approval row per section (one transaction)."""
    now = time.time()
    with sa.begin() as conn:
        version = (conn.execute(select(func.max(specs.c.version)).where(specs.c.project_id == project_id))
                   .scalar() or 0) + 1
        spec_id = conn.execute(insert(specs).values(
            project_id=project_id, version=version, spec_json=json.dumps(spec), raw_brief_text=raw_brief_text,
            status="draft", generation_source=generation_source, llm_model=llm_model, created_at=now, updated_at=now,
            **_readiness_values(spec)).returning(specs.c.id)).scalar_one()
        conn.execute(insert(approvals), [{"spec_id": spec_id, "section_key": key, "status": "draft",
                                          "created_at": now, "updated_at": now} for key in SPEC_SECTION_ORDER])
    return spec_id


def _full_spec(conn, row) -> dict:
    d = dict(row._mapping)
    d["spec"] = json.loads(d["spec_json"])
    d["readiness"] = json.loads(d["readiness_json"]) if d.get("readiness_json") else None
    d["section_approvals"] = {r.section_key: dict(r._mapping)
                              for r in conn.execute(select(approvals).where(approvals.c.spec_id == d["id"]))}
    d["clarifications"] = [dict(r._mapping) for r in conn.execute(
        select(clarifications).where(clarifications.c.spec_id == d["id"]).order_by(clarifications.c.created_at))]
    return d


def get_latest_spec(project_id: int) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(select(specs).where(specs.c.project_id == project_id)
                           .order_by(specs.c.version.desc()).limit(1)).first()
        return _full_spec(conn, row) if row else None


def get_spec_by_id(spec_id: int) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(select(specs).where(specs.c.id == spec_id)).first()
        return _full_spec(conn, row) if row else None


def update_spec(spec_id: int, spec: dict) -> bool:
    with sa.begin() as conn:
        conn.execute(update(specs).where(specs.c.id == spec_id).values(
            spec_json=json.dumps(spec), updated_at=time.time(), **_readiness_values(spec)))
    return True


def update_spec_section(
    spec_id: int, section_key: str, content: Any, analyst_note: str = "", actor: str = "analyst"
) -> bool:
    now = time.time()
    with sa.begin() as conn:
        raw = conn.execute(select(specs.c.spec_json).where(specs.c.id == spec_id)).scalar()
        if raw is None:
            return False
        spec = json.loads(raw)
        sections = spec.get("sections", {})
        old_value = json.dumps(sections.get(section_key, {}).get("content", ""))
        if section_key in sections:
            sections[section_key]["content"] = content
            sections[section_key]["edited"] = True
        else:
            sections[section_key] = {"title": section_key, "content": content, "edited": True}
        spec["sections"] = sections
        conn.execute(update(specs).where(specs.c.id == spec_id).values(
            spec_json=json.dumps(spec), updated_at=now, **_readiness_values(spec)))
        approval_id = conn.execute(select(approvals.c.id).where(approvals.c.spec_id == spec_id,
                                                                approvals.c.section_key == section_key)).scalar()
        if approval_id is not None:
            conn.execute(update(approvals).where(approvals.c.id == approval_id).values(
                edited_content=_as_text(content), analyst_note=analyst_note, status="edited", updated_at=now))
        else:
            conn.execute(insert(approvals).values(spec_id=spec_id, section_key=section_key, status="edited",
                                                  edited_content=_as_text(content), analyst_note=analyst_note,
                                                  created_at=now, updated_at=now))
        _audit(conn, spec_id, "section_edit", actor, now, section_key=section_key, old_value=old_value,
               new_value=_as_text(content))
    return True


def update_spec_industry(spec_id: int, name: str, reasoning: str = "", actor: str = "analyst") -> bool:
    """Update the top-level `industry` field (a sibling of `sections`, not a section
    itself — see domains/spec/service.py's spec_data construction)."""
    now = time.time()
    with sa.begin() as conn:
        raw = conn.execute(select(specs.c.spec_json).where(specs.c.id == spec_id)).scalar()
        if raw is None:
            return False
        spec = json.loads(raw)
        old_value = json.dumps(spec.get("industry") or {})
        spec["industry"] = {"name": name, "reasoning": reasoning}
        conn.execute(update(specs).where(specs.c.id == spec_id).values(spec_json=json.dumps(spec), updated_at=now))
        _audit(conn, spec_id, "industry_edit", actor, now, section_key="industry", old_value=old_value,
               new_value=json.dumps(spec["industry"]))
    return True


def _section_change(spec_id: int, section_key: str, values, action: str, new_value: str, actor: str) -> bool:
    now = time.time()
    with sa.begin() as conn:
        conn.execute(update(approvals).where(approvals.c.spec_id == spec_id, approvals.c.section_key == section_key)
                     .values(**values(now)))
        _audit(conn, spec_id, action, actor, now, section_key=section_key, new_value=new_value)
    return True


def approve_spec_section(spec_id: int, section_key: str, reviewer: str = "analyst") -> bool:
    return _section_change(spec_id, section_key, lambda now: {"status": "approved", "reviewed_by": reviewer,
                                                              "reviewed_at": now, "updated_at": now},
                           "section_approved", "approved", reviewer)


def lock_spec_section(spec_id: int, section_key: str, locked_by: str = "analyst") -> bool:
    return _section_change(spec_id, section_key, lambda now: {"is_locked": 1, "locked_by": locked_by,
                                                              "locked_at": now, "updated_at": now},
                           "section_locked", "locked", locked_by)


def unlock_spec_section(spec_id: int, section_key: str, actor: str = "analyst") -> bool:
    return _section_change(spec_id, section_key, lambda now: {"is_locked": 0, "locked_by": None,
                                                              "locked_at": None, "updated_at": now},
                           "section_unlocked", "unlocked", actor)


def approve_full_spec(spec_id: int, reviewer: str = "analyst") -> bool:
    """Approve the whole spec; refused (False) while its stored readiness lists blocking issues."""
    now = time.time()
    with sa.begin() as conn:
        raw = conn.execute(select(specs.c.readiness_json).where(specs.c.id == spec_id)).scalar()
        if raw and json.loads(raw).get("blocking_issues"):
            return False
        conn.execute(update(specs).where(specs.c.id == spec_id).values(
            approval_status="approved", approved_by=reviewer, approved_at=now, status="approved", updated_at=now))
        _audit(conn, spec_id, "spec_approved", reviewer, now, new_value="approved")
    return True


def reject_spec(spec_id: int, reason: str = "", reviewer: str = "analyst") -> bool:
    now = time.time()
    with sa.begin() as conn:
        conn.execute(update(specs).where(specs.c.id == spec_id).values(
            approval_status="revision_requested", rejected_reason=reason, status="revision_requested",
            updated_at=now))
        _audit(conn, spec_id, "spec_rejected", reviewer, now, new_value=reason)
    return True


def update_spec_docx(spec_id: int, docx_path: str):
    now = time.time()
    with sa.begin() as conn:
        conn.execute(update(specs).where(specs.c.id == spec_id).values(docx_path=docx_path, docx_generated_at=now,
                                                                       updated_at=now))


def list_spec_versions(project_id: int) -> list[dict]:
    s = specs.c
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(
            select(s.id, s.version, s.status, s.readiness_status, s.approval_status, s.generation_source, s.docx_path,
                   s.created_at, s.updated_at).where(s.project_id == project_id).order_by(s.version.desc()))]


def get_spec_audit(spec_id: int) -> list[dict]:
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(select(audit).where(audit.c.spec_id == spec_id)
                                                       .order_by(audit.c.created_at.desc()))]


# ─── Research Spec Clarifications ─────────────────────────────────────────────

def add_clarification(
    spec_id: int, question: str, section_key: str = "", is_blocking: bool = True
) -> int:
    now = time.time()
    with sa.begin() as conn:
        cid = conn.execute(insert(clarifications).values(
            spec_id=spec_id, section_key=section_key, question=question, is_blocking=1 if is_blocking else 0,
            created_at=now, updated_at=now).returning(clarifications.c.id)).scalar_one()
        _audit(conn, spec_id, "clarification_added", "system", now, section_key=section_key, new_value=question)
        _recompute_and_save_readiness(conn, spec_id, now)
    return cid


def resolve_clarification(
    clarification_id: int, answer: str, resolved_by: str = "analyst"
) -> bool:
    now = time.time()
    with sa.begin() as conn:
        row = conn.execute(select(clarifications.c.spec_id, clarifications.c.question)
                           .where(clarifications.c.id == clarification_id)).first()
        if not row:
            return False
        conn.execute(update(clarifications).where(clarifications.c.id == clarification_id).values(
            answer=answer, resolved_by=resolved_by, resolved_at=now, updated_at=now))
        _audit(conn, row.spec_id, "clarification_resolved", resolved_by, now, old_value=row.question,
               new_value=answer)
        _recompute_and_save_readiness(conn, row.spec_id, now)
    return True


def remove_clarifications_except(spec_id: int, keep_questions: set[str]) -> int:
    """Drop a spec's clarifications whose question a reanalysis no longer raises; returns how many went."""
    with sa.begin() as conn:
        rows = conn.execute(select(clarifications.c.id, clarifications.c.question)
                            .where(clarifications.c.spec_id == spec_id)).all()
        stale = [r.id for r in rows if r.question not in keep_questions]
        if stale:
            conn.execute(clarifications.delete().where(clarifications.c.id.in_(stale)))
            _recompute_and_save_readiness(conn, spec_id, time.time())
    return len(stale)


def get_clarifications(spec_id: int, unresolved_only: bool = False) -> list[dict]:
    q = select(clarifications).where(clarifications.c.spec_id == spec_id)
    if unresolved_only:
        q = q.where(clarifications.c.resolved_at.is_(None))
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(q.order_by(clarifications.c.created_at))]


# ─── Readiness Engine ─────────────────────────────────────────────────────────

MANDATORY_SECTIONS = [
    "project_understanding",
    "business_objective",
    "research_objectives",
    "research_questions",
    "scope_dimensions",
    "entities",
    "methodology",
    "data_requirements",
    "deliverables",
    "success_criteria",
]


def _compute_readiness(spec: dict) -> dict:
    sections = spec.get("sections", {})
    blocking_issues: list[str] = []
    warnings: list[str] = []
    section_status: dict[str, str] = {}

    for key in MANDATORY_SECTIONS:
        sec = sections.get(key, {})
        content = sec.get("content", "")
        if not content or (isinstance(content, str) and not content.strip()):
            blocking_issues.append(f"Mandatory section '{key}' is empty")
            section_status[key] = "empty"
        else:
            section_status[key] = "filled"

    rqs = sections.get("research_questions", {}).get("content", [])
    if isinstance(rqs, list) and len(rqs) == 0:
        blocking_issues.append("No research questions defined")
    elif isinstance(rqs, str) and not rqs.strip():
        blocking_issues.append("No research questions defined")

    entities_content = sections.get("entities", {}).get("content", [])
    if isinstance(entities_content, list) and len(entities_content) == 0:
        blocking_issues.append("No entities identified")

    for key in SPEC_SECTION_ORDER:
        if key not in section_status:
            sec = sections.get(key, {})
            content = sec.get("content", "")
            if not content or (isinstance(content, str) and not content.strip()):
                if key not in MANDATORY_SECTIONS:
                    warnings.append(f"Optional section '{key}' is empty")
                    section_status[key] = "empty"
            else:
                section_status[key] = "filled"

    filled_count = sum(1 for v in section_status.values() if v == "filled")
    total_count = len(SPEC_SECTION_ORDER)

    status = "ready" if not blocking_issues else "not_ready"
    return {
        "status": status,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "section_status": section_status,
        "filled_count": filled_count,
        "total_count": total_count,
        "completeness_pct": round((filled_count / total_count) * 100) if total_count else 0,
    }


def _unresolved_blocking(conn, spec_id: int) -> int:
    return conn.execute(select(func.count()).select_from(clarifications).where(
        clarifications.c.spec_id == spec_id, clarifications.c.is_blocking == 1,
        clarifications.c.resolved_at.is_(None))).scalar_one()


def _readiness_with_clarifications(conn, spec_id: int, spec: dict) -> dict:
    readiness = _compute_readiness(spec)
    open_count = _unresolved_blocking(conn, spec_id)
    if open_count > 0:
        readiness["blocking_issues"].append(f"{open_count} unresolved blocking clarification(s)")
        readiness["status"] = "not_ready"
    return readiness


def _recompute_and_save_readiness(conn, spec_id: int, now: float):
    raw = conn.execute(select(specs.c.spec_json).where(specs.c.id == spec_id)).scalar()
    if raw is None:
        return
    readiness = _readiness_with_clarifications(conn, spec_id, json.loads(raw))
    conn.execute(update(specs).where(specs.c.id == spec_id).values(
        readiness_status=readiness["status"], readiness_json=json.dumps(readiness), updated_at=now))


def get_spec_readiness(spec_id: int) -> Optional[dict]:
    with sa.begin() as conn:
        raw = conn.execute(select(specs.c.spec_json).where(specs.c.id == spec_id)).scalar()
        if raw is None:
            return None
        return _readiness_with_clarifications(conn, spec_id, json.loads(raw))


def get_clarification_project_id(clarification_id: int) -> int | None:
    """The project owning a clarification (through its spec), for the access check; None when there is none."""
    with sa.begin() as conn:
        return conn.execute(select(specs.c.project_id).select_from(
            clarifications.join(specs, specs.c.id == clarifications.c.spec_id))
            .where(clarifications.c.id == clarification_id)).scalar()
