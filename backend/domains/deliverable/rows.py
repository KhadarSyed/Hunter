"""Ingest stage: approved datasets -> one EngineRow per unique URL, routed to RQs by file and by query."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from ...core import store
from ..exclusions.service import excluded as excluded_by, rules_for_project
from ..execution.service import _is_excluded, _load_dataset
from .boolean_query import matches
from .engine_types import RQ, EngineRow
from .ingest import Article, infer_date_order, normalize_url, parse_date

logger = logging.getLogger(__name__)


_COUNTRY_ALIASES = {"us": "united states", "usa": "united states", "united states of america": "united states",
                    "uk": "united kingdom", "gb": "united kingdom", "great britain": "united kingdom",
                    "england": "united kingdom", "uae": "united arab emirates"}
_ANY_COUNTRY = {"", "global", "worldwide", "international"}
# project_id -> (articles dropped for another country, articles kept with no country, the project's country)
COUNTRY_FILTER: dict[int, tuple[int, int, str]] = {}


def _country_key(value) -> str:
    key = " ".join(str(value or "").lower().replace(".", "").split())
    return _COUNTRY_ALIASES.get(key, key)


def _country_of(project_id: int) -> str:
    """The country the deck is about; '' for a Global project (every country's coverage counts)."""
    from ...core import writing_locale
    key = _country_key(writing_locale.project_geography(store.get_project(project_id)))
    return "" if key in _ANY_COUNTRY else key


def country_note(project_id: int) -> str:
    """The ingest log's line on the country filter ('' when nothing was filtered or unstated)."""
    dropped, blank, country = COUNTRY_FILTER.get(project_id, (0, 0, ""))
    parts = [f"{dropped} from outside {country.title()} left out"] if dropped else []
    parts += [f"{blank} with no country kept"] if blank else []
    return "; ".join(parts)


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


# Script-running schemes are never coverage. Other identifiers (e.g. Meltwater's moodys:publicid: broadcast clip
# ids) are real articles: they count, and the page links only http(s) addresses.
_EXECUTABLE_URL = re.compile(r"^\s*(javascript|data|vbscript):", re.IGNORECASE)


def _row(rec: dict, rq: str | None, source_file: str, index: int, date_order: str = "ymd") -> EngineRow | None:
    url = str(rec.get("url") or "").strip()
    if url.lower().startswith("www."):
        url = "https://" + url
    if not url or _EXECUTABLE_URL.match(url):
        return None
    title = str(rec.get("title") or rec.get("headline") or "").strip()
    article = Article(url=url, norm_url=normalize_url(url), title=title, date=parse_date(rec.get("date"), date_order),
                      outlet=str(rec.get("source_name") or rec.get("source") or ""),
                      text=str(rec.get("content") or title),
                      sentiment=rec.get("overall_sentiment") or rec.get("sentiment") or None,
                      reach=_to_float(rec.get("reach")), source_file=source_file, row_index=index,
                      image=str(rec.get("image") or "").strip())
    return EngineRow(article=article, rq_ids={rq} if rq else set(), media_type=str(rec.get("media_type") or ""),
                     themes=_theme_labels(rec.get("themes")), entities=rec.get("entities") or {},
                     tags=rec.get("question_tags") if isinstance(rec.get("question_tags"), dict) else {},
                     author_type=str(rec.get("author_type") or ""),
                     brand_mention=str(rec.get("brand_mention") or ""),
                     dynamic_tags=rec.get("dynamic_tags") if isinstance(rec.get("dynamic_tags"), dict) else {},
                     tag_evidence=rec.get("tag_evidence") if isinstance(rec.get("tag_evidence"), dict) else {})


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
            # one article under several questions keeps every question's own tags (their names differ)
            existing.dynamic_tags = {**row.dynamic_tags, **existing.dynamic_tags}
            existing.tag_evidence = {**row.tag_evidence, **existing.tag_evidence}
            if not existing.article.image:      # an enriched record may lack the picture its export row carries
                existing.article.image = row.article.image
        else:
            merged[row.article.norm_url] = row

    # Enriched records come first (their tags win); every row of every file is then read too, because enrichment
    # may cover only a sample (or be empty, left by a misparsed file). An analyst's exclusion drops the URL.
    enriched = [r for r in store.get_enriched_records_by_project(project_id) if r.get("dataset_id") in approved]
    file_records = {ds["id"]: _load_dataset(ds["file_path"]) for ds in datasets
                    if ds.get("file_path") and Path(ds["file_path"]).exists()}
    # each export's own dates say whether its 05-11-2026 is 5 November or 11 May
    orders = {did: infer_date_order([r.get("date") for r in file_records.get(did, [])] +
                                    [r.get("date") for r in enriched if r.get("dataset_id") == did])
              for did in approved}
    excluded: set[str] = set()
    # the deck is about the project's country: an article from another country never reaches it (Global: all count);
    # an article whose export states no country is kept, and counted in the run log
    country = _country_of(project_id)
    foreign: set[str] = set()
    unstated: set[str] = set()

    def in_country(rec: dict) -> bool:
        url = normalize_url(str(rec.get("url") or ""))
        stated = _country_key(rec.get("country"))
        if not country:
            return True
        if not stated:
            unstated.add(url)
            return True
        if stated != country:
            foreign.add(url)
            return False
        return True

    for i, rec in enumerate(enriched):
        if _is_excluded(rec) or not in_country(rec):
            excluded.add(normalize_url(str(rec.get("url") or "")))
        else:
            add(_row(rec, rec.get("research_question_id"), rec.get("dataset_file_name") or "", i,
                     orders.get(rec.get("dataset_id"), "ymd")))
    for ds in datasets:
        for i, rec in enumerate(file_records.get(ds["id"], [])):
            if not in_country(rec):
                continue
            row = _row(rec, ds.get("research_question_id"), ds.get("file_name") or "", i, orders[ds["id"]])
            if row is not None and row.article.norm_url not in excluded:
                add(row)
    kept = {r for r in merged}
    COUNTRY_FILTER[project_id] = (len(foreign - kept), len(unstated & kept), country)
    if foreign:
        logger.info("project %s: %d articles from outside %s left out", project_id, len(foreign - kept), country)
    return _without_excluded(project_id, list(merged.values()))


def _without_excluded(project_id: int, rows: list[EngineRow]) -> list[EngineRow]:
    """Rows from the organization's excluded websites, or naming an excluded keyword, never reach a chart, an
    insight, a verbatim or a slide (Settings > Exclusions)."""
    rules = rules_for_project(project_id)
    if not rules:
        return rows
    kept = [r for r in rows if not excluded_by(rules, r.article.url, r.article.title, r.article.text)]
    if len(kept) < len(rows):
        logger.info("project %s: exclusion list removed %d of %d articles", project_id, len(rows) - len(kept), len(rows))
    return kept


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


_COVERAGE_CACHE: dict[tuple, dict] = {}
_COVERAGE_CACHE_MAX = 64


def coverage(project_id: int) -> dict:
    """Per question: does it have an approved upload of its own, and if not, how many articles from the other
    approved uploads match its Meltwater query (the engine's routing will send exactly those to it). Only questions
    without an upload are matched, and the answer is cached per (approved datasets, questions): routing every
    article for every question took minutes on a large project and starved the server."""
    rqs = load_rqs(project_id)
    datasets = _approved_datasets(project_id)
    with_upload = {d.get("research_question_id") for d in datasets}
    missing = [q for q in rqs if q.id not in with_upload]
    key = (project_id, tuple(sorted(d["id"] for d in datasets)), tuple((q.id, q.query) for q in rqs))
    if key in _COVERAGE_CACHE:
        return _COVERAGE_CACHE[key]
    shared = {q.id: 0 for q in missing}
    if missing and datasets:
        for row in load_rows(project_id, rqs):
            text = f"{row.article.title}\n{row.article.text}"
            for q in missing:
                if q.query and matches(q.query, text):
                    shared[q.id] += 1
    result = {"rqs": [{"rq_id": q.id, "has_own_upload": q.id in with_upload, "shared": shared.get(q.id)} for q in rqs]}
    if len(_COVERAGE_CACHE) >= _COVERAGE_CACHE_MAX:
        _COVERAGE_CACHE.pop(next(iter(_COVERAGE_CACHE)))
    _COVERAGE_CACHE[key] = result
    return result


def ingest_summary(project_id: int, rows: list[EngineRow]) -> dict:
    by_rq: dict[str, int] = {}
    for r in rows:
        for q in r.rq_ids:
            by_rq[q] = by_rq.get(q, 0) + 1
    return {"files": len(_approved_datasets(project_id)), "unique_urls": len(rows),
            "stories": len({r.story_key for r in rows}), "base_n": total_results(by_rq) or base_n(rows),
            "total_results": total_results(by_rq), "by_rq": dict(sorted(by_rq.items()))}


def total_results(by_rq: dict[str, int]) -> int:
    """The deck's total: every question's result volume added up -- an article that answers several questions counts
    once in each, as each question's search returned it (the unique-article count is reported beside it)."""
    return sum(by_rq.values())
