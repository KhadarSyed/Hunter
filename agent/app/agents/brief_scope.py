"""Brief & Scope Agent — converts a raw client brief into a validated
ProjectSpecification before any research begins.

This agent uses the LLM to deeply understand the brief, disambiguate entities,
separate objectives, define scope boundaries, and self-validate.  It NEVER
performs research — only interpretation and structuring.

v2.0.0 — Fixes from live test:
  1. Commissioning brand vs research subject distinction
  2. Canonical research_questions array with IDs
  3. Structured audience segments
  4. Normalized excluded_scope with individual items
  5. Sentiment-scoring conflict detection
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Optional

from ..ollama_client import OllamaClient

EventFn = Callable[[str, dict], None]


# ─── System prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are the Brief & Scope Agent for a PR and social intelligence research firm.
Your job: read a client brief and return a structured Project Specification as JSON.
You do NOT research. You only interpret what the client is asking.

━━━ RULES ━━━

1. NEVER interpret entity names literally or by splitting words.
   "Mrs. T's" = Mrs. T's Pierogies brand, NOT the word "Mrs".
   Always preserve full names including punctuation and possessives.

2. NEVER add analyses the brief did not request.
   If the brief says nothing about "Share of Voice", do NOT include it.

3. NEVER confuse audience with competitor.
   "Moms" as a demographic = audience, NOT a competitor brand.

4. Distinguish FOUR roles:
   COMMISSIONING BRAND: the brand paying for the research
   RESEARCH SUBJECT: what the research is actually about (may be the brand, may be broader)
   RESEARCH AUDIENCE: the people whose conversations are analyzed
   STRATEGIC APPLICATION: how findings will be used

   The commissioning brand is NOT always the research subject.
   Example: Brand "Mrs. T's" commissions a study. The research subject is "broader social conversations among moms about food, priorities, and tensions." Mrs. T's is context, not the subject of every question.
   If the brief says the study is NOT about the brand itself, frame research questions around the audience and their conversations, NOT around the brand's products.

5. Default these to EXCLUDED unless the brief explicitly requests them:
   Share of Voice, Sentiment Analysis / Sentiment Scoring, Competitive Benchmarking,
   Brand Perception, Editorial Coverage, Owned Content Audit,
   Generic Market Overview, Demographic Breakdown.

6. Distinguish QUALITATIVE TONE from FORMAL SENTIMENT:
   ALLOWED (qualitative): identifying frustrations, anxieties, trade-offs, resolutions, emotional context, tension analysis
   NOT ALLOWED unless requested: positive/neutral/negative percentages, net sentiment, automated sentiment scoring, sentiment comparison charts, quantified sentiment claims
   If sentiment is excluded, do NOT mention "sentiment scoring" in the methodology.

7. If the brief requests COMPARING audience sub-groups, list each as a separate segment.

━━━ ENTITY VALIDATION ━━━

For every named entity, provide:
- type: one of brand, competitor, audience, category, topic, campaign, product, executive, geography
- confidence: high / medium / low
- alternatives_considered: other possible interpretations (REQUIRED)
- reasoning: why your interpretation is correct and others are wrong

Example:
Brief says "Conduct analysis for Mrs. T's with focus on Mom's"
Entity "Mrs. T's":
  type: brand, confidence: high
  alternatives_considered: ["honorific Mrs.", "movie Mrs.", "grammar term"]
  reasoning: "Mrs. T's with possessive apostrophe is a frozen food brand, not the word Mrs"
Entity "Moms":
  type: audience, confidence: high
  alternatives_considered: ["competitor brand", "product line"]
  reasoning: "Moms refers to mothers as the research audience, not a brand"

━━━ OUTPUT FORMAT ━━━

Return ONLY a JSON object with these exact keys:

{
  "executive_interpretation": "2-3 sentence summary of what the client actually wants",
  "commissioning_brand": {
    "name": "brand paying for the research",
    "role": "why this brand commissioned this study"
  },
  "research_subject": {
    "description": "what the research is actually about — may differ from the brand",
    "is_brand_study": false
  },
  "research_audience": {
    "description": "whose conversations or behaviors are being studied"
  },
  "strategic_application": "how findings will be used by the commissioning brand",
  "business_objective": "the business problem being solved",
  "research_objective": "one-sentence summary of the research goal",
  "deliverable_objective": "what must be produced and in what format",
  "validated_entities": [
    {
      "name": "exact name from brief",
      "type": "brand|competitor|audience|category|topic|campaign|product|executive|geography",
      "confidence": "high|medium|low",
      "alternatives_considered": ["other interpretations considered"],
      "reasoning": "why this interpretation is correct"
    }
  ],
  "research_questions": [
    {
      "question_id": "RQ1",
      "question": "the research question",
      "source": "explicit or implicit",
      "priority": "primary or secondary",
      "required": true
    }
  ],
  "included_scope": {
    "brands": ["brand(s) involved"],
    "primary_audience": {
      "name": "main audience group",
      "geography": "country"
    },
    "audience_segments": [
      {
        "segment_id": "A1",
        "name": "segment name",
        "role": "comparison segment or primary"
      }
    ],
    "competitors": [],
    "platforms": ["platforms to cover"],
    "countries": ["geographic scope"],
    "languages": ["language scope"],
    "time_period": "date range",
    "content_types": ["types of content"],
    "expected_analyses": [],
    "deliverables": ["artifacts to produce"]
  },
  "excluded_scope": [
    {
      "item": "analysis or approach excluded",
      "reason": "why it is excluded",
      "severity": "hard exclusion"
    }
  ],
  "missing_information": [
    {
      "item": "what is missing",
      "why_it_matters": "impact",
      "can_proceed_without": true,
      "assumption_if_missing": "default assumption",
      "confidence": "high|medium|low"
    }
  ],
  "assumptions": [
    {
      "assumption": "what you assume",
      "why_it_matters": "why it matters",
      "confidence": "high|medium|low"
    }
  ],
  "recommended_methodology": {
    "primary": "main approach — do NOT include sentiment scoring if sentiment is excluded",
    "reasoning": "why this fits",
    "alternatives_considered": [
      {"method": "alternative", "why_less_appropriate": "reason"}
    ]
  },
  "risks": [
    {"risk": "what could go wrong", "severity": "high|medium|low", "mitigation": "how to reduce"}
  ],
  "success_criteria": [
    "measurable questions the output must answer — NOT slide counts"
  ],
  "confidence_assessment": {
    "overall": "high|medium|low",
    "entity_confidence": "high|medium|low",
    "scope_confidence": "high|medium|low",
    "methodology_confidence": "high|medium|low",
    "reasoning": "explanation"
  },
  "self_validation": {
    "correct_entity": {"answer": true, "reasoning": "why"},
    "correct_audience": {"answer": true, "reasoning": "why"},
    "audience_not_confused_with_competitor": {"answer": true, "reasoning": "why"},
    "no_unrequested_analyses": {"answer": true, "reasoning": "why"},
    "assumptions_documented": {"answer": true, "reasoning": "why"},
    "would_prevent_mrs_ts_failure": {"answer": true, "reasoning": "why"}
  }
}
"""


# ─── Schema definition (for programmatic validation) ────────────────────────

ENTITY_TYPES = frozenset({
    "brand", "competitor", "audience", "category", "topic",
    "campaign", "product", "executive", "geography",
})

CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})

REQUIRED_TOP_KEYS = [
    "executive_interpretation",
    "commissioning_brand",
    "research_subject",
    "research_audience",
    "strategic_application",
    "business_objective",
    "research_objective",
    "deliverable_objective",
    "validated_entities",
    "research_questions",
    "included_scope",
    "excluded_scope",
    "missing_information",
    "assumptions",
    "recommended_methodology",
    "risks",
    "success_criteria",
    "confidence_assessment",
    "self_validation",
]

INCLUDED_SCOPE_KEYS = [
    "brands", "primary_audience", "audience_segments", "competitors",
    "platforms", "countries", "languages", "time_period", "content_types",
    "expected_analyses", "deliverables",
]

SELF_VALIDATION_KEYS = [
    "correct_entity",
    "correct_audience",
    "audience_not_confused_with_competitor",
    "no_unrequested_analyses",
    "assumptions_documented",
    "would_prevent_mrs_ts_failure",
]

SENTIMENT_TERMS = re.compile(
    r"sentiment\s*(?:scor|analys|percentag|comparison|chart|quantif|net\s+sentiment)",
    re.IGNORECASE,
)

EXCLUDED_ANALYSIS_KEYWORDS = {
    "share of voice", "sentiment analysis", "sentiment scoring",
    "competitive benchmarking", "brand perception", "editorial coverage",
    "owned content audit", "market overview", "demographic breakdown",
}


# ─── Response parsing ────────────────────────────────────────────────────────

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


# ─── Programmatic validation ─────────────────────────────────────────────────

class ValidationError:
    """One specific problem found during spec validation."""
    def __init__(self, field: str, message: str, severity: str = "error"):
        self.field = field
        self.message = message
        self.severity = severity

    def __repr__(self) -> str:
        return f"[{self.severity.upper()}] {self.field}: {self.message}"


def validate_spec(spec: dict, brief_text: str) -> list[ValidationError]:
    """Run programmatic checks on a ProjectSpecification dict."""
    errors: list[ValidationError] = []

    for key in REQUIRED_TOP_KEYS:
        if key not in spec:
            errors.append(ValidationError(key, f"Missing required key '{key}'"))

    if not spec.get("executive_interpretation"):
        errors.append(ValidationError(
            "executive_interpretation", "Empty — must summarize client intent"))

    if not spec.get("business_objective"):
        errors.append(ValidationError(
            "business_objective", "Empty — must state the business problem"))

    _validate_brand_subject_audience(spec, errors)
    _validate_entities(spec, errors)
    _validate_research_questions(spec, brief_text, errors)
    _validate_audience_segments(spec, brief_text, errors)
    _validate_scope(spec, errors)
    _validate_excluded_scope(spec, errors)
    _validate_methodology(spec, errors)
    _validate_success_criteria(spec, errors)
    _validate_self_validation(spec, errors)
    _cross_validate_against_brief(spec, brief_text, errors)
    _validate_exclusion_conflicts(spec, errors)

    return errors


def _validate_brand_subject_audience(
    spec: dict, errors: list[ValidationError]
) -> None:
    cb = spec.get("commissioning_brand", {})
    if not cb or not cb.get("name"):
        errors.append(ValidationError(
            "commissioning_brand.name",
            "Missing commissioning brand name"))

    rs = spec.get("research_subject", {})
    if not rs or not rs.get("description"):
        errors.append(ValidationError(
            "research_subject.description",
            "Missing research subject description"))

    ra = spec.get("research_audience", {})
    if not ra or not ra.get("description"):
        errors.append(ValidationError(
            "research_audience.description",
            "Missing research audience description"))


def _validate_entities(spec: dict, errors: list[ValidationError]) -> None:
    entities = spec.get("validated_entities", [])
    if not entities:
        errors.append(ValidationError(
            "validated_entities",
            "No entities found — every brief has at least one brand"))
        return

    has_brand = False
    for i, ent in enumerate(entities):
        etype = ent.get("type", "")
        if etype not in ENTITY_TYPES:
            errors.append(ValidationError(
                f"validated_entities[{i}].type",
                f"Invalid entity type '{etype}'"))
        if etype == "brand":
            has_brand = True
        conf = ent.get("confidence", "")
        if conf not in CONFIDENCE_LEVELS:
            errors.append(ValidationError(
                f"validated_entities[{i}].confidence",
                f"Invalid confidence '{conf}'"))
        if not ent.get("reasoning"):
            errors.append(ValidationError(
                f"validated_entities[{i}].reasoning",
                "Entity must have reasoning for its classification"))
        if not ent.get("alternatives_considered"):
            errors.append(ValidationError(
                f"validated_entities[{i}].alternatives_considered",
                "Entity must list alternative interpretations considered",
                severity="warning"))
    if not has_brand:
        errors.append(ValidationError(
            "validated_entities",
            "No entity typed as 'brand' — every brief has a primary brand"))


def _validate_research_questions(
    spec: dict, brief_text: str, errors: list[ValidationError]
) -> None:
    rqs = spec.get("research_questions", [])
    if not rqs:
        errors.append(ValidationError(
            "research_questions",
            "No research questions — the research has no direction"))
        return

    brief_questions = _extract_brief_questions(brief_text)
    if brief_questions and len(rqs) < len(brief_questions):
        errors.append(ValidationError(
            "research_questions",
            f"Brief has {len(brief_questions)} explicit questions but only "
            f"{len(rqs)} research questions defined — questions may have been "
            f"merged inappropriately",
            severity="warning"))

    seen_ids = set()
    for i, rq in enumerate(rqs):
        if not isinstance(rq, dict):
            errors.append(ValidationError(
                f"research_questions[{i}]",
                "Research question must be a structured object with question_id, "
                "question, source, priority, required"))
            continue
        qid = rq.get("question_id", "")
        if not qid:
            errors.append(ValidationError(
                f"research_questions[{i}].question_id",
                "Missing question_id"))
        elif qid in seen_ids:
            errors.append(ValidationError(
                f"research_questions[{i}].question_id",
                f"Duplicate question_id '{qid}'"))
        else:
            seen_ids.add(qid)
        if not rq.get("question"):
            errors.append(ValidationError(
                f"research_questions[{i}].question",
                "Empty question text"))
        source = rq.get("source", "")
        if source and source not in ("explicit", "implicit"):
            errors.append(ValidationError(
                f"research_questions[{i}].source",
                f"Source must be 'explicit' or 'implicit', got '{source}'",
                severity="warning"))
        prio = rq.get("priority", "")
        if prio and prio not in ("primary", "secondary"):
            errors.append(ValidationError(
                f"research_questions[{i}].priority",
                f"Priority must be 'primary' or 'secondary', got '{prio}'",
                severity="warning"))


def _validate_audience_segments(
    spec: dict, brief_text: str, errors: list[ValidationError]
) -> None:
    scope = spec.get("included_scope", {})
    primary = scope.get("primary_audience", {})
    if not primary or not primary.get("name"):
        errors.append(ValidationError(
            "included_scope.primary_audience.name",
            "Missing primary audience name"))

    segments = scope.get("audience_segments", [])
    brief_lower = brief_text.lower()
    comparison_signals = [
        "versus", "compared to", "different for", "differ between",
        "young children", "older children", "teenagers", "compare",
    ]
    has_comparison = any(s in brief_lower for s in comparison_signals)

    if has_comparison and len(segments) < 2:
        errors.append(ValidationError(
            "included_scope.audience_segments",
            "Brief requests audience comparison but fewer than 2 segments defined",
            severity="warning"))

    seen_ids = set()
    for i, seg in enumerate(segments):
        sid = seg.get("segment_id", "")
        if sid in seen_ids:
            errors.append(ValidationError(
                f"audience_segments[{i}].segment_id",
                f"Duplicate segment_id '{sid}'"))
        elif sid:
            seen_ids.add(sid)
        if not seg.get("name"):
            errors.append(ValidationError(
                f"audience_segments[{i}].name",
                "Missing segment name"))


def _validate_scope(spec: dict, errors: list[ValidationError]) -> None:
    scope = spec.get("included_scope", {})
    if not scope.get("brands"):
        errors.append(ValidationError(
            "included_scope.brands", "No brands in scope — at least one required"))


def _validate_excluded_scope(
    spec: dict, errors: list[ValidationError]
) -> None:
    excluded = spec.get("excluded_scope", [])
    if not excluded:
        errors.append(ValidationError(
            "excluded_scope",
            "Empty exclusion list — must explicitly state what is NOT in scope",
            severity="warning"))
        return

    seen_items = set()
    for i, entry in enumerate(excluded):
        if isinstance(entry, str):
            if "," in entry and len(entry) > 60:
                errors.append(ValidationError(
                    f"excluded_scope[{i}]",
                    "Comma-separated exclusion string detected — each exclusion "
                    "must be a separate structured object with item, reason, severity"))
            continue
        if isinstance(entry, dict):
            item = entry.get("item", "")
            if not item:
                errors.append(ValidationError(
                    f"excluded_scope[{i}].item",
                    "Missing exclusion item name"))
            item_lower = item.lower()
            if item_lower in seen_items:
                errors.append(ValidationError(
                    f"excluded_scope[{i}]",
                    f"Duplicate exclusion: '{item}'"))
            else:
                seen_items.add(item_lower)
            if not entry.get("reason"):
                errors.append(ValidationError(
                    f"excluded_scope[{i}].reason",
                    "Missing exclusion reason",
                    severity="warning"))


def _validate_methodology(spec: dict, errors: list[ValidationError]) -> None:
    methodology = spec.get("recommended_methodology", {})
    if not methodology.get("primary"):
        errors.append(ValidationError(
            "recommended_methodology.primary",
            "No primary methodology recommended"))
    if not methodology.get("reasoning"):
        errors.append(ValidationError(
            "recommended_methodology.reasoning",
            "Methodology recommendation has no reasoning"))


def _validate_success_criteria(
    spec: dict, errors: list[ValidationError]
) -> None:
    criteria = spec.get("success_criteria", [])
    if not criteria:
        errors.append(ValidationError(
            "success_criteria",
            "No success criteria — cannot measure completion without them"))
        return
    slide_count_pattern = re.compile(r"\d+.?slide", re.IGNORECASE)
    for i, c in enumerate(criteria):
        if isinstance(c, str) and slide_count_pattern.search(c):
            errors.append(ValidationError(
                f"success_criteria[{i}]",
                "Success criteria should measure answering business questions, "
                "not slide counts",
                severity="warning"))


def _validate_self_validation(
    spec: dict, errors: list[ValidationError]
) -> None:
    validation = spec.get("self_validation", {})
    for key in SELF_VALIDATION_KEYS:
        entry = validation.get(key, {})
        if not entry:
            errors.append(ValidationError(
                f"self_validation.{key}", "Missing self-validation check"))
        elif not entry.get("reasoning"):
            errors.append(ValidationError(
                f"self_validation.{key}",
                "Self-validation check has no reasoning",
                severity="warning"))


def _cross_validate_against_brief(
    spec: dict, brief_text: str, errors: list[ValidationError]
) -> None:
    """Check the spec against the original brief for consistency."""
    brief_lower = brief_text.lower()

    scope = spec.get("included_scope", {})
    expected_analyses = scope.get("expected_analyses", [])
    unrequested_defaults = {
        "share of voice": "Share of Voice",
        "sentiment analysis": "Sentiment",
        "competitive benchmarking": "Competitive Benchmarking",
        "brand perception": "Brand Perception",
        "editorial coverage": "Editorial Coverage",
    }
    for keyword, label in unrequested_defaults.items():
        if keyword not in brief_lower:
            for analysis in expected_analyses:
                if isinstance(analysis, str) and keyword in analysis.lower():
                    errors.append(ValidationError(
                        "included_scope.expected_analyses",
                        f"'{label}' included but the brief never mentions it",
                        severity="warning"))

    brands = scope.get("brands", [])
    for brand in brands:
        if brand.lower() in brief_lower:
            continue
        parts = brand.lower().split()
        if not any(p in brief_lower for p in parts if len(p) > 3):
            errors.append(ValidationError(
                "included_scope.brands",
                f"Brand '{brand}' does not appear in the brief text",
                severity="warning"))

    competitors = scope.get("competitors", [])
    primary_aud = scope.get("primary_audience", {})
    aud_name = (primary_aud.get("name", "") if isinstance(primary_aud, dict)
                else str(primary_aud)).lower()
    for comp in competitors:
        if isinstance(comp, str) and comp.lower() == aud_name:
            errors.append(ValidationError(
                "included_scope",
                f"'{comp}' appears as both audience and competitor — "
                f"these are mutually exclusive categories"))


def _validate_exclusion_conflicts(
    spec: dict, errors: list[ValidationError]
) -> None:
    """If an analysis appears in excluded_scope, it cannot appear in
    methodology, expected_analyses, or success_criteria."""
    excluded_items = set()
    for entry in spec.get("excluded_scope", []):
        if isinstance(entry, dict):
            item = entry.get("item", "").lower()
        elif isinstance(entry, str):
            item = entry.lower()
        else:
            continue
        for kw in EXCLUDED_ANALYSIS_KEYWORDS:
            if kw in item:
                excluded_items.add(kw)

    methodology_text = (
        spec.get("recommended_methodology", {}).get("primary", "")
    ).lower()
    for excl in excluded_items:
        if excl in methodology_text:
            errors.append(ValidationError(
                "recommended_methodology.primary",
                f"'{excl}' appears in methodology but is in excluded_scope — "
                f"these conflict"))

    if "sentiment" in " ".join(excluded_items):
        if SENTIMENT_TERMS.search(methodology_text):
            errors.append(ValidationError(
                "recommended_methodology.primary",
                "Methodology mentions sentiment scoring but sentiment is excluded"))

    scope = spec.get("included_scope", {})
    for analysis in scope.get("expected_analyses", []):
        if isinstance(analysis, str):
            for excl in excluded_items:
                if excl in analysis.lower():
                    errors.append(ValidationError(
                        "included_scope.expected_analyses",
                        f"'{analysis}' is in expected_analyses but also in "
                        f"excluded_scope — direct conflict"))

    for i, criterion in enumerate(spec.get("success_criteria", [])):
        if isinstance(criterion, str):
            for excl in excluded_items:
                if excl in criterion.lower():
                    errors.append(ValidationError(
                        f"success_criteria[{i}]",
                        f"References '{excl}' which is in excluded_scope"))


# ─── Agent runner ─────────────────────────────────────────────────────────────

def run(
    brief_text: str,
    client: OllamaClient,
    emit: Optional[EventFn] = None,
    brief_filename: str = "",
    max_retries: int = 2,
) -> dict:
    """Execute the Brief & Scope Agent.

    Returns a dict with keys:
      spec: the validated ProjectSpecification
      validation_errors: list of remaining warnings (errors cause retry)
      attempts: how many LLM calls were made
      elapsed_seconds: wall-clock time
    """
    if emit is None:
        emit = lambda event_type, payload: None

    start = time.time()
    emit("brief_scope_started", {
        "brief_length": len(brief_text),
        "filename": brief_filename,
    })

    user_message = _build_user_prompt(brief_text, brief_filename)

    spec = None
    all_errors: list[ValidationError] = []
    attempt = 0

    for attempt in range(1, max_retries + 2):
        emit("brief_scope_attempt", {"attempt": attempt})

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        if attempt > 1 and all_errors:
            correction = _build_correction_prompt(all_errors)
            messages.append({"role": "assistant", "content": json.dumps(spec)})
            messages.append({"role": "user", "content": correction})

        emit("brief_scope_reasoning", {"status": "LLM analyzing brief..."})

        try:
            raw_response = client.chat(
                messages,
                on_token=lambda t: None,
                format_json=True,
            )
        except Exception as e:
            emit("brief_scope_error", {"error": f"LLM call failed: {e}"})
            continue

        try:
            spec = _extract_json(raw_response)
        except (json.JSONDecodeError, ValueError) as e:
            emit("brief_scope_error", {"error": f"JSON parse failed: {e}"})
            continue

        _apply_defaults(spec)
        _normalize_excluded_scope(spec)
        _auto_populate_exclusions(spec, brief_text)
        _normalize_research_questions(spec)
        _supplement_research_questions(spec, brief_text)
        _normalize_audience_segments(spec, brief_text)

        all_errors = validate_spec(spec, brief_text)
        hard_errors = [e for e in all_errors if e.severity == "error"]

        emit("brief_scope_validated", {
            "attempt": attempt,
            "errors": len(hard_errors),
            "warnings": len(all_errors) - len(hard_errors),
        })

        if not hard_errors:
            break

    elapsed = round(time.time() - start, 1)

    if spec is None:
        emit("brief_scope_failed", {"elapsed": elapsed})
        return {
            "spec": None,
            "validation_errors": [repr(e) for e in all_errors],
            "attempts": attempt,
            "elapsed_seconds": elapsed,
        }

    spec["_meta"] = {
        "agent": "brief_scope",
        "version": "2.0.0",
        "attempts": attempt,
        "elapsed_seconds": elapsed,
        "hard_errors": len([e for e in all_errors if e.severity == "error"]),
        "warnings": len([e for e in all_errors if e.severity == "warning"]),
        "brief_filename": brief_filename,
    }

    emit("brief_scope_complete", {
        "client": _extract_primary_brand(spec),
        "methodology": spec.get("recommended_methodology", {}).get("primary", ""),
        "entity_count": len(spec.get("validated_entities", [])),
        "research_questions": len(spec.get("research_questions", [])),
        "confidence": spec.get("confidence_assessment", {}).get("overall", ""),
        "elapsed": elapsed,
    })

    return {
        "spec": spec,
        "validation_errors": [repr(e) for e in all_errors],
        "attempts": attempt,
        "elapsed_seconds": elapsed,
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_user_prompt(brief_text: str, filename: str) -> str:
    parts = ["Analyze this client brief and return a Project Specification as JSON.\n"]
    if filename:
        parts.append(f"Filename: {filename}\n")
    parts.append(f"--- BRIEF START ---\n{brief_text}\n--- BRIEF END ---")
    return "\n".join(parts)


def _build_correction_prompt(errors: list[ValidationError]) -> str:
    lines = [
        "Your previous response had validation errors. Fix these specific problems "
        "and return the corrected JSON:\n"
    ]
    for e in errors:
        if e.severity == "error":
            lines.append(f"  ERROR in {e.field}: {e.message}")
    lines.append("\nReturn the complete corrected JSON.")
    return "\n".join(lines)


def _apply_defaults(spec: dict) -> None:
    """Fill in structural defaults the LLM may have omitted."""
    if "commissioning_brand" not in spec:
        spec["commissioning_brand"] = {"name": "", "role": ""}
    if "research_subject" not in spec:
        spec["research_subject"] = {"description": "", "is_brand_study": False}
    if "research_audience" not in spec:
        spec["research_audience"] = {"description": ""}
    if "strategic_application" not in spec:
        spec["strategic_application"] = ""

    if "research_questions" not in spec:
        spec["research_questions"] = []

    if "included_scope" not in spec:
        spec["included_scope"] = {}
    scope = spec["included_scope"]
    for key in INCLUDED_SCOPE_KEYS:
        if key not in scope:
            if key == "time_period":
                scope[key] = ""
            elif key == "primary_audience":
                scope[key] = {"name": "", "geography": ""}
            elif key == "audience_segments":
                scope[key] = []
            else:
                scope[key] = []

    if "excluded_scope" not in spec:
        spec["excluded_scope"] = []
    if "missing_information" not in spec:
        spec["missing_information"] = []
    if "assumptions" not in spec:
        spec["assumptions"] = []
    if "risks" not in spec:
        spec["risks"] = []
    if "success_criteria" not in spec:
        spec["success_criteria"] = []

    if "confidence_assessment" not in spec:
        spec["confidence_assessment"] = {
            "overall": "low", "entity_confidence": "low",
            "scope_confidence": "low", "methodology_confidence": "low",
            "reasoning": "Auto-defaulted — LLM did not provide assessment",
        }

    if "self_validation" not in spec:
        spec["self_validation"] = {}
    for key in SELF_VALIDATION_KEYS:
        if key not in spec["self_validation"]:
            spec["self_validation"][key] = {
                "answer": False,
                "reasoning": "Not evaluated — LLM omitted this check",
            }


def _normalize_excluded_scope(spec: dict) -> None:
    """Convert flat strings or comma-separated entries into structured objects."""
    raw = spec.get("excluded_scope", [])
    normalized = []
    for entry in raw:
        if isinstance(entry, dict) and "item" in entry:
            normalized.append(entry)
        elif isinstance(entry, str):
            if "," in entry and len(entry) > 60:
                parts = [p.strip() for p in entry.split(",") if p.strip()]
                for part in parts:
                    normalized.append({
                        "item": part,
                        "reason": "Not requested in the brief",
                        "severity": "hard exclusion",
                    })
            else:
                normalized.append({
                    "item": entry,
                    "reason": "Not requested in the brief",
                    "severity": "hard exclusion",
                })
    spec["excluded_scope"] = normalized


def _normalize_research_questions(spec: dict) -> None:
    """If the LLM put questions as plain strings, convert to structured format.
    Also pull any questions from included_scope.research_questions into the
    canonical top-level array.  Normalizes source/priority to lowercase enums."""
    rqs = spec.get("research_questions", [])
    scope_rqs = spec.get("included_scope", {}).get("research_questions", [])

    existing_texts = set()
    normalized = []
    counter = 1

    for rq in rqs:
        if isinstance(rq, dict) and "question" in rq:
            if not rq.get("question_id"):
                rq["question_id"] = f"RQ{counter}"
            rq.setdefault("source", "explicit")
            rq.setdefault("priority", "primary")
            rq.setdefault("required", True)
            rq["source"] = _normalize_enum(
                rq["source"], {"explicit", "implicit"}, "explicit")
            rq["priority"] = _normalize_enum(
                rq["priority"], {"primary", "secondary"}, "primary")
            existing_texts.add(rq["question"].lower().strip())
            normalized.append(rq)
            counter += 1
        elif isinstance(rq, str) and rq.strip():
            existing_texts.add(rq.lower().strip())
            normalized.append({
                "question_id": f"RQ{counter}",
                "question": rq.strip(),
                "source": "explicit",
                "priority": "primary",
                "required": True,
            })
            counter += 1

    for sq in scope_rqs:
        text = sq if isinstance(sq, str) else sq.get("question", "")
        if text.lower().strip() not in existing_texts:
            existing_texts.add(text.lower().strip())
            normalized.append({
                "question_id": f"RQ{counter}",
                "question": text.strip(),
                "source": "explicit",
                "priority": "primary",
                "required": True,
            })
            counter += 1

    spec["research_questions"] = normalized
    if "included_scope" in spec:
        spec["included_scope"].pop("research_questions", None)


def _normalize_enum(value: str, allowed: set, default: str) -> str:
    """Map a verbose LLM value to its closest enum match."""
    low = value.strip().lower()
    if low in allowed:
        return low
    for a in allowed:
        if a in low:
            return a
    return default


def _auto_populate_exclusions(spec: dict, brief_text: str) -> None:
    """Ensure excluded_scope contains all items the brief explicitly rules out.
    Adds missing exclusions even when the LLM already provided some."""
    brief_lower = brief_text.lower()
    exclusion_signals = [
        "not primarily", "not a", "do not", "does not include",
        "is not", "excluded", "out of scope", "should not",
    ]
    has_exclusion_language = any(s in brief_lower for s in exclusion_signals)
    if not has_exclusion_language:
        return

    existing = spec.get("excluded_scope", [])
    existing_items = set()
    for entry in existing:
        if isinstance(entry, dict):
            existing_items.add(entry.get("item", "").lower())
        elif isinstance(entry, str):
            existing_items.add(entry.lower())

    defaults = [
        ("Share of Voice", "share of voice",
         "Brief explicitly states this is not in scope"),
        ("Competitor benchmarking", "competitor",
         "Brief explicitly states this is not in scope"),
        ("Brand sentiment", "sentiment",
         "Brief explicitly states this is not a brand-sentiment study"),
        ("Brand perception analysis", "brand-tracking",
         "Brief explicitly states this is not a brand-tracking study"),
        ("Editorial or news coverage", None,
         "Not requested in the brief"),
        ("Generic food and beverage market analysis", None,
         "Not requested in the brief"),
        ("Unsupported demographic claims", None,
         "Not supported without evidence"),
        ("Unsupported quantitative metrics", None,
         "Not supported without evidence"),
        ("Charts without underlying data", None,
         "Not supported without evidence"),
    ]

    for item, keyword, reason in defaults:
        if item.lower() in existing_items:
            continue
        for existing_text in existing_items:
            if item.lower() in existing_text or existing_text in item.lower():
                break
        else:
            if keyword is None or keyword in brief_lower:
                existing.append({
                    "item": item,
                    "reason": reason,
                    "severity": "hard exclusion",
                })

    spec["excluded_scope"] = existing


def _extract_brief_questions(brief_text: str) -> list[str]:
    """Extract explicit questions from the brief (bullet points ending with ?)."""
    questions = []
    for line in brief_text.splitlines():
        stripped = line.strip()
        stripped = re.sub(r"^[\*\-\d\.]+\s*", "", stripped)
        if stripped.endswith("?"):
            questions.append(stripped)
    return questions


def _supplement_research_questions(spec: dict, brief_text: str) -> None:
    """If the LLM merged brief questions, extract explicit questions from the
    brief and add any that aren't covered by existing research questions."""
    brief_questions = _extract_brief_questions(brief_text)
    if not brief_questions:
        return

    existing_rqs = spec.get("research_questions", [])
    if len(existing_rqs) >= len(brief_questions):
        return

    existing_texts = set()
    for rq in existing_rqs:
        if isinstance(rq, dict):
            existing_texts.add(rq.get("question", "").lower().strip().rstrip("?"))

    counter = len(existing_rqs) + 1
    for bq in brief_questions:
        bq_normalized = bq.lower().strip().rstrip("?")
        bq_words = set(bq_normalized.split())
        covered = False
        for et in existing_texts:
            et_words = set(et.split())
            overlap = len(bq_words & et_words)
            if overlap >= len(bq_words) * 0.6 or overlap >= len(et_words) * 0.6:
                covered = True
                break
        if not covered:
            existing_rqs.append({
                "question_id": f"RQ{counter}",
                "question": bq,
                "source": "explicit",
                "priority": "primary",
                "required": True,
            })
            existing_texts.add(bq_normalized)
            counter += 1

    spec["research_questions"] = existing_rqs


def _normalize_audience_segments(spec: dict, brief_text: str) -> None:
    """When the brief requests comparison between audience groups but the LLM
    combined them into a single segment, split them."""
    scope = spec.get("included_scope", {})
    segments = scope.get("audience_segments", [])

    brief_lower = brief_text.lower()
    comparison_signals = [
        "young children", "older children", "teenagers",
        "versus", "compared to", "different for",
    ]
    has_comparison = sum(1 for s in comparison_signals if s in brief_lower) >= 2

    if not has_comparison or len(segments) >= 2:
        return

    young_terms = ["young children", "young kids", "little children"]
    older_terms = ["older children", "teenagers", "teens", "adolescent"]
    has_young = any(t in brief_lower for t in young_terms)
    has_older = any(t in brief_lower for t in older_terms)

    if has_young and has_older:
        scope["audience_segments"] = [
            {
                "segment_id": "A1",
                "name": "Moms with young children",
                "role": "comparison segment",
            },
            {
                "segment_id": "A2",
                "name": "Moms with older children or teenagers",
                "role": "comparison segment",
            },
        ]


def _extract_primary_brand(spec: dict) -> str:
    cb = spec.get("commissioning_brand", {})
    if isinstance(cb, dict) and cb.get("name"):
        return cb["name"]
    for ent in spec.get("validated_entities", []):
        if ent.get("type") == "brand":
            return ent.get("name", "")
    brands = spec.get("included_scope", {}).get("brands", [])
    return brands[0] if brands else "Unknown"
