"""Publishing Gateway repository (connection helper: core/db.py)."""

from __future__ import annotations

import json
import time

from ...core.db import _conn

# ─── Publishing Gateway ────────────────────────────────────────────────────

def _parse_json_fields(d: dict, fields: list[str]) -> dict:
    for f in fields:
        val = d.get(f)
        if val and isinstance(val, str):
            try:
                d[f] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def create_pub_validation(project_id: int, presentation_id: int, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pub_validations "
        "(project_id, presentation_id, status, readiness_score, readiness_class, "
        "scores_json, issues_json, warnings_json, pptx_job_id, word_job_id, "
        "validated_by, started_at, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, presentation_id,
         kw.get("status", "pending"), kw.get("readiness_score", 0),
         kw.get("readiness_class", "draft"),
         json.dumps(kw.get("scores", {})), json.dumps(kw.get("issues", [])),
         json.dumps(kw.get("warnings", [])),
         kw.get("pptx_job_id"), kw.get("word_job_id"),
         kw.get("validated_by", "system"), now, now),
    )
    vid = cur.lastrowid
    conn.commit()
    conn.close()
    return vid


def get_pub_validation(validation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pub_validations WHERE id=?",
                       (validation_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["scores_json", "issues_json", "warnings_json"])


def get_latest_pub_validation(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pub_validations WHERE presentation_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["scores_json", "issues_json", "warnings_json"])


def update_pub_validation(validation_id: int, **kw) -> None:
    if not kw:
        return
    sets, vals = [], []
    json_fields = {"scores": "scores_json", "issues": "issues_json", "warnings": "warnings_json"}
    for k, v in kw.items():
        col = json_fields.get(k, k)
        if k in json_fields:
            v = json.dumps(v)
        sets.append(f"{col}=?")
        vals.append(v)
    vals.append(validation_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_pub_validations SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def list_pub_validations(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_validations WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    return [_parse_json_fields(dict(r), ["scores_json", "issues_json", "warnings_json"]) for r in rows]


def create_pub_diff_report(validation_id: int, project_id: int,
                           presentation_id: int, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_diff_reports "
        "(validation_id, project_id, presentation_id, status, match_pct, "
        "differences_json, summary_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (validation_id, project_id, presentation_id,
         kw.get("status", "pending"), kw.get("match_pct", 0),
         json.dumps(kw.get("differences", [])),
         json.dumps(kw.get("summary", {})), time.time()),
    )
    did = cur.lastrowid
    conn.commit()
    conn.close()
    return did


def get_pub_diff_report(diff_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pub_diff_reports WHERE id=?",
                       (diff_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["differences_json", "summary_json"])


def get_latest_diff_report(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pub_diff_reports WHERE presentation_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["differences_json", "summary_json"])


def create_pub_version(project_id: int, presentation_id: int, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_versions "
        "(project_id, presentation_id, major, minor, revision, version_label, "
        "pipeline_version, renderer_version, presentation_version, "
        "approval_status, approved_by, approved_at, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, presentation_id,
         kw.get("major", 1), kw.get("minor", 0), kw.get("revision", 0),
         kw.get("version_label"), kw.get("pipeline_version"),
         kw.get("renderer_version"), kw.get("presentation_version", 1),
         kw.get("approval_status", "draft"), kw.get("approved_by"),
         kw.get("approved_at"), kw.get("notes"), time.time()),
    )
    vid = cur.lastrowid
    conn.commit()
    conn.close()
    return vid


def get_pub_version(version_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pub_versions WHERE id=?",
                       (version_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_pub_version(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pub_versions WHERE presentation_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_pub_versions(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_versions WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_pub_version(version_id: int, **kw) -> None:
    if not kw:
        return
    sets, vals = [], []
    for k, v in kw.items():
        sets.append(f"{k}=?")
        vals.append(v)
    vals.append(version_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_pub_versions SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def create_pub_package(project_id: int, presentation_id: int, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_packages "
        "(project_id, presentation_id, version_id, validation_id, status, "
        "package_path, package_size_bytes, manifest_json, contents_json, "
        "created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, presentation_id,
         kw.get("version_id"), kw.get("validation_id"),
         kw.get("status", "building"), kw.get("package_path"),
         kw.get("package_size_bytes", 0),
         json.dumps(kw.get("manifest", {})),
         json.dumps(kw.get("contents", [])),
         kw.get("created_by", "system"), time.time()),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_pub_package(package_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pub_packages WHERE id=?",
                       (package_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["manifest_json", "contents_json"])


def get_latest_pub_package(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pub_packages WHERE presentation_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["manifest_json", "contents_json"])


def update_pub_package(package_id: int, **kw) -> None:
    if not kw:
        return
    sets, vals = [], []
    json_fields = {"manifest": "manifest_json", "contents": "contents_json"}
    for k, v in kw.items():
        col = json_fields.get(k, k)
        if k in json_fields:
            v = json.dumps(v)
        sets.append(f"{col}=?")
        vals.append(v)
    vals.append(package_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_pub_packages SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def list_pub_packages(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_packages WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    return [_parse_json_fields(dict(r), ["manifest_json", "contents_json"]) for r in rows]


def create_pub_approval(project_id: int, presentation_id: int, action: str,
                        status: str, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_approvals "
        "(project_id, presentation_id, version_id, action, status, actor, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (project_id, presentation_id, kw.get("version_id"),
         action, status, kw.get("actor", "system"),
         kw.get("notes"), time.time()),
    )
    aid = cur.lastrowid
    conn.commit()
    conn.close()
    return aid


def list_pub_approvals(presentation_id: int, limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_approvals WHERE presentation_id=? ORDER BY created_at DESC LIMIT ?",
        (presentation_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_pub_download(project_id: int, file_type: str, file_path: str, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_downloads "
        "(project_id, package_id, file_type, file_path, file_size_bytes, downloaded_by, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (project_id, kw.get("package_id"), file_type, file_path,
         kw.get("file_size_bytes", 0), kw.get("downloaded_by", "system"), time.time()),
    )
    did = cur.lastrowid
    conn.commit()
    conn.close()
    return did


def list_pub_downloads(project_id: int, limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_downloads WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_pub_audit(project_id: int, entity_type: str, action: str, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_audit "
        "(project_id, presentation_id, entity_type, entity_id, action, actor, details_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (project_id, kw.get("presentation_id"), entity_type,
         kw.get("entity_id"), action, kw.get("actor", "system"),
         json.dumps(kw.get("details", {})), time.time()),
    )
    aid = cur.lastrowid
    conn.commit()
    conn.close()
    return aid


def list_pub_audit(project_id: int, limit: int = 100) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_audit WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    return [_parse_json_fields(dict(r), ["details_json"]) for r in rows]


def get_pub_stats(project_id: int) -> dict:
    conn = _conn()
    val_count = conn.execute(
        "SELECT COUNT(*) FROM intel_pub_validations WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    pkg_count = conn.execute(
        "SELECT COUNT(*) FROM intel_pub_packages WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    ver_count = conn.execute(
        "SELECT COUNT(*) FROM intel_pub_versions WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    dl_count = conn.execute(
        "SELECT COUNT(*) FROM intel_pub_downloads WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    pub_count = conn.execute(
        "SELECT COUNT(*) FROM intel_pub_approvals WHERE project_id=? AND action='publish'",
        (project_id,),
    ).fetchone()[0]
    conn.close()
    return {
        "validations": val_count,
        "packages": pkg_count,
        "versions": ver_count,
        "downloads": dl_count,
        "publications": pub_count,
    }
