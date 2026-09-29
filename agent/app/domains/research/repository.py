"""Background Research repository (connection helper: core/db.py).

Also contains:
- news_approval: News Item Approvals repository (connection helper: core/db.py).
"""
from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn

# ─── Background Research ─────────────────────────────────────────────────────

def save_background_research(project_id: int, research: dict, llm_output: dict | None = None) -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_background_research WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1

    cur = conn.execute(
        "INSERT INTO intel_background_research (project_id, version, status, research_json, llm_output_json, created_at) "
        "VALUES (?, ?, 'draft', ?, ?, ?)",
        (project_id, version, json.dumps(research), json.dumps(llm_output) if llm_output else None, now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def save_background_research_update(research_id: int, research: dict, llm_output: dict | None = None):
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_research SET research_json = ?, llm_output_json = ? WHERE id = ?",
        (json.dumps(research), json.dumps(llm_output) if llm_output else None, research_id),
    )
    conn.commit()
    conn.close()


def get_latest_research(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_background_research WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["research"] = json.loads(d["research_json"])
    if d.get("llm_output_json"):
        d["llm_output"] = json.loads(d["llm_output_json"])
    return d


def get_research_by_id(research_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_background_research WHERE id = ?",
        (research_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["research"] = json.loads(d["research_json"])
    if d.get("llm_output_json"):
        d["llm_output"] = json.loads(d["llm_output_json"])
    return d


def approve_research(research_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_research SET approval_status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (reviewer, time.time(), research_id),
    )
    conn.commit()
    conn.close()
    return True


def reject_research(research_id: int, notes: str = "") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_research SET approval_status = 'revision_requested', notes = ? WHERE id = ?",
        (notes, research_id),
    )
    conn.commit()
    conn.close()
    return True


# ─── News Approval ─────────────────────────────────────────────────────

# ─── News Item Approvals ────────────────────────────────────────────────────

def update_news_approval(research_id: int, item_index: int, status: str, notes: str = ""):
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT id FROM intel_news_approvals WHERE research_id = ? AND item_index = ?",
        (research_id, item_index),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE intel_news_approvals SET status = ?, notes = ?, updated_at = ? WHERE id = ?",
            (status, notes, now, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO intel_news_approvals (research_id, item_index, status, notes, updated_at) VALUES (?, ?, ?, ?, ?)",
            (research_id, item_index, status, notes, now),
        )
    conn.commit()
    conn.close()


def get_news_approvals(research_id: int) -> dict[int, dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_news_approvals WHERE research_id = ?",
        (research_id,),
    ).fetchall()
    conn.close()
    return {row["item_index"]: dict(row) for row in rows}


# ─── Brand logos ─────────────────────────────────────────────────────────────

def get_brand_logo(brand_key: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM brand_logos WHERE brand_key = ?", (brand_key,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_brand_logo(brand_key: str, brand_name: str, logo_url: str | None,
                    domain: str | None, source: str) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO brand_logos (brand_key, brand_name, logo_url, domain, source, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(brand_key) DO UPDATE SET brand_name = excluded.brand_name, "
        "logo_url = excluded.logo_url, domain = excluded.domain, source = excluded.source, "
        "fetched_at = excluded.fetched_at",
        (brand_key, brand_name, logo_url, domain, source, time.time()),
    )
    conn.commit()
    conn.close()


# ─── Pexels background images ────────────────────────────────────────────────

def get_pexels_image(query_key: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM pexels_images WHERE query_key = ?", (query_key,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_pexels_image(query_key: str, query_text: str, image_url: str | None,
                      photographer: str | None, source_url: str | None) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO pexels_images (query_key, query_text, image_url, photographer, source_url, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(query_key) DO UPDATE SET query_text = excluded.query_text, "
        "image_url = excluded.image_url, photographer = excluded.photographer, "
        "source_url = excluded.source_url, fetched_at = excluded.fetched_at",
        (query_key, query_text, image_url, photographer, source_url, time.time()),
    )
    conn.commit()
    conn.close()


# ─── Research Items (multi-source pipeline) ──────────────────────────────────

def upsert_research_item(project_id: int, research_id: int | None, item: dict) -> int:
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO intel_research_items "
        "(project_id, research_id, topic, source_api, platform, publication, "
        "published_date, title, content, url, author, thumbnail_url, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(project_id, url) DO UPDATE SET "
        "research_id = excluded.research_id, topic = excluded.topic, "
        "source_api = excluded.source_api, platform = excluded.platform, "
        "publication = excluded.publication, published_date = excluded.published_date, "
        "title = excluded.title, content = excluded.content, author = excluded.author, "
        "thumbnail_url = excluded.thumbnail_url",
        (
            project_id, research_id, item["topic"], item["source_api"], item.get("platform"),
            item.get("publication"), item["published_date"], item.get("title"),
            item.get("content"), item["url"], item.get("author"), item.get("thumbnail_url"), now,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM intel_research_items WHERE project_id = ? AND url = ?",
        (project_id, item["url"]),
    ).fetchone()
    conn.close()
    return row["id"]


def get_research_items(project_id: int, topic: str | None = None,
                        since: float | None = None, until: float | None = None) -> list[dict]:
    """`since`/`until` (Unix timestamps, both inclusive) scope to a date_range — e.g. the
    current run's window — using the (project_id, published_date) index, so a project's
    earlier runs/date windows don't silently bleed into a scoped read."""
    conn = _conn()
    query = "SELECT * FROM intel_research_items WHERE project_id = ?"
    params: list = [project_id]
    if topic:
        query += " AND topic = ?"
        params.append(topic)
    if since is not None:
        query += " AND published_date >= ?"
        params.append(since)
    if until is not None:
        query += " AND published_date <= ?"
        params.append(until)
    query += " ORDER BY published_date DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
