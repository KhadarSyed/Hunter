"""Ingest stage: approved datasets -> one EngineRow per unique URL, routed to RQs by file and by query."""
from __future__ import annotations

import re
from pathlib import Path

from ...core import store
from ..execution.service import _is_excluded, _load_dataset
from .boolean_query import matches
from .engine_types import RQ, EngineRow
from .ingest import Article, normalize_url, parse_date


def load_rqs(project_id: int) -> list[RQ]:
    strategy = (store.get_latest_strategy(project_id) or {}).get("strategy") or {}
    return [RQ(id=q.get("question_id") or f"RQ{i}", question=q.get("question") or "", query=q.get("query") or "")
            for i, q in enumerate(strategy.get("research_question_queries") or [], start=1)]


def _approved_datasets(project_id: int) -> list[dict]:
    return [d for d in store.get_datasets_by_project(project_id)
            if d.get("approval_status") == "approved" and (d.get("processing_status") or "done") == "done"]


def _theme_labels(themes) -> list[str]:
    if isinstance(themes, dict):
        return [str(themes[k]) for k in ("primary", "secondary") if themes.get(k)]
    return [str(t) for t in themes or [] if t]


def _to_float(v) -> float:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _row(rec: dict, rq: str | None, source_file: str, index: int) -> EngineRow | None:
    url = str(rec.get("url") or "").strip()
    if not url:
        return None
    title = str(rec.get("title") or rec.get("headline") or "").strip()
    article = Article(url=url, norm_url=normalize_url(url), title=title, date=parse_date(rec.get("date")),
                      outlet=str(rec.get("source_name") or rec.get("source") or ""),
                      text=str(rec.get("content") or title),
                      sentiment=rec.get("overall_sentiment") or rec.get("sentiment") or None,
                      reach=_to_float(rec.get("reach")), source_file=source_file, row_index=index)
    return EngineRow(article=article, rq_ids={rq} if rq else set(), media_type=str(rec.get("media_type") or ""),
                     themes=_theme_labels(rec.get("themes")), entities=rec.get("entities") or {})


def load_rows(project_id: int, rqs: list[RQ]) -> list[EngineRow]:
    datasets = _approved_datasets(project_id)
    approved = {d["id"] for d in datasets}
    merged: dict[str, EngineRow] = {}

    def add(row: EngineRow | None) -> None:
        if row is None:
            return
        existing = merged.get(row.article.norm_url)
        if existing:
            existing.rq_ids |= row.rq_ids
        else:
            merged[row.article.norm_url] = row

    enriched = [r for r in store.get_enriched_records_by_project(project_id) if r.get("dataset_id") in approved]
    enriched_ids = {r["dataset_id"] for r in enriched}
    for i, rec in enumerate(enriched):
        if not _is_excluded(rec):
            add(_row(rec, rec.get("research_question_id"), rec.get("dataset_file_name") or "", i))
    for ds in datasets:
        fp = ds.get("file_path") or ""
        if ds["id"] in enriched_ids or not fp or not Path(fp).exists():
            continue
        for i, rec in enumerate(_load_dataset(fp)):
            add(_row(rec, ds.get("research_question_id"), ds.get("file_name") or "", i))
    return list(merged.values())


def route(rows: list[EngineRow], rqs: list[RQ]) -> list[EngineRow]:
    """Adds every RQ whose Meltwater query matches the article (on top of the file it was uploaded for)."""
    for row in rows:
        text = f"{row.article.title}\n{row.article.text}"
        for rq in rqs:
            if rq.query and rq.id not in row.rq_ids and matches(rq.query, text):
                row.rq_ids.add(rq.id)
    return rows


def _story_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:120]


def assign_stories(rows: list[EngineRow]) -> list[EngineRow]:
    """Syndicated copies (same normalised headline, different URLs) form one story; each row records its size."""
    groups: dict[str, list[EngineRow]] = {}
    for row in rows:
        row.story_key = _story_key(row.article.title) or row.article.norm_url
        groups.setdefault(row.story_key, []).append(row)
    for members in groups.values():
        for row in members:
            row.copies = len(members)
    return rows


def base_n(rows: list[EngineRow]) -> int:
    return len({r.article.norm_url for r in rows if r.rq_ids})


def rq_rows(rows: list[EngineRow], rq_id: str) -> list[EngineRow]:
    return [r for r in rows if rq_id in r.rq_ids]


def ingest_summary(project_id: int, rows: list[EngineRow]) -> dict:
    by_rq: dict[str, int] = {}
    for r in rows:
        for q in r.rq_ids:
            by_rq[q] = by_rq.get(q, 0) + 1
    return {"files": len(_approved_datasets(project_id)), "unique_urls": len(rows),
            "stories": len({r.story_key for r in rows}), "base_n": base_n(rows), "by_rq": dict(sorted(by_rq.items()))}
