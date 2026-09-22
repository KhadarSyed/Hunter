"""Brand Intelligence Agent — produces structured brand background research
to ground all downstream Hunter agents with accurate entity context.

This agent takes a validated project spec (from Brief & Scope) and produces
comprehensive brand background research covering: brand overview, category
context, entity disambiguation, search term implications, and source quality
assessment.  When a web research adapter is provided, it can augment LLM
knowledge with live web results.

v1.0.0 — Initial implementation.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from ..ollama_client import OllamaClient

EventFn = Callable[[str, dict], None]


# ─── Web research adapter protocol ────────────────────────────────────────────

@runtime_checkable
class WebResearchAdapter(Protocol):
    """Typed interface for future web research integration.

    Any class implementing these two async methods can be passed as the
    web_adapter argument to ``run()``.  The agent will use it to supplement
    LLM knowledge with live search results and page content.
    """

    async def search(self, query: str, time_period: str) -> list[dict]:
        """Execute a web search and return a list of result dicts.

        Each dict should contain at minimum:
          - url: str
          - title: str
          - snippet: str
        """
        ...

    async def fetch_url(self, url: str) -> dict:
        """Fetch and extract content from a URL.

        Should return a dict with at minimum:
          - url: str
          - title: str
          - text: str  (extracted body text)
          - status: int
        """
        ...


# ─── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are the Brand Intelligence Agent for a PR and social intelligence research firm.
Your job: given a project specification, produce comprehensive brand background
research as structured JSON.  This research grounds every downstream agent with
accurate context so they never misidentify entities or confuse categories.

━━━ YOUR PURPOSE ━━━

Downstream agents (topic mapping, narrative analysis, social listening) will
use your output to:
  1. Understand what the brand IS and IS NOT
  2. Know the competitive and category landscape
  3. Disambiguate entities that share names with unrelated things
  4. Construct precise search queries that avoid false positives
  5. Evaluate whether a source is credible for this domain

━━━ RULES ━━━

1. ACCURACY OVER COMPLETENESS.
   If you are not confident about a fact, say so.  Use the confidence field.
   Never fabricate founding dates, revenue figures, or executive names.

2. DISAMBIGUATION IS CRITICAL.
   Many brand names are common words or overlap with other entities.
   "Jaguar" = car brand AND animal AND Mac OS version AND Fender guitar model.
   For each entity, list ALL plausible alternative meanings and explain why
   your interpretation is correct for this research context.

3. SEARCH IMPLICATIONS MATTER.
   Social listening tools will query platforms using search terms you define.
   Every term must be evaluated for false-positive risk.
   "Apple" alone captures fruit discussions.  "Apple iPhone" is more precise.
   Provide include-terms, exclude-terms, and boolean query suggestions.

4. SOURCE QUALITY IS NON-NEGOTIABLE.
   Not all sources are equal.  Trade publications > blogs > social posts
   for factual claims.  Rate each source type's reliability for this brand.

5. PRESERVE EXACT ENTITY NAMES.
   "Mrs. T's" includes the apostrophe and period.  Never normalize or
   simplify entity names from the specification.

6. CATEGORY CONTEXT MUST BE SPECIFIC.
   "Consumer goods" is too broad.  "Frozen pierogies within the frozen
   appetizers/sides subcategory of frozen foods" is useful.

━━━ OUTPUT FORMAT ━━━

Return ONLY a JSON object with these exact keys:

{
  "brand_overview": {
    "name": "official brand name exactly as used in commerce",
    "parent_company": "parent/holding company if applicable, null if independent",
    "founded": "founding year or null if uncertain",
    "headquarters": "city, state/country",
    "category": "specific product/service category",
    "subcategory": "narrower classification",
    "brand_positioning": "how the brand positions itself in the market",
    "target_demographic": "who the brand targets",
    "key_products": ["list of primary products or services"],
    "brand_lifecycle_stage": "launch|growth|mature|declining|revitalizing",
    "confidence": "high|medium|low"
  },
  "category_context": {
    "industry": "broad industry",
    "category": "specific category",
    "market_characteristics": "key traits of this market",
    "seasonality": "seasonal patterns if any, null otherwise",
    "key_players": [
      {
        "name": "competitor or peer brand",
        "relationship": "direct competitor|indirect competitor|category peer|aspirational peer",
        "relevance": "why this player matters for the research"
      }
    ],
    "category_trends": ["current trends shaping this category"],
    "regulatory_context": "relevant regulations or industry standards, null if none"
  },
  "entity_disambiguation": [
    {
      "entity": "the entity name being disambiguated",
      "intended_meaning": "what this entity means in this research context",
      "alternative_meanings": [
        {
          "meaning": "another possible interpretation",
          "domain": "where this alternative meaning exists",
          "false_positive_risk": "high|medium|low",
          "distinguishing_signals": "how to tell the intended meaning from this one"
        }
      ],
      "disambiguation_strategy": "recommended approach for filters and queries"
    }
  ],
  "search_implications": {
    "primary_search_terms": [
      {
        "term": "the search term",
        "purpose": "what this term captures",
        "false_positive_risk": "high|medium|low",
        "risk_explanation": "why false positives may or may not occur"
      }
    ],
    "recommended_exclude_terms": [
      {
        "term": "term to exclude from searches",
        "reason": "what false positives it prevents"
      }
    ],
    "boolean_query_suggestions": [
      {
        "platform": "platform or tool this query targets",
        "query": "the boolean query string",
        "purpose": "what this query is designed to capture"
      }
    ],
    "hashtags_and_handles": {
      "official_handles": ["@handle"],
      "official_hashtags": ["#hashtag"],
      "community_hashtags": ["#hashtag"],
      "competitor_handles": ["@handle"]
    },
    "platform_specific_notes": [
      {
        "platform": "platform name",
        "note": "platform-specific search consideration"
      }
    ]
  },
  "source_quality_assessment": {
    "tier_1_authoritative": {
      "description": "most reliable sources for this brand/category",
      "examples": ["specific publication or source type"],
      "use_for": "what claims these sources can support"
    },
    "tier_2_credible": {
      "description": "generally reliable but verify claims",
      "examples": ["specific publication or source type"],
      "use_for": "what these sources are good for"
    },
    "tier_3_supplementary": {
      "description": "useful for sentiment/volume but not factual claims",
      "examples": ["specific publication or source type"],
      "use_for": "what these sources add"
    },
    "unreliable_sources": {
      "description": "sources to deprioritize or flag",
      "examples": ["specific source types to watch for"],
      "why_unreliable": "reason these are not trustworthy for this domain"
    },
    "geographic_source_considerations": "notes on source geography relevance"
  },
  "research_context": {
    "brand_in_news_recently": "summary of recent notable coverage, null if unknown",
    "known_controversies": "active controversies that may skew data, null if none",
    "upcoming_events": "product launches, campaigns, or events that may affect data, null if unknown",
    "data_availability_assessment": "how much social/media data likely exists for this brand"
  },
  "confidence_assessment": {
    "overall": "high|medium|low",
    "brand_knowledge": "high|medium|low",
    "category_knowledge": "high|medium|low",
    "disambiguation_confidence": "high|medium|low",
    "search_term_confidence": "high|medium|low",
    "reasoning": "explanation of confidence levels and any gaps"
  }
}
"""


# ─── Output schema (for programmatic reference) ──────────────────────────────

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "brand_overview",
        "category_context",
        "entity_disambiguation",
        "search_implications",
        "source_quality_assessment",
        "research_context",
        "confidence_assessment",
    ],
    "properties": {
        "brand_overview": {
            "type": "object",
            "required": ["name", "category", "confidence"],
        },
        "category_context": {
            "type": "object",
            "required": ["industry", "category"],
        },
        "entity_disambiguation": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "entity",
                    "intended_meaning",
                    "alternative_meanings",
                    "disambiguation_strategy",
                ],
            },
        },
        "search_implications": {
            "type": "object",
            "required": [
                "primary_search_terms",
                "recommended_exclude_terms",
                "boolean_query_suggestions",
            ],
        },
        "source_quality_assessment": {
            "type": "object",
            "required": [
                "tier_1_authoritative",
                "tier_2_credible",
                "tier_3_supplementary",
            ],
        },
        "research_context": {
            "type": "object",
        },
        "confidence_assessment": {
            "type": "object",
            "required": ["overall", "reasoning"],
        },
    },
}

CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})

REQUIRED_TOP_KEYS = [
    "brand_overview",
    "category_context",
    "entity_disambiguation",
    "search_implications",
    "source_quality_assessment",
    "research_context",
    "confidence_assessment",
]

BRAND_OVERVIEW_REQUIRED = ["name", "category", "confidence"]
SEARCH_IMPLICATIONS_REQUIRED = [
    "primary_search_terms",
    "recommended_exclude_terms",
    "boolean_query_suggestions",
]
SOURCE_TIERS = ["tier_1_authoritative", "tier_2_credible", "tier_3_supplementary"]


# ─── Response parsing ─────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Pull the first valid JSON object from LLM output, tolerating markdown
    fences, preamble text, and trailing commentary."""
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
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[brace_start : i + 1]
                return json.loads(candidate)

    return json.loads(text[brace_start:])


# ─── Validation ───────────────────────────────────────────────────────────────

def validate_output(data: dict) -> tuple[list[str], list[str]]:
    """Validate brand intelligence output against the expected schema.

    Returns:
        (errors, warnings) — errors are hard failures that indicate the
        output is unusable; warnings are quality issues that should be
        flagged but do not block downstream processing.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Top-level keys ---
    for key in REQUIRED_TOP_KEYS:
        if key not in data:
            errors.append(f"Missing required section: '{key}'")

    # --- brand_overview ---
    overview = data.get("brand_overview", {})
    if not isinstance(overview, dict):
        errors.append("brand_overview must be a dict")
    else:
        for field in BRAND_OVERVIEW_REQUIRED:
            if not overview.get(field):
                errors.append(f"brand_overview.{field} is missing or empty")
        conf = overview.get("confidence", "")
        if conf and conf not in CONFIDENCE_LEVELS:
            warnings.append(
                f"brand_overview.confidence has invalid value '{conf}'")
        if not overview.get("parent_company") and overview.get("parent_company") is not None:
            warnings.append(
                "brand_overview.parent_company is empty — set to null if "
                "the brand is independent")
        if not overview.get("key_products"):
            warnings.append("brand_overview.key_products is empty")

    # --- category_context ---
    category = data.get("category_context", {})
    if not isinstance(category, dict):
        errors.append("category_context must be a dict")
    else:
        if not category.get("industry"):
            errors.append("category_context.industry is missing or empty")
        if not category.get("category"):
            errors.append("category_context.category is missing or empty")
        players = category.get("key_players", [])
        if not players:
            warnings.append(
                "category_context.key_players is empty — most brands have "
                "at least one competitor or category peer")
        for i, player in enumerate(players):
            if isinstance(player, dict) and not player.get("name"):
                errors.append(
                    f"category_context.key_players[{i}].name is missing")

    # --- entity_disambiguation ---
    entities = data.get("entity_disambiguation", [])
    if not isinstance(entities, list):
        errors.append("entity_disambiguation must be a list")
    elif not entities:
        warnings.append(
            "entity_disambiguation is empty — most entities need "
            "disambiguation for search accuracy")
    else:
        for i, ent in enumerate(entities):
            if not isinstance(ent, dict):
                errors.append(
                    f"entity_disambiguation[{i}] must be a dict")
                continue
            if not ent.get("entity"):
                errors.append(
                    f"entity_disambiguation[{i}].entity is missing")
            if not ent.get("intended_meaning"):
                errors.append(
                    f"entity_disambiguation[{i}].intended_meaning is missing")
            if not ent.get("disambiguation_strategy"):
                warnings.append(
                    f"entity_disambiguation[{i}].disambiguation_strategy "
                    f"is missing")
            alts = ent.get("alternative_meanings", [])
            if not alts:
                warnings.append(
                    f"entity_disambiguation[{i}].alternative_meanings is "
                    f"empty — consider whether the name could be confused")
            for j, alt in enumerate(alts):
                if isinstance(alt, dict):
                    risk = alt.get("false_positive_risk", "")
                    if risk and risk not in CONFIDENCE_LEVELS:
                        warnings.append(
                            f"entity_disambiguation[{i}]."
                            f"alternative_meanings[{j}]."
                            f"false_positive_risk has invalid value '{risk}'")

    # --- search_implications ---
    search = data.get("search_implications", {})
    if not isinstance(search, dict):
        errors.append("search_implications must be a dict")
    else:
        for field in SEARCH_IMPLICATIONS_REQUIRED:
            if field not in search:
                errors.append(
                    f"search_implications.{field} is missing")
        terms = search.get("primary_search_terms", [])
        if isinstance(terms, list):
            if not terms:
                errors.append(
                    "search_implications.primary_search_terms is empty — "
                    "at least one search term is required")
            for i, term in enumerate(terms):
                if isinstance(term, dict):
                    if not term.get("term"):
                        errors.append(
                            f"search_implications.primary_search_terms[{i}]"
                            f".term is missing")
                    risk = term.get("false_positive_risk", "")
                    if risk and risk not in CONFIDENCE_LEVELS:
                        warnings.append(
                            f"search_implications.primary_search_terms[{i}]"
                            f".false_positive_risk has invalid value '{risk}'")

    # --- source_quality_assessment ---
    sources = data.get("source_quality_assessment", {})
    if not isinstance(sources, dict):
        errors.append("source_quality_assessment must be a dict")
    else:
        for tier in SOURCE_TIERS:
            tier_data = sources.get(tier, {})
            if not tier_data:
                warnings.append(
                    f"source_quality_assessment.{tier} is missing or empty")
            elif isinstance(tier_data, dict):
                if not tier_data.get("description"):
                    warnings.append(
                        f"source_quality_assessment.{tier}.description "
                        f"is missing")
                if not tier_data.get("examples"):
                    warnings.append(
                        f"source_quality_assessment.{tier}.examples "
                        f"is missing")

    # --- confidence_assessment ---
    confidence = data.get("confidence_assessment", {})
    if not isinstance(confidence, dict):
        errors.append("confidence_assessment must be a dict")
    else:
        overall = confidence.get("overall", "")
        if not overall:
            errors.append("confidence_assessment.overall is missing")
        elif overall not in CONFIDENCE_LEVELS:
            warnings.append(
                f"confidence_assessment.overall has invalid value '{overall}'")
        if not confidence.get("reasoning"):
            warnings.append(
                "confidence_assessment.reasoning is missing — "
                "confidence levels should be explained")

    return errors, warnings


# ─── Agent runner ─────────────────────────────────────────────────────────────

def _build_user_prompt(spec: dict) -> str:
    """Construct the user prompt from a project specification."""
    parts = [
        "Produce comprehensive brand intelligence research for the "
        "following project specification.  Return your findings as JSON.\n"
    ]

    # Extract key fields from the spec for the prompt.
    cb = spec.get("commissioning_brand", {})
    if isinstance(cb, dict) and cb.get("name"):
        parts.append(f"Commissioning brand: {cb['name']}")
        if cb.get("role"):
            parts.append(f"  Role: {cb['role']}")

    rs = spec.get("research_subject", {})
    if isinstance(rs, dict) and rs.get("description"):
        parts.append(f"Research subject: {rs['description']}")

    ra = spec.get("research_audience", {})
    if isinstance(ra, dict) and ra.get("description"):
        parts.append(f"Research audience: {ra['description']}")

    if spec.get("business_objective"):
        parts.append(f"Business objective: {spec['business_objective']}")

    if spec.get("research_objective"):
        parts.append(f"Research objective: {spec['research_objective']}")

    # Entities from the spec.
    entities = spec.get("validated_entities", [])
    if entities:
        parts.append("\nValidated entities:")
        for ent in entities:
            if isinstance(ent, dict):
                name = ent.get("name", "")
                etype = ent.get("type", "")
                parts.append(f"  - {name} ({etype})")

    # Scope information.
    scope = spec.get("included_scope", {})
    if scope:
        if scope.get("platforms"):
            parts.append(f"\nPlatforms: {', '.join(scope['platforms'])}")
        if scope.get("countries"):
            parts.append(f"Countries: {', '.join(scope['countries'])}")
        if scope.get("time_period"):
            parts.append(f"Time period: {scope['time_period']}")

    # Research questions for context.
    rqs = spec.get("research_questions", [])
    if rqs:
        parts.append("\nResearch questions:")
        for rq in rqs:
            if isinstance(rq, dict) and rq.get("question"):
                qid = rq.get("question_id", "")
                parts.append(f"  {qid}: {rq['question']}")

    parts.append(
        "\n--- Produce brand intelligence research covering brand overview, "
        "category context, entity disambiguation, search implications, "
        "and source quality assessment. ---"
    )
    return "\n".join(parts)


async def run(
    spec: dict,
    *,
    emit: EventFn | None = None,
    ollama: OllamaClient | None = None,
    web_adapter: WebResearchAdapter | None = None,
) -> dict:
    """Execute the Brand Intelligence Agent.

    Parameters:
        spec: A validated project specification dict (output of Brief & Scope).
        emit: Optional event callback for progress tracking.
        ollama: OllamaClient instance for LLM calls.
        web_adapter: Optional web research adapter for live search augmentation.

    Returns a dict with keys:
        brand_intelligence: the validated brand research output
        validation_errors: list of hard errors (should be empty on success)
        validation_warnings: list of quality warnings
        web_augmented: whether web research was used
        elapsed_seconds: wall-clock time
    """
    if emit is None:
        emit = lambda event_type, payload: None

    start = time.time()

    brand_name = ""
    cb = spec.get("commissioning_brand", {})
    if isinstance(cb, dict):
        brand_name = cb.get("name", "")
    if not brand_name:
        for ent in spec.get("validated_entities", []):
            if isinstance(ent, dict) and ent.get("type") == "brand":
                brand_name = ent.get("name", "")
                break

    emit("brand_intelligence_started", {
        "brand": brand_name,
        "has_web_adapter": web_adapter is not None,
    })

    # Build the user prompt from the spec.
    user_prompt = _build_user_prompt(spec)

    # If a web adapter is available, augment the prompt with live search data.
    web_augmented = False
    if web_adapter is not None and brand_name:
        emit("brand_intelligence_web_search", {"brand": brand_name})
        try:
            search_results = await web_adapter.search(
                f"{brand_name} brand overview company", "past_year"
            )
            if search_results:
                web_augmented = True
                web_context_parts = ["\n\n--- WEB RESEARCH CONTEXT ---"]
                for result in search_results[:5]:
                    title = result.get("title", "")
                    snippet = result.get("snippet", "")
                    url = result.get("url", "")
                    web_context_parts.append(
                        f"Source: {title}\nURL: {url}\n{snippet}\n"
                    )
                web_context_parts.append("--- END WEB RESEARCH CONTEXT ---")
                user_prompt += "\n".join(web_context_parts)
        except Exception as e:
            emit("brand_intelligence_web_error", {
                "error": f"Web search failed: {e}",
            })

    # Call the LLM.
    if ollama is None:
        elapsed = round(time.time() - start, 1)
        emit("brand_intelligence_failed", {
            "error": "No OllamaClient provided",
            "elapsed": elapsed,
        })
        return {
            "brand_intelligence": None,
            "validation_errors": ["No OllamaClient provided"],
            "validation_warnings": [],
            "web_augmented": False,
            "elapsed_seconds": elapsed,
        }

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    emit("brand_intelligence_reasoning", {
        "status": "LLM producing brand intelligence...",
    })

    try:
        raw_response = ollama.chat(
            messages,
            on_token=lambda t: None,
            format_json=True,
        )
    except Exception as e:
        elapsed = round(time.time() - start, 1)
        emit("brand_intelligence_error", {
            "error": f"LLM call failed: {e}",
            "elapsed": elapsed,
        })
        return {
            "brand_intelligence": None,
            "validation_errors": [f"LLM call failed: {e}"],
            "validation_warnings": [],
            "web_augmented": web_augmented,
            "elapsed_seconds": elapsed,
        }

    # Parse JSON from the response.
    try:
        result = _extract_json(raw_response)
    except (json.JSONDecodeError, ValueError) as e:
        elapsed = round(time.time() - start, 1)
        emit("brand_intelligence_error", {
            "error": f"JSON parse failed: {e}",
            "elapsed": elapsed,
        })
        return {
            "brand_intelligence": None,
            "validation_errors": [f"JSON parse failed: {e}"],
            "validation_warnings": [],
            "web_augmented": web_augmented,
            "elapsed_seconds": elapsed,
        }

    # Validate the output.
    validation_errors, validation_warnings = validate_output(result)

    elapsed = round(time.time() - start, 1)

    # Attach metadata.
    result["_meta"] = {
        "agent": "brand_intelligence",
        "version": "1.0.0",
        "brand": brand_name,
        "web_augmented": web_augmented,
        "elapsed_seconds": elapsed,
        "validation_errors": len(validation_errors),
        "validation_warnings": len(validation_warnings),
    }

    if validation_errors:
        emit("brand_intelligence_validated", {
            "errors": len(validation_errors),
            "warnings": len(validation_warnings),
            "elapsed": elapsed,
        })
    else:
        emit("brand_intelligence_complete", {
            "brand": brand_name,
            "disambiguation_count": len(
                result.get("entity_disambiguation", [])),
            "search_terms": len(
                result.get("search_implications", {})
                .get("primary_search_terms", [])),
            "confidence": result.get(
                "confidence_assessment", {}).get("overall", ""),
            "web_augmented": web_augmented,
            "elapsed": elapsed,
        })

    return {
        "brand_intelligence": result,
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings,
        "web_augmented": web_augmented,
        "elapsed_seconds": elapsed,
    }
