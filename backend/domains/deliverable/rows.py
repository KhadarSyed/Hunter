"""Ingest stage: approved article-RQ rows (Data set) -> one EngineRow per article, routed to its approved RQs."""
from __future__ import annotations

import json
import logging
import re

from ...core import store
from ..exclusions.service import excluded as excluded_by, rules_for_project
from .engine_types import RQ, EngineRow
from .ingest import Article, normalize_url, parse_date, parse_hour
from .labels import theme_key

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
    return [RQ(id=q.get("question_id") or f"RQ{i}", question=q.get("question") or "",
               query=q.get("match_query") or q.get("query") or "",   # match_query: what uploads are matched on
               status=q.get("status") or "approved")
            for i, q in enumerate(strategy.get("research_question_queries") or [], start=1)]


def approved_rqs(project_id: int) -> list[RQ]:
    return [q for q in load_rqs(project_id) if q.status == "approved"]


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


# the account in a social post's own address: facebook.com/<page>/..., x.com/<handle>/status/..., tiktok.com/@<handle>
_ACCOUNT_URL = re.compile(r"^https?://(?:www\.|m\.)?(?:facebook\.com|x\.com|twitter\.com|instagram\.com|tiktok\.com|"
                          r"youtube\.com|threads\.net)/(@?[A-Za-z0-9_.\-]+)", re.IGNORECASE)
_NOT_ACCOUNTS = {"p", "reel", "reels", "watch", "status", "share", "story.php", "permalink.php", "groups", "video",
                 "shorts", "channel", "user", "c", "i", "home", "hashtag", "explore"}


def author_of(rec: dict, url: str) -> str:
    """Who wrote or posted it: the export's author handle or name, else the account a social post's URL names (never
    guessed beyond that)."""
    named = str(rec.get("author_handle") or rec.get("author_name") or rec.get("author") or "").strip()
    if named:
        return named
    m = _ACCOUNT_URL.match(url)
    if m and m.group(1).lstrip("@").lower() not in _NOT_ACCOUNTS:
        return m.group(1) if m.group(1).startswith("@") or "facebook.com" in url.lower() else "@" + m.group(1)
    reddit = re.match(r"^https?://(?:www\.|old\.)?reddit\.com/(r|u|user)/([A-Za-z0-9_\-]+)", url, re.IGNORECASE)
    return f"{'r' if reddit.group(1) == 'r' else 'u'}/{reddit.group(2)}" if reddit else ""


_URL_DATE = re.compile(r"/(20\d\d)/(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?:/|$)")
_HOST = re.compile(r"^https?://(?:www\.)?([^/:?#]+)", re.IGNORECASE)


def _url_facts(url: str) -> tuple[str, str]:
    """The outlet (its domain) and the publish date a URL states, for hand-collected rows that carry only a URL
    and a title ('/2025/06/12/' in the path is the publisher's own date)."""
    host = _HOST.match(url)
    day = _URL_DATE.search(url)
    when = f"{day.group(1)}-{int(day.group(2)):02d}-{int(day.group(3)):02d}" if day else ""
    return (host.group(1).lower() if host else ""), when


def _row(rec: dict, rq: str | None, source_file: str, index: int, date_order: str = "ymd") -> EngineRow | None:
    url = str(rec.get("url") or "").strip()
    if url.lower().startswith("www."):
        url = "https://" + url
    if not url or _EXECUTABLE_URL.match(url):
        return None
    full_title = str(rec.get("title") or rec.get("headline") or "").strip()
    title = full_title.split("\n", 1)[0].strip()      # a pasted headline can carry its subheadline on the next line
    url_outlet, url_date = _url_facts(url)
    article = Article(url=url, norm_url=normalize_url(url), title=title,
                      date=parse_date(rec.get("date"), date_order) or parse_date(url_date or None, "ymd"),
                      outlet=str(rec.get("source_name") or rec.get("source") or url_outlet),
                      text=str(rec.get("content") or full_title),
                      sentiment=rec.get("overall_sentiment") or rec.get("sentiment") or None,
                      reach=_to_float(rec.get("reach")), source_file=source_file, row_index=index,
                      image=str(rec.get("image") or "").strip(), country=str(rec.get("country") or "").strip(),
                      state=str(rec.get("state") or "").strip(), region=str(rec.get("region") or "").strip(),
                      author=author_of(rec, url), hour=parse_hour(rec.get("time"), rec.get("date")))
    return EngineRow(article=article, rq_ids={rq} if rq else set(), media_type=str(rec.get("media_type") or ""),
                     themes=_theme_labels(rec.get("themes")), entities=rec.get("entities") or {},
                     tags=rec.get("question_tags") if isinstance(rec.get("question_tags"), dict) else {},
                     author_type=str(rec.get("author_type") or ""),
                     brand_mention=str(rec.get("brand_mention") or ""),
                     dynamic_tags=rec.get("dynamic_tags") if isinstance(rec.get("dynamic_tags"), dict) else {},
                     tag_evidence=rec.get("tag_evidence") if isinstance(rec.get("tag_evidence"), dict) else {})


def _json(text, default):
    try:
        value = json.loads(text) if isinstance(text, str) and text else text
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def approved_rows(project_id: int, rq_id: str | None = None) -> list[EngineRow]:
    """One EngineRow per article with an approved row for an approved RQ (or for rq_id alone); its rq_ids are exactly
    the approved RQs it was approved for, so each RQ section reads only its own approved rows."""
    from ..dataset import repository as dataset_repo
    rq_ids = [q.id for q in approved_rqs(project_id) if rq_id is None or q.id == rq_id]
    titles = dataset_repo.theme_titles(project_id)
    # the deck is about the project's country: an article from another country never reaches it (Global: all count);
    # an article that states no country is kept, and counted in the run log
    country = _country_of(project_id)
    foreign = unstated = 0
    out: list[EngineRow] = []
    for i, a in enumerate(dataset_repo.approved(project_id, rq_ids)):
        stated = _country_key(a.get("country"))
        if country and stated and stated != country:
            foreign += 1
            continue
        unstated += bool(country and not stated)
        tags = _json(a.get("tags_json"), {})
        per_rq = [(_json(r.get("tags"), {}), _json(r.get("evidence"), {})) for r in (a.get("rq") or {}).values()]
        q_tags = {k: v for t, _ in per_rq for k, v in t.items()}       # one article under several questions keeps each one's tags
        themes = [titles.get(theme_key(t), t) for t in _theme_labels(tags.get("themes"))]
        raw = _json(a.get("raw_json"), {})
        rec = {**raw,        # the export row still carries image, state, region, time
               "url": a.get("url"), "title": a.get("title"), "content": a.get("content") or a.get("summary"),
               "source_name": a.get("outlet"), "date": a.get("published"), "country": a.get("country"),
               "reach": a.get("reach"), "overall_sentiment": a.get("sentiment") or tags.get("overall_sentiment"),
               "themes": themes, "entities": tags.get("entities") or {}, "question_tags": q_tags,
               "author_type": tags.get("author_type"), "media_type": a.get("channel"),
               "author_name": a.get("author_name"), "author_handle": a.get("author_id"),
               "dynamic_tags": q_tags, "tag_evidence": {k: v for _, e in per_rq for k, v in e.items()}}
        row = _row(rec, None, "", i)
        if row is not None:
            if row.article.hour is None:    # `published` is a bare date: the hour lives in the export's timestamp
                row.article.hour = parse_hour(raw.get("time"), raw.get("date"))
            row.rq_ids = set(a.get("approved_rq_ids") or [])
            out.append(row)
    COUNTRY_FILTER[project_id] = (foreign, unstated, country)
    if foreign:
        logger.info("project %s: %d articles from outside %s left out", project_id, foreign, country)
    return _without_excluded(project_id, out)


def load_rows(project_id: int, rqs: list[RQ]) -> list[EngineRow]:
    """The approved rows, routed to the given questions by their approvals (a question's rows are its approved ones)."""
    wanted = {q.id for q in rqs}
    rows = [r for r in approved_rows(project_id) if r.rq_ids & wanted]
    for r in rows:
        r.rq_ids &= wanted
    return rows


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


def coverage(project_id: int) -> dict:
    """Per question: how many approved articles it has (the rows its deck section will read)."""
    from ..dataset import repository as dataset_repo
    counts = dataset_repo.approved_counts_by_rq(project_id, [q.id for q in approved_rqs(project_id)])
    return {"rqs": [{"rq_id": q.id, "has_own_upload": counts.get(q.id, 0) > 0, "shared": counts.get(q.id, 0)}
                    for q in load_rqs(project_id)]}


def ingest_summary(project_id: int, rows: list[EngineRow]) -> dict:
    by_rq: dict[str, int] = {}
    for r in rows:
        for q in r.rq_ids:
            by_rq[q] = by_rq.get(q, 0) + 1
    from ..dataset import repository as dataset_repo
    return {"files": len(dataset_repo.list_files(project_id)), "unique_urls": len(rows),
            "stories": len({r.story_key for r in rows}), "base_n": base_n(rows),
            "total_results": total_results(by_rq), "by_rq": dict(sorted(by_rq.items()))}


def total_results(by_rq: dict[str, int]) -> int:
    """The deck's total: every question's result volume added up -- an article that answers several questions counts
    once in each, as each question's search returned it (the unique-article count is reported beside it)."""
    return sum(by_rq.values())
