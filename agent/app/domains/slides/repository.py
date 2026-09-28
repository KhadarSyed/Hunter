"""Slide Intelligence repository (connection helper: core/db.py)."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from ...core.db import _conn

# ─── Slide Intelligence: Presentations ─────────────────────────────────────

def create_si_presentation(filename: str, file_path: str, file_size: int = 0,
                           file_hash: str | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_presentations (filename, file_path, file_size, file_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (filename, file_path, file_size, file_hash, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_si_presentation(pres_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_si_presentations WHERE id = ?", (pres_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_si_presentations() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM intel_si_presentations ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_si_presentation(pres_id: int, **kwargs: Any) -> bool:
    allowed = {"slide_count", "processed_count", "status", "error", "started_at",
               "completed_at", "file_hash"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False
    conn = _conn()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [pres_id]
    conn.execute(f"UPDATE intel_si_presentations SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def delete_si_presentation(pres_id: int):
    conn = _conn()
    slide_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM intel_si_slides WHERE presentation_id = ?", (pres_id,)
    ).fetchall()]
    for sid in slide_ids:
        conn.execute("DELETE FROM intel_si_template_members WHERE slide_id = ?", (sid,))
        conn.execute("DELETE FROM intel_si_corrections WHERE slide_id = ?", (sid,))
        conn.execute("DELETE FROM intel_si_embeddings WHERE slide_id = ?", (sid,))
        conn.execute("DELETE FROM intel_si_storyline_matches WHERE slide_id = ?", (sid,))
    conn.execute("DELETE FROM intel_si_slides WHERE presentation_id = ?", (pres_id,))
    conn.execute("DELETE FROM intel_si_detected_projects WHERE presentation_id = ?", (pres_id,))
    conn.execute("DELETE FROM intel_si_style_patterns WHERE presentation_id = ?", (pres_id,))
    conn.execute("DELETE FROM intel_si_processing_logs WHERE presentation_id = ?", (pres_id,))
    conn.execute("DELETE FROM intel_si_presentations WHERE id = ?", (pres_id,))
    conn.commit()
    conn.close()


# ─── Slide Intelligence: Slides ────────────────────────────────────────────

def create_si_slide(presentation_id: int, slide_number: int, **kwargs: Any) -> int:
    conn = _conn()
    now = time.time()
    base_cols = ["presentation_id", "slide_number", "created_at"]
    base_vals = [presentation_id, slide_number, now]
    allowed = {
        "all_text", "title_text", "body_text", "footer_text", "notes_text",
        "shape_count", "text_shape_count", "chart_count", "table_count", "image_count",
        "has_chart", "has_table", "has_image", "thumbnail_b64",
        "slide_purpose", "layout_type", "visual_type", "narrative_role", "report_type",
        "industry", "client", "brand", "data_density", "executive_suitability",
        "visual_complexity", "classification_confidence", "detected_project_id",
        "status", "processed_at",
    }
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            base_cols.append(k)
            base_vals.append(v)
    placeholders = ", ".join("?" for _ in base_vals)
    col_str = ", ".join(base_cols)
    cur = conn.execute(
        f"INSERT INTO intel_si_slides ({col_str}) VALUES ({placeholders})", base_vals
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_si_slide(slide_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_si_slides WHERE id = ?", (slide_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for bf in ("has_chart", "has_table", "has_image", "is_excluded", "is_template_approved"):
        if bf in d:
            d[bf] = bool(d[bf])
    return d


def list_si_slides(presentation_id: int | None = None, *,
                   slide_purpose: str | None = None, layout_type: str | None = None,
                   visual_type: str | None = None, client: str | None = None,
                   report_type: str | None = None, is_excluded: bool | None = None,
                   search: str | None = None,
                   sort_by: str = "slide_number", sort_dir: str = "ASC",
                   limit: int = 200, offset: int = 0) -> list[dict]:
    conn = _conn()
    clauses, params = [], []
    if presentation_id is not None:
        clauses.append("presentation_id = ?")
        params.append(presentation_id)
    if slide_purpose:
        clauses.append("slide_purpose = ?")
        params.append(slide_purpose)
    if layout_type:
        clauses.append("layout_type = ?")
        params.append(layout_type)
    if visual_type:
        clauses.append("visual_type = ?")
        params.append(visual_type)
    if client:
        clauses.append("client = ?")
        params.append(client)
    if report_type:
        clauses.append("report_type = ?")
        params.append(report_type)
    if is_excluded is not None:
        clauses.append("is_excluded = ?")
        params.append(1 if is_excluded else 0)
    if search:
        clauses.append("(all_text LIKE ? OR title_text LIKE ? OR client LIKE ? OR brand LIKE ?)")
        s = f"%{search}%"
        params.extend([s, s, s, s])
    where = " AND ".join(clauses) if clauses else "1=1"
    valid_sort = {"slide_number", "slide_purpose", "layout_type", "client", "classification_confidence",
                  "created_at", "processed_at"}
    col = sort_by if sort_by in valid_sort else "slide_number"
    direction = "DESC" if sort_dir.upper() == "DESC" else "ASC"
    rows = conn.execute(
        f"SELECT * FROM intel_si_slides WHERE {where} ORDER BY {col} {direction} LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for bf in ("has_chart", "has_table", "has_image", "is_excluded", "is_template_approved"):
            if bf in d:
                d[bf] = bool(d[bf])
        result.append(d)
    return result


def update_si_slide(slide_id: int, **kwargs: Any) -> bool:
    allowed = {
        "all_text", "title_text", "body_text", "footer_text", "notes_text",
        "shape_count", "text_shape_count", "chart_count", "table_count", "image_count",
        "has_chart", "has_table", "has_image", "thumbnail_b64",
        "slide_purpose", "layout_type", "visual_type", "narrative_role", "report_type",
        "industry", "client", "brand", "data_density", "executive_suitability",
        "visual_complexity", "classification_confidence", "detected_project_id",
        "is_excluded", "is_template_approved", "status", "error", "processed_at",
    }
    fields = {}
    for k, v in kwargs.items():
        if k in allowed:
            if k in ("has_chart", "has_table", "has_image", "is_excluded", "is_template_approved"):
                fields[k] = int(v) if isinstance(v, bool) else v
            else:
                fields[k] = v
    if not fields:
        return False
    conn = _conn()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [slide_id]
    conn.execute(f"UPDATE intel_si_slides SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def delete_si_slide(slide_id: int):
    conn = _conn()
    conn.execute("DELETE FROM intel_si_template_members WHERE slide_id = ?", (slide_id,))
    conn.execute("DELETE FROM intel_si_corrections WHERE slide_id = ?", (slide_id,))
    conn.execute("DELETE FROM intel_si_embeddings WHERE slide_id = ?", (slide_id,))
    conn.execute("DELETE FROM intel_si_storyline_matches WHERE slide_id = ?", (slide_id,))
    conn.execute("DELETE FROM intel_si_slides WHERE id = ?", (slide_id,))
    conn.commit()
    conn.close()


def count_si_slides(presentation_id: int | None = None, **filters) -> int:
    conn = _conn()
    clauses, params = [], []
    if presentation_id is not None:
        clauses.append("presentation_id = ?")
        params.append(presentation_id)
    for k in ("slide_purpose", "layout_type", "visual_type", "client", "status"):
        if k in filters and filters[k] is not None:
            clauses.append(f"{k} = ?")
            params.append(filters[k])
    where = " AND ".join(clauses) if clauses else "1=1"
    cnt = conn.execute(f"SELECT COUNT(*) FROM intel_si_slides WHERE {where}", params).fetchone()[0]
    conn.close()
    return cnt


# ─── Slide Intelligence: Template Families ─────────────────────────────────

def create_si_template_family(family_name: str, typical_layout: str | None = None,
                              typical_visual: str | None = None, typical_purpose: str | None = None,
                              required_inputs: list | None = None,
                              recommended_usage: str | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_template_families "
        "(family_name, typical_layout, typical_visual, typical_purpose, required_inputs, "
        "recommended_usage, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (family_name, typical_layout, typical_visual, typical_purpose,
         json.dumps(required_inputs or []), recommended_usage, now, now),
    )
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return fid


def get_si_template_family(family_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_si_template_families WHERE id = ?", (family_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["is_approved"] = bool(d.get("is_approved", 0))
    if d.get("required_inputs"):
        try:
            d["required_inputs"] = json.loads(d["required_inputs"])
        except (json.JSONDecodeError, TypeError):
            d["required_inputs"] = []
    return d


def list_si_template_families() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_si_template_families ORDER BY member_count DESC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["is_approved"] = bool(d.get("is_approved", 0))
        if d.get("required_inputs"):
            try:
                d["required_inputs"] = json.loads(d["required_inputs"])
            except (json.JSONDecodeError, TypeError):
                d["required_inputs"] = []
        result.append(d)
    return result


def update_si_template_family(family_id: int, **kwargs: Any) -> bool:
    allowed = {"family_name", "typical_layout", "typical_visual", "typical_purpose",
               "required_inputs", "recommended_usage", "member_count", "is_approved"}
    fields = {}
    for k, v in kwargs.items():
        if k in allowed:
            if k == "required_inputs" and isinstance(v, list):
                fields[k] = json.dumps(v)
            elif k == "is_approved" and isinstance(v, bool):
                fields[k] = int(v)
            else:
                fields[k] = v
    if not fields:
        return False
    fields["updated_at"] = time.time()
    conn = _conn()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [family_id]
    conn.execute(f"UPDATE intel_si_template_families SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def delete_si_template_family(family_id: int):
    conn = _conn()
    conn.execute("DELETE FROM intel_si_template_members WHERE family_id = ?", (family_id,))
    conn.execute("DELETE FROM intel_si_template_families WHERE id = ?", (family_id,))
    conn.commit()
    conn.close()


def add_si_template_member(family_id: int, slide_id: int,
                           is_representative: bool = False,
                           similarity_score: float = 0.0) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_template_members (family_id, slide_id, is_representative, "
        "similarity_score, created_at) VALUES (?, ?, ?, ?, ?)",
        (family_id, slide_id, int(is_representative), similarity_score, now),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_si_template_members(family_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT tm.*, s.slide_number, s.title_text, s.slide_purpose, s.layout_type, "
        "s.presentation_id FROM intel_si_template_members tm "
        "JOIN intel_si_slides s ON tm.slide_id = s.id "
        "WHERE tm.family_id = ? ORDER BY tm.is_representative DESC, tm.similarity_score DESC",
        (family_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Slide Intelligence: Detected Projects ─────────────────────────────────

def create_si_detected_project(presentation_id: int, start_slide: int, end_slide: int,
                               project_name: str | None = None, client_name: str | None = None,
                               brand_name: str | None = None, analyst_name: str | None = None,
                               slide_count: int = 0, confidence: float = 0.0) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_detected_projects "
        "(presentation_id, project_name, client_name, brand_name, analyst_name, "
        "start_slide, end_slide, slide_count, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (presentation_id, project_name, client_name, brand_name, analyst_name,
         start_slide, end_slide, slide_count, confidence, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def list_si_detected_projects(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_si_detected_projects WHERE presentation_id = ? "
        "ORDER BY start_slide", (presentation_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_si_detected_project(project_id: int, **kwargs: Any) -> bool:
    allowed = {"project_name", "client_name", "brand_name", "analyst_name",
               "start_slide", "end_slide", "slide_count", "confidence", "is_confirmed"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    if "is_confirmed" in fields and isinstance(fields["is_confirmed"], bool):
        fields["is_confirmed"] = int(fields["is_confirmed"])
    conn = _conn()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [project_id]
    conn.execute(f"UPDATE intel_si_detected_projects SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


# ─── Slide Intelligence: Style Patterns ────────────────────────────────────

def add_si_style_pattern(pattern_type: str, pattern_name: str, pattern_data: dict,
                         presentation_id: int | None = None, frequency: int = 1,
                         source_slides: list | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_style_patterns "
        "(presentation_id, pattern_type, pattern_name, pattern_data, frequency, source_slides, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (presentation_id, pattern_type, pattern_name, json.dumps(pattern_data),
         frequency, json.dumps(source_slides or []), now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def list_si_style_patterns(presentation_id: int | None = None,
                           pattern_type: str | None = None) -> list[dict]:
    conn = _conn()
    clauses, params = [], []
    if presentation_id is not None:
        clauses.append("presentation_id = ?")
        params.append(presentation_id)
    if pattern_type:
        clauses.append("pattern_type = ?")
        params.append(pattern_type)
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT * FROM intel_si_style_patterns WHERE {where} ORDER BY frequency DESC", params
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for jf in ("pattern_data", "source_slides"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


# ─── Slide Intelligence: Storyline Matches ─────────────────────────────────

def create_si_storyline_match(storyline_id: int, node_id: int, slide_id: int,
                              similarity_score: float = 0.0, match_reason: str | None = None,
                              recommended_elements: list | None = None,
                              elements_not_to_reuse: list | None = None,
                              recommended_layout: str | None = None,
                              recommended_visual: str | None = None,
                              recommended_chart: str | None = None,
                              confidence: float = 0.0) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_storyline_matches "
        "(storyline_id, node_id, slide_id, similarity_score, match_reason, "
        "recommended_elements, elements_not_to_reuse, recommended_layout, "
        "recommended_visual, recommended_chart, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (storyline_id, node_id, slide_id, similarity_score, match_reason,
         json.dumps(recommended_elements or []), json.dumps(elements_not_to_reuse or []),
         recommended_layout, recommended_visual, recommended_chart, confidence, now),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_si_storyline_matches(storyline_id: int | None = None,
                             node_id: int | None = None) -> list[dict]:
    conn = _conn()
    clauses, params = [], []
    if storyline_id is not None:
        clauses.append("m.storyline_id = ?")
        params.append(storyline_id)
    if node_id is not None:
        clauses.append("m.node_id = ?")
        params.append(node_id)
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT m.*, s.slide_number, s.title_text, s.slide_purpose, s.layout_type, "
        f"s.visual_type, s.client, s.presentation_id "
        f"FROM intel_si_storyline_matches m "
        f"JOIN intel_si_slides s ON m.slide_id = s.id "
        f"WHERE {where} ORDER BY m.similarity_score DESC",
        params,
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for jf in ("recommended_elements", "elements_not_to_reuse"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        d["is_accepted"] = bool(d.get("is_accepted", 0))
        result.append(d)
    return result


def delete_si_storyline_matches(storyline_id: int | None = None,
                                node_id: int | None = None):
    conn = _conn()
    if node_id is not None:
        conn.execute("DELETE FROM intel_si_storyline_matches WHERE node_id = ?", (node_id,))
    elif storyline_id is not None:
        conn.execute("DELETE FROM intel_si_storyline_matches WHERE storyline_id = ?", (storyline_id,))
    conn.commit()
    conn.close()


# ─── Slide Intelligence: Processing Logs ───────────────────────────────────

def add_si_processing_log(presentation_id: int, step: str, status: str,
                          slide_number: int | None = None, message: str | None = None,
                          duration_ms: float | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_processing_logs "
        "(presentation_id, step, slide_number, status, message, duration_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (presentation_id, step, slide_number, status, message, duration_ms, now),
    )
    lid = cur.lastrowid
    conn.commit()
    conn.close()
    return lid


def get_si_processing_logs(presentation_id: int, limit: int = 200) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_si_processing_logs WHERE presentation_id = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (presentation_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Slide Intelligence: Manual Corrections ────────────────────────────────

def add_si_correction(slide_id: int, field_name: str, new_value: str,
                      old_value: str | None = None, corrected_by: str = "analyst") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_corrections (slide_id, field_name, old_value, new_value, "
        "corrected_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (slide_id, field_name, old_value, new_value, corrected_by, now),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def get_si_corrections(slide_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_si_corrections WHERE slide_id = ? ORDER BY created_at DESC",
        (slide_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Slide Intelligence: Embeddings ────────────────────────────────────────

def save_si_embedding(slide_id: int, embedding_blob: bytes, model_name: str = "nomic-embed-text"):
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO intel_si_embeddings (slide_id, embedding_blob, model_name, created_at) "
        "VALUES (?, ?, ?, ?)",
        (slide_id, embedding_blob, model_name, now),
    )
    conn.commit()
    conn.close()


def get_si_embedding(slide_id: int) -> Optional[bytes]:
    conn = _conn()
    row = conn.execute(
        "SELECT embedding_blob FROM intel_si_embeddings WHERE slide_id = ?", (slide_id,)
    ).fetchone()
    conn.close()
    return row["embedding_blob"] if row else None


def get_all_si_embeddings() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT slide_id, embedding_blob FROM intel_si_embeddings").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Slide Intelligence: Retrieval History ─────────────────────────────────

def add_si_retrieval_history(query_text: str, results: list, node_id: int | None = None,
                             storyline_id: int | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_retrieval_history "
        "(query_text, node_id, storyline_id, results_json, result_count, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (query_text, node_id, storyline_id, json.dumps(results), len(results), now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


# ─── Slide Intelligence: Dashboard Aggregates ──────────────────────────────

def get_si_dashboard() -> dict:
    conn = _conn()
    pres_count = conn.execute("SELECT COUNT(*) FROM intel_si_presentations").fetchone()[0]
    slide_count = conn.execute("SELECT COUNT(*) FROM intel_si_slides").fetchone()[0]
    processed = conn.execute(
        "SELECT COUNT(*) FROM intel_si_slides WHERE status = 'processed'"
    ).fetchone()[0]
    excluded = conn.execute(
        "SELECT COUNT(*) FROM intel_si_slides WHERE is_excluded = 1"
    ).fetchone()[0]
    family_count = conn.execute("SELECT COUNT(*) FROM intel_si_template_families").fetchone()[0]
    project_count = conn.execute("SELECT COUNT(*) FROM intel_si_detected_projects").fetchone()[0]
    purpose_counts = {}
    for row in conn.execute(
        "SELECT slide_purpose, COUNT(*) as cnt FROM intel_si_slides "
        "WHERE slide_purpose IS NOT NULL GROUP BY slide_purpose ORDER BY cnt DESC"
    ).fetchall():
        purpose_counts[row["slide_purpose"]] = row["cnt"]
    layout_counts = {}
    for row in conn.execute(
        "SELECT layout_type, COUNT(*) as cnt FROM intel_si_slides "
        "WHERE layout_type IS NOT NULL GROUP BY layout_type ORDER BY cnt DESC"
    ).fetchall():
        layout_counts[row["layout_type"]] = row["cnt"]
    client_counts = {}
    for row in conn.execute(
        "SELECT client, COUNT(*) as cnt FROM intel_si_slides "
        "WHERE client IS NOT NULL GROUP BY client ORDER BY cnt DESC"
    ).fetchall():
        client_counts[row["client"]] = row["cnt"]
    duplicate_count = 0
    conn.close()
    return {
        "presentation_count": pres_count,
        "total_slides": slide_count,
        "processed_slides": processed,
        "excluded_slides": excluded,
        "template_families": family_count,
        "detected_projects": project_count,
        "duplicate_count": duplicate_count,
        "purpose_distribution": purpose_counts,
        "layout_distribution": layout_counts,
        "client_distribution": client_counts,
    }
