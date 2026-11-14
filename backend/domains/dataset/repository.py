"""SQL for the data set (migration 37) through SQLAlchemy Core: upload files, project-wide articles, per-RQ rows,
theme titles.

Article tags_json is read as {"themes": {"primary": ...}, "brands": [{"brand": ...}]} by the theme/brand filters.
"""
from __future__ import annotations

import json
import time

from sqlalchemy import (BigInteger, Double, Text, and_, any_, bindparam, case, cast, column, delete, exists, func,
                        literal, not_, or_, select, true, union_all, update)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, insert as pg_insert

from ...core import sa
from .models import (intel_article_rq as R, intel_articles as A, intel_deliverable_runs as D, intel_projects as P,
                     intel_theme_titles as T, intel_upload_files as F)

_LIST_COLS = tuple(A.c[n] for n in (
    "id", "project_id", "norm_url", "url", "channel", "title", "summary", "outlet", "published", "country", "reach",
    "author_name", "author_id", "post_id", "file_id", "content_status", "tags_json", "tag_status", "tag_error",
    "sentiment", "sentiment_confidence", "syndicated_json", "similar_json", "excluded_reason", "keep_by", "keep_at",
    "keep_comment"))
_RQ_COLS = tuple(R.c[n] for n in (
    "id", "article_id", "rq_id", "signature", "matched", "match_confidence", "keywords_json", "tags_json",
    "evidence_json", "summary", "reason", "status", "decided_by", "decided_at", "decision_reason", "tagged_at",
    "query_changed"))
_INSERT_CHUNK = 1000        # rows per multi-row INSERT: keeps each statement under Postgres's 65535 parameters


def _ids(values) -> object:
    """A list bound as one array parameter (= ANY(...)), however long, instead of one parameter per id."""
    return any_(bindparam(None, list(values), type_=ARRAY(BigInteger)))


def _texts(values) -> object:
    return any_(bindparam(None, list(values), type_=ARRAY(Text)))


def _all(query) -> list[dict]:
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(query)]


def _first(query) -> dict | None:
    with sa.begin() as conn:
        r = conn.execute(query).first()
    return dict(r._mapping) if r else None


def _scalar(query):
    with sa.begin() as conn:
        return conn.execute(query).scalar()


def _exec(query) -> int:
    with sa.begin() as conn:
        return conn.execute(query).rowcount


def _chunks(rows: list) -> list[list]:
    return [rows[i:i + _INSERT_CHUNK] for i in range(0, len(rows), _INSERT_CHUNK)]


# ---- upload files --------------------------------------------------------------------------------------------------
def add_file(project_id: int, file_name: str, s3_key: str | None, content: bytes | None, uploaded_by: str | None) -> int:
    return int(_scalar(F.insert().values(project_id=project_id, file_name=file_name, s3_key=s3_key, content=content,
                                         uploaded_by=uploaded_by, created_at=time.time()).returning(F.c.id)))


def finish_file(file_id: int, rows_read: int, added: int, duplicates: int, error: str | None = None) -> None:
    _exec(update(F).where(F.c.id == file_id).values(rows_read=rows_read, added=added, duplicates=duplicates,
                                                     error=error))


def list_files(project_id: int) -> list[dict]:
    return _all(select(F.c.id, F.c.file_name, F.c.s3_key, F.c.rows_read, F.c.added, F.c.duplicates, F.c.error,
                       F.c.uploaded_by, F.c.created_at).where(F.c.project_id == project_id).order_by(F.c.id.desc()))


def _file_articles(project_id: int, file_id: int):
    return select(A.c.id).where(A.c.project_id == project_id, A.c.file_id == file_id)


def get_file(project_id: int, file_id: int) -> dict | None:
    return _first(select(F.c.id, F.c.file_name, F.c.s3_key).where(F.c.project_id == project_id, F.c.id == file_id))


def file_impact(project_id: int, file_id: int) -> dict:
    """What removing a file takes with it: its articles (deduped copies stay with the file that added them)."""
    arts = _file_articles(project_id, file_id)
    with sa.begin() as conn:
        articles = conn.execute(select(func.count()).select_from(arts.subquery())).scalar()
        approved_n = conn.execute(select(func.count(R.c.article_id.distinct())).where(
            R.c.status == "approved", R.c.article_id.in_(arts))).scalar()
    return {"articles": int(articles), "approved": int(approved_n)}


def delete_file(project_id: int, file_id: int) -> dict:
    """Remove a file, its articles and their RQ rows in one transaction."""
    impact = file_impact(project_id, file_id)
    with sa.begin() as conn:
        conn.execute(delete(R).where(R.c.article_id.in_(_file_articles(project_id, file_id))))
        conn.execute(delete(A).where(A.c.project_id == project_id, A.c.file_id == file_id))
        conn.execute(delete(F).where(F.c.project_id == project_id, F.c.id == file_id))
    return {"articles_removed": impact["articles"], "approved_removed": impact["approved"]}


# ---- articles ------------------------------------------------------------------------------------------------------
def insert_articles(project_id: int, file_id: int, records: list[dict]) -> tuple[int, int]:
    """New articles of an upload; one already in the project (same normalised URL) is a duplicate."""
    now = time.time()
    rows = [{"project_id": project_id, "norm_url": r["norm_url"], "url": r["url"], "channel": r["channel"],
             "title": r.get("title", ""), "summary": r.get("summary", ""), "outlet": r.get("outlet", ""),
             "published": r.get("published"), "country": r.get("country", ""), "reach": r.get("reach") or 0,
             "author_name": r.get("author_name", ""), "author_id": r.get("author_id", ""),
             "post_id": r.get("post_id", ""), "raw_json": json.dumps(r.get("raw") or {}, default=str),
             "file_id": file_id, "created_at": now} for r in records]
    added = 0
    with sa.begin() as conn:
        for chunk in _chunks(rows):
            stmt = pg_insert(A).values(chunk).on_conflict_do_nothing(index_elements=[A.c.project_id, A.c.norm_url])
            added += len(conn.execute(stmt.returning(A.c.id)).all())
    return added, len(records) - added


def channel_counts(project_id: int) -> dict[str, int]:
    return {r["channel"]: int(r["n"]) for r in _all(
        select(A.c.channel, func.count().label("n")).where(A.c.project_id == project_id).group_by(A.c.channel))}


def articles_needing(project_id: int, phase: str, limit: int) -> list[dict]:
    # social rows go through the content phase too: content.fetch keeps the post's own text, with no network call
    # content: matched rows, and unmatched rows with too little text to match on yet (headline-only uploads), so a
    # term only in the body can still bring the article in on the second match
    cond = {"content": lambda: and_(
                A.c.content_status == "pending", A.c.copy_of.is_(None),
                or_(A.c.rq_matched.is_distinct_from(0),
                    func.length(func.coalesce(A.c.summary, "")) + func.length(func.coalesce(A.c.content, "")) < 400)),
            "tags": lambda: and_(A.c.tag_status.in_(("pending", "failed")), A.c.content_status != "pending",
                                 A.c.rq_matched.is_distinct_from(0), A.c.copy_of.is_(None))}[phase]()
    return _all(select(A.c.id, A.c.norm_url, A.c.url, A.c.channel, A.c.title, A.c.summary, A.c.outlet, A.c.published,
                       A.c.content, A.c.content_status, A.c.tags_json)
                .where(A.c.project_id == project_id, cond).order_by(A.c.id).limit(limit))


def all_articles(project_id: int) -> list[dict]:
    """Every article with the columns the theme and relation phases read (tags_json is the stored JSON text)."""
    return _all(select(A.c.id, A.c.url, A.c.title, A.c.outlet, A.c.content, A.c.summary, A.c.tag_status, A.c.tags_json,
                       A.c.syndicated_json).where(A.c.project_id == project_id).order_by(A.c.id))


def save_content(article_id: int, content: str, status: str, author: str = "") -> None:
    """The fetched text; the page's byline fills the author only where the export left it empty."""
    values = {"content": content, "content_status": status}
    if author:
        values["author_name"] = func.coalesce(func.nullif(A.c.author_name, ""), author)
    _exec(update(A).where(A.c.id == article_id).values(**values))


def save_tags(article_id: int, tags: dict | None, error: str | None) -> None:
    t = tags or {}
    _exec(update(A).where(A.c.id == article_id).values(
        tags_json=json.dumps(tags, default=str) if tags is not None else None,
        sentiment=t.get("overall_sentiment"), sentiment_confidence=t.get("overall_sentiment_confidence"),
        tag_status="failed" if error or tags is None else "tagged", tag_error=error))


def save_relations(project_id: int, relations: dict[int, dict]) -> None:
    with sa.begin() as conn:
        for aid, rel in relations.items():
            conn.execute(update(A).where(A.c.id == aid, A.c.project_id == project_id).values(
                syndicated_json=json.dumps(rel.get("syndicated") or []),
                similar_json=json.dumps(rel.get("similar") or [])))


def tagging_counts(project_id: int) -> dict:
    out: dict = {"total": 0, "content": {}, "tags": {}}
    pool = func.coalesce(A.c.rq_matched, -1)
    with sa.begin() as conn:
        for key, col in (("content", A.c.content_status), ("tags", A.c.tag_status)):
            for s, n in conn.execute(select(col, func.count()).where(
                    A.c.project_id == project_id, A.c.rq_matched.is_distinct_from(0)).group_by(col)):
                out[key][s] = int(n)
        pools = {m: int(n) for m, n in conn.execute(
            select(pool, func.count()).where(A.c.project_id == project_id).group_by(pool))}
        aside = {k: int(conn.execute(select(func.count()).where(A.c.project_id == project_id,
                                                                A.c.excluded_reason.like(p + "%"))).scalar() or 0)
                 for k, p in (("blocked", BLOCK_PREFIX), ("out_of_scope", OUT_OF_SCOPE_PREFIX))}
    out["total"] = sum(out["tags"].values())
    out["matched"], out["unmatched"] = pools.get(1, 0), pools.get(-1, 0)
    out["irrelevant"] = max(pools.get(0, 0) - aside["blocked"] - aside["out_of_scope"], 0)
    out.update(aside)
    return out


def save_copies(project_id: int, copy_of: dict[int, int]) -> None:
    """copy id -> original id; every other article of the project is an original."""
    with sa.begin() as conn:
        conn.execute(update(A).where(A.c.project_id == project_id).values(copy_of=None))
        for copy_id, orig in copy_of.items():
            conn.execute(update(A).where(A.c.id == copy_id, A.c.project_id == project_id).values(copy_of=orig))


def inherit_article_tags(project_id: int) -> int:
    """Copies take their tagged original's article tags (no GPT call of their own)."""
    o = A.alias("o")
    return _exec(update(A).where(A.c.copy_of == o.c.id, A.c.project_id == project_id, o.c.tag_status == "tagged",
                                 A.c.tag_status != "tagged").values(
        tags_json=o.c.tags_json, sentiment=o.c.sentiment, sentiment_confidence=o.c.sentiment_confidence,
        tag_status=o.c.tag_status, tag_error=None,
        content_status=case((A.c.content_status == "pending", "not_needed"), else_=A.c.content_status)))


def inherit_rq_rows(project_id: int) -> int:
    """Copies take their original's research-question result (match, tags, summary, status) for each question both
    rows exist for; a copy an analyst decided is never touched."""
    o = R.alias("o")
    return _exec(update(R).where(
        R.c.article_id == A.c.id, A.c.copy_of == o.c.article_id, o.c.rq_id == R.c.rq_id, R.c.project_id == project_id,
        R.c.decided_by.is_(None), o.c.tagged_at.isnot(None),
        or_(R.c.signature != o.c.signature, R.c.tagged_at.is_(None))).values(
        signature=o.c.signature, matched=o.c.matched, match_confidence=o.c.match_confidence,
        keywords_json=o.c.keywords_json, tags_json=o.c.tags_json, evidence_json=o.c.evidence_json,
        summary=o.c.summary, reason=o.c.reason, status=o.c.status, tagged_at=o.c.tagged_at))


def dataset_approval(project_id: int) -> dict | None:
    row = _first(select(P.c.dataset_approved_at.label("at"), P.c.dataset_approved_by.label("by"))
                 .where(P.c.id == project_id))
    return {"at": row["at"], "by": row["by"]} if row and row["at"] else None


def set_dataset_approval(project_id: int, by: str | None) -> None:
    """by=None clears it (the data changed, so the analyst approves again)."""
    _exec(update(P).where(P.c.id == project_id).values(dataset_approved_at=time.time() if by else None,
                                                       dataset_approved_by=by))


def _analyst_relevant():
    """The article has a question row an analyst decided as relevant (approved or sent back to review)."""
    return exists().where(R.c.article_id == A.c.id, R.c.decided_by.isnot(None), R.c.status != "irrelevant")


def save_rq_matches(project_id: int, by_rq: dict[str, set[int]]) -> None:
    """The Boolean match, in one transaction: a "needs tagging" row per matched (article, question) pair (a row
    already there is left as it is), and each article flagged matched (1) or Irrelevant (0). An article an analyst
    marked relevant stays matched whatever its query says, so the next Re-tag tags it."""
    matched = set().union(*by_rq.values()) if by_rq else set()
    rows = [{"project_id": project_id, "article_id": aid, "rq_id": rq_id, "signature": "", "matched": 1,
             "status": "pending"} for rq_id, ids in by_rq.items() for aid in ids]
    with sa.begin() as conn:
        for chunk in _chunks(rows):
            conn.execute(pg_insert(R).values(chunk).on_conflict_do_nothing(index_elements=[R.c.article_id, R.c.rq_id]))
        conn.execute(update(A).where(A.c.project_id == project_id).values(
            rq_matched=case((or_(A.c.id == _ids(matched), _analyst_relevant()), 1), else_=0)))


def promote_analyst_relevant(project_id: int) -> int:
    """Irrelevant articles an analyst just marked relevant move to the matched pool (tagged on the next Re-tag)."""
    return _exec(update(A).where(A.c.project_id == project_id, A.c.rq_matched.is_distinct_from(1),
                                 _analyst_relevant()).values(rq_matched=1))


def articles_by_ids(project_id: int, article_ids: list[int]) -> dict[int, dict]:
    """{id: article} (title, summary, content, rq_matched, tags_json) for this project's articles among the ids."""
    if not article_ids:
        return {}
    return {r["id"]: r for r in _all(select(A.c.id, A.c.title, A.c.summary, A.c.content, A.c.rq_matched, A.c.tags_json)
                                     .where(A.c.project_id == project_id, A.c.id == _ids(article_ids)))}


def article_vectors(project_id: int, model: str) -> dict[str, bytes]:
    """{article url: stored embedding bytes (float32)} for the project's articles the tagging job's relations phase
    embedded with `model` (intel_research_item_vectors, kind "article")."""
    from ..research.models import intel_research_item_vectors as V
    q = (select(A.c.url, V.c.vector).select_from(A.join(V, and_(V.c.kind == "article", V.c.item_id == A.c.id)))
         .where(A.c.project_id == project_id, V.c.model == model))
    with sa.begin() as conn:
        return {r.url: bytes(r.vector) for r in conn.execute(q)}


def delete_undecided_articles(project_id: int, article_ids: list[int]) -> set[int]:
    """Deletes these articles and their question rows, except any an analyst decided on (a decision is final).
    Returns the ids actually deleted."""
    if not article_ids:
        return set()
    decided = select(R.c.article_id).where(R.c.project_id == project_id, R.c.decided_by.isnot(None))
    with sa.begin() as conn:
        gone = set(conn.execute(delete(A).where(A.c.project_id == project_id, A.c.id == _ids(article_ids),
                                                A.c.id.notin_(decided)).returning(A.c.id)).scalars())
        if gone:
            conn.execute(delete(R).where(R.c.project_id == project_id, R.c.article_id == _ids(gone)))
    return gone


def save_theme_titles(project_id: int, mapping: dict[str, str]) -> None:
    with sa.begin() as conn:
        for key, title in mapping.items():
            stmt = pg_insert(T).values(project_id=project_id, label_key=key, title=title)
            conn.execute(stmt.on_conflict_do_update(index_elements=[T.c.project_id, T.c.label_key],
                                                    set_={"title": stmt.excluded.title}))


def theme_titles(project_id: int) -> dict[str, str]:
    return {r["label_key"]: r["title"] for r in _all(select(T.c.label_key, T.c.title).where(T.c.project_id == project_id))}


# ---- per-RQ rows ---------------------------------------------------------------------------------------------------
# Signature of a row a query edit re-matched for free: current until the next RQ run adopts the real signature.
# An empty signature marks a row that needs tagging (e.g. it matches the edited query and did not before).
REMATCHED = "rematched"


def _needing(project_id: int, rq_id: str, signature: str):
    """Only the (article, question) pairs the Boolean match wrote: an article a question's query misses is never sent."""
    return (A.join(R, and_(R.c.article_id == A.c.id, R.c.rq_id == rq_id, R.c.matched == 1)),
            and_(A.c.project_id == project_id, A.c.tag_status == "tagged", A.c.copy_of.is_(None),
                 R.c.signature.notin_((signature, REMATCHED))))


def rq_rows_needing(project_id: int, rq_id: str, signature: str, limit: int) -> list[dict]:
    joined, cond = _needing(project_id, rq_id, signature)
    return _all(select(A.c.id, A.c.norm_url, A.c.url, A.c.channel, A.c.title, A.c.summary, A.c.content,
                       A.c.content_status, A.c.tags_json).select_from(joined).where(cond).order_by(A.c.id).limit(limit))


def adopt_rematched(project_id: int, rq_id: str, signature: str) -> None:
    _exec(update(R).where(R.c.project_id == project_id, R.c.rq_id == rq_id, R.c.signature == REMATCHED)
          .values(signature=signature))


def rq_counts(project_id: int, rq_id: str, signature: str) -> dict:
    joined, cond = _needing(project_id, rq_id, signature)
    with sa.begin() as conn:
        row = conn.execute(select(
            func.coalesce(func.sum(R.c.matched), 0).label("matched"), func.count(R.c.tagged_at).label("tagged"),
            func.coalesce(func.sum(case((R.c.status == "approved", 1), else_=0)), 0).label("approved"),
            func.coalesce(func.sum(R.c.query_changed), 0).label("query_changed"))
            .where(R.c.project_id == project_id, R.c.rq_id == rq_id)).one()._mapping
        need = conn.execute(select(func.count()).select_from(joined).where(cond)).scalar()
    return {**{k: int(row[k]) for k in ("matched", "tagged", "approved", "query_changed")}, "needs_tagging": int(need)}


def match_texts(project_id: int) -> list[dict]:
    """Every article's id, title and the text a Boolean query is matched on (title, summary, content)."""
    return _all(select(A.c.id, A.c.title, A.c.url, A.c.keep_at, A.c.published, A.c.country,
                       func.concat_ws(func.chr(10), A.c.title, A.c.summary, A.c.content).label("text"))
                .where(A.c.project_id == project_id).order_by(A.c.id))


BLOCK_PREFIX = "Blocked by the organization's exclusion list"
OUT_OF_SCOPE_PREFIX = "Out of scope"        # the Data set scope filter (country, date range); never tagged


def _set_aside(col):
    return or_(col.like(BLOCK_PREFIX + "%"), col.like(OUT_OF_SCOPE_PREFIX + "%"))


def save_blocked(project_id: int, reasons: dict[int, str]) -> None:
    """The exclusion list over the Data set, in one transaction, before the match is saved: rows the list moved to
    Irrelevant whose article is no longer blocked (rule removed, or kept relevant) are cleared so the match brings them
    back; each blocked article's reason is set (others cleared) and its undecided, unapproved question rows move to
    Irrelevant with that reason. An analyst's decision is final: decided rows are never touched."""
    with sa.begin() as conn:
        conn.execute(delete(R).where(R.c.project_id == project_id, R.c.decided_by.is_(None),
                                     _set_aside(R.c.reason), not_(R.c.article_id == _ids(reasons))))
        conn.execute(update(A).where(A.c.project_id == project_id, A.c.excluded_reason.isnot(None))
                     .values(excluded_reason=None))
        for aid, why in reasons.items():
            conn.execute(update(A).where(A.c.id == aid, A.c.project_id == project_id).values(excluded_reason=why))
            conn.execute(update(R).where(R.c.project_id == project_id, R.c.article_id == aid, R.c.decided_by.is_(None),
                                         R.c.status != "approved")
                         .values(matched=0, status="irrelevant", reason=why))


def keep_relevant(project_id: int, article_id: int, by: str, comment: str) -> dict | None:
    """An analyst keeps a blocked article: the override (who, when, why) and the block reason it overrode."""
    row = _first(select(A.c.id, A.c.url, A.c.title, A.c.excluded_reason)
                 .where(A.c.id == article_id, A.c.project_id == project_id))
    if not row:
        return None
    _exec(update(A).where(A.c.id == article_id, A.c.project_id == project_id).values(
        keep_by=by, keep_at=time.time(), keep_comment=comment, excluded_reason=None))
    return row


def kept_urls(project_id: int) -> set[str]:
    """Normalised URLs of the articles an analyst kept relevant despite the exclusion list."""
    return {r["norm_url"] for r in _all(select(A.c.norm_url).where(A.c.project_id == project_id,
                                                                   A.c.keep_at.isnot(None)))}


def matched_ids(project_id: int, rq_id: str) -> list[int]:
    return [r["article_id"] for r in _all(select(R.c.article_id).where(R.c.project_id == project_id,
                                                                      R.c.rq_id == rq_id, R.c.matched == 1))]


def apply_rematch(project_id: int, rq_id: str, old_signature: str, added: list[int], dropped: list[int],
                  reason: str) -> None:
    """After a query edit, in one transaction:
    - rows tagged under the pre-edit signature count as current (REMATCHED; the next RQ run adopts the new one);
    - an added article needs tagging (matched, empty signature, pending), unless its row already matches or an
      analyst decided it (never touched);
    - a dropped row neither decided nor approved becomes irrelevant; a decided or approved one keeps its status and
      is flagged query_changed."""
    with sa.begin() as conn:
        conn.execute(update(R).where(R.c.project_id == project_id, R.c.rq_id == rq_id, R.c.signature == old_signature)
                     .values(signature=REMATCHED))
        for aid in added:
            stmt = pg_insert(R).values(project_id=project_id, article_id=aid, rq_id=rq_id, signature="", matched=1,
                                       status="pending")
            conn.execute(stmt.on_conflict_do_update(
                index_elements=[R.c.article_id, R.c.rq_id],
                set_={"signature": "", "matched": 1, "query_changed": 0, "status": "pending"},
                where=and_(R.c.matched == 0, R.c.decided_by.is_(None))))
        if dropped:
            scope = (R.c.project_id == project_id, R.c.rq_id == rq_id, R.c.article_id == _ids(dropped))
            conn.execute(update(R).where(*scope, R.c.decided_by.is_(None), R.c.status != "approved")
                         .values(matched=0, status="irrelevant", reason=reason))
            conn.execute(update(R).where(*scope, or_(R.c.decided_by.isnot(None), R.c.status == "approved"))
                         .values(query_changed=1))
        if added or dropped:
            # the article's own flag follows its question rows: an added one is matched (tagging takes only matched
            # articles), one no question matches any more is Irrelevant (an analyst's relevant mark still holds)
            matched_row = exists().where(R.c.article_id == A.c.id, R.c.matched == 1)
            conn.execute(update(A).where(A.c.project_id == project_id, A.c.id == _ids(sorted(set(added) | set(dropped))))
                         .values(rq_matched=case((or_(matched_row, _analyst_relevant()), 1), else_=0)))


def deck_run_active(project_id: int) -> bool:
    return _first(select(literal(1)).where(D.c.project_id == project_id, D.c.status.in_(("running", "queued")))
                  .limit(1)) is not None


def save_rq(article_id: int, project_id: int, rq_id: str, signature: str, result: dict, status: str) -> None:
    stmt = pg_insert(R).values(
        project_id=project_id, article_id=article_id, rq_id=rq_id, signature=signature,
        matched=int(bool(result.get("matched"))), match_confidence=result.get("match_confidence"),
        keywords_json=json.dumps(result.get("keywords") or []), tags_json=json.dumps(result.get("tags") or {}, default=str),
        evidence_json=json.dumps(result.get("evidence") or {}, default=str), summary=result.get("summary") or "",
        reason=result.get("reason") or "", status=status, tagged_at=time.time())    # a model's null is no text
    new = stmt.excluded
    _exec(stmt.on_conflict_do_update(index_elements=[R.c.article_id, R.c.rq_id], set_={
        "signature": new.signature, "matched": new.matched, "match_confidence": new.match_confidence,
        "keywords_json": new.keywords_json, "tags_json": new.tags_json, "evidence_json": new.evidence_json,
        "summary": new.summary, "reason": new.reason,
        "status": case((R.c.decided_by.is_(None), new.status), else_=R.c.status), "tagged_at": new.tagged_at}))


def decide(project_id: int, article_ids: list[int], rq_ids: list[str] | None, status: str, by: str,
           reason: str | None) -> list[dict]:
    """Set status on those articles' RQ rows; returns the snapshot `undo` needs (created rows are marked).
    Only articles of this project are touched; ids of other projects are dropped. rq_ids None ("all matched RQs")
    touches only existing rows: matched ones, plus analyst-decided ones when not approving, and creates none."""
    if not article_ids:
        return []
    now = time.time()
    with sa.begin() as conn:
        article_ids = list(conn.execute(select(A.c.id).where(A.c.project_id == project_id,
                                                             A.c.id == _ids(article_ids))).scalars())
        if not article_ids:
            return []
        q = select(R.c.id, R.c.status, R.c.decided_by, R.c.decided_at, R.c.decision_reason).where(
            R.c.project_id == project_id, R.c.article_id == _ids(article_ids))
        if rq_ids is not None:
            q = q.where(R.c.rq_id == _texts(rq_ids))
        elif status == "approved":      # never approve an RQ the article did not match
            q = q.where(R.c.matched == 1)
        else:
            q = q.where(or_(R.c.matched == 1, R.c.decided_by.isnot(None)))
        snapshot = [dict(r._mapping) for r in conn.execute(q)]
        if snapshot:
            conn.execute(update(R).where(R.c.id == _ids(s["id"] for s in snapshot)).values(
                status=status, decided_by=by, decided_at=now, decision_reason=reason))
        have = {(a, r) for a, r in conn.execute(select(R.c.article_id, R.c.rq_id).where(
            R.c.project_id == project_id, R.c.article_id == _ids(article_ids)))}
        pairs = [(aid, rq) for aid in article_ids for rq in rq_ids or [] if (aid, rq) not in have]
        rows = [{"project_id": project_id, "article_id": aid, "rq_id": rq, "signature": "", "matched": 1,
                 "status": status, "decided_by": by, "decided_at": now, "decision_reason": reason} for aid, rq in pairs]
        for chunk in _chunks(rows):     # a missing (article, RQ) row is created, e.g. bulk "approve for RQ2"
            made = conn.execute(pg_insert(R).values(chunk).on_conflict_do_nothing(
                index_elements=[R.c.article_id, R.c.rq_id]).returning(R.c.id)).scalars()
            snapshot += [{"id": m, "created": True} for m in made]
    return snapshot


def undo(project_id: int, snapshot: list[dict]) -> None:
    created = [s["id"] for s in snapshot if s.get("created")]
    old = [s for s in snapshot if not s.get("created")]
    with sa.begin() as conn:
        if created:
            conn.execute(delete(R).where(R.c.id == _ids(created), R.c.project_id == project_id))
        if old:      # one statement run per restored row (executemany)
            conn.execute(update(R).where(R.c.id == bindparam("b_id"), R.c.project_id == project_id).values(
                status=bindparam("b_status"), decided_by=bindparam("b_by"),
                decided_at=bindparam("b_at", type_=Double), decision_reason=bindparam("b_reason")),
                [{"b_id": s["id"], "b_status": s["status"], "b_by": s["decided_by"], "b_at": s["decided_at"],
                  "b_reason": s["decision_reason"]} for s in old])


# ---- listing -------------------------------------------------------------------------------------------------------
def _status_clause(status: str, rq_id: str | None):
    """approved = every counted RQ row approved; review = any counted row pending; irrelevant = counted rows all
    irrelevant; no_match = no counted row. A row counts when the RQ matched it or an analyst decided it."""
    m = R.alias("m")

    def ex(*extra):
        scope = [m.c.article_id == A.c.id] + ([m.c.rq_id == rq_id] if rq_id else [])
        return exists().where(*scope, or_(m.c.matched == 1, m.c.decided_by.isnot(None)), *extra)
    if status == "approved":
        return and_(ex(), not_(ex(m.c.status != "approved")))
    if status == "review":
        return ex(m.c.status == "pending")
    if status == "no_match":
        return not_(ex())
    return and_(ex(), not_(ex(m.c.status != "irrelevant")))


def _tags():
    return cast(A.c.tags_json, JSONB)


def _where(project_id: int, f: dict) -> list:
    cond = [A.c.project_id == project_id]
    for name in ("channel", "sentiment", "content_status"):
        if f.get(name):
            cond.append(A.c[name] == f[name])
    if f.get("theme"):
        cond.append(or_(*(func.lower(_tags()[("themes", p)].astext) == func.lower(f["theme"])
                          for p in ("primary", "secondary", "tertiary"))))
    if f.get("brand"):
        b = func.jsonb_array_elements(func.coalesce(_tags()["brands"], cast(literal("[]"), JSONB))) \
            .table_valued(column("value", JSONB)).alias("b")
        cond.append(exists(select(literal(1)).select_from(b)
                           .where(func.lower(b.c.value["brand"].astext) == func.lower(f["brand"]))))
    if f.get("pool") == "irrelevant":       # matched no question; blocked and out-of-scope have their own pools
        cond.append(and_(A.c.rq_matched == 0, or_(A.c.excluded_reason.is_(None), not_(_set_aside(A.c.excluded_reason)))))
    elif f.get("pool") == "blocked":
        cond.append(A.c.excluded_reason.like(BLOCK_PREFIX + "%"))
    elif f.get("pool") == "outscope":
        cond.append(A.c.excluded_reason.like(OUT_OF_SCOPE_PREFIX + "%"))
    elif f.get("pool") == "matched":
        cond.append(A.c.rq_matched.is_distinct_from(0))
    if f.get("ids"):
        cond.append(A.c.id == _ids(f["ids"]))
    if f.get("q"):
        like = f"%{f['q']}%"
        cond.append(or_(A.c.title.ilike(like), A.c.summary.ilike(like), A.c.outlet.ilike(like)))
    if f.get("status"):
        cond.append(_status_clause(f["status"], f.get("rq_id")))
    elif f.get("rq_id"):
        m = R.alias("m")
        cond.append(exists().where(m.c.article_id == A.c.id, m.c.rq_id == f["rq_id"]))
    return cond


def page(project_id: int, *, channel=None, status=None, rq_id=None, sentiment=None, theme=None, brand=None,
         content_status=None, q=None, ids=None, pool=None, offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
    cond = _where(project_id, dict(channel=channel, status=status, rq_id=rq_id, sentiment=sentiment, theme=theme,
                                   brand=brand, content_status=content_status, q=q, ids=ids, pool=pool))
    with sa.begin() as conn:
        total = int(conn.execute(select(func.count()).select_from(A).where(*cond)).scalar())
        arts = [dict(r._mapping) for r in conn.execute(
            select(*_LIST_COLS, A.c.content).where(*cond).order_by(A.c.id).limit(limit).offset(offset))]
        rows = [dict(r._mapping) for r in conn.execute(
            select(*_RQ_COLS).where(R.c.project_id == project_id, R.c.article_id == _ids(a["id"] for a in arts))
            .order_by(R.c.rq_id))] if arts else []
    by_art: dict[int, list[dict]] = {}
    for r in rows:
        by_art.setdefault(r["article_id"], []).append(r)
    for a in arts:
        a["rq"] = by_art.get(a["id"], [])
    return arts, total


def facets(project_id: int, channel: str) -> dict:
    """The filter dropdowns' values for one channel: distinct theme labels, brand names and content statuses."""
    scope = (A.c.project_id == project_id, A.c.channel == channel)
    labels = union_all(*(select(_tags()[("themes", p)].astext.label("v")).where(*scope)
                         for p in ("primary", "secondary", "tertiary"))).subquery()
    brands_of = case((func.jsonb_typeof(_tags()["brands"]) == "array", _tags()["brands"]),
                     else_=cast(literal("[]"), JSONB))
    b = func.jsonb_array_elements(brands_of).table_valued(column("value", JSONB)).lateral("b")
    names = select(b.c.value["brand"].astext.label("v")).select_from(A).join(b, true()).where(*scope).subquery()
    with sa.begin() as conn:
        themes = conn.execute(select(labels.c.v).distinct().where(func.coalesce(labels.c.v, "") != "")
                              .order_by(labels.c.v)).scalars().all()
        brands = conn.execute(select(names.c.v).distinct().where(func.coalesce(names.c.v, "") != "")
                              .order_by(names.c.v)).scalars().all()
        statuses = conn.execute(select(A.c.content_status).distinct().where(*scope)
                                .order_by(A.c.content_status)).scalars().all()
    return {"themes": list(themes), "brands": list(brands), "content_statuses": list(statuses)}


def ids_matching(project_id: int, **filters) -> list[int]:
    return [r["id"] for r in _all(select(A.c.id).where(*_where(project_id, filters)).order_by(A.c.id))]


def approved(project_id: int, rq_ids: list[str]) -> list[dict]:
    """Articles with an approved row for any of rq_ids: approved_rq_ids, and per RQ its {"tags", "evidence"} (JSON text)."""
    if not rq_ids:
        return []
    rows = _all(select(*_LIST_COLS, A.c.content, A.c.raw_json, R.c.rq_id, R.c.tags_json.label("rq_tags_json"),
                       R.c.evidence_json.label("rq_evidence_json"))
                .select_from(A.join(R, R.c.article_id == A.c.id))
                .where(A.c.project_id == project_id, R.c.project_id == project_id, R.c.status == "approved",
                       R.c.rq_id == _texts(rq_ids)).order_by(A.c.id, R.c.rq_id))
    per_rq = ("rq_id", "rq_tags_json", "rq_evidence_json")
    out: dict[int, dict] = {}
    for r in rows:
        d = out.setdefault(r["id"], {**{k: v for k, v in r.items() if k not in per_rq}, "approved_rq_ids": [], "rq": {}})
        d["approved_rq_ids"].append(r["rq_id"])
        d["rq"][r["rq_id"]] = {"tags": r["rq_tags_json"], "evidence": r["rq_evidence_json"]}
    return list(out.values())


def approved_count(project_id: int, rq_ids: list[str]) -> int:
    """Approved article-RQ rows of this project for any of rq_ids."""
    if not rq_ids:
        return 0
    return int(_scalar(select(func.count()).select_from(R).where(
        R.c.project_id == project_id, R.c.status == "approved", R.c.rq_id == _texts(rq_ids))))


def approved_counts_by_rq(project_id: int, rq_ids: list[str]) -> dict[str, int]:
    """{rq_id: approved article rows} of this project for those RQs."""
    if not rq_ids:
        return {}
    return {r["rq_id"]: int(r["n"]) for r in _all(
        select(R.c.rq_id, func.count().label("n")).where(R.c.project_id == project_id, R.c.status == "approved",
                                                         R.c.rq_id == _texts(rq_ids)).group_by(R.c.rq_id))}


def edit_article(project_id: int, article_id: int, sentiment: str | None, themes: list[str] | None,
                 brands: list[str] | None) -> list[str] | None:
    """Apply an analyst's edit to the article's tags; returns the matched RQ ids still undecided (an edit confirms
    those; an analyst's earlier decision stays), or None when it is not found."""
    row = _first(select(A.c.tags_json).where(A.c.id == article_id, A.c.project_id == project_id))
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
    with sa.begin() as conn:
        conn.execute(update(A).where(A.c.id == article_id).values(
            tags_json=json.dumps(tags, default=str), sentiment=func.coalesce(sentiment, A.c.sentiment)))
        return list(conn.execute(select(R.c.rq_id).where(R.c.article_id == article_id, R.c.matched == 1,
                                                         R.c.decided_by.is_(None)).order_by(R.c.rq_id)).scalars())
