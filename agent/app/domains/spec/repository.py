"""Research Specifications repository (connection helper: core/db.py)."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Optional

from ...core.db import _conn
from ..projects.repository import get_project, update_project

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


def save_research_spec(
    project_id: int,
    spec: dict,
    raw_brief_text: str = "",
    generation_source: str = "manual",
    llm_model: str = "",
) -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_research_specifications WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1
    readiness = _compute_readiness(spec)
    cur = conn.execute(
        "INSERT INTO intel_research_specifications "
        "(project_id, version, spec_json, raw_brief_text, status, readiness_status, readiness_json, "
        "generation_source, llm_model, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)",
        (
            project_id, version, json.dumps(spec), raw_brief_text,
            readiness["status"], json.dumps(readiness),
            generation_source, llm_model, now, now,
        ),
    )
    spec_id = cur.lastrowid
    for key in SPEC_SECTION_ORDER:
        conn.execute(
            "INSERT INTO intel_spec_section_approvals "
            "(spec_id, section_key, status, created_at, updated_at) VALUES (?, ?, 'draft', ?, ?)",
            (spec_id, key, now, now),
        )
    conn.commit()
    conn.close()
    return spec_id


def get_latest_spec(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_research_specifications WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    d["spec"] = json.loads(d["spec_json"])
    d["readiness"] = json.loads(d["readiness_json"]) if d.get("readiness_json") else None
    section_rows = conn.execute(
        "SELECT * FROM intel_spec_section_approvals WHERE spec_id = ?", (d["id"],)
    ).fetchall()
    d["section_approvals"] = {r["section_key"]: dict(r) for r in section_rows}
    clar_rows = conn.execute(
        "SELECT * FROM intel_spec_clarifications WHERE spec_id = ? ORDER BY created_at",
        (d["id"],),
    ).fetchall()
    d["clarifications"] = [dict(r) for r in clar_rows]
    conn.close()
    return d


def get_spec_by_id(spec_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_research_specifications WHERE id = ?", (spec_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    d["spec"] = json.loads(d["spec_json"])
    d["readiness"] = json.loads(d["readiness_json"]) if d.get("readiness_json") else None
    section_rows = conn.execute(
        "SELECT * FROM intel_spec_section_approvals WHERE spec_id = ?", (spec_id,)
    ).fetchall()
    d["section_approvals"] = {r["section_key"]: dict(r) for r in section_rows}
    clar_rows = conn.execute(
        "SELECT * FROM intel_spec_clarifications WHERE spec_id = ? ORDER BY created_at",
        (spec_id,),
    ).fetchall()
    d["clarifications"] = [dict(r) for r in clar_rows]
    conn.close()
    return d


def update_spec(spec_id: int, spec: dict) -> bool:
    conn = _conn()
    now = time.time()
    readiness = _compute_readiness(spec)
    conn.execute(
        "UPDATE intel_research_specifications SET spec_json = ?, readiness_status = ?, "
        "readiness_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(spec), readiness["status"], json.dumps(readiness), now, spec_id),
    )
    conn.commit()
    conn.close()
    return True


def update_spec_section(
    spec_id: int, section_key: str, content: Any, analyst_note: str = "", actor: str = "analyst"
) -> bool:
    conn = _conn()
    now = time.time()
    row = conn.execute(
        "SELECT spec_json FROM intel_research_specifications WHERE id = ?", (spec_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    spec = json.loads(row["spec_json"])
    sections = spec.get("sections", {})
    old_value = json.dumps(sections.get(section_key, {}).get("content", ""))
    if section_key in sections:
        sections[section_key]["content"] = content
        sections[section_key]["edited"] = True
    else:
        sections[section_key] = {"title": section_key, "content": content, "edited": True}
    spec["sections"] = sections
    readiness = _compute_readiness(spec)
    conn.execute(
        "UPDATE intel_research_specifications SET spec_json = ?, readiness_status = ?, "
        "readiness_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(spec), readiness["status"], json.dumps(readiness), now, spec_id),
    )
    sa_row = conn.execute(
        "SELECT id FROM intel_spec_section_approvals WHERE spec_id = ? AND section_key = ?",
        (spec_id, section_key),
    ).fetchone()
    if sa_row:
        conn.execute(
            "UPDATE intel_spec_section_approvals SET edited_content = ?, analyst_note = ?, "
            "status = 'edited', updated_at = ? WHERE id = ?",
            (json.dumps(content) if not isinstance(content, str) else content, analyst_note, now, sa_row["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO intel_spec_section_approvals "
            "(spec_id, section_key, status, edited_content, analyst_note, created_at, updated_at) "
            "VALUES (?, ?, 'edited', ?, ?, ?, ?)",
            (spec_id, section_key, json.dumps(content) if not isinstance(content, str) else content, analyst_note, now, now),
        )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, old_value, new_value, actor, created_at) "
        "VALUES (?, 'section_edit', ?, ?, ?, ?, ?)",
        (spec_id, section_key, old_value, json.dumps(content) if not isinstance(content, str) else content, actor, now),
    )
    conn.commit()
    conn.close()
    return True


def update_spec_industry(spec_id: int, name: str, reasoning: str = "", actor: str = "analyst") -> bool:
    """Update the top-level `industry` field (a sibling of `sections`, not a section
    itself — see domains/spec/service.py's spec_data construction)."""
    conn = _conn()
    now = time.time()
    row = conn.execute(
        "SELECT spec_json FROM intel_research_specifications WHERE id = ?", (spec_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    spec = json.loads(row["spec_json"])
    old_value = json.dumps(spec.get("industry") or {})
    spec["industry"] = {"name": name, "reasoning": reasoning}
    conn.execute(
        "UPDATE intel_research_specifications SET spec_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(spec), now, spec_id),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, old_value, new_value, actor, created_at) "
        "VALUES (?, 'industry_edit', 'industry', ?, ?, ?, ?)",
        (spec_id, old_value, json.dumps(spec["industry"]), actor, now),
    )
    conn.commit()
    conn.close()
    return True


def approve_spec_section(
    spec_id: int, section_key: str, reviewer: str = "analyst"
) -> bool:
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_spec_section_approvals SET status = 'approved', reviewed_by = ?, "
        "reviewed_at = ?, updated_at = ? WHERE spec_id = ? AND section_key = ?",
        (reviewer, now, now, spec_id, section_key),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, new_value, actor, created_at) "
        "VALUES (?, 'section_approved', ?, 'approved', ?, ?)",
        (spec_id, section_key, reviewer, now),
    )
    conn.commit()
    conn.close()
    return True


def lock_spec_section(
    spec_id: int, section_key: str, locked_by: str = "analyst"
) -> bool:
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_spec_section_approvals SET is_locked = 1, locked_by = ?, "
        "locked_at = ?, updated_at = ? WHERE spec_id = ? AND section_key = ?",
        (locked_by, now, now, spec_id, section_key),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, new_value, actor, created_at) "
        "VALUES (?, 'section_locked', ?, 'locked', ?, ?)",
        (spec_id, section_key, locked_by, now),
    )
    conn.commit()
    conn.close()
    return True


def unlock_spec_section(
    spec_id: int, section_key: str, actor: str = "analyst"
) -> bool:
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_spec_section_approvals SET is_locked = 0, locked_by = NULL, "
        "locked_at = NULL, updated_at = ? WHERE spec_id = ? AND section_key = ?",
        (now, spec_id, section_key),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, new_value, actor, created_at) "
        "VALUES (?, 'section_unlocked', ?, 'unlocked', ?, ?)",
        (spec_id, section_key, actor, now),
    )
    conn.commit()
    conn.close()
    return True


def approve_full_spec(spec_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    now = time.time()
    row = conn.execute(
        "SELECT readiness_json FROM intel_research_specifications WHERE id = ?", (spec_id,)
    ).fetchone()
    if row and row["readiness_json"]:
        readiness = json.loads(row["readiness_json"])
        if readiness.get("blocking_issues"):
            conn.close()
            return False
    conn.execute(
        "UPDATE intel_research_specifications SET approval_status = 'approved', "
        "approved_by = ?, approved_at = ?, status = 'approved', updated_at = ? WHERE id = ?",
        (reviewer, now, now, spec_id),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, new_value, actor, created_at) "
        "VALUES (?, 'spec_approved', 'approved', ?, ?)",
        (spec_id, reviewer, now),
    )
    conn.commit()
    conn.close()
    return True


def reject_spec(spec_id: int, reason: str = "", reviewer: str = "analyst") -> bool:
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_research_specifications SET approval_status = 'revision_requested', "
        "rejected_reason = ?, status = 'revision_requested', updated_at = ? WHERE id = ?",
        (reason, now, spec_id),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, new_value, actor, created_at) "
        "VALUES (?, 'spec_rejected', ?, ?, ?)",
        (spec_id, reason, reviewer, now),
    )
    conn.commit()
    conn.close()
    return True


def update_spec_docx(spec_id: int, docx_path: str):
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_research_specifications SET docx_path = ?, docx_generated_at = ?, updated_at = ? WHERE id = ?",
        (docx_path, now, now, spec_id),
    )
    conn.commit()
    conn.close()


def list_spec_versions(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT id, version, status, readiness_status, approval_status, generation_source, "
        "docx_path, created_at, updated_at FROM intel_research_specifications "
        "WHERE project_id = ? ORDER BY version DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_spec_audit(spec_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_spec_audit WHERE spec_id = ? ORDER BY created_at DESC",
        (spec_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Research Spec Clarifications ─────────────────────────────────────────────

def add_clarification(
    spec_id: int, question: str, section_key: str = "", is_blocking: bool = True
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_spec_clarifications "
        "(spec_id, section_key, question, is_blocking, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (spec_id, section_key, question, 1 if is_blocking else 0, now, now),
    )
    cid = cur.lastrowid
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, new_value, actor, created_at) "
        "VALUES (?, 'clarification_added', ?, ?, 'system', ?)",
        (spec_id, section_key, question, now),
    )
    _recompute_and_save_readiness(conn, spec_id, now)
    conn.commit()
    conn.close()
    return cid


def resolve_clarification(
    clarification_id: int, answer: str, resolved_by: str = "analyst"
) -> bool:
    conn = _conn()
    now = time.time()
    row = conn.execute(
        "SELECT spec_id, question FROM intel_spec_clarifications WHERE id = ?",
        (clarification_id,),
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE intel_spec_clarifications SET answer = ?, resolved_by = ?, "
        "resolved_at = ?, updated_at = ? WHERE id = ?",
        (answer, resolved_by, now, now, clarification_id),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, old_value, new_value, actor, created_at) "
        "VALUES (?, 'clarification_resolved', ?, ?, ?, ?)",
        (row["spec_id"], row["question"], answer, resolved_by, now),
    )
    _recompute_and_save_readiness(conn, row["spec_id"], now)
    conn.commit()
    conn.close()
    return True


def get_clarifications(spec_id: int, unresolved_only: bool = False) -> list[dict]:
    conn = _conn()
    sql = "SELECT * FROM intel_spec_clarifications WHERE spec_id = ?"
    if unresolved_only:
        sql += " AND resolved_at IS NULL"
    sql += " ORDER BY created_at"
    rows = conn.execute(sql, (spec_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


def _recompute_and_save_readiness(conn: sqlite3.Connection, spec_id: int, now: float):
    row = conn.execute(
        "SELECT spec_json FROM intel_research_specifications WHERE id = ?", (spec_id,)
    ).fetchone()
    if not row:
        return
    spec = json.loads(row["spec_json"])
    readiness = _compute_readiness(spec)
    unresolved = conn.execute(
        "SELECT COUNT(*) as cnt FROM intel_spec_clarifications "
        "WHERE spec_id = ? AND is_blocking = 1 AND resolved_at IS NULL",
        (spec_id,),
    ).fetchone()
    if unresolved and unresolved["cnt"] > 0:
        readiness["blocking_issues"].append(
            f"{unresolved['cnt']} unresolved blocking clarification(s)"
        )
        readiness["status"] = "not_ready"
    conn.execute(
        "UPDATE intel_research_specifications SET readiness_status = ?, readiness_json = ?, updated_at = ? WHERE id = ?",
        (readiness["status"], json.dumps(readiness), now, spec_id),
    )


def get_spec_readiness(spec_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT spec_json, readiness_json FROM intel_research_specifications WHERE id = ?",
        (spec_id,),
    ).fetchone()
    if not row:
        conn.close()
        return None
    spec = json.loads(row["spec_json"])
    readiness = _compute_readiness(spec)
    unresolved = conn.execute(
        "SELECT COUNT(*) as cnt FROM intel_spec_clarifications "
        "WHERE spec_id = ? AND is_blocking = 1 AND resolved_at IS NULL",
        (spec_id,),
    ).fetchone()
    conn.close()
    if unresolved and unresolved["cnt"] > 0:
        readiness["blocking_issues"].append(
            f"{unresolved['cnt']} unresolved blocking clarification(s)"
        )
        readiness["status"] = "not_ready"
    return readiness
