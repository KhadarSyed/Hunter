"""Projects and their background jobs, through SQLAlchemy Core (models.py), plus project deletion: every row that
belongs to a project, found through the schema's links, deleted children-first in one transaction."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Optional

from sqlalchemy import column, delete, func, insert, select, table, update

from ...core import sa
from ...core.db import _PATH_COLUMNS, declared_foreign_keys
from .models import intel_jobs as jobs
from .models import intel_projects as projects

# core/store.py star-imports this module: export only the repository functions and the card text limit
__all__ = ["DESCRIPTION_MAX_CHARS", "create_project", "get_project", "list_projects", "set_project_owner",
           "update_project", "get_or_create_project", "create_job", "update_job", "get_job", "list_jobs",
           "cancel_stale_running_jobs", "delete_project", "project_name_taken"]

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
    now = time.time()
    with sa.begin() as conn:
        return conn.execute(insert(projects).values(
            project_name=name, spec_json=json.dumps(spec), project_type=project_type,
            brand=(brand or "").strip() or None, created_at=now, updated_at=now).returning(projects.c.id)).scalar_one()


def get_project(project_id: int) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(select(projects).where(projects.c.id == project_id)).first()
    if not row:
        return None
    d = dict(row._mapping)
    return {**d, "spec": json.loads(d["spec_json"])}


def list_projects(project_type: str | None = None, org_id: int | None = None,
                  owner_user_id: int | None = None, include_archived: bool = False) -> list[dict]:
    """Projects for the list page, newest first, with card fields (brand, description,
    geography, client) resolved server-side so the page needs a single request.
    org_id/owner_user_id scope the list to the caller's role (see projects/router.py);
    archived projects are excluded unless include_archived is True."""
    p = projects.c
    q = select(p.id, p.project_name, p.project_type, p.brand, p.spec_json, p.created_at, p.updated_at, p.org_id,
               p.owner_user_id, p.archived_at).order_by(p.updated_at.desc())
    if project_type:
        q = q.where(p.project_type == project_type)
    if org_id is not None:
        q = q.where(p.org_id == org_id)
    if owner_user_id is not None:
        q = q.where(p.owner_user_id == owner_user_id)
    if not include_archived:
        q = q.where(p.archived_at.is_(None))
    with sa.begin() as conn:
        rows = [dict(r._mapping) for r in conn.execute(q)]
    out = []
    for d in rows:
        spec = json.loads(d.pop("spec_json") or "{}")
        out.append({**d, **_card_fields(spec)})
    return out


def set_project_owner(project_id: int, org_id: int | None, owner_user_id: int) -> None:
    with sa.begin() as conn:
        conn.execute(update(projects).where(projects.c.id == project_id)
                     .values(org_id=org_id, owner_user_id=owner_user_id))


def update_project(
    project_id: int, project_name: str | None = None, spec: dict | None = None, brand: str | None = None
) -> bool:
    """Partially update a project; only provided fields change (brand only when passed)."""
    values: dict = {"updated_at": time.time()}
    if project_name is not None:
        values["project_name"] = project_name
    if spec is not None:
        values["spec_json"] = json.dumps(spec)
    if brand is not None:
        values["brand"] = brand
    with sa.begin() as conn:
        conn.execute(update(projects).where(projects.c.id == project_id).values(**values))
    return True


def get_or_create_project(spec: dict, org_id: int | None = None, owner_user_id: int | None = None) -> int:
    """The latest project with the brief's name, or a new one owned by `owner_user_id` (an existing one keeps its owner)."""
    name = ""
    cb = spec.get("commissioning_brand", {})
    if isinstance(cb, dict):
        name = cb.get("name", "")
    if not name:
        name = spec.get("project_name", "Untitled")
    q = select(projects.c.id).where(projects.c.project_name == name)
    if org_id is not None:                      # never match another org's same-named project
        q = q.where(projects.c.org_id == org_id)
    with sa.begin() as conn:
        found = conn.execute(q.order_by(projects.c.created_at.desc(), projects.c.id.desc()).limit(1)).scalar()
    if found is not None:
        return found
    pid = create_project(name, spec)
    if owner_user_id is not None:
        set_project_owner(pid, org_id, owner_user_id)
    return pid


def project_name_taken(org_id: int | None, name: str, exclude_id: int | None = None) -> bool:
    """Project names are unique within an organization, ignoring case and surrounding spaces (archived included).
    shortcut: checked, not indexed (a project gets its org right after the insert); a same-second race could slip by."""
    p = projects.c
    q = select(p.id).where(p.org_id.is_(None) if org_id is None else p.org_id == org_id,
                           func.lower(func.trim(p.project_name)) == func.lower(func.trim(name)))
    if exclude_id is not None:
        q = q.where(p.id != exclude_id)
    with sa.begin() as conn:
        return conn.execute(q.limit(1)).first() is not None


# ─── Jobs ────────────────────────────────────────────────────────────────────

def _with_result(d: dict) -> dict:
    if d.get("result_json"):
        d["result"] = json.loads(d["result_json"])
    return d


def create_job(job_id: str, project_id: int, job_type: str) -> str:
    with sa.begin() as conn:
        conn.execute(insert(jobs).values(id=job_id, project_id=project_id, job_type=job_type, status="pending",
                                         created_at=time.time()))
    return job_id


def update_job(job_id: str, *, status: str | None = None, progress_pct: int | None = None,
               progress_message: str | None = None, result: dict | None = None, error: str | None = None):
    values: dict = {}
    if status is not None:
        values["status"] = status
        if status == "running":                     # (re)set on every move to running, as before
            values["started_at"] = time.time()
        if status in ("completed", "failed", "cancelled"):
            values["finished_at"] = time.time()
    if progress_pct is not None:
        values["progress_pct"] = progress_pct
    if progress_message is not None:
        values["progress_message"] = progress_message
    if result is not None:
        values["result_json"] = json.dumps(result)
    if error is not None:
        values["error"] = error
    if values:
        with sa.begin() as conn:
            conn.execute(update(jobs).where(jobs.c.id == job_id).values(**values))


def get_job(job_id: str) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(select(jobs).where(jobs.c.id == job_id)).first()
    return _with_result(dict(row._mapping)) if row else None


def list_jobs(project_id: int, job_type: str | None = None) -> list[dict]:
    q = select(jobs).where(jobs.c.project_id == project_id).order_by(jobs.c.created_at.desc())
    if job_type:
        q = q.where(jobs.c.job_type == job_type)
    with sa.begin() as conn:
        return [_with_result(dict(r._mapping)) for r in conn.execute(q)]


def cancel_stale_running_jobs():
    with sa.begin() as conn:
        conn.execute(update(jobs).where(jobs.c.status.in_(("running", "pending")))     # queued jobs die with the process too
                     .values(status="cancelled", finished_at=time.time(),
                             error="Canceled: stale job from prior session"))


# ─── Project deletion ───────────────────────────────────────────────────────

# Parent links that exist in practice but are not declared as FOREIGN KEYs in the schema.
_UNDECLARED_LINKS: list[tuple[str, str, str]] = [  # (child table, child column, parent table)
    ("intel_word_jobs", "presentation_id", "intel_pc_presentations"),
    ("intel_word_documents", "presentation_id", "intel_pc_presentations"),
    ("intel_word_history", "presentation_id", "intel_pc_presentations"),
    ("intel_word_metrics", "job_id", "intel_word_jobs"),
    ("intel_si_storyline_matches", "storyline_id", "intel_storylines"),
    ("intel_dataset_files", "dataset_id", "intel_datasets"),   # the uploaded file's bytes
    ("intel_deliverable_sections", "run_id", "intel_deliverable_runs"),   # a deck's content; was left behind before
]
_ROOT = "intel_projects"
_DELETE_CHUNK = 500  # keeps each IN list bounded

_info_columns = table("columns", column("table_name"), column("column_name"), column("table_schema"),
                      schema="information_schema")
_info_tables = table("tables", column("table_name"), column("table_schema"), schema="information_schema")


def _schema_columns(conn) -> dict[str, set[str]]:
    """Every table of the current schema (tests: their own) and its columns, read once per deletion."""
    tables = set(conn.execute(select(_info_tables.c.table_name)
                              .where(_info_tables.c.table_schema == func.current_schema())).scalars())
    cols: dict[str, set[str]] = {t: set() for t in tables}
    for t, c in conn.execute(select(_info_columns.c.table_name, _info_columns.c.column_name)
                             .where(_info_columns.c.table_schema == func.current_schema())):
        if t in cols:
            cols[t].add(c)
    return cols


def _child_links(columns: dict[str, set[str]]) -> dict[str, list[tuple[str, str]]]:
    """parent table -> [(child table, child column)]: the schema's declared FKs, every
    table with a project_id column, and _UNDECLARED_LINKS."""
    links: dict[str, set[tuple[str, str]]] = {}
    for child, col, parent in declared_foreign_keys():   # from the schema, so Postgres (no FKs) gets them too
        if child in columns and parent != child:          # skip self-references (e.g. library canonical_id)
            links.setdefault(parent, set()).add((child, col))
    for t, cols in columns.items():
        if t != _ROOT and "project_id" in cols:
            links.setdefault(_ROOT, set()).add((t, "project_id"))
    for child, col, parent in _UNDECLARED_LINKS:
        if child in columns:
            links.setdefault(parent, set()).add((child, col))
    return {k: sorted(v) for k, v in links.items()}


def _chunks(ids: list):
    for i in range(0, len(ids), _DELETE_CHUNK):
        yield ids[i:i + _DELETE_CHUNK]


def delete_project(project_id: int) -> dict[str, int] | None:
    """Delete a project and every row that belongs to it (children first) in one
    transaction, then its files on disk inside the data folder (uploads, rendered decks).
    Returns rows deleted per table plus a "files" count, or None if the project doesn't exist."""
    with sa.begin() as conn:
        if conn.execute(select(projects.c.id).where(projects.c.id == project_id)).first() is None:
            return None
        columns = _schema_columns(conn)
        links = _child_links(columns)
        plan: list[tuple[str, list]] = []          # (table, ids), deepest first
        keyed: list[tuple[str, str, list]] = []    # tables with no id column (keyed by their link): deleted by it
        seen: set[tuple[str, object]] = set()

        def collect(parent: str, ids: list) -> None:
            for child, col in links.get(parent, []):
                if "id" not in columns.get(child, ()):    # e.g. agent_autopilots, intel_deliverable_plans
                    keyed.append((child, col, ids))
                    continue
                t = table(child, column("id"), column(col))
                found = []
                for chunk in _chunks(ids):
                    found += list(conn.execute(select(t.c.id).where(t.c[col].in_(chunk))).scalars())
                found = [x for x in found if (child, x) not in seen]
                if found:
                    seen.update((child, x) for x in found)
                    collect(child, found)
                    plan.append((child, found))

        collect(_ROOT, [project_id])
        plan.append((_ROOT, [project_id]))
        files = _referenced_files(conn, plan)
        deleted: dict[str, int] = {}
        for name, col, ids in keyed:
            t = table(name, column(col))
            for chunk in _chunks(ids):
                deleted[name] = deleted.get(name, 0) + conn.execute(delete(t).where(t.c[col].in_(chunk))).rowcount
        for name, ids in plan:
            t = table(name, column("id"))
            for chunk in _chunks(ids):
                deleted[name] = deleted.get(name, 0) + conn.execute(delete(t).where(t.c.id.in_(chunk))).rowcount
        # project-scoped memory is keyed by scope/scope_id, not a project_id column, so _child_links misses it
        memory = table("memory_items", column("scope"), column("scope_id"))
        deleted["memory_items"] = conn.execute(delete(memory).where(memory.c.scope == "project",
                                                                    memory.c.scope_id == str(project_id))).rowcount
    # its files go with its rows, after the commit (a failed delete keeps both): what the rows pointed at, the
    # project's deliverables folder
    from ...core import config
    deleted["files"] = _remove_files(files + [config.DELIVERABLE_DIR / f"project_{project_id}"], config.DATA_DIR)
    return deleted


def _referenced_files(conn, plan: list[tuple[str, list]]) -> list[Path]:
    """Every file or folder the project's rows point at (core.db._PATH_COLUMNS)."""
    out = []
    for name, ids in plan:
        for col in (c for t, c in _PATH_COLUMNS if t == name and not c.endswith("_json")):
            t = table(name, column("id"), column(col))
            for chunk in _chunks(ids):
                out += [Path(v) for v in conn.execute(select(t.c[col]).where(t.c.id.in_(chunk), t.c[col].is_not(None)))
                        .scalars() if v]
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
