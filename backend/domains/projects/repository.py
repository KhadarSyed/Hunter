"""Projects repository (connection helper: core/db.py).

Also contains:
- jobs: Jobs repository (connection helper: core/db.py).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Optional

from ...core.db import _PATH_COLUMNS, _conn, declared_foreign_keys, table_columns, table_names

# ─── Projects ────────────────────────────────────────────────────────────────

DESCRIPTION_MAX_CHARS = 220


def _card_fields(spec: dict) -> dict:
    """Display fields for the project list, derived from the stored spec."""
    text = ""
    for key in ("executive_interpretation", "research_objective", "raw_brief"):
        val = spec.get(key)
        if isinstance(val, str) and val.strip():
            text = " ".join(val.split())
            break
    if len(text) > DESCRIPTION_MAX_CHARS:
        text = text[: DESCRIPTION_MAX_CHARS - 1].rstrip() + "…"
    scope = spec.get("included_scope") if isinstance(spec.get("included_scope"), dict) else {}
    return {
        "description": text,
        "geography": spec.get("geography") or scope.get("geography") or "",
        "client": spec.get("client") or "",
        # {"type": "pdf"|"docx"|...|"text", "file_name": ...}; older projects: pasted text
        "brief_source": spec.get("brief_source") or ({"type": "text"} if spec.get("raw_brief") else None),
    }


def create_project(name: str, spec: dict, project_type: str = "research", brand: str | None = None) -> int:
    """Create a project. `brand` is the Client name from the New Project form (drives the
    Brandfetch logo); it is stored as entered and never inferred from the brief."""
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_projects (project_name, spec_json, project_type, brand, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, json.dumps(spec), project_type, (brand or "").strip() or None, now, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_project(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {**dict(row), "spec": json.loads(row["spec_json"])}


def list_projects(project_type: str | None = None, org_id: int | None = None,
                   owner_user_id: int | None = None, include_archived: bool = False) -> list[dict]:
    """Projects for the list page, newest first, with card fields (brand, description,
    geography, client) resolved server-side so the page needs a single request.
    org_id/owner_user_id scope the list to the caller's role (see projects/router.py);
    archived projects are excluded unless include_archived is True."""
    sql = ("SELECT id, project_name, project_type, brand, spec_json, created_at, updated_at, "
           "org_id, owner_user_id, archived_at FROM intel_projects")
    clauses: list[str] = []
    params: list = []
    if project_type:
        clauses.append("project_type = ?")
        params.append(project_type)
    if org_id is not None:
        clauses.append("org_id = ?")
        params.append(org_id)
    if owner_user_id is not None:
        clauses.append("owner_user_id = ?")
        params.append(owner_user_id)
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    conn = _conn()
    rows = conn.execute(sql + " ORDER BY updated_at DESC", tuple(params)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        spec = json.loads(d.pop("spec_json") or "{}")
        out.append({**d, **_card_fields(spec)})
    return out


def set_project_owner(project_id: int, org_id: int | None, owner_user_id: int) -> None:
    conn = _conn()
    conn.execute("UPDATE intel_projects SET org_id = ?, owner_user_id = ? WHERE id = ?",
                 (org_id, owner_user_id, project_id))
    conn.commit()
    conn.close()


def update_project(
    project_id: int, project_name: str | None = None, spec: dict | None = None, brand: str | None = None
) -> bool:
    """Partially update a project; only provided fields change (brand only when passed)."""
    conn = _conn()
    conn.execute(
        "UPDATE intel_projects SET project_name = COALESCE(?, project_name), "
        "spec_json = COALESCE(?, spec_json), brand = COALESCE(?, brand), updated_at = ? WHERE id = ?",
        (project_name, json.dumps(spec) if spec is not None else None, brand, time.time(), project_id),
    )
    conn.commit()
    conn.close()
    return True


def get_or_create_project(spec: dict, org_id: int | None = None, owner_user_id: int | None = None) -> int:
    """The latest project with the brief's name, or a new one owned by `owner_user_id` (an existing one keeps its owner)."""
    name = ""
    cb = spec.get("commissioning_brand", {})
    if isinstance(cb, dict):
        name = cb.get("name", "")
    if not name:
        name = spec.get("project_name", "Untitled")

    conn = _conn()
    in_org = " AND org_id = ?" if org_id is not None else ""     # never match another org's same-named project
    row = conn.execute(
        f"SELECT id FROM intel_projects WHERE project_name = ?{in_org} ORDER BY created_at DESC, id DESC LIMIT 1",
        (name, org_id) if org_id is not None else (name,),
    ).fetchone()
    conn.close()

    if row:
        return row["id"]
    pid = create_project(name, spec)
    if owner_user_id is not None:
        set_project_owner(pid, org_id, owner_user_id)
    return pid


# ─── Jobs ────────────────────────────────────────────────────────────────────

def create_job(job_id: str, project_id: int, job_type: str) -> str:
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO intel_jobs (id, project_id, job_type, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
        (job_id, project_id, job_type, now),
    )
    conn.commit()
    conn.close()
    return job_id


def update_job(job_id: str, *, status: str | None = None, progress_pct: int | None = None,
               progress_message: str | None = None, result: dict | None = None, error: str | None = None):
    conn = _conn()
    parts = []
    vals = []
    if status is not None:
        parts.append("status = ?")
        vals.append(status)
        if status == "running" and not parts.__contains__("started_at"):
            parts.append("started_at = ?")
            vals.append(time.time())
        if status in ("completed", "failed", "cancelled"):
            parts.append("finished_at = ?")
            vals.append(time.time())
    if progress_pct is not None:
        parts.append("progress_pct = ?")
        vals.append(progress_pct)
    if progress_message is not None:
        parts.append("progress_message = ?")
        vals.append(progress_message)
    if result is not None:
        parts.append("result_json = ?")
        vals.append(json.dumps(result))
    if error is not None:
        parts.append("error = ?")
        vals.append(error)

    if parts:
        vals.append(job_id)
        conn.execute(f"UPDATE intel_jobs SET {', '.join(parts)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def get_job(job_id: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("result_json"):
        d["result"] = json.loads(d["result_json"])
    return d


def list_jobs(project_id: int, job_type: str | None = None) -> list[dict]:
    conn = _conn()
    if job_type:
        rows = conn.execute(
            "SELECT * FROM intel_jobs WHERE project_id = ? AND job_type = ? ORDER BY created_at DESC",
            (project_id, job_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intel_jobs WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("result_json"):
            d["result"] = json.loads(d["result_json"])
        result.append(d)
    return result


def cancel_stale_running_jobs():
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_jobs SET status = 'cancelled', finished_at = ?, error = 'Canceled: stale running job from prior session' "
        "WHERE status = 'running'",
        (now,),
    )
    conn.commit()
    conn.close()


# ─── Project deletion ───────────────────────────────────────────────────────

# Parent links that exist in practice but are not declared as FOREIGN KEYs in the schema.
_UNDECLARED_LINKS: list[tuple[str, str, str]] = [  # (child table, child column, parent table)
    ("intel_word_jobs", "presentation_id", "intel_pc_presentations"),
    ("intel_word_documents", "presentation_id", "intel_pc_presentations"),
    ("intel_word_history", "presentation_id", "intel_pc_presentations"),
    ("intel_word_metrics", "job_id", "intel_word_jobs"),
    ("intel_si_storyline_matches", "storyline_id", "intel_storylines"),
    ("intel_dataset_files", "dataset_id", "intel_datasets"),   # the uploaded file's bytes
]
_ROOT = "intel_projects"
_DELETE_CHUNK = 500  # stay under SQLite's bound-parameter limit


def _child_links(conn) -> dict[str, list[tuple[str, str]]]:
    """parent table -> [(child table, child column)]: the schema's declared FKs, every
    table with a project_id column, and _UNDECLARED_LINKS."""
    links: dict[str, set[tuple[str, str]]] = {}
    tables = table_names(conn)
    for child, col, parent in declared_foreign_keys():   # from the schema, so Postgres (no FKs) gets them too
        if child in tables and parent != child:            # skip self-references (e.g. library canonical_id)
            links.setdefault(parent, set()).add((child, col))
    for t in tables:
        if t != _ROOT and "project_id" in table_columns(conn, t):
            links.setdefault(_ROOT, set()).add((t, "project_id"))
    for child, col, parent in _UNDECLARED_LINKS:
        if child in tables:
            links.setdefault(parent, set()).add((child, col))
    return {k: sorted(v) for k, v in links.items()}


def delete_project(project_id: int) -> dict[str, int] | None:
    """Delete a project and every row that belongs to it (children first) in one
    transaction, then its files on disk inside the data folder (uploads, rendered decks).
    Returns rows deleted per table plus a "files" count, or None if the project doesn't exist."""
    conn = _conn()
    try:
        if not conn.execute("SELECT 1 FROM intel_projects WHERE id = ?", (project_id,)).fetchone():
            return None
        links = _child_links(conn)
        plan: list[tuple[str, list]] = []  # (table, ids), deepest first
        keyed: list[tuple[str, str, list]] = []  # tables with no id column (keyed by their link): deleted by it
        seen: set[tuple[str, object]] = set()

        def collect(table: str, ids: list) -> None:
            for child, col in links.get(table, []):
                if "id" not in table_columns(conn, child):   # e.g. agent_autopilots, intel_deliverable_plans
                    keyed.append((child, col, ids))
                    continue
                found = []
                for i in range(0, len(ids), _DELETE_CHUNK):
                    chunk = ids[i:i + _DELETE_CHUNK]
                    marks = ",".join("?" * len(chunk))
                    found += [r[0] for r in conn.execute(f'SELECT id FROM "{child}" WHERE "{col}" IN ({marks})', chunk)]
                found = [x for x in found if (child, x) not in seen]
                if found:
                    seen.update((child, x) for x in found)
                    collect(child, found)
                    plan.append((child, found))

        collect(_ROOT, [project_id])
        plan.append((_ROOT, [project_id]))
        files = _referenced_files(conn, plan)
        deleted: dict[str, int] = {}
        with conn:
            for table, col, ids in keyed:
                for i in range(0, len(ids), _DELETE_CHUNK):
                    chunk = ids[i:i + _DELETE_CHUNK]
                    marks = ",".join("?" * len(chunk))
                    deleted[table] = deleted.get(table, 0) + conn.execute(
                        f'DELETE FROM "{table}" WHERE "{col}" IN ({marks})', chunk).rowcount
            for table, ids in plan:
                for i in range(0, len(ids), _DELETE_CHUNK):
                    chunk = ids[i:i + _DELETE_CHUNK]
                    marks = ",".join("?" * len(chunk))
                    deleted[table] = deleted.get(table, 0) + conn.execute(
                        f'DELETE FROM "{table}" WHERE id IN ({marks})', chunk).rowcount
        # its files go with its rows, after the commit (a failed delete keeps both): what the rows pointed at, the
        # project's deliverables folder
        from ...core import config
        deleted["files"] = _remove_files(files + [config.DELIVERABLE_DIR / f"project_{project_id}"], config.DATA_DIR)
        return deleted
    finally:
        conn.close()


def _referenced_files(conn, plan: list[tuple[str, list]]) -> list[Path]:
    """Every file or folder the project's rows point at (core.db._PATH_COLUMNS)."""
    out = []
    for table, ids in plan:
        for col in (c for t, c in _PATH_COLUMNS if t == table and not c.endswith("_json")):
            for i in range(0, len(ids), _DELETE_CHUNK):
                chunk = ids[i:i + _DELETE_CHUNK]
                marks = ",".join("?" * len(chunk))
                out += [Path(r[0]) for r in conn.execute(
                    f'SELECT "{col}" FROM "{table}" WHERE id IN ({marks}) AND "{col}" IS NOT NULL', chunk) if r[0]]
    return out


def _remove_files(paths: list[Path], root: Path) -> int:
    """Deletes each file or folder, but only inside the app's data folder: a stray path in a row never reaches
    anything else. Returns how many were removed."""
    root, n = root.resolve(), 0
    for p in dict.fromkeys(paths):
        try:
            target = p.resolve()
        except OSError:
            continue
        if root not in target.parents or not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
        n += 1
    return n
