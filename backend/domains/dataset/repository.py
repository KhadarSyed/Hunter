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
            "summary, reason, status, decided_by, decided_at, decision_reason, tagged_at, query_changed")
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


_FILE_ARTICLES = "SELECT id FROM intel_articles WHERE project_id = ? AND file_id = ?"


def get_file(project_id: int, file_id: int) -> dict | None:
    rows = _dicts(_run("SELECT id, file_name, s3_key FROM intel_upload_files WHERE project_id = ? AND id = ?",
                       (project_id, file_id)))
    return rows[0] if rows else None


def file_impact(project_id: int, file_id: int) -> dict:
    """What removing a file takes with it: its articles (deduped copies stay with the file that added them)."""
    row = _run(f"SELECT (SELECT COUNT(*) FROM ({_FILE_ARTICLES}) f) AS articles, "
               f"(SELECT COUNT(DISTINCT article_id) FROM intel_article_rq WHERE status = 'approved' "
               f"AND article_id IN ({_FILE_ARTICLES})) AS approved",
               (project_id, file_id, project_id, file_id), one=True)
    return {"articles": int(row["articles"]), "approved": int(row["approved"])}


def delete_file(project_id: int, file_id: int) -> dict:
    """Remove a file, its articles and their RQ rows in one transaction."""
    impact = file_impact(project_id, file_id)
    conn = _conn()
    try:
        conn.execute(f"DELETE FROM intel_article_rq WHERE article_id IN ({_FILE_ARTICLES})", (project_id, file_id))
        conn.execute("DELETE FROM intel_articles WHERE project_id = ? AND file_id = ?", (project_id, file_id))
        conn.execute("DELETE FROM intel_upload_files WHERE project_id = ? AND id = ?", (project_id, file_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"articles_removed": impact["articles"], "approved_removed": impact["approved"]}


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
    # social rows go through the content phase too: content.fetch keeps the post's own text, with no network call
    cond = {"content": "content_status = 'pending' AND rq_matched IS DISTINCT FROM 0 AND copy_of IS NULL",
            "tags": "tag_status IN ('pending', 'failed') AND content_status <> 'pending' AND rq_matched IS DISTINCT FROM 0 "
                    "AND copy_of IS NULL"}[phase]
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
        for r in _run(f"SELECT {col} AS s, COUNT(*) AS n FROM intel_articles WHERE project_id = ? "
                      f"AND rq_matched IS DISTINCT FROM 0 GROUP BY {col}", (project_id,)):
            out[key][r["s"]] = int(r["n"])
    out["total"] = sum(out["tags"].values())
    pools = {r["m"]: int(r["n"]) for r in _run("SELECT COALESCE(rq_matched, -1) AS m, COUNT(*) AS n FROM intel_articles "
                                               "WHERE project_id = ? GROUP BY 1", (project_id,))}
    out["matched"], out["irrelevant"], out["unmatched"] = pools.get(1, 0), pools.get(0, 0), pools.get(-1, 0)
    return out


def save_copies(project_id: int, copy_of: dict[int, int]) -> None:
    """copy id -> original id; every other article of the project is an original."""
    conn = _conn()
    try:
        conn.execute("UPDATE intel_articles SET copy_of = NULL WHERE project_id = ?", (project_id,))
        for copy_id, orig in copy_of.items():
            conn.execute("UPDATE intel_articles SET copy_of = ? WHERE id = ? AND project_id = ?", (orig, copy_id, project_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def inherit_article_tags(project_id: int) -> int:
    """Copies take their tagged original's article tags (no GPT call of their own)."""
    conn = _conn()
    try:
        n = conn.execute(
            "UPDATE intel_articles a SET tags_json = o.tags_json, sentiment = o.sentiment, "
            "sentiment_confidence = o.sentiment_confidence, tag_status = o.tag_status, tag_error = NULL, "
            "content_status = CASE WHEN a.content_status = 'pending' THEN 'not_needed' ELSE a.content_status END "
            "FROM intel_articles o WHERE a.copy_of = o.id AND a.project_id = ? AND o.tag_status = 'tagged' "
            "AND a.tag_status <> 'tagged'", (project_id,)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def inherit_rq_rows(project_id: int) -> int:
    """Copies take their original's research-question result (match, tags, summary, status) for each question both
    rows exist for; a copy an analyst decided is never touched."""
    conn = _conn()
    try:
        n = conn.execute(
            "UPDATE intel_article_rq r SET signature = o.signature, matched = o.matched, "
            "match_confidence = o.match_confidence, keywords_json = o.keywords_json, tags_json = o.tags_json, "
            "evidence_json = o.evidence_json, summary = o.summary, reason = o.reason, status = o.status, "
            "tagged_at = o.tagged_at FROM intel_articles a, intel_article_rq o "
            "WHERE r.article_id = a.id AND a.copy_of = o.article_id AND o.rq_id = r.rq_id AND r.project_id = ? "
            "AND r.decided_by IS NULL AND o.tagged_at IS NOT NULL "
            "AND (r.signature <> o.signature OR r.tagged_at IS NULL)", (project_id,)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def save_rq_matches(project_id: int, by_rq: dict[str, set[int]]) -> None:
    """The Boolean match, in one transaction: a "needs tagging" row per matched (article, question) pair (a row
    already there is left as it is), and each article flagged matched (1) or Irrelevant (0)."""
    matched = set().union(*by_rq.values()) if by_rq else set()
    conn = _conn()
    try:
        for rq_id, ids in by_rq.items():
            for aid in ids:
                conn.execute("INSERT INTO intel_article_rq (project_id, article_id, rq_id, signature, matched, status) "
                             "VALUES (?, ?, ?, '', 1, 'pending') ON CONFLICT (article_id, rq_id) DO NOTHING",
                             (project_id, aid, rq_id))
        conn.execute("UPDATE intel_articles SET rq_matched = CASE WHEN id = ANY(?) THEN 1 ELSE 0 END "
                     "WHERE project_id = ?", (list(matched), project_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
# Signature of a row a query edit re-matched for free: current until the next RQ run adopts the real signature.
# An empty signature marks a row that needs tagging (e.g. it matches the edited query and did not before).
REMATCHED = "rematched"
# only the (article, question) pairs the Boolean match wrote: an article a question's query misses is never sent
_NEEDING = ("FROM intel_articles a JOIN intel_article_rq r ON r.article_id = a.id AND r.rq_id = ? AND r.matched = 1 "
            "WHERE a.project_id = ? AND a.tag_status = 'tagged' AND a.copy_of IS NULL AND r.signature NOT IN (?, ?)")


def rq_rows_needing(project_id: int, rq_id: str, signature: str, limit: int) -> list[dict]:
    return _dicts(_run(
        "SELECT a.id, a.norm_url, a.url, a.channel, a.title, a.summary, a.content, a.content_status, a.tags_json "
        f"{_NEEDING} ORDER BY a.id LIMIT ?", (rq_id, project_id, signature, REMATCHED, limit)))


def adopt_rematched(project_id: int, rq_id: str, signature: str) -> None:
    _run("UPDATE intel_article_rq SET signature = ? WHERE project_id = ? AND rq_id = ? AND signature = ?",
         (signature, project_id, rq_id, REMATCHED))


def rq_counts(project_id: int, rq_id: str, signature: str) -> dict:
    row = _run("SELECT COALESCE(SUM(matched), 0) AS matched, COUNT(tagged_at) AS tagged, "
               "COALESCE(SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END), 0) AS approved, "
               "COALESCE(SUM(query_changed), 0) AS query_changed FROM intel_article_rq "
               "WHERE project_id = ? AND rq_id = ?", (project_id, rq_id), one=True)
    need = _run(f"SELECT COUNT(*) {_NEEDING}", (rq_id, project_id, signature, REMATCHED), one=True)[0]
    return {**{k: int(row[k]) for k in ("matched", "tagged", "approved", "query_changed")}, "needs_tagging": int(need)}


def match_texts(project_id: int) -> list[dict]:
    """Every article's id, title and the text a Boolean query is matched on (title, summary, content)."""
    return _dicts(_run("SELECT id, title, CONCAT_WS(CHR(10), title, summary, content) AS text FROM intel_articles "
                       "WHERE project_id = ? ORDER BY id", (project_id,)))


def matched_ids(project_id: int, rq_id: str) -> list[int]:
    return [r[0] for r in _run("SELECT article_id FROM intel_article_rq WHERE project_id = ? AND rq_id = ? AND matched = 1",
                               (project_id, rq_id))]


def apply_rematch(project_id: int, rq_id: str, old_signature: str, added: list[int], dropped: list[int],
                  reason: str) -> None:
    """After a query edit, in one transaction:
    - rows tagged under the pre-edit signature count as current (REMATCHED; the next RQ run adopts the new one);
    - an added article needs tagging (matched, empty signature, pending), unless its row already matches or an
      analyst decided it (never touched);
    - a dropped row neither decided nor approved becomes irrelevant; a decided or approved one keeps its status and
      is flagged query_changed."""
    conn = _conn()
    try:
        conn.execute("UPDATE intel_article_rq SET signature = ? WHERE project_id = ? AND rq_id = ? AND signature = ?",
                     (REMATCHED, project_id, rq_id, old_signature))
        for aid in added:
            conn.execute(
                "INSERT INTO intel_article_rq (project_id, article_id, rq_id, signature, matched, status) "
                "VALUES (?, ?, ?, '', 1, 'pending') ON CONFLICT (article_id, rq_id) DO UPDATE SET signature = '', "
                "matched = 1, query_changed = 0, status = 'pending' "
                "WHERE intel_article_rq.matched = 0 AND intel_article_rq.decided_by IS NULL", (project_id, aid, rq_id))
        if dropped:
            conn.execute("UPDATE intel_article_rq SET matched = 0, status = 'irrelevant', reason = ? "
                         "WHERE project_id = ? AND rq_id = ? AND decided_by IS NULL AND status <> 'approved' "
                         "AND article_id = ANY(?)", (reason, project_id, rq_id, dropped))
            conn.execute("UPDATE intel_article_rq SET query_changed = 1 WHERE project_id = ? AND rq_id = ? "
                         "AND (decided_by IS NOT NULL OR status = 'approved') AND article_id = ANY(?)",
                         (project_id, rq_id, dropped))
        conn.commit()
    finally:
        conn.close()


def deck_run_active(project_id: int) -> bool:
    return _run("SELECT 1 FROM intel_deliverable_runs WHERE project_id = ? AND status IN ('running', 'queued') "
                "LIMIT 1", (project_id,), one=True) is not None


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
    rows = conn.execute("SELECT article_id, rq_id FROM intel_article_rq WHERE project_id = ? "
                        "AND article_id = ANY(?)", (project_id, article_ids)).fetchall()
    return {(r[0], r[1]) for r in rows}


def decide(project_id: int, article_ids: list[int], rq_ids: list[str] | None, status: str, by: str,
           reason: str | None) -> list[dict]:
    """Set status on those articles' RQ rows; returns the snapshot `undo` needs (created rows are marked).
    Only articles of this project are touched; ids of other projects are dropped. rq_ids None ("all matched RQs")
    touches only existing rows: matched ones, plus analyst-decided ones when not approving, and creates none."""
    if not article_ids:
        return []
    now = time.time()
    conn = _conn()
    try:
        article_ids = [r[0] for r in conn.execute("SELECT id FROM intel_articles WHERE project_id = ? AND id = ANY(?)",
                                                  (project_id, list(article_ids))).fetchall()]
        if not article_ids:
            return []
        sql = ("SELECT id, status, decided_by, decided_at, decision_reason FROM intel_article_rq "
               "WHERE project_id = ? AND article_id = ANY(?)")
        params: list = [project_id, article_ids]
        if rq_ids is not None:
            sql += " AND rq_id = ANY(?)"
            params.append(list(rq_ids))
        else:   # never approve an RQ the article did not match
            sql += " AND matched = 1" if status == "approved" else " AND (matched = 1 OR decided_by IS NOT NULL)"
        snapshot = _dicts(conn.execute(sql, tuple(params)).fetchall())
        if snapshot:
            conn.execute("UPDATE intel_article_rq SET status = ?, decided_by = ?, decided_at = ?, decision_reason = ? "
                         "WHERE id = ANY(?)", (status, by, now, reason, [s["id"] for s in snapshot]))
        have = _existing_pairs(conn, project_id, article_ids)
        pairs = [(aid, rq) for aid in article_ids for rq in rq_ids or [] if (aid, rq) not in have]
        if pairs:   # a missing (article, RQ) row is created, e.g. bulk "approve for RQ2"
            made = conn.execute(
                "INSERT INTO intel_article_rq (project_id, article_id, rq_id, signature, matched, status, decided_by, "
                "decided_at, decision_reason) SELECT ?, t.a, t.r, '', 1, ?, ?, ?, ? "
                "FROM unnest(?::bigint[], ?::text[]) AS t(a, r) ON CONFLICT (article_id, rq_id) DO NOTHING RETURNING id",
                (project_id, status, by, now, reason, [p[0] for p in pairs], [p[1] for p in pairs])).fetchall()
            snapshot += [{"id": m[0], "created": True} for m in made]
        conn.commit()
        return snapshot
    finally:
        conn.close()


def undo(project_id: int, snapshot: list[dict]) -> None:
    conn = _conn()
    try:
        created = [s["id"] for s in snapshot if s.get("created")]
        old = [s for s in snapshot if not s.get("created")]
        if created:
            conn.execute("DELETE FROM intel_article_rq WHERE id = ANY(?) AND project_id = ?", (created, project_id))
        if old:
            conn.execute(
                "UPDATE intel_article_rq m SET status = t.s, decided_by = t.b, decided_at = t.d, decision_reason = t.r "
                "FROM unnest(?::bigint[], ?::text[], ?::text[], ?::float8[], ?::text[]) AS t(i, s, b, d, r) "
                "WHERE m.id = t.i AND m.project_id = ?",
                ([s["id"] for s in old], [s["status"] for s in old], [s["decided_by"] for s in old],
                 [s["decided_at"] for s in old], [s["decision_reason"] for s in old], project_id))
        conn.commit()
    finally:
        conn.close()


# ---- listing -------------------------------------------------------------------------------------------------------
def _status_clause(status: str, rq_id: str | None) -> tuple[str, tuple]:
    """approved = every counted RQ row approved; review = any counted row pending; irrelevant = counted rows all irrelevant; no_match = no counted row."""
    scope = "m.article_id = a.id" + (" AND m.rq_id = ?" if rq_id else "")
    args = (rq_id,) if rq_id else ()
    ex = f"EXISTS (SELECT 1 FROM intel_article_rq m WHERE {scope} AND {_COUNTED}"
    if status == "approved":
        return f"{ex}) AND NOT {ex} AND m.status <> 'approved')", args + args
    if status == "review":
        return f"{ex} AND m.status = 'pending')", args
    if status == "no_match":
        return f"NOT {ex})", args
    return f"{ex}) AND NOT {ex} AND m.status <> 'irrelevant')", args + args


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
    if f.get("pool") == "irrelevant":
        sql.append("a.rq_matched = 0")
    elif f.get("pool") == "matched":
        sql.append("a.rq_matched IS DISTINCT FROM 0")
    if f.get("ids"):
        sql.append("a.id = ANY(?)")
        params.append(list(f["ids"]))
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
         content_status=None, q=None, ids=None, pool=None, offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
    where, params = _where(project_id, dict(channel=channel, status=status, rq_id=rq_id, sentiment=sentiment,
                                            theme=theme, brand=brand, content_status=content_status, q=q, ids=ids,
                                            pool=pool))
    total = int(_run(f"SELECT COUNT(*) FROM intel_articles a WHERE {where}", tuple(params), one=True)[0])
    arts = _dicts(_run(f"SELECT {_LIST_COLS}, a.content FROM intel_articles a WHERE {where} ORDER BY a.id LIMIT ? OFFSET ?",
                       (*params, limit, offset)))
    if arts:
        rows = _run("SELECT " + _RQ_COLS + " FROM intel_article_rq WHERE project_id = ? AND article_id = ANY(?) ORDER BY rq_id",
                    (project_id, [a["id"] for a in arts]))
        by_art: dict[int, list[dict]] = {}
        for r in rows:
            by_art.setdefault(r["article_id"], []).append(dict(r))
        for a in arts:
            a["rq"] = by_art.get(a["id"], [])
    return arts, total


def facets(project_id: int, channel: str) -> dict:
    """The filter dropdowns' values for one channel: distinct theme labels, brand names and content statuses."""
    base = "FROM intel_articles a WHERE a.project_id = ? AND a.channel = ?"
    themes = _run("SELECT DISTINCT x.v FROM intel_articles a CROSS JOIN LATERAL (VALUES "
                  + ", ".join(f"(CAST(a.tags_json AS jsonb) #>> '{{themes,{p}}}')" for p in ("primary", "secondary", "tertiary"))
                  + ") AS x(v) WHERE a.project_id = ? AND a.channel = ? AND COALESCE(x.v, '') <> '' ORDER BY x.v",
                  (project_id, channel))
    brands = _run("SELECT DISTINCT b ->> 'brand' AS v FROM intel_articles a CROSS JOIN LATERAL jsonb_array_elements("
                  "CASE WHEN jsonb_typeof(CAST(a.tags_json AS jsonb) -> 'brands') = 'array' "
                  "THEN CAST(a.tags_json AS jsonb) -> 'brands' ELSE CAST('[]' AS jsonb) END) b "
                  "WHERE a.project_id = ? AND a.channel = ? AND COALESCE(b ->> 'brand', '') <> '' ORDER BY 1",
                  (project_id, channel))
    statuses = _run(f"SELECT DISTINCT a.content_status AS v {base} ORDER BY 1", (project_id, channel))
    return {"themes": [r[0] for r in themes], "brands": [r[0] for r in brands],
            "content_statuses": [r[0] for r in statuses]}


def ids_matching(project_id: int, **filters) -> list[int]:
    where, params = _where(project_id, filters)
    return [r[0] for r in _run(f"SELECT a.id FROM intel_articles a WHERE {where} ORDER BY a.id", tuple(params))]


def approved(project_id: int, rq_ids: list[str]) -> list[dict]:
    """Articles with an approved row for any of rq_ids: approved_rq_ids, and per RQ its {"tags", "evidence"} (JSON text)."""
    if not rq_ids:
        return []
    rows = _run(f"SELECT {_LIST_COLS}, a.content, a.raw_json, m.rq_id, m.tags_json AS rq_tags_json, "
                f"m.evidence_json AS rq_evidence_json FROM intel_articles a JOIN intel_article_rq m "
                f"ON m.article_id = a.id WHERE a.project_id = ? AND m.project_id = ? AND m.status = 'approved' "
                f"AND m.rq_id = ANY(?) ORDER BY a.id, m.rq_id", (project_id, project_id, list(rq_ids)))
    per_rq = ("rq_id", "rq_tags_json", "rq_evidence_json")
    out: dict[int, dict] = {}
    for r in rows:
        d = out.setdefault(r["id"], {**{k: r[k] for k in r.keys() if k not in per_rq}, "approved_rq_ids": [], "rq": {}})
        d["approved_rq_ids"].append(r["rq_id"])
        d["rq"][r["rq_id"]] = {"tags": r["rq_tags_json"], "evidence": r["rq_evidence_json"]}
    return list(out.values())


def approved_count(project_id: int, rq_ids: list[str]) -> int:
    """Approved article-RQ rows of this project for any of rq_ids."""
    if not rq_ids:
        return 0
    return int(_run("SELECT COUNT(*) FROM intel_article_rq WHERE project_id = ? AND status = 'approved' "
                    "AND rq_id = ANY(?)", (project_id, list(rq_ids)), one=True)[0])


def approved_counts_by_rq(project_id: int, rq_ids: list[str]) -> dict[str, int]:
    """{rq_id: approved article rows} of this project for those RQs."""
    if not rq_ids:
        return {}
    return {r["rq_id"]: int(r["n"]) for r in _run(
        "SELECT rq_id, COUNT(*) AS n FROM intel_article_rq WHERE project_id = ? AND status = 'approved' "
        "AND rq_id = ANY(?) GROUP BY rq_id", (project_id, list(rq_ids)))}


def edit_article(project_id: int, article_id: int, sentiment: str | None, themes: list[str] | None,
                 brands: list[str] | None) -> list[str] | None:
    """Apply an analyst's edit to the article's tags; returns the matched RQ ids still undecided (an edit confirms
    those; an analyst's earlier decision stays), or None when it is not found."""
    row = _run("SELECT tags_json FROM intel_articles WHERE id = ? AND project_id = ?", (article_id, project_id), one=True)
    if not row:
        return None
    tags = json.loads(row["tags_json"] or "{}")
    if sentiment is not None:
        tags["overall_sentiment"] = sentiment
    if themes is not None:
        tags["themes"] = dict(zip(("primary", "secondary", "tertiary"), [*themes[:3], None, None, None]))
    if brands is not None:
        known = {str(b.get("brand", "")).lower(): b for b in tags.get("brands") or []}
        tags["brands"] = [known.get(b.lower(), {"brand": b}) for b in brands]
        tags["entities"] = {**(tags.get("entities") or {}), "brands": list(brands)}   # the deck reads entities.brands
    _run("UPDATE intel_articles SET tags_json = ?, sentiment = COALESCE(?, sentiment) WHERE id = ?",
         (json.dumps(tags, default=str), sentiment, article_id))
    return [r[0] for r in _run("SELECT rq_id FROM intel_article_rq WHERE article_id = ? AND matched = 1 "
                               "AND decided_by IS NULL ORDER BY rq_id",
                               (article_id,))]
