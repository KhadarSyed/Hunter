"""Web-search grounding for entities the brief-interpretation LLM cannot know from the
brief text alone — the current CEO/top executive and recent product launches.

brief_scope.py's entity extraction is a pure text-interpretation pass over the brief: its
own system prompt instructs it to name a competitor from general industry knowledge (RULE
#8), but has no equivalent instruction for an executive or a product launch, because
neither is a "well-known, stable" fact the way a competitor list is — a CEO can change
mid-year, and the LLM's training data has a cutoff, so even guessing from its own knowledge
risks naming a brand's *previous* CEO with false confidence. This module does what the LLM
structurally cannot: a live web search for "{brand} CEO <year>" / "{brand} new product
launch <year>", grounding the answer in that search's own snippets (never the LLM's
internal knowledge) and only injecting an entity when the search itself clearly names one.

Uses the same SerpAPI + Tavily + Google News RSS stack as the rest of research
(web_research.py's `_ddg_web_search`) — not DuckDuckGo directly, which this codebase
already abandoned for returning 0 results in production (see web_research.py's own
history). Never raises: any search or LLM failure just leaves the spec's entities
unchanged for that one kind, since a missing CEO entity is a gap, not a pipeline failure.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from ..domains.research.web_research import _ddg_web_search

logger = logging.getLogger(__name__)

_EXECUTIVE_SYSTEM_PROMPT = """\
You read real web search snippets about a named brand/company and extract ONE fact: who \
is its current CEO or top executive. Use ONLY the snippets given — never your own prior \
knowledge of this brand, which may be outdated. If the snippets clearly and consistently \
name a current CEO/president, return that person. If the snippets are unclear, silent on \
leadership, or disagree with each other, return an empty list rather than guessing.

Return ONLY a JSON object: {"entities": [{"name": "<full name>", "title": "<their exact \
title, e.g. \\"CEO\\" or \\"President and CEO\\">", "source_note": "<one short phrase \
citing which outlet/snippet named them>"}]} — empty "entities" array if the snippets don't \
clearly answer this."""

_PRODUCT_LAUNCH_SYSTEM_PROMPT = """\
You read real web search snippets about a named brand/company and extract up to 3 \
products, menu items, or offerings it has recently launched or newly announced. Use ONLY \
the snippets given — never your own prior knowledge. If nothing in the snippets describes \
a specific named launch, return an empty list rather than guessing or listing the brand's \
long-standing/flagship products.

Return ONLY a JSON object: {"entities": [{"name": "<product/launch name>", "source_note": \
"<one short phrase citing which outlet/snippet named it>"}]} — empty "entities" array if \
the snippets don't clearly name a specific recent launch."""


def _extract_json_object(text: str) -> dict:
    """Pull the first valid JSON object from LLM output, tolerating markdown fences —
    same tolerant-parse pattern used by every other agent in this codebase."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    brace_start = text.find("{")
    if brace_start == -1:
        raise ValueError("No JSON object found in LLM response")
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[brace_start:], start=brace_start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[brace_start:i + 1])
    raise ValueError("Unbalanced JSON object in LLM response")


def _search_snippets(query: str, max_results: int = 6) -> list[dict]:
    try:
        return _ddg_web_search(query, max_results=max_results)
    except Exception:
        logger.warning("Entity-grounding web search failed for %r", query, exc_info=True)
        return []


def _extract_grounded_entities(llm_client: Any, system_prompt: str, brand_name: str,
                               snippets: list[dict]) -> list[dict]:
    if not snippets:
        return []
    joined = "\n".join(
        f"- {s.get('title', '')}: {s.get('snippet', '')} ({s.get('source', '')})"
        for s in snippets[:6] if s.get("title") or s.get("snippet")
    )
    if not joined.strip():
        return []
    try:
        raw = llm_client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Brand: {brand_name}\n\nSearch snippets:\n{joined}"},
            ],
            format_json=True,
        )
        data = _extract_json_object(raw)
        entities = data.get("entities", [])
        return entities if isinstance(entities, list) else []
    except Exception:
        logger.warning("Entity-grounding LLM extraction failed for %r", brand_name, exc_info=True)
        return []


def ground_missing_entities(spec: dict, brand_name: str, llm_client: Any) -> dict:
    """Returns `spec` with a live-web-search-sourced "executive" entity and/or recent-launch
    "product" entities appended, but only for whichever kind the brief-only pass didn't
    already surface — never duplicates or overrides an entity brief_scope.py already found.
    No-ops (returns `spec` unchanged) when `brand_name` is empty or `llm_client` can't
    reach a chat backend."""
    if not brand_name or not llm_client or not getattr(llm_client, "is_reachable", lambda: False)():
        return spec

    entities = list(spec.get("validated_entities") or [])
    has_executive = any(e.get("type") == "executive" for e in entities)
    has_new_launch = any(
        e.get("type") in ("product", "product_group") and e.get("group") == "new_launch"
        for e in entities
    )

    year = date.today().year
    added: list[dict] = []

    if not has_executive:
        snippets = _search_snippets(f'"{brand_name}" CEO {year}')
        for hit in _extract_grounded_entities(llm_client, _EXECUTIVE_SYSTEM_PROMPT, brand_name, snippets):
            name = (hit.get("name") or "").strip()
            if not name:
                continue
            title = hit.get("title") or "executive"
            added.append({
                "name": name,
                "type": "executive",
                "confidence": "medium",
                "alternatives_considered": ["Not named in the brief text itself"],
                "reasoning": f"Identified via live web search as {brand_name}'s {title} "
                             f"({hit.get('source_note', 'current news coverage')}) — not "
                             f"named in the brief, verified current as of {year} rather "
                             f"than assumed from the brief author's or model's own "
                             f"potentially outdated knowledge.",
            })

    if not has_new_launch:
        snippets = _search_snippets(f'"{brand_name}" new product launch {year}')
        for hit in _extract_grounded_entities(llm_client, _PRODUCT_LAUNCH_SYSTEM_PROMPT, brand_name, snippets):
            name = (hit.get("name") or "").strip()
            if not name:
                continue
            added.append({
                "name": name,
                "type": "product",
                "confidence": "medium",
                "alternatives_considered": ["Not named in the brief text itself"],
                "reasoning": f"Identified via live web search as a recent {brand_name} "
                             f"launch ({hit.get('source_note', 'current news coverage')}) — "
                             f"not named in the brief.",
                "group": "new_launch",
            })

    if not added:
        return spec
    return {**spec, "validated_entities": entities + added}
