"""Multi-source research pipeline: Boolean query building, concurrent fan-out to
Tavily/SerpAPI/Google News RSS, per-item persistence, and map-reduce LLM summarization.

Replaces web_research.py's build_search_queries() (plain-string, stale spec fields — see
docs/superpowers/specs/2026-09-29-multi-source-research-pipeline-design.md §1) and
research/service.py's single fixed-truncation LLM call.
"""
from __future__ import annotations

from dataclasses import dataclass


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
