"""Multi-source research pipeline: Boolean query building, concurrent fan-out to
Tavily/SerpAPI/Google News RSS, per-item persistence, and map-reduce LLM summarization.

Replaces web_research.py's build_search_queries() (plain-string, stale spec fields — see
docs/superpowers/specs/2026-09-29-multi-source-research-pipeline-design.md §1) and
research/service.py's single fixed-truncation LLM call.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from . import news_search
from . import repository

logger = logging.getLogger(__name__)


@dataclass
class TopicQuery:
    topic: str
    boolean_query: str   # SerpAPI + Google News RSS (Boolean/Google search syntax)
    natural_query: str    # Tavily (plain language, no operators)


def _entities_by_type(spec: dict, entity_type: str) -> list[str]:
    entities = spec.get("validated_entities", [])
    return [e["name"] for e in entities if isinstance(e, dict) and e.get("type") == entity_type and e.get("name")]


def _or_group(terms: list[str]) -> str:
    return "(" + " OR ".join(f'"{t}"' for t in terms) + ")"


def _exclusion_suffix(spec: dict) -> str:
    excluded = spec.get("excluded_scope", [])
    terms = []
    for item in excluded if isinstance(excluded, list) else []:
        if isinstance(item, dict) and item.get("description"):
            terms.append(item["description"])
        elif isinstance(item, str):
            terms.append(item)
    return "".join(f' -"{t}"' for t in terms)


def build_boolean_queries(spec: dict) -> list[TopicQuery]:
    """Build one TopicQuery per research angle from an approved Research Specification.
    Every topic includes the brand OR'd with every competitor (brand_or_competitors) — no
    topic is brand-only or competitor-only, so no query is blind to the competitive set."""
    brand_name = (spec.get("commissioning_brand") or {}).get("name", "")
    competitors = _entities_by_type(spec, "competitor")
    products = _entities_by_type(spec, "product") + _entities_by_type(spec, "product_group")
    events = _entities_by_type(spec, "event")

    category = (spec.get("industry") or {}).get("name", "")
    if not category:
        category = (spec.get("research_subject") or {}).get("description", "")[:60]

    brand_or_competitors_terms = ([brand_name] if brand_name else []) + competitors
    if not brand_or_competitors_terms:
        return []
    brand_group_bool = _or_group(brand_or_competitors_terms)
    brand_group_natural = ", ".join(brand_or_competitors_terms)
    exclusion = _exclusion_suffix(spec)

    topics: list[TopicQuery] = []

    topics.append(TopicQuery(
        topic="brand_activity",
        boolean_query=f"{brand_group_bool} AND (news OR announcement OR campaign){exclusion}",
        natural_query=f"{brand_group_natural} news and announcements",
    ))

    if category:
        topics.append(TopicQuery(
            topic="competitive_landscape",
            boolean_query=f'{brand_group_bool} AND "{category}"{exclusion}',
            natural_query=f"{brand_group_natural} {category} market",
        ))
        topics.append(TopicQuery(
            topic="category_trends",
            boolean_query=f'{brand_group_bool} AND "{category}" AND (trend OR market){exclusion}',
            natural_query=f"{category} market trends: {brand_group_natural}",
        ))

    if products:
        topics.append(TopicQuery(
            topic="product_mentions",
            boolean_query=f"{brand_group_bool} AND {_or_group(products)}{exclusion}",
            natural_query=f"{brand_group_natural} — {', '.join(products)}",
        ))

    for event in events:
        topics.append(TopicQuery(
            topic=f"event_{event.lower().replace(' ', '_')}",
            boolean_query=f'{brand_group_bool} AND "{event}"{exclusion}',
            natural_query=f"{brand_group_natural} — {event}",
        ))

    research_questions = spec.get("research_questions", [])
    for i, rq in enumerate(research_questions[:3]):
        question = rq.get("question", "") if isinstance(rq, dict) else str(rq)
        if not question:
            continue
        phrase = question[:80]
        topics.append(TopicQuery(
            topic=f"research_question_{i + 1}",
            boolean_query=f'{brand_group_bool} AND "{phrase}"{exclusion}',
            natural_query=f"{brand_group_natural} {phrase}",
        ))

    return topics


_SOCIAL_PLATFORM_DOMAINS = {
    "twitter.com": "twitter", "x.com": "twitter", "instagram.com": "instagram",
    "facebook.com": "facebook", "reddit.com": "reddit", "linkedin.com": "linkedin",
}


def _platform_for_url(url: str) -> str | None:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return None
    for domain, platform in _SOCIAL_PLATFORM_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return platform
    return None


def _parse_to_timestamp(date_str: str) -> float:
    from .news_search import _parse_date
    parsed = _parse_date(date_str)
    return parsed.timestamp() if parsed else time.time()


def _to_normalized_items(bucket_result: dict, topic: str) -> list[dict]:
    items = []
    for bucket_name in ("social_media", "traditional_media"):
        for raw in bucket_result.get(bucket_name, []):
            url = raw.get("published_url", "")
            if not url:
                continue
            title = raw.get("title") or raw.get("content", "")[:80]
            date_str = raw.get("published_date") or raw.get("date_posted") or ""
            published_ts = _parse_to_timestamp(date_str)
            items.append({
                "topic": topic,
                "source_api": raw.get("_source", "unknown"),
                "platform": _platform_for_url(url),
                "publication": raw.get("publisher_name", ""),
                "published_date": published_ts,
                "title": title,
                "content": raw.get("content", ""),
                "url": url,
            })
    return items


def fetch_and_persist(
    project_id: int,
    topics: list[TopicQuery],
    date_range: tuple,
    geography: str,
    research_id: int | None = None,
    emit=None,
) -> dict:
    """Fetch every topic query (each topic itself fans out to 3 sources concurrently inside
    fetch_and_normalize), normalize, and upsert into intel_research_items as results arrive —
    a worker crash mid-run still leaves partial results queryable."""
    def _emit(step: str, payload: dict) -> None:
        if emit:
            emit(step, payload)

    items_fetched = 0
    items_persisted = 0
    source_status: dict[str, str] = {"tavily": "ok", "serpapi": "ok", "google_rss": "ok"}

    for i, topic in enumerate(topics):
        _emit("fetching_topic", {"topic": topic.topic, "index": i + 1, "total": len(topics)})
        bucket_result = news_search.fetch_and_normalize(
            query=topic.boolean_query,
            country=geography,
            date_range=date_range,
            max_results=15,
            tavily_query=topic.natural_query,
        )
        for failed in bucket_result.get("failed_sources", []):
            key = "google_rss" if failed == "google_news_rss" else failed
            source_status[key] = "degraded"

        normalized = _to_normalized_items(bucket_result, topic.topic)
        items_fetched += len(normalized)
        for item in normalized:
            repository.upsert_research_item(project_id, research_id, item)
            items_persisted += 1

    _emit("fetch_complete", {"items_fetched": items_fetched, "items_persisted": items_persisted})
    return {
        "items_fetched": items_fetched,
        "items_persisted": items_persisted,
        "source_status": source_status,
    }
