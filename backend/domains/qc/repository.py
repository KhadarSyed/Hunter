"""QC flow repository (reports, runs, findings, exports), through SQLAlchemy Core (models.py)."""

from __future__ import annotations

import json
import time
from typing import Optional

from sqlalchemy import insert, select, update

from ...core import sa
from .models import qc_exports, qc_findings, qc_reports, qc_runs, qc_source_cache

# core/store.py star-imports this module: export only the repository functions
__all__ = ["create_qc_report", "update_qc_report", "get_qc_report", "get_qc_report_for_project",
           "save_qc_field_mapping", "create_qc_run", "update_qc_run", "get_qc_run", "get_qc_runs_for_report",
           "add_qc_findings_batch", "get_qc_findings", "update_qc_finding_action", "create_qc_export",
           "get_qc_export", "get_qc_run_project_id", "get_qc_finding_project_id", "get_qc_export_project_id",
           "get_cached_source", "upsert_source_cache"]

_REPORT_FIELDS = ("row_count", "column_count", "columns_json", "field_mapping", "parse_status", "parse_error")
_RUN_FIELDS = ("status", "total_rows", "total_checks", "total_findings", "score", "score_breakdown", "started_at",
               "completed_at")


def _stored(v):
    return json.dumps(v) if isinstance(v, (dict, list)) else v


def _loaded(d: dict, *keys: str) -> dict:
    """JSON text columns back to objects; anything that is not JSON is left as stored."""
    for k in keys:
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _one(query) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(query).first()
    return dict(row._mapping) if row else None


def _all(query) -> list[dict]:
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(query)]


# ─── QC Reports ─────────────────────────────────────────────────────────────

def create_qc_report(project_id: int, file_name: str, file_path: str) -> int:
    now = time.time()
    with sa.begin() as conn:
        return conn.execute(insert(qc_reports).values(project_id=project_id, file_name=file_name, file_path=file_path,
                                                      created_at=now, updated_at=now)
                            .returning(qc_reports.c.id)).scalar_one()


def update_qc_report(report_id: int, **kwargs) -> None:
    values = {k: _stored(v) for k, v in kwargs.items() if k in _REPORT_FIELDS}      # other keys are ignored
    if values:
        with sa.begin() as conn:
            conn.execute(update(qc_reports).where(qc_reports.c.id == report_id)
                         .values(**values, updated_at=time.time()))


def get_qc_report(report_id: int) -> Optional[dict]:
    d = _one(select(qc_reports).where(qc_reports.c.id == report_id))
    return _loaded(d, "columns_json", "field_mapping") if d else None


def get_qc_report_for_project(project_id: int) -> Optional[dict]:
    d = _one(select(qc_reports).where(qc_reports.c.project_id == project_id)
             .order_by(qc_reports.c.created_at.desc(), qc_reports.c.id.desc()).limit(1))
    return _loaded(d, "columns_json", "field_mapping") if d else None


def save_qc_field_mapping(report_id: int, mapping: dict) -> None:
    with sa.begin() as conn:
        conn.execute(update(qc_reports).where(qc_reports.c.id == report_id)
                     .values(field_mapping=json.dumps(mapping), updated_at=time.time()))


# ─── QC Runs ────────────────────────────────────────────────────────────────

def create_qc_run(report_id: int) -> int:
    with sa.begin() as conn:
        return conn.execute(insert(qc_runs).values(report_id=report_id, status="pending", created_at=time.time())
                            .returning(qc_runs.c.id)).scalar_one()


def update_qc_run(run_id: int, **kwargs) -> None:
    values = {k: _stored(v) for k, v in kwargs.items() if k in _RUN_FIELDS}         # other keys are ignored
    if values:
        with sa.begin() as conn:
            conn.execute(update(qc_runs).where(qc_runs.c.id == run_id).values(**values))


def get_qc_run(run_id: int) -> Optional[dict]:
    d = _one(select(qc_runs).where(qc_runs.c.id == run_id))
    return _loaded(d, "score_breakdown") if d else None


def get_qc_runs_for_report(report_id: int) -> list[dict]:
    return _all(select(qc_runs).where(qc_runs.c.report_id == report_id).order_by(qc_runs.c.created_at.desc()))


# ─── QC Findings ────────────────────────────────────────────────────────────

def add_qc_findings_batch(findings: list[dict]) -> int:
    if not findings:
        return 0
    now = time.time()
    rows = [{"run_id": f["run_id"], "report_id": f["report_id"], "check_type": f["check_type"],
             "row_number": f.get("row_number"), "column_name": f.get("column_name"), "severity": f["severity"],
             "message": f["message"], "expected": f.get("expected"), "actual": f.get("actual"),
             "source_url": f.get("source_url"), "created_at": now} for f in findings]
    with sa.begin() as conn:
        conn.execute(insert(qc_findings), rows)
    return len(rows)


def get_qc_findings(run_id: int, severity: str | None = None, check_type: str | None = None) -> list[dict]:
    q = select(qc_findings).where(qc_findings.c.run_id == run_id)
    if severity:
        q = q.where(qc_findings.c.severity == severity)
    if check_type:
        q = q.where(qc_findings.c.check_type == check_type)
    return _all(q.order_by(qc_findings.c.row_number.asc(), qc_findings.c.severity.asc()))


def update_qc_finding_action(finding_id: int, action: str) -> None:
    with sa.begin() as conn:
        conn.execute(update(qc_findings).where(qc_findings.c.id == finding_id).values(analyst_action=action))


# ─── QC Exports ─────────────────────────────────────────────────────────────

def create_qc_export(run_id: int, file_name: str, file_path: str) -> int:
    with sa.begin() as conn:
        return conn.execute(insert(qc_exports).values(run_id=run_id, file_name=file_name, file_path=file_path,
                                                      format="xlsx", created_at=time.time())
                            .returning(qc_exports.c.id)).scalar_one()


def get_qc_export(export_id: int) -> Optional[dict]:
    return _one(select(qc_exports).where(qc_exports.c.id == export_id))


# ─── owner lookups for the access checks (core/auth.py): the project of a run, finding or export ───────────────────
def _project_of(query) -> int | None:
    with sa.begin() as conn:
        return conn.execute(query).scalar()


def get_qc_run_project_id(run_id: int) -> int | None:
    return _project_of(select(qc_reports.c.project_id).select_from(
        qc_runs.join(qc_reports, qc_reports.c.id == qc_runs.c.report_id)).where(qc_runs.c.id == run_id))


def get_qc_finding_project_id(finding_id: int) -> int | None:
    return _project_of(select(qc_reports.c.project_id).select_from(
        qc_findings.join(qc_reports, qc_reports.c.id == qc_findings.c.report_id)).where(qc_findings.c.id == finding_id))


def get_qc_export_project_id(export_id: int) -> int | None:
    return _project_of(select(qc_reports.c.project_id).select_from(
        qc_exports.join(qc_runs, qc_runs.c.id == qc_exports.c.run_id)
        .join(qc_reports, qc_reports.c.id == qc_runs.c.report_id)).where(qc_exports.c.id == export_id))


# ─── source cache (QC link checks) ──────────────────────────────────────────────────────────────────────────
def get_cached_source(url: str) -> Optional[dict]:
    return _one(select(qc_source_cache).where(qc_source_cache.c.url == url))


def upsert_source_cache(url: str, **fields) -> None:
    """The latest fetch of a source URL: update the cached row (only the given fields), else insert one."""
    now = time.time()
    with sa.begin() as conn:
        row_id = conn.execute(select(qc_source_cache.c.id).where(qc_source_cache.c.url == url)).scalar()
        if row_id is None:
            conn.execute(insert(qc_source_cache).values(url=url, fetched_at=now, **fields))
        else:
            conn.execute(update(qc_source_cache).where(qc_source_cache.c.id == row_id)
                         .values(fetched_at=now, **fields))
