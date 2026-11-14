"""Background Research repository, through SQLAlchemy Core (models.py): research versions, news item approvals,
the brand-logo / Pexels / YouTube lookup caches, multi-source research items and their embeddings."""
from __future__ import annotations

import json
import time
from typing import Optional

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import sa
from .models import brand_logos, intel_background_research, intel_news_approvals, intel_research_item_vectors
from .models import intel_research_items, pexels_images, research_article_fulltext, youtube_videos

# core/store.py star-imports this module: export only the repository functions (and the lookup chunk size)
__all__ = ["save_background_research", "save_background_research_update", "get_latest_research",
           "get_research_by_id", "approve_research", "reject_research", "update_news_approval", "get_news_approvals",
           "get_brand_logo", "save_brand_logo", "get_pexels_image", "save_pexels_image", "get_youtube_video",
           "save_youtube_video", "upsert_research_item", "research_item_urls", "get_item_vectors",
           "save_item_classifications", "save_item_vectors", "get_research_item", "get_research_items",
           "VECTOR_LOOKUP_CHUNK", "get_article_fulltext", "save_article_fulltext", "recent_site_statuses"]


def recent_site_statuses(host: str, limit: int = 3) -> list[dict]:
    """The newest cached fetch results (status, error) for any article on this site, newest first."""
    t = research_article_fulltext
    host = host.lower().removeprefix("www.")
    url = func.lower(t.c.url)
    pats = [f"{s}://{h}/%" for s in ("https", "http") for h in (host, "www." + host)]
    return _all(select(t.c.status, t.c.error).where(or_(*(url.like(p) for p in pats)))
                .order_by(t.c.fetched_at.desc()).limit(limit))

R, NA, I, V = intel_background_research, intel_news_approvals, intel_research_items, intel_research_item_vectors
VECTOR_LOOKUP_CHUNK = 1000


def _one(query) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(query).first()
    return dict(row._mapping) if row else None


def _all(query) -> list[dict]:
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(query)]


def _with_json(d: Optional[dict]) -> Optional[dict]:
    if not d:
        return None
    d["research"] = json.loads(d["research_json"])
    if d.get("llm_output_json"):
        d["llm_output"] = json.loads(d["llm_output_json"])
    return d


def _upsert(table, key: str, values: dict) -> None:
    """Insert, or replace every non-key column of the row with the same key."""
    stmt = pg_insert(table).values(**values)
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=[table.c[key]],
                                                set_={c: stmt.excluded[c] for c in values if c != key}))


# ─── Background Research ─────────────────────────────────────────────────────

def save_background_research(project_id: int, research: dict, llm_output: dict | None = None) -> int:
    """The project's next research version, as a draft (version read and row written in one transaction)."""
    with sa.begin() as conn:
        version = (conn.execute(select(func.max(R.c.version)).where(R.c.project_id == project_id)).scalar() or 0) + 1
        return conn.execute(insert(R).values(
            project_id=project_id, version=version, status="draft", research_json=json.dumps(research),
            llm_output_json=json.dumps(llm_output) if llm_output else None, created_at=time.time())
            .returning(R.c.id)).scalar_one()


def save_background_research_update(research_id: int, research: dict, llm_output: dict | None = None):
    with sa.begin() as conn:
        conn.execute(update(R).where(R.c.id == research_id).values(
            research_json=json.dumps(research), llm_output_json=json.dumps(llm_output) if llm_output else None))


def get_latest_research(project_id: int) -> Optional[dict]:
    return _with_json(_one(select(R).where(R.c.project_id == project_id).order_by(R.c.version.desc()).limit(1)))


def get_research_by_id(research_id: int) -> Optional[dict]:
    return _with_json(_one(select(R).where(R.c.id == research_id)))


def approve_research(research_id: int, reviewer: str = "analyst") -> bool:
    with sa.begin() as conn:
        conn.execute(update(R).where(R.c.id == research_id).values(
            approval_status="approved", approved_by=reviewer, approved_at=time.time()))
    return True


def reject_research(research_id: int, notes: str = "") -> bool:
    with sa.begin() as conn:
        conn.execute(update(R).where(R.c.id == research_id).values(approval_status="revision_requested", notes=notes))
    return True


# ─── News Item Approvals ────────────────────────────────────────────────────

def update_news_approval(research_id: int, item_index: int, status: str, notes: str = ""):
    now = time.time()
    with sa.begin() as conn:
        existing = conn.execute(select(NA.c.id).where(NA.c.research_id == research_id,
                                                      NA.c.item_index == item_index)).scalar()
        if existing is not None:
            conn.execute(update(NA).where(NA.c.id == existing).values(status=status, notes=notes, updated_at=now))
        else:
            conn.execute(insert(NA).values(research_id=research_id, item_index=item_index, status=status, notes=notes,
                                           updated_at=now))


def get_news_approvals(research_id: int) -> dict[int, dict]:
    return {row["item_index"]: row for row in _all(select(NA).where(NA.c.research_id == research_id))}


# ─── Lookup caches: brand logos, Pexels images, YouTube videos ───────────────

def get_brand_logo(brand_key: str) -> Optional[dict]:
    return _one(select(brand_logos).where(brand_logos.c.brand_key == brand_key))


def save_brand_logo(brand_key: str, brand_name: str, logo_url: str | None,
                    domain: str | None, source: str) -> None:
    _upsert(brand_logos, "brand_key", {"brand_key": brand_key, "brand_name": brand_name, "logo_url": logo_url,
                                       "domain": domain, "source": source, "fetched_at": time.time()})


def get_pexels_image(query_key: str) -> Optional[dict]:
    return _one(select(pexels_images).where(pexels_images.c.query_key == query_key))


def save_pexels_image(query_key: str, query_text: str, image_url: str | None,
                      photographer: str | None, source_url: str | None,
                      video_url: str | None = None) -> None:
    _upsert(pexels_images, "query_key", {"query_key": query_key, "query_text": query_text, "image_url": image_url,
                                         "photographer": photographer, "source_url": source_url,
                                         "video_url": video_url, "fetched_at": time.time()})


def get_youtube_video(query_key: str) -> Optional[dict]:
    return _one(select(youtube_videos).where(youtube_videos.c.query_key == query_key))


def save_youtube_video(query_key: str, query_text: str, video_id: str | None, embed_url: str | None,
                       title: str | None, thumbnail_url: str | None) -> None:
    _upsert(youtube_videos, "query_key", {"query_key": query_key, "query_text": query_text, "video_id": video_id,
                                          "embed_url": embed_url, "title": title, "thumbnail_url": thumbnail_url,
                                          "fetched_at": time.time()})


# ─── Research Items (multi-source pipeline) ──────────────────────────────────

def upsert_research_item(project_id: int, research_id: int | None, item: dict) -> int:
    """Same (project_id, url) across two sources (e.g. SerpAPI finds it, then Google News
    RSS finds the same real article once its wrapper link is decoded) is a natural
    cross-source duplicate, not a second article — ON CONFLICT merges it into the one row.
    source_api accumulates every distinct source that reported this URL (comma-joined, e.g.
    "serpapi,google_news_rss") instead of the later source silently overwriting the earlier
    one's attribution, so the "All Articles" table can show all of them for that row."""
    with sa.begin() as conn:
        known = conn.execute(select(I.c.source_api).where(I.c.project_id == project_id,
                                                          I.c.url == item["url"])).scalar()
        source_api = item["source_api"]
        if known:
            sources = [s for s in known.split(",") if s]
            source_api = known if source_api in sources else ",".join(sources + [source_api])
        stmt = pg_insert(I).values(
            project_id=project_id, research_id=research_id, topic=item["topic"], source_api=source_api,
            platform=item.get("platform"), publication=item.get("publication"),
            published_date=item["published_date"], title=item.get("title"), content=item.get("content"),
            url=item["url"], author=item.get("author"), thumbnail_url=item.get("thumbnail_url"),
            access=item.get("access"), created_at=time.time())
        changed = ("research_id", "topic", "source_api", "platform", "publication", "published_date", "title",
                   "content", "author", "thumbnail_url")
        return conn.execute(stmt.on_conflict_do_update(
            index_elements=[I.c.project_id, I.c.url],
            set_={**{c: stmt.excluded[c] for c in changed},
                  "access": func.coalesce(stmt.excluded.access, I.c.access)})   # an unknown never erases a known
            .returning(I.c.id)).scalar_one()


def research_item_urls(project_id: int) -> list[str]:
    """Every stored research-item URL of a project, so a new fetch can match variants of pages it already has."""
    with sa.begin() as conn:
        return list(conn.execute(select(I.c.url).where(I.c.project_id == project_id)).scalars())


def get_item_vectors(item_ids: list[int], model: str, kind: str = "research") -> dict[int, bytes]:
    """Stored embedding bytes (float32) per item id of one kind ("research" items or Data set "article"s), only
    those made with `model`."""
    found: dict[int, bytes] = {}
    with sa.begin() as conn:
        for start in range(0, len(item_ids), VECTOR_LOOKUP_CHUNK):     # keeps each statement's IN list bounded
            chunk = item_ids[start:start + VECTOR_LOOKUP_CHUNK]
            rows = conn.execute(select(V.c.item_id, V.c.vector).where(V.c.kind == kind, V.c.model == model,
                                                                      V.c.item_id.in_(chunk)))
            found.update({r.item_id: bytes(r.vector) for r in rows})
    return found


def save_item_classifications(rows: list[tuple[int, float, str, float, str]]) -> None:
    """(item id, about_brand probability, sentiment, sentiment confidence, brand classified for) per item."""
    with sa.begin() as conn:
        for item_id, about, sentiment, confidence, brand in rows:
            conn.execute(update(I).where(I.c.id == item_id).values(
                about_brand=about, sentiment=sentiment, sentiment_confidence=confidence, classified_for=brand))


def save_item_vectors(vectors: dict[int, bytes], model: str, dim: int, kind: str = "research") -> None:
    if not vectors:
        return
    now = time.time()
    stmt = pg_insert(V)
    with sa.begin() as conn:            # no RETURNING: the rows hold the vector bytes
        conn.execute(stmt.on_conflict_do_update(index_elements=[V.c.kind, V.c.item_id], set_={
            c: stmt.excluded[c] for c in ("model", "dim", "vector", "created_at")}),
            [{"kind": kind, "item_id": i, "model": model, "dim": dim, "vector": blob, "created_at": now}
             for i, blob in vectors.items()])


def get_research_item(item_id: int) -> dict | None:
    return _one(select(I).where(I.c.id == item_id))


def get_research_items(project_id: int, topic: str | None = None,
                       since: float | None = None, until: float | None = None) -> list[dict]:
    """`since`/`until` (Unix timestamps, both inclusive) scope to a date_range — e.g. the
    current run's window — using the (project_id, published_date) index, so a project's
    earlier runs/date windows don't silently bleed into a scoped read."""
    q = select(I).where(I.c.project_id == project_id)
    if topic:
        q = q.where(I.c.topic == topic)
    if since is not None:
        q = q.where(I.c.published_date >= since)
    if until is not None:
        q = q.where(I.c.published_date <= until)
    return _all(q.order_by(I.c.published_date.desc()))


# ─── Article reader cache ─────────────────────────────────────────────────────
def get_article_fulltext(url: str) -> Optional[dict]:
    """The cached extraction of an article (status, title, blocks_json, error, platform, embed_url), or None."""
    t = research_article_fulltext
    return _one(select(t.c.status, t.c.title, t.c.blocks_json, t.c.error, t.c.platform, t.c.embed_url)
                .where(t.c.url == url))


def save_article_fulltext(url: str, status: str, title: Optional[str], blocks_json: str, error: Optional[str],
                          platform: Optional[str], embed_url: Optional[str]) -> None:
    _upsert(research_article_fulltext, "url", {"url": url, "status": status, "title": title,
                                                 "blocks_json": blocks_json, "error": error, "platform": platform,
                                                 "embed_url": embed_url, "fetched_at": time.time()})
