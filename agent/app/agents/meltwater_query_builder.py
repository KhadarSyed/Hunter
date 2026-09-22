"""Meltwater Query Builder Agent -- generates Meltwater-compatible Boolean
search strategies from a validated ProjectSpecification.

This agent uses the LLM to translate research questions, entities, and scope
into optimised Boolean queries suitable for Meltwater's search syntax.  It
produces broad / balanced / precise variants, research-question subqueries,
exclusion logic, filter recommendations, and quality scores.

It NEVER executes searches -- only builds the query strategy.

v1.0.0 -- Initial implementation.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

from ..ollama_client import OllamaClient

EventFn = Callable[[str, dict], None]


# --- System prompt ---------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the Meltwater Query Builder Agent for a PR and social intelligence
research firm.  Your job: read a validated ProjectSpecification and produce a
comprehensive Boolean search strategy compatible with Meltwater's search
syntax.  You do NOT execute searches.  You only build queries.

=== MELTWATER BOOLEAN SYNTAX RULES ===

1. OPERATORS: AND, OR, NOT (always UPPERCASE).
2. PHRASES: Wrap multi-word terms in double quotes -- "social media".
3. GROUPING: Use parentheses to control precedence --
   ("term one" OR "term two") AND ("term three").
4. PROXIMITY: Use NEAR/n -- "brand" NEAR/5 "product".
5. WILDCARDS: Use * for stemming -- invest* matches invest, investing, investment.
6. NOT must follow another term or group -- never start a query with NOT.
7. Each query should be under 4000 characters for Meltwater compatibility.

=== OUTPUT REQUIREMENTS ===

Return ONLY a JSON object with these exact keys:

{
  "strategy_summary": "2-3 sentence overview of the search strategy",

  "query_modules": [
    {
      "module_id": "M1",
      "name": "descriptive module name",
      "purpose": "what this module captures",
      "terms": {
        "primary": ["core search terms"],
        "synonyms": ["alternative phrasings"],
        "exclusions": ["terms to exclude via NOT"]
      }
    }
  ],

  "query_versions": {
    "broad": {
      "query": "the broad Boolean query string",
      "description": "what this version captures and why",
      "estimated_noise_level": "high|medium|low",
      "use_case": "when to use this version"
    },
    "balanced": {
      "query": "the balanced Boolean query string",
      "description": "what this version captures and why",
      "estimated_noise_level": "high|medium|low",
      "use_case": "when to use this version"
    },
    "precise": {
      "query": "the precise Boolean query string",
      "description": "what this version captures and why",
      "estimated_noise_level": "high|medium|low",
      "use_case": "when to use this version"
    }
  },

  "research_question_queries": [
    {
      "question_id": "RQ1",
      "question": "the research question text",
      "query": "Boolean query targeting this specific question",
      "rationale": "why this query answers the question"
    }
  ],

  "exclusion_strategy": {
    "global_exclusions": "NOT terms applied to all queries",
    "rationale": "why these exclusions are needed",
    "exclusion_categories": [
      {
        "category": "spam|irrelevant_industry|geographic|other",
        "terms": ["excluded terms"],
        "reason": "why excluded"
      }
    ]
  },

  "filter_recommendations": {
    "date_range": "recommended date range",
    "geography": ["countries or regions"],
    "language": ["languages"],
    "source_types": ["news|social|blogs|forums|reviews"],
    "platforms": ["specific platforms if applicable"],
    "additional_filters": [
      {
        "filter": "filter name",
        "value": "recommended value",
        "reason": "why this filter helps"
      }
    ]
  },

  "quality_assessment": {
    "overall_score": 1-10,
    "coverage_score": 1-10,
    "precision_score": 1-10,
    "potential_gaps": ["areas the queries may miss"],
    "potential_noise": ["areas that may generate false positives"],
    "recommendations": ["suggestions for query refinement"]
  }
}

=== RULES ===

1. ALWAYS preserve entity names exactly as given -- including punctuation,
   possessives, and special characters.  "Mrs. T's" must appear as
   "Mrs. T's" in queries, not "Mrs T" or "Mrs".

2. For brand names with special characters, include both the exact form and
   common misspellings/variations as OR alternatives.

3. Build queries progressively:
   - Broad: maximise recall, accept more noise
   - Balanced: good recall with reasonable precision
   - Precise: maximise precision, accept some recall loss

4. Each research question MUST have its own targeted subquery.

5. Exclusion logic should remove:
   - Spam and promotional content patterns
   - Irrelevant industry mentions (homonyms, unrelated uses)
   - Geographic noise (if scope is limited)
   - Bot and automated content patterns

6. Filter recommendations must align with the ProjectSpecification's
   included_scope (countries, languages, platforms, time_period).

7. Quality scores must be honest -- flag gaps and noise risks.

8. Never generate queries longer than 4000 characters each.

9. Use NEAR/n operators for contextual relevance where appropriate.

10. Include wildcard stemming (invest*) only when it adds genuine value
    without introducing excessive noise.
"""


# --- Output schema definition (for programmatic validation) ----------------------

OUTPUT_SCHEMA: dict[str, Any] = {
    "required_top_keys": [
        "strategy_summary",
        "query_modules",
        "query_versions",
        "research_question_queries",
        "exclusion_strategy",
        "filter_recommendations",
        "quality_assessment",
    ],
    "query_version_keys": ["broad", "balanced", "precise"],
    "query_version_fields": [
        "query", "description", "estimated_noise_level", "use_case",
    ],
    "noise_levels": ["high", "medium", "low"],
    "module_fields": ["module_id", "name", "purpose", "terms"],
    "rq_query_fields": ["question_id", "question", "query", "rationale"],
    "quality_score_range": (1, 10),
}


# --- Boolean syntax validator ----------------------------------------------------

def validate_boolean_syntax(query: str) -> list[str]:
    """Check a Boolean query string for syntax errors.

    Returns a list of human-readable error messages.  An empty list means the
    query passed all checks.
    """
    errors: list[str] = []
    if not query or not query.strip():
        errors.append("Query is empty")
        return errors

    # -- Balanced parentheses --
    depth = 0
    for i, ch in enumerate(query):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth < 0:
            errors.append(
                f"Unbalanced parentheses: unexpected ')' at position {i}")
            break
    if depth > 0:
        errors.append(
            f"Unbalanced parentheses: {depth} unclosed '(' remaining")

    # -- Unclosed quotes --
    in_quote = False
    for i, ch in enumerate(query):
        if ch == '"':
            in_quote = not in_quote
    if in_quote:
        errors.append("Unclosed double quote in query")

    # -- Adjacent duplicate operators --
    # Tokenise outside of quoted strings to find operator sequences.
    tokens = _tokenise_query(query)
    operators = {"AND", "OR", "NOT"}
    for i in range(len(tokens) - 1):
        if tokens[i] in operators and tokens[i + 1] in operators:
            pair = f"{tokens[i]} {tokens[i + 1]}"
            # NOT NOT and AND NOT / OR NOT are technically adjacent but
            # AND NOT and OR NOT are valid Meltwater patterns.
            if tokens[i + 1] == "NOT" and tokens[i] in ("AND", "OR"):
                continue
            errors.append(f"Adjacent operators: '{pair}'")

    # -- Leading operator --
    if tokens and tokens[0] in ("AND", "OR"):
        errors.append(f"Query starts with operator '{tokens[0]}'")

    # -- Trailing operator --
    if tokens and tokens[-1] in operators:
        errors.append(f"Query ends with operator '{tokens[-1]}'")

    return errors


def _tokenise_query(query: str) -> list[str]:
    """Split a Boolean query into tokens, treating quoted phrases as single
    tokens and recognising parentheses as separate tokens."""
    tokens: list[str] = []
    i = 0
    n = len(query)
    while i < n:
        ch = query[i]
        if ch in " \t\n\r":
            i += 1
            continue
        if ch == '"':
            # Consume the entire quoted phrase as one token.
            j = query.find('"', i + 1)
            if j == -1:
                j = n  # unclosed quote -- take rest of string
            tokens.append(query[i : j + 1])
            i = j + 1
            continue
        if ch in "()":
            tokens.append(ch)
            i += 1
            continue
        # Consume a word token.
        j = i
        while j < n and query[j] not in ' \t\n\r()"':
            j += 1
        tokens.append(query[i:j])
        i = j
    return tokens


# --- Output validation ------------------------------------------------------------

def validate_output(data: dict) -> tuple[list[str], list[str]]:
    """Validate the structured output from the LLM.

    Returns (errors, warnings) -- errors are hard failures, warnings are
    advisory.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # -- Required top-level keys --
    for key in OUTPUT_SCHEMA["required_top_keys"]:
        if key not in data:
            errors.append(f"Missing required key '{key}'")

    # -- strategy_summary --
    if not data.get("strategy_summary"):
        errors.append("strategy_summary is empty")

    # -- query_modules --
    modules = data.get("query_modules", [])
    if not modules:
        errors.append("No query_modules defined")
    else:
        seen_ids: set[str] = set()
        for i, mod in enumerate(modules):
            for field in OUTPUT_SCHEMA["module_fields"]:
                if not mod.get(field):
                    errors.append(f"query_modules[{i}] missing '{field}'")
            mid = mod.get("module_id", "")
            if mid in seen_ids:
                errors.append(f"Duplicate module_id '{mid}'")
            elif mid:
                seen_ids.add(mid)

    # -- query_versions --
    versions = data.get("query_versions", {})
    for version_key in OUTPUT_SCHEMA["query_version_keys"]:
        version = versions.get(version_key, {})
        if not version:
            errors.append(f"Missing query version '{version_key}'")
            continue
        for field in OUTPUT_SCHEMA["query_version_fields"]:
            if not version.get(field):
                errors.append(
                    f"query_versions.{version_key} missing '{field}'")
        query_text = version.get("query", "")
        if query_text:
            syntax_errors = validate_boolean_syntax(query_text)
            for se in syntax_errors:
                errors.append(
                    f"query_versions.{version_key}: {se}")
            if len(query_text) > 4000:
                warnings.append(
                    f"query_versions.{version_key} exceeds 4000 characters "
                    f"({len(query_text)} chars)")
        noise = version.get("estimated_noise_level", "")
        if noise and noise not in OUTPUT_SCHEMA["noise_levels"]:
            warnings.append(
                f"query_versions.{version_key}.estimated_noise_level "
                f"'{noise}' is not one of {OUTPUT_SCHEMA['noise_levels']}")

    # -- research_question_queries --
    rq_queries = data.get("research_question_queries", [])
    if not rq_queries:
        warnings.append("No research_question_queries defined")
    else:
        for i, rqq in enumerate(rq_queries):
            for field in OUTPUT_SCHEMA["rq_query_fields"]:
                if not rqq.get(field):
                    errors.append(
                        f"research_question_queries[{i}] missing '{field}'")
            rq_query = rqq.get("query", "")
            if rq_query:
                syntax_errors = validate_boolean_syntax(rq_query)
                for se in syntax_errors:
                    errors.append(
                        f"research_question_queries[{i}]: {se}")

    # -- exclusion_strategy --
    exclusion = data.get("exclusion_strategy", {})
    if not exclusion.get("global_exclusions") and \
       not exclusion.get("exclusion_categories"):
        warnings.append("No exclusion terms defined in exclusion_strategy")

    # -- filter_recommendations --
    filters = data.get("filter_recommendations", {})
    if not filters:
        warnings.append("No filter_recommendations provided")

    # -- quality_assessment --
    quality = data.get("quality_assessment", {})
    if not quality:
        errors.append("Missing quality_assessment")
    else:
        lo, hi = OUTPUT_SCHEMA["quality_score_range"]
        for score_key in ("overall_score", "coverage_score", "precision_score"):
            score = quality.get(score_key)
            if score is None:
                errors.append(f"quality_assessment missing '{score_key}'")
            elif not isinstance(score, (int, float)) or not (lo <= score <= hi):
                warnings.append(
                    f"quality_assessment.{score_key} should be {lo}-{hi}, "
                    f"got {score}")

    return errors, warnings


# --- Response parsing -------------------------------------------------------------

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


# --- Agent runner -----------------------------------------------------------------

async def run(
    spec: dict,
    brand_intelligence: dict,
    *,
    emit: EventFn | None = None,
    ollama: OllamaClient | None = None,
) -> dict:
    """Execute the Meltwater Query Builder Agent.

    Parameters
    ----------
    spec : dict
        A validated ProjectSpecification (output of the Brief & Scope Agent).
    brand_intelligence : dict
        Brand intelligence context -- known aliases, products, competitors,
        and domain-specific terminology that should be incorporated into
        query construction.
    emit : EventFn, optional
        Callback for progress events.
    ollama : OllamaClient, optional
        LLM client for query generation.

    Returns
    -------
    dict
        Keys:
          queries : the validated query strategy dict
          validation_errors : list of remaining error strings
          validation_warnings : list of warning strings
          attempts : how many LLM calls were made
          elapsed_seconds : wall-clock time
    """
    if emit is None:
        emit = lambda event_type, payload: None

    if ollama is None:
        raise ValueError("OllamaClient is required for query generation")

    start = time.time()
    brand_name = _extract_brand_name(spec)
    rq_count = len(spec.get("research_questions", []))

    emit("query_builder_started", {
        "brand": brand_name,
        "research_questions": rq_count,
    })

    user_message = _build_user_prompt(spec, brand_intelligence)

    queries: dict | None = None
    all_errors: list[str] = []
    all_warnings: list[str] = []
    max_retries = 1
    attempt = 0

    for attempt in range(1, max_retries + 2):
        emit("query_builder_attempt", {"attempt": attempt})

        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        if attempt > 1 and queries is not None and all_errors:
            correction = _build_correction_prompt(all_errors)
            messages.append({"role": "assistant", "content": json.dumps(queries)})
            messages.append({"role": "user", "content": correction})

        emit("query_builder_reasoning", {
            "status": "LLM generating Boolean queries...",
        })

        try:
            raw_response = ollama.chat(
                messages,
                format_json=True,
            )
        except Exception as e:
            logger.error("[query_builder] LLM call failed: %s", e, exc_info=True)
            emit("query_builder_error", {"error": f"LLM call failed: {e}"})
            continue

        logger.info("[query_builder] LLM response length: %d chars, first 500: %s",
                     len(raw_response) if raw_response else 0,
                     (raw_response[:500] if raw_response else "(empty)"))

        try:
            queries = _extract_json(raw_response)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("[query_builder] JSON parse failed: %s — last 200 chars: %s",
                          e, raw_response[-200:] if raw_response else "(empty)")
            emit("query_builder_error", {"error": f"JSON parse failed: {e}"})
            continue

        _apply_defaults(queries, spec)

        all_errors, all_warnings = validate_output(queries)

        emit("query_builder_validated", {
            "attempt": attempt,
            "errors": len(all_errors),
            "warnings": len(all_warnings),
        })

        if not all_errors:
            break

    elapsed = round(time.time() - start, 1)

    if queries is None:
        emit("query_builder_failed", {"elapsed": elapsed})
        return {
            "queries": None,
            "validation_errors": all_errors,
            "validation_warnings": all_warnings,
            "attempts": attempt,
            "elapsed_seconds": elapsed,
        }

    queries["_meta"] = {
        "agent": "meltwater_query_builder",
        "version": "1.0.0",
        "attempts": attempt,
        "elapsed_seconds": elapsed,
        "errors": len(all_errors),
        "warnings": len(all_warnings),
        "brand": brand_name,
        "research_questions": rq_count,
    }

    emit("query_builder_complete", {
        "brand": brand_name,
        "modules": len(queries.get("query_modules", [])),
        "versions": list(queries.get("query_versions", {}).keys()),
        "rq_queries": len(queries.get("research_question_queries", [])),
        "quality_score": queries.get("quality_assessment", {}).get(
            "overall_score", None),
        "elapsed": elapsed,
    })

    return {
        "queries": queries,
        "validation_errors": all_errors,
        "validation_warnings": all_warnings,
        "attempts": attempt,
        "elapsed_seconds": elapsed,
    }


# --- Helpers ----------------------------------------------------------------------

def _extract_brand_name(spec: dict) -> str:
    """Pull the primary brand name from a ProjectSpecification."""
    cb = spec.get("commissioning_brand", {})
    if isinstance(cb, dict) and cb.get("name"):
        return cb["name"]
    for ent in spec.get("validated_entities", []):
        if ent.get("type") == "brand":
            return ent.get("name", "")
    brands = spec.get("included_scope", {}).get("brands", [])
    return brands[0] if brands else "Unknown"


def _build_user_prompt(spec: dict, brand_intelligence: dict) -> str:
    """Assemble the user-facing prompt from spec and brand context."""
    parts = [
        "Build a comprehensive Meltwater Boolean search strategy for the "
        "following project.\n",
    ]

    # Inject core spec sections the LLM needs.
    brand_name = _extract_brand_name(spec)
    parts.append(f"Brand: {brand_name}")

    rs = spec.get("research_subject", {})
    if rs.get("description"):
        parts.append(f"Research Subject: {rs['description']}")

    ra = spec.get("research_audience", {})
    if ra.get("description"):
        parts.append(f"Research Audience: {ra['description']}")

    # Research questions.
    rqs = spec.get("research_questions", [])
    if rqs:
        parts.append("\nResearch Questions:")
        for rq in rqs:
            qid = rq.get("question_id", "")
            q = rq.get("question", "")
            parts.append(f"  {qid}: {q}")

    # Scope details.
    scope = spec.get("included_scope", {})
    if scope.get("platforms"):
        parts.append(f"\nPlatforms: {', '.join(scope['platforms'])}")
    if scope.get("countries"):
        parts.append(f"Countries: {', '.join(scope['countries'])}")
    if scope.get("languages"):
        parts.append(f"Languages: {', '.join(scope['languages'])}")
    if scope.get("time_period"):
        parts.append(f"Time Period: {scope['time_period']}")
    if scope.get("competitors"):
        parts.append(f"Competitors: {', '.join(scope['competitors'])}")

    # Exclusions from brief scope.
    excluded = spec.get("excluded_scope", [])
    if excluded:
        parts.append("\nExcluded from scope:")
        for entry in excluded:
            if isinstance(entry, dict):
                parts.append(f"  - {entry.get('item', '')}")
            elif isinstance(entry, str):
                parts.append(f"  - {entry}")

    # Brand intelligence context.
    if brand_intelligence:
        parts.append("\n--- BRAND INTELLIGENCE ---")
        if brand_intelligence.get("aliases"):
            parts.append(
                f"Known aliases: {', '.join(brand_intelligence['aliases'])}")
        if brand_intelligence.get("products"):
            parts.append(
                f"Products: {', '.join(brand_intelligence['products'])}")
        if brand_intelligence.get("industry_terms"):
            parts.append(
                f"Industry terms: "
                f"{', '.join(brand_intelligence['industry_terms'])}")
        if brand_intelligence.get("common_misspellings"):
            parts.append(
                f"Common misspellings: "
                f"{', '.join(brand_intelligence['common_misspellings'])}")

    return "\n".join(parts)


def _build_correction_prompt(errors: list[str]) -> str:
    """Build a correction prompt from validation errors."""
    lines = [
        "Your previous response had validation errors.  Fix these specific "
        "problems and return the corrected JSON:\n",
    ]
    for error in errors:
        lines.append(f"  ERROR: {error}")
    lines.append("\nReturn the complete corrected JSON.")
    return "\n".join(lines)


def _apply_defaults(queries: dict, spec: dict) -> None:
    """Fill in structural defaults the LLM may have omitted."""
    if "strategy_summary" not in queries:
        queries["strategy_summary"] = ""

    if "query_modules" not in queries:
        queries["query_modules"] = []

    if "query_versions" not in queries:
        queries["query_versions"] = {}
    for version_key in ("broad", "balanced", "precise"):
        if version_key not in queries["query_versions"]:
            queries["query_versions"][version_key] = {
                "query": "",
                "description": "",
                "estimated_noise_level": "",
                "use_case": "",
            }

    if "research_question_queries" not in queries:
        queries["research_question_queries"] = []

    if "exclusion_strategy" not in queries:
        queries["exclusion_strategy"] = {
            "global_exclusions": "",
            "rationale": "",
            "exclusion_categories": [],
        }

    if "filter_recommendations" not in queries:
        # Pull defaults from the spec's included_scope.
        scope = spec.get("included_scope", {})
        queries["filter_recommendations"] = {
            "date_range": scope.get("time_period", ""),
            "geography": scope.get("countries", []),
            "language": scope.get("languages", []),
            "source_types": [],
            "platforms": scope.get("platforms", []),
            "additional_filters": [],
        }

    if "quality_assessment" not in queries:
        queries["quality_assessment"] = {
            "overall_score": 1,
            "coverage_score": 1,
            "precision_score": 1,
            "potential_gaps": ["Auto-defaulted -- LLM did not provide assessment"],
            "potential_noise": [],
            "recommendations": [],
        }
