"""Multi-source research pipeline: Boolean query building, concurrent fan-out to
Tavily/SerpAPI/Google News RSS, per-item persistence, and map-reduce LLM summarization.

Replaces web_research.py's build_search_queries() (plain-string, stale spec fields — see
docs/superpowers/specs/2026-09-29-multi-source-research-pipeline-design.md §1) and
research/service.py's single fixed-truncation LLM call.
"""
from __future__ import annotations

import json as _json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from . import news_search
from . import repository

logger = logging.getLogger(__name__)


@dataclass
class TopicQuery:
    topic: str
    boolean_query: str   # SerpAPI + Google News RSS (Boolean/Google search syntax)
    natural_query: str    # Tavily (plain language, no operators)
    # Human-readable label for progress UI — distinct from natural_query, which repeats the
    # full brand/competitor OR-list on every topic (noisy once shown topic after topic).
    display_label: str = ""


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
        category = ((spec.get("research_subject") or {}).get("description") or "")[:60]

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
        display_label="Brand News & Announcements",
    ))

    if category:
        topics.append(TopicQuery(
            topic="competitive_landscape",
            boolean_query=f'{brand_group_bool} AND "{category}"{exclusion}',
            natural_query=f"{brand_group_natural} {category} market",
            display_label="Competitive Landscape",
        ))
        topics.append(TopicQuery(
            topic="category_trends",
            boolean_query=f'{brand_group_bool} AND "{category}" AND (trend OR market){exclusion}',
            natural_query=f"{category} market trends: {brand_group_natural}",
            display_label="Category & Market Trends",
        ))

    if products:
        topics.append(TopicQuery(
            topic="product_mentions",
            boolean_query=f"{brand_group_bool} AND {_or_group(products)}{exclusion}",
            natural_query=f"{brand_group_natural} — {', '.join(products)}",
            display_label="Product Mentions",
        ))

    for event in events:
        topics.append(TopicQuery(
            topic=f"event_{event.lower().replace(' ', '_')}",
            boolean_query=f'{brand_group_bool} AND "{event}"{exclusion}',
            natural_query=f"{brand_group_natural} — {event}",
            display_label=f"Event: {event}",
        ))

    research_questions = spec.get("research_questions", [])
    for i, rq in enumerate(research_questions):
        question = rq.get("question", "") if isinstance(rq, dict) else str(rq)
        if not question:
            continue
        phrase = question[:80]
        topics.append(TopicQuery(
            topic=f"research_question_{i + 1}",
            boolean_query=f'{brand_group_bool} AND "{phrase}"{exclusion}',
            natural_query=f"{brand_group_natural} {phrase}",
            display_label=phrase,
        ))

    return topics


def _platform_for_url(url: str) -> str | None:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return None
    for domain, platform in news_search.SOCIAL_PLATFORM_DOMAINS.items():
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
                "author": raw.get("author") or None,
                "thumbnail_url": raw.get("thumbnail") or None,
            })
    return items


MAX_RESULTS_PER_SOURCE = 40  # per source, per fetch call (general or social-biased) — up from
                              # 15; Tavily/SerpAPI both support well beyond this per call


def _build_social_query(boolean_query: str) -> str:
    """Bias a Boolean query toward social platforms via site: operators — works natively for
    SerpAPI/Google News RSS's Google-search-flavored syntax. Tavily gets its own include_domains
    restriction instead (see fetch_and_persist), since Tavily's natural-language search doesn't
    parse embedded site: operators as a filter."""
    domains = sorted(news_search.SOCIAL_PLATFORM_DOMAINS.keys())
    site_group = "(" + " OR ".join(f"site:{d}" for d in domains) + ")"
    return f"({boolean_query}) AND {site_group}"


def fetch_and_persist(
    project_id: int,
    topics: list[TopicQuery],
    date_range: tuple,
    geography: str,
    research_id: int | None = None,
    emit=None,
) -> dict:
    """Fetch every topic query. Each topic makes TWO fetch_and_normalize calls (each itself
    fanning out to 3 sources concurrently): a general call, and a social-biased call restricted
    to known social platforms — so social coverage gets its own guaranteed budget rather than
    competing for space within one shared result window. Normalizes and upserts into
    intel_research_items as results arrive — a worker crash mid-run still leaves partial
    results queryable. Overlapping URLs between the two calls are deduped before persisting."""
    def _emit(step: str, payload: dict) -> None:
        if emit:
            emit(step, payload)

    items_fetched = 0
    items_persisted = 0
    source_status: dict[str, str] = {"tavily": "ok", "serpapi": "ok", "google_rss": "ok"}
    social_domains = list(news_search.SOCIAL_PLATFORM_DOMAINS.keys())

    def _track_failures(bucket_result: dict) -> None:
        for failed in bucket_result.get("failed_sources", []):
            key = "google_rss" if failed == "google_news_rss" else failed
            source_status[key] = "degraded"

    for i, topic in enumerate(topics):
        _emit("fetching_topic", {"topic": topic.topic, "display_label": topic.display_label,
                                  "index": i + 1, "total": len(topics)})

        general_result = news_search.fetch_and_normalize(
            query=topic.boolean_query, country=geography, date_range=date_range,
            max_results=MAX_RESULTS_PER_SOURCE, tavily_query=topic.natural_query,
        )
        _track_failures(general_result)

        social_result = news_search.fetch_and_normalize(
            query=_build_social_query(topic.boolean_query), country=geography,
            date_range=date_range, max_results=MAX_RESULTS_PER_SOURCE,
            tavily_query=topic.natural_query, include_domains=social_domains,
        )
        _track_failures(social_result)

        # Social items first: kept ahead of the general call's items so they're never crowded
        # out downstream (e.g. LLM map-reduce batching, which processes items in this order).
        social_items = _to_normalized_items(social_result, topic.topic)
        general_items = _to_normalized_items(general_result, topic.topic)

        seen_urls: set[str] = set()
        combined: list[dict] = []
        for item in social_items + general_items:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            combined.append(item)

        items_fetched += len(combined)
        for item in combined:
            repository.upsert_research_item(project_id, research_id, item)
            items_persisted += 1

    _emit("fetch_complete", {"items_fetched": items_fetched, "items_persisted": items_persisted})
    return {
        "items_fetched": items_fetched,
        "items_persisted": items_persisted,
        "source_status": source_status,
    }


BATCH_SIZE = 18  # items per map-step LLM call; sized to stay comfortably under a typical
                 # prompt-token budget for ~18 title+300-char-content items

_REDUCE_KEYS = [
    "company_introduction", "executive_summary", "brand_developments",
    "brand_narrative", "competitor_developments", "industry_context", "methodology",
]


def date_range_to_timestamps(date_range: tuple) -> tuple[float, float]:
    """(start, end) dates -> (since, until) Unix timestamps, inclusive of the whole end date —
    matches news_search._within_range's date-boundary fix (an exclusive-next-midnight upper
    bound), so a run's own fetch and this run's own brief agree on what's "in range"."""
    start, end = date_range
    start_dt = start if isinstance(start, datetime) else datetime.combine(start, datetime.min.time())
    end_dt = end if isinstance(end, datetime) else datetime.combine(end, datetime.min.time())
    return start_dt.timestamp(), (end_dt + timedelta(days=1)).timestamp()


def _current_date_prefix() -> str:
    now = datetime.now()
    return (f"Today's date is {now.strftime('%Y-%m-%d')} ({now.strftime('%A')}). "
            "Use this, not your own assumption, for any relative date reasoning.\n\n")


def _batch_items(items: list[dict], batch_size: int) -> list[list[dict]]:
    by_topic: dict[str, list[dict]] = {}
    for item in items:
        by_topic.setdefault(item["topic"], []).append(item)
    batches = []
    for topic_items in by_topic.values():
        for i in range(0, len(topic_items), batch_size):
            batches.append(topic_items[i:i + batch_size])
    return batches


def _map_batch(llm_client, batch: list[dict]) -> dict | None:
    topic = batch[0]["topic"]
    lines = []
    for item in batch:
        lines.append(f"- [{item.get('publication', '')}] {item.get('title', '')}")
        if item.get("content"):
            lines.append(f"  {item['content'][:300]}")

    prompt = (
        _current_date_prefix()
        + f'Summarize these {len(batch)} items about "{topic}" into 3-6 key points a '
        "competitive-intelligence analyst would care about. Return ONLY JSON: "
        '{"topic": "' + topic + '", "key_points": ["...", ...], "notable_sources": ["...", ...]}\n\n'
        + "\n".join(lines)
    )
    try:
        response = llm_client.chat(
            [{"role": "system", "content": "Return only valid JSON."},
             {"role": "user", "content": prompt}],
            format_json=True,
        )
        cleaned = response.strip()
        if cleaned.startswith("```"):
            import re
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        return _json.loads(cleaned)
    except Exception:
        logger.exception("Map-step batch summary failed for topic=%r — skipping this batch", topic)
        return None


def _coerce_to_markdown(value) -> str:
    """The reduce LLM call is prompted for markdown strings per section, but a model can still
    return a raw JSON list or dict for a given key — coerce it into the same bullet/heading
    shape the prompt asked for, so every section["content"] downstream is always a str."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(f"- {_coerce_to_markdown(item)}" for item in value)
    if isinstance(value, dict):
        return "\n\n".join(f"## {k}\n{_coerce_to_markdown(v)}" for k, v in value.items())
    return "" if value is None else str(value)


def _reduce_batches(llm_client, batch_summaries: list[dict], brand_name: str, competitors: list[str]) -> dict:
    summary_block = _json.dumps(batch_summaries, indent=2)
    comp_list = ", ".join(competitors) if competitors else "no named competitors identified"
    prompt = (
        _current_date_prefix()
        + f"You are a senior competitive intelligence analyst writing a brief for {brand_name}, "
        f"benchmarked against these competitors: {comp_list}. "
        "Below are topic-grouped summaries of research findings. Combine them into a full brief. "
        f"Every section must weigh {brand_name} against the named competitors, not describe "
        f"{brand_name} in isolation. Return ONLY JSON with these exact keys:\n"
        + ", ".join(_REDUCE_KEYS) + "\n\n"
        + "SECTION GUIDANCE:\n"
        f"- company_introduction: 2-3 paragraph overview of {brand_name}, ending with a sentence "
        f"on how it is positioned relative to {comp_list}.\n"
        "- executive_summary: 3-5 analytical paragraphs synthesizing the key themes across "
        f"{brand_name}, {comp_list}, and the industry — explicitly compare, don't just recap "
        f"{brand_name} alone. Then a \"## What this means for {brand_name}\" sub-heading with "
        "4-6 strategic bullets that reference the competitive set.\n"
        f"- brand_developments: {brand_name}'s own most significant developments, \"## Date | Headline\" "
        "format, 2-4 sentences each — each description should note how the development compares to "
        "or is likely to affect the competitive set when relevant.\n"
        "- brand_narrative: 4-6 bullets on narrative positioning, each assessed relative to "
        f"{comp_list}, not in a vacuum.\n"
        "- competitor_developments: for EACH competitor in "
        f"{comp_list}, write \"## CompetitorName\" then a 2-3 sentence company-introduction "
        "paragraph (what it does, market position, scale — the same depth as company_introduction "
        "but for that competitor), then its developments as \"### Date | Headline\" entries, "
        "2-3 sentences each with [S#] citations. Every named competitor gets its own intro, "
        "even if research volume for it is thin — write a shorter but still analytical version.\n"
        "- industry_context: 3-6 industry themes covering the whole competitive set (not just "
        f"{brand_name}), ending with "
        '"## Key issues to monitor over the next 6-12 months" and 5-8 bullets.\n'
        "- methodology: 5-7 bullets on scope, time window, competitor set, selection rule.\n\n"
        "BATCH SUMMARIES:\n" + summary_block
    )
    response = llm_client.chat(
        [{"role": "system", "content": "You are a senior competitive intelligence analyst. Return only valid JSON."},
         {"role": "user", "content": prompt}],
        format_json=True,
    )
    cleaned = response.strip()
    if cleaned.startswith("```"):
        import re
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
    parsed = _json.loads(cleaned)
    return {key: _coerce_to_markdown(parsed.get(key, "")) for key in _REDUCE_KEYS}


def summarize_map_reduce(project_id: int, spec: dict, llm_client, emit=None, date_range: tuple | None = None) -> dict:
    """Batch-summarize persisted research items for this project (no truncation caps), then
    combine batch summaries into the 7-key Brief section shape. Failed batches are skipped,
    not fatal. Returns {} if there are zero items (caller falls back to _compose_rule_based,
    matching today's zero-results behavior).

    `date_range`, when given, scopes to that window (typically the current run's) so a
    project's earlier runs or date windows don't silently bleed into this brief."""
    def _emit(step: str, payload: dict) -> None:
        if emit:
            emit(step, payload)

    if date_range:
        since, until = date_range_to_timestamps(date_range)
        items = repository.get_research_items(project_id, since=since, until=until)
    else:
        items = repository.get_research_items(project_id)
    if not items:
        return {}

    brand_name = (spec.get("commissioning_brand") or {}).get("name", "the brand")
    competitors = _entities_by_type(spec, "competitor")
    batches = _batch_items(items, BATCH_SIZE)
    batch_summaries = []
    for i, batch in enumerate(batches):
        _emit("summarizing_batch", {"index": i + 1, "total": len(batches)})
        summary = _map_batch(llm_client, batch)
        if summary:
            batch_summaries.append(summary)

    if not batch_summaries:
        return {}

    _emit("combining_summaries", {"batch_count": len(batch_summaries)})
    return _reduce_batches(llm_client, batch_summaries, brand_name, competitors)
