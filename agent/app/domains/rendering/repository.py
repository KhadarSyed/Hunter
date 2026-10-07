"""PowerPoint Renderer repository (connection helper: core/db.py).

Also contains:
- word_renderer: Word Renderer repository (connection helper: core/db.py).
"""
from __future__ import annotations

import json
import time

from ...core.db import _conn

# ── PowerPoint Renderer store functions ──────────────────────────────

def create_render_job(job_id: str, presentation_id: int, **kw) -> str:
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO intel_render_jobs "
        "(id, presentation_id, job_type, status, progress_pct, progress_message, "
        "slide_ids_json, theme_id, output_path, warnings_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, presentation_id,
         kw.get("job_type", "full"), kw.get("status", "pending"),
         0, "", json.dumps(kw.get("slide_ids", [])),
         kw.get("theme_id", "hunter_default"),
         kw.get("output_path"), json.dumps([]), now),
    )
    conn.commit()
    conn.close()
    return job_id


def get_render_job(job_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_render_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for jf in ("slide_ids_json", "warnings_json"):
        if d.get(jf):
            try:
                d[jf] = json.loads(d[jf])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def list_render_jobs(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_render_jobs WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for jf in ("slide_ids_json", "warnings_json"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def update_render_job(job_id: str, **kw) -> None:
    if not kw:
        return
    sets = []
    vals = []
    json_map = {"slide_ids": "slide_ids_json", "warnings": "warnings_json"}
    for k, v in kw.items():
        col = json_map.get(k, k)
        if k in json_map:
            v = json.dumps(v)
        sets.append(f"{col}=?")
        vals.append(v)
    vals.append(job_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_render_jobs SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def create_rendered_presentation(job_id: str, presentation_id: int,
                                  output_path: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_rendered_presentations "
        "(job_id, presentation_id, version, output_path, output_size_bytes, "
        "slide_count, theme_id, render_duration_ms, metadata_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (job_id, presentation_id,
         kw.get("version", 1), output_path,
         kw.get("output_size_bytes", 0), kw.get("slide_count", 0),
         kw.get("theme_id", "hunter_default"),
         kw.get("render_duration_ms", 0),
         json.dumps(kw.get("metadata", {})), now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def get_rendered_presentation(rp_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_rendered_presentations WHERE id=?", (rp_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("metadata_json"):
        try:
            d["metadata_json"] = json.loads(d["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def get_latest_rendered(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_rendered_presentations WHERE presentation_id=? "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("metadata_json"):
        try:
            d["metadata_json"] = json.loads(d["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def list_rendered_presentations(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_rendered_presentations WHERE presentation_id=? "
        "ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("metadata_json"):
            try:
                d["metadata_json"] = json.loads(d["metadata_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def add_render_metric(job_id: str, slide_id: int, slide_number: int,
                      render_type: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_render_metrics "
        "(job_id, slide_id, slide_number, render_type, duration_ms, warnings_json, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (job_id, slide_id, slide_number, render_type,
         kw.get("duration_ms", 0), json.dumps(kw.get("warnings", [])), now),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_render_metrics(job_id: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_render_metrics WHERE job_id=? ORDER BY slide_number",
        (job_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("warnings_json"):
            try:
                d["warnings_json"] = json.loads(d["warnings_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def create_theme(theme_id: str, name: str, **kw) -> str:
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO intel_themes "
        "(id, name, description, primary_color, secondary_color, accent_color, "
        "background_color, text_color, font_heading, font_body, "
        "font_size_title, font_size_body, font_size_caption, "
        "logo_position, footer_style, color_palette_json, "
        "is_default, is_active, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (theme_id, name, kw.get("description"),
         kw.get("primary_color", "#5B2C9D"),
         kw.get("secondary_color", "#5E35B1"),
         kw.get("accent_color", "#A6CAEC"),
         kw.get("background_color", "#FFFFFF"),
         kw.get("text_color", "#1A1A1A"),
         kw.get("font_heading", "Calibri"),
         kw.get("font_body", "Calibri"),
         kw.get("font_size_title", 26),
         kw.get("font_size_body", 14),
         kw.get("font_size_caption", 9),
         kw.get("logo_position", "top_right"),
         kw.get("footer_style", "grey_band"),
         json.dumps(kw.get("color_palette", [])),
         1 if kw.get("is_default") else 0,
         1, now, now),
    )
    conn.commit()
    conn.close()
    return theme_id


def get_theme(theme_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_themes WHERE id=?", (theme_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("color_palette_json"):
        try:
            d["color_palette_json"] = json.loads(d["color_palette_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def list_themes(active_only: bool = True) -> list[dict]:
    conn = _conn()
    q = "SELECT * FROM intel_themes"
    if active_only:
        q += " WHERE is_active=1"
    q += " ORDER BY is_default DESC, name"
    rows = conn.execute(q).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("color_palette_json"):
            try:
                d["color_palette_json"] = json.loads(d["color_palette_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def create_template_version(theme_id: str, template_path: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    max_ver = conn.execute(
        "SELECT COALESCE(MAX(version), 0) as mv FROM intel_template_versions WHERE theme_id=?",
        (theme_id,),
    ).fetchone()
    ver = (max_ver["mv"] if max_ver else 0) + 1
    cur = conn.execute(
        "INSERT INTO intel_template_versions (theme_id, version, template_path, changelog, created_at) "
        "VALUES (?,?,?,?,?)",
        (theme_id, ver, template_path, kw.get("changelog"), now),
    )
    tv_id = cur.lastrowid
    conn.commit()
    conn.close()
    return tv_id


def list_template_versions(theme_id: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_template_versions WHERE theme_id=? ORDER BY version DESC",
        (theme_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_render_history(presentation_id: int, job_id: str, action: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_render_history "
        "(presentation_id, job_id, action, actor, details_json, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (presentation_id, job_id, action,
         kw.get("actor", "system"),
         json.dumps(kw.get("details", {})), now),
    )
    hid = cur.lastrowid
    conn.commit()
    conn.close()
    return hid


def get_render_history(presentation_id: int, limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_render_history WHERE presentation_id=? ORDER BY created_at DESC LIMIT ?",
        (presentation_id, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("details_json"):
            try:
                d["details_json"] = json.loads(d["details_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def ensure_default_theme() -> None:
    existing = get_theme("hunter_default")
    if existing:
        return
    create_theme(
        "hunter_default", "Hunter PR Default",
        description="Lavender/violet brand theme from Hunter PR template",
        primary_color="#5B2C9D",
        secondary_color="#5E35B1",
        accent_color="#A6CAEC",
        background_color="#FFFFFF",
        text_color="#1A1A1A",
        font_heading="Calibri",
        font_body="Calibri",
        color_palette=["#5E35B1", "#156082", "#A02B93", "#4EA72E",
                        "#196B24", "#DE2A00", "#A6CAEC", "#D1C4E9"],
        is_default=True,
    )


# ─── Word Renderer ─────────────────────────────────────────────────────

# ─── Word Renderer ───────────────────────────────────────────────────────────

def create_word_job(job_id: str, presentation_id: int, **kw) -> str:
    conn = _conn()
    conn.execute(
        "INSERT INTO intel_word_jobs (id, presentation_id, job_type, status, theme_id, created_at) "
        "VALUES (?, ?, ?, 'pending', ?, ?)",
        (job_id, presentation_id, kw.get("job_type", "full"),
         kw.get("theme_id", "hunter_default"), time.time()),
    )
    conn.commit()
    conn.close()
    return job_id


def get_word_job(job_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_word_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("sections_json", "warnings_json"):
        if d.get(k) and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def list_word_jobs(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_word_jobs WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for k in ("sections_json", "warnings_json"):
            if d.get(k) and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def update_word_job(job_id: str, **kw) -> None:
    json_map = {"sections": "sections_json", "warnings": "warnings_json"}
    sets, vals = [], []
    for k, v in kw.items():
        col = json_map.get(k, k)
        if k in json_map:
            v = json.dumps(v) if not isinstance(v, str) else v
        sets.append(f"{col}=?")
        vals.append(v)
    if not sets:
        return
    vals.append(job_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_word_jobs SET {','.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def create_word_document(job_id: str, presentation_id: int, output_path: str, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_word_documents "
        "(job_id, presentation_id, output_path, version, output_size_bytes, "
        " section_count, page_count, word_count, theme_id, render_duration_ms, metadata_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, presentation_id, output_path,
         kw.get("version", 1), kw.get("output_size_bytes", 0),
         kw.get("section_count", 0), kw.get("page_count", 0),
         kw.get("word_count", 0), kw.get("theme_id", "hunter_default"),
         kw.get("render_duration_ms", 0),
         json.dumps(kw.get("metadata", {})), time.time()),
    )
    doc_id = cur.lastrowid
    conn.commit()
    conn.close()
    return doc_id


def list_word_documents(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_word_documents WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_word_document(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_word_documents WHERE presentation_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def add_word_metric(job_id: str, section_name: str, section_number: int,
                    render_type: str = "section", **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_word_metrics "
        "(job_id, section_name, section_number, render_type, duration_ms, element_count, warnings_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, section_name, section_number, render_type,
         kw.get("duration_ms", 0), kw.get("element_count", 0),
         json.dumps(kw.get("warnings", [])), time.time()),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_word_metrics(job_id: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_word_metrics WHERE job_id=? ORDER BY section_number",
        (job_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("warnings_json") and isinstance(d["warnings_json"], str):
            try:
                d["warnings_json"] = json.loads(d["warnings_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def add_word_history(presentation_id: int, job_id: str, action: str, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_word_history (presentation_id, job_id, action, actor, details_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (presentation_id, job_id, action,
         kw.get("actor", "system"),
         json.dumps(kw.get("details", {})), time.time()),
    )
    hid = cur.lastrowid
    conn.commit()
    conn.close()
    return hid


def get_word_history(presentation_id: int, limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_word_history WHERE presentation_id=? ORDER BY created_at DESC LIMIT ?",
        (presentation_id, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("details_json") and isinstance(d["details_json"], str):
            try:
                d["details_json"] = json.loads(d["details_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result
