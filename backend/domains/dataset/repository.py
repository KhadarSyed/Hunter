"""SQL for the data set (migration 37): upload files, project-wide articles, per-RQ rows, theme titles.

Article tags_json is read as {"themes": [labels], "brands": [{"name": ...}]} by the theme/brand filters.
"""
from __future__ import annotations

import json
import time

from ...core.db import _conn

_LIST_COLS = ("a.id, a.project_id, a.norm_url, a.url, a.channel, a.title, a.summary, a.outlet, a.published, "
              "a.country, a.reach, a.author_name, a.author_id, a.post_id, a.file_id, a.content_status, a.tags_json, "
              "a.tag_status, a.tag_error, a.sentiment, a.sentiment_confidence, a.syndicated_json, a.similar_json")
_RQ_COLS = ("id, article_id, rq_id, signature, matched, match_confidence, keywords_json, tags_json, evidence_json, "
            "summary, reason, status, decided_by, decided_at, decision_reason, tagged_at")
# A row counts toward an article's status when the RQ matched it or an analyst decided it.
_COUNTED = "(m.matched = 1 OR m.decided_by IS NOT NULL)"


def _run(sql: str, params: tuple = (), *, one: bool = False):
    conn = _conn()
    try:
        cur = conn.execute(sql, params)
        out = cur.fetchone() if one else cur.fetchall()
        conn.commit()
        return out
    finally:
        conn.close()


def _dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def _marks(n: int) -> str:
    return ",".join("?" * n)


# ---- upload files --------------------------------------------------------------------------------------------------
def add_file(project_id: int, file_name: str, s3_key: str | None, content: bytes | None, uploaded_by: str | None) -> int:
    return int(_run("INSERT INTO intel_upload_files (project_id, file_name, s3_key, content, uploaded_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                    (project_id, file_name, s3_key, content, uploaded_by, time.time()), one=True)[0])


def finish_file(file_id: int, rows_read: int, added: int, duplicates: int, error: str | None = None) -> None:
    _run("UPDATE intel_upload_files SET rows_read = ?, added = ?, duplicates = ?, error = ? WHERE id = ?",
         (rows_read, added, duplicates, error, file_id))


def list_files(project_id: int) -> list[dict]:
    return _dicts(_run("SELECT id, file_name, s3_key, rows_read, added, duplicates, error, uploaded_by, created_at "
                       "FROM intel_upload_files WHERE project_id = ? ORDER BY id DESC", (project_id,)))


# ---- articles ------------------------------------------------------------------------------------------------------
def insert_articles(project_id: int, file_id: int, records: list[dict]) -> tuple[int, int]:
    added = 0
    conn = _conn()
    try:
        for r in records:
            row = conn.execute(
                "INSERT INTO intel_articles (project_id, norm_url, url, channel, title, summary, outlet, published, "
                "country, reach, author_name, author_id, post_id, raw_json, file_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (project_id, norm_url) DO NOTHING RETURNING id",
                (project_id, r["norm_url"], r["url"], r["channel"], r.get("title", ""), r.get("summary", ""),
                 r.get("outlet", ""), r.get("published"), r.get("country", ""), r.get("reach") or 0,
                 r.get("author_name", ""), r.get("author_id", ""), r.get("post_id", ""),
                 json.dumps(r.get("raw") or {}, default=str), file_id, time.time())).fetchone()
            added += row is not None
        conn.commit()
    finally:
        conn.close()
    return added, len(records) - added


def channel_counts(project_id: int) -> dict[str, int]:
    return {r["channel"]: int(r["n"]) for r in _run(
        "SELECT channel, COUNT(*) AS n FROM intel_articles WHERE project_id = ? GROUP BY channel", (project_id,))}


def articles_needing(project_id: int, phase: str, limit: int) -> list[dict]:
    cond = {"content": "content_status = 'pending' AND channel = 'traditional'",
            "tags": "tag_status IN ('pending', 'failed') AND content_status <> 'pending'"}[phase]
    return _dicts(_run(f"SELECT id, norm_url, url, channel, title, summary, outlet, published, content, content_status, "
                       f"tags_json FROM intel_articles WHERE project_id = ? AND {cond} ORDER BY id LIMIT ?",
                       (project_id, limit)))


def all_articles(project_id: int) -> list[dict]:
    """Every article with the columns the theme and relation phases read (tags_json is the stored JSON text)."""
    return _dicts(_run("SELECT id, url, title, outlet, content, summary, tag_status, tags_json, syndicated_json "
                       "FROM intel_articles WHERE project_id = ? ORDER BY id", (project_id,)))


def save_content(article_id: int, content: str, status: str) -> None:
    _run("UPDATE intel_articles SET content = ?, content_status = ? WHERE id = ?", (content, status, article_id))


def save_tags(article_id: int, tags: dict | None, error: str | None) -> None:
    t = tags or {}
    _run("UPDATE intel_articles SET tags_json = ?, sentiment = ?, sentiment_confidence = ?, tag_status = ?, "
         "tag_error = ? WHERE id = ?",
         (json.dumps(tags, default=str) if tags is not None else None, t.get("overall_sentiment"), t.get("overall_sentiment_confidence"),
          "failed" if error or tags is None else "tagged", error, article_id))


def save_relations(project_id: int, relations: dict[int, dict]) -> None:
    conn = _conn()
    try:
        for aid, rel in relations.items():
            conn.execute("UPDATE intel_articles SET syndicated_json = ?, similar_json = ? "
                         "WHERE id = ? AND project_id = ?",
                         (json.dumps(rel.get("syndicated") or []), json.dumps(rel.get("similar") or []), aid, project_id))
        conn.commit()
    finally:
        conn.close()


def tagging_counts(project_id: int) -> dict:
    out: dict = {"total": 0, "content": {}, "tags": {}}
    for key, col in (("content", "content_status"), ("tags", "tag_status")):
        for r in _run(f"SELECT {col} AS s, COUNT(*) AS n FROM intel_articles WHERE project_id = ? GROUP BY {col}",
                      (project_id,)):
            out[key][r["s"]] = int(r["n"])
    out["total"] = sum(out["tags"].values())
    return out


def save_theme_titles(project_id: int, mapping: dict[str, str]) -> None:
    conn = _conn()
    try:
        for key, title in mapping.items():
            conn.execute("INSERT INTO intel_theme_titles (project_id, label_key, title) VALUES (?, ?, ?) "
                         "ON CONFLICT (project_id, label_key) DO UPDATE SET title = EXCLUDED.title",
                         (project_id, key, title))
        conn.commit()
    finally:
        conn.close()


def theme_titles(project_id: int) -> dict[str, str]:
    return {r["label_key"]: r["title"] for r in
            _run("SELECT label_key, title FROM intel_theme_titles WHERE project_id = ?", (project_id,))}


# ---- per-RQ rows ---------------------------------------------------------------------------------------------------
def rq_rows_needing(project_id: int, rq_id: str, signature: str, limit: int) -> list[dict]:
    return _dicts(_run(
        "SELECT a.id, a.norm_url, a.url, a.channel, a.title, a.summary, a.content, a.content_status, a.tags_json "
        "FROM intel_articles a LEFT JOIN intel_article_rq r ON r.article_id = a.id AND r.rq_id = ? "
        "WHERE a.project_id = ? AND a.tag_status = 'tagged' AND (r.id IS NULL OR r.signature <> ?) "
        "ORDER BY a.id LIMIT ?", (rq_id, project_id, signature, limit)))


def save_rq(article_id: int, project_id: int, rq_id: str, signature: str, result: dict, status: str) -> None:
    _run("INSERT INTO intel_article_rq (project_id, article_id, rq_id, signature, matched, match_confidence, "
         "keywords_json, tags_json, evidence_json, summary, reason, status, tagged_at) "
         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (article_id, rq_id) DO UPDATE SET "
         "signature = EXCLUDED.signature, matched = EXCLUDED.matched, match_confidence = EXCLUDED.match_confidence, "
         "keywords_json = EXCLUDED.keywords_json, tags_json = EXCLUDED.tags_json, "
         "evidence_json = EXCLUDED.evidence_json, summary = EXCLUDED.summary, reason = EXCLUDED.reason, "
         "status = CASE WHEN intel_article_rq.decided_by IS NULL THEN EXCLUDED.status "
         "ELSE intel_article_rq.status END, tagged_at = EXCLUDED.tagged_at",
         (project_id, article_id, rq_id, signature, int(bool(result.get("matched"))), result.get("match_confidence"),
          json.dumps(result.get("keywords") or []), json.dumps(result.get("tags") or {}, default=str),
          json.dumps(result.get("evidence") or {}, default=str), result.get("summary", ""), result.get("reason", ""),
          status, time.time()))


def _existing_pairs(conn, project_id: int, article_ids: list[int]) -> set[tuple[int, str]]:
    rows = conn.execute(f"SELECT article_id, rq_id FROM intel_article_rq WHERE project_id = ? "
                        f"AND article_id IN ({_marks(len(article_ids))})", (project_id, *article_ids)).fetchall()
    return {(r[0], r[1]) for r in rows}


def decide(project_id: int, article_ids: list[int], rq_ids: list[str] | None, status: str, by: str,
           reason: str | None) -> list[dict]:
    """Set status on those articles' RQ rows; returns the snapshot `undo` needs (created rows are marked)."""
    if not article_ids:
        return []
    now = time.time()
    conn = _conn()
    try:
        sql = ("SELECT id, status, decided_by, decided_at, decision_reason FROM intel_article_rq "
               f"WHERE project_id = ? AND article_id IN ({_marks(len(article_ids))})")
        params: list = [project_id, *article_ids]
        if rq_ids is not None:
            sql += f" AND rq_id IN ({_marks(len(rq_ids))})"
            params += rq_ids
        snapshot = _dicts(conn.execute(sql, tuple(params)).fetchall())
        for s in snapshot:
            conn.execute("UPDATE intel_article_rq SET status = ?, decided_by = ?, decided_at = ?, decision_reason = ? "
                         "WHERE id = ?", (status, by, now, reason, s["id"]))
        have = _existing_pairs(conn, project_id, article_ids)
        for aid in article_ids:
            for rq in rq_ids or []:  # a missing (article, RQ) row is created, e.g. bulk "approve for RQ2"
                if (aid, rq) in have:
                    continue
                new = conn.execute(
                    "INSERT INTO intel_article_rq (project_id, article_id, rq_id, signature, matched, status, "
                    "decided_by, decided_at, decision_reason) VALUES (?, ?, ?, '', 1, ?, ?, ?, ?) "
                    "ON CONFLICT (article_id, rq_id) DO NOTHING RETURNING id",
                    (project_id, aid, rq, status, by, now, reason)).fetchone()
                if new:
                    snapshot.append({"id": new[0], "created": True})
        conn.commit()
        return snapshot
    finally:
        conn.close()


def undo(project_id: int, snapshot: list[dict]) -> None:
    conn = _conn()
    try:
        for s in snapshot:
            if s.get("created"):
                conn.execute("DELETE FROM intel_article_rq WHERE id = ? AND project_id = ?", (s["id"], project_id))
            else:
                conn.execute("UPDATE intel_article_rq SET status = ?, decided_by = ?, decided_at = ?, "
                             "decision_reason = ? WHERE id = ? AND project_id = ?",
                             (s["status"], s["decided_by"], s["decided_at"], s["decision_reason"], s["id"], project_id))
        conn.commit()
    finally:
        conn.close()


# ---- listing -------------------------------------------------------------------------------------------------------
def _status_clause(status: str, rq_id: str | None) -> tuple[str, tuple]:
    """approved = every counted RQ row approved; review = any counted row pending; irrelevant = none or all irrelevant."""
    scope = "m.article_id = a.id" + (" AND m.rq_id = ?" if rq_id else "")
    args = (rq_id,) if rq_id else ()
    ex = f"EXISTS (SELECT 1 FROM intel_article_rq m WHERE {scope} AND {_COUNTED}"
    if status == "approved":
        return f"{ex}) AND NOT {ex} AND m.status <> 'approved')", args + args
    if status == "review":
        return f"{ex} AND m.status = 'pending')", args
    return f"NOT {ex} AND m.status <> 'irrelevant')", args


def _where(project_id: int, f: dict) -> tuple[str, list]:
    sql, params = ["a.project_id = ?"], [project_id]
    for col in ("channel", "sentiment", "content_status"):
        if f.get(col):
            sql.append(f"a.{col} = ?")
            params.append(f[col])
    if f.get("theme"):
        paths = ("primary", "secondary", "tertiary")
        sql.append("(" + " OR ".join(f"LOWER(CAST(a.tags_json AS jsonb) #>> '{{themes,{p}}}') = LOWER(?)"
                                     for p in paths) + ")")
        params += [f["theme"]] * len(paths)
    if f.get("brand"):
        sql.append("EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(CAST(a.tags_json AS jsonb) -> 'brands', "
                   "CAST('[]' AS jsonb))) b WHERE LOWER(b ->> 'brand') = LOWER(?))")
        params.append(f["brand"])
    if f.get("q"):
        sql.append("(a.title ILIKE ? OR a.summary ILIKE ? OR a.outlet ILIKE ?)")
        params += [f"%{f['q']}%"] * 3
    if f.get("status"):
        clause, args = _status_clause(f["status"], f.get("rq_id"))
        sql.append(clause)
        params += args
    elif f.get("rq_id"):
        sql.append("EXISTS (SELECT 1 FROM intel_article_rq m WHERE m.article_id = a.id AND m.rq_id = ?)")
        params.append(f["rq_id"])
    return " AND ".join(sql), params


def page(project_id: int, *, channel=None, status=None, rq_id=None, sentiment=None, theme=None, brand=None,
         content_status=None, q=None, offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
    where, params = _where(project_id, dict(channel=channel, status=status, rq_id=rq_id, sentiment=sentiment,
                                            theme=theme, brand=brand, content_status=content_status, q=q))
    total = int(_run(f"SELECT COUNT(*) FROM intel_articles a WHERE {where}", tuple(params), one=True)[0])
    arts = _dicts(_run(f"SELECT {_LIST_COLS} FROM intel_articles a WHERE {where} ORDER BY a.id LIMIT ? OFFSET ?",
                       (*params, limit, offset)))
    if arts:
        rows = _run(f"SELECT {_RQ_COLS} FROM intel_article_rq WHERE article_id IN ({_marks(len(arts))}) ORDER BY rq_id",
                    tuple(a["id"] for a in arts))
        by_art: dict[int, list[dict]] = {}
        for r in rows:
            by_art.setdefault(r["article_id"], []).append(dict(r))
        for a in arts:
            a["rq"] = by_art.get(a["id"], [])
    return arts, total


def ids_matching(project_id: int, **filters) -> list[int]:
    where, params = _where(project_id, filters)
    return [r[0] for r in _run(f"SELECT a.id FROM intel_articles a WHERE {where} ORDER BY a.id", tuple(params))]


def approved(project_id: int, rq_ids: list[str]) -> list[dict]:
    if not rq_ids:
        return []
    rows = _run(f"SELECT {_LIST_COLS}, a.content, m.rq_id FROM intel_articles a JOIN intel_article_rq m "
                f"ON m.article_id = a.id WHERE a.project_id = ? AND m.status = 'approved' "
                f"AND m.rq_id IN ({_marks(len(rq_ids))}) ORDER BY a.id, m.rq_id", (project_id, *rq_ids))
    out: dict[int, dict] = {}
    for r in rows:
        d = out.setdefault(r["id"], {**{k: r[k] for k in r.keys() if k != "rq_id"}, "approved_rq_ids": []})
        d["approved_rq_ids"].append(r["rq_id"])
    return list(out.values())
