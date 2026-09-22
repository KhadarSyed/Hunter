"""Research Planner Agent — transforms an approved ProjectSpecification into
a structured Research Plan.

This agent thinks like a senior consultant planning a research engagement.
It decomposes business questions into granular research objectives, assigns
platforms with justification, defines search concepts (not queries), and
maps every objective to a client deliverable.

It NEVER performs research — only plans it.
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
You are the Research Planner for a PR and social intelligence research firm.
Your job: transform an approved Project Specification into a Research Plan.
You do NOT perform research. You design the optimal research strategy.
Think like a senior consultant planning a research engagement.

━━━ RULES ━━━

1. DECOMPOSE every research question into 2–5 smaller research objectives.
   Each objective must be independently researchable.
   If two research questions overlap, create shared objectives and list
   both question IDs in business_question_ids.

2. NEVER include analyses the specification excludes.
   Check the EXCLUDED SCOPE carefully.
   If something is excluded, it must NOT appear anywhere in your plan —
   not in methods, search concepts, platforms, or expected outputs.
   This includes: Share of Voice, Sentiment Scoring, Sentiment Analysis,
   Competitive Benchmarking, Brand Perception, Editorial Coverage.

3. EVERY research objective must trace to a client deliverable.
   If you cannot explain what insight an objective supports, remove it.

4. Recommend platforms INDIVIDUALLY with justification.
   Do not recommend every platform automatically.
   Only include platforms where the evidence needed is most likely found.
   Common platforms: Reddit, Facebook, Instagram, TikTok, X, Threads, YouTube.
   Each platform has different strengths:
   - Reddit: long-form discussion, problem-solving, authentic tensions
   - TikTok: behaviour demonstration, hacks, simplification
   - Instagram: lifestyle, visual inspiration, aspirational content
   - Facebook: community groups, parent discussions, neighbourhood
   - Threads: emerging conversations, brief opinions
   - X: breaking discussion, reaction, news amplification
   - YouTube: tutorials, routines, long-form storytelling

5. Define SEARCH CONCEPTS, not Boolean queries or platform syntax.
   Concepts are the ideas and terms people actually use in conversation.
   Example: "weeknight cooking", "freezer meals", "decision fatigue"

6. Distinguish MANDATORY evidence (without it, the question cannot be answered)
   from OPTIONAL evidence (strengthens the answer but not strictly required).

7. Standard INCLUSION rules: personal experience, parent discussions,
   first-hand stories, advice-seeking, questions, routine descriptions.
   Standard EXCLUSION rules: ads, brand marketing, sponsored content,
   coupons, recipes without discussion, retail promotions, spam, bot content.

8. Analytical methods must support a specific business question.
   Valid methods: Thematic Analysis, Narrative Analysis, Conversation Mapping,
   Tension Analysis, Behaviour Analysis, Language Analysis,
   Life-stage Comparison, Platform Comparison, Trend Analysis,
   Secondary Validation.

━━━ OUTPUT FORMAT ━━━

Return ONLY a JSON object:

{
  "plan_summary": "2-3 sentence strategy overview",
  "research_objectives": [
    {
      "objective_id": "RO1",
      "business_question_ids": ["RQ1"],
      "objective": "what must actually be learned",
      "priority": "high",
      "reason": "why this matters for the client",
      "platforms": [
        {"name": "Reddit", "justification": "why this platform helps answer this"}
      ],
      "search_concepts": ["concept 1", "concept 2", "concept 3"],
      "evidence": {
        "mandatory": ["what evidence is required to answer this"],
        "optional": ["what would strengthen the answer"]
      },
      "inclusion_rules": ["personal experience", "parent discussions"],
      "exclusion_rules": ["ads", "sponsored content", "bot content"],
      "methods": ["Thematic Analysis"],
      "secondary_research": "published surveys or reports to validate against, or none",
      "expected_output": "what this objective produces",
      "deliverable_mapping": {
        "supports": "which insight or section this feeds",
        "evidence_type": "verbatims, themes, framework, etc.",
        "recommended_visual": "theme map, behaviour framework, comparison chart, etc."
      },
      "dependencies": [],
      "confidence_target": "high",
      "estimated_complexity": "medium"
    }
  ],
  "validation": {
    "question_coverage": "list which RQs map to which ROs",
    "duplicate_check": "confirm no duplicate objectives",
    "scope_compliance": "confirm all objectives within approved scope",
    "excluded_items_check": "confirm no excluded analyses appear in the plan"
  }
}
"""


# ─── Schema constants ────────────────────────────────────────────────────────

VALID_METHODS = frozenset({
    "thematic analysis",
    "narrative analysis",
    "conversation mapping",
    "tension analysis",
    "behaviour analysis",
    "language analysis",
    "life-stage comparison",
    "platform comparison",
    "trend analysis",
    "secondary validation",
})

CANONICAL_METHOD_NAMES = {
    "thematic analysis": "Thematic Analysis",
    "narrative analysis": "Narrative Analysis",
    "conversation mapping": "Conversation Mapping",
    "tension analysis": "Tension Analysis",
    "behaviour analysis": "Behaviour Analysis",
    "behavior analysis": "Behaviour Analysis",
    "language analysis": "Language Analysis",
    "life-stage comparison": "Life-stage Comparison",
    "life stage comparison": "Life-stage Comparison",
    "platform comparison": "Platform Comparison",
    "trend analysis": "Trend Analysis",
    "secondary validation": "Secondary Validation",
}

PLATFORM_ALIASES = {
    "twitter": "X",
    "x/twitter": "X",
    "twitter/x": "X",
    "x (twitter)": "X",
    "twitter (x)": "X",
    "tik tok": "TikTok",
    "tik-tok": "TikTok",
    "fb": "Facebook",
    "ig": "Instagram",
    "yt": "YouTube",
}

EXCLUDED_ANALYSIS_KEYWORDS = frozenset({
    "share of voice", "sentiment scoring", "sentiment analysis",
    "sentiment percentage", "net sentiment", "competitive benchmarking",
    "brand perception", "editorial coverage", "editorial research",
    "news coverage", "owned content audit", "market overview",
    "demographic breakdown",
})

REQUIRED_OBJECTIVE_KEYS = [
    "objective_id", "business_question_ids", "objective", "priority",
    "platforms", "search_concepts", "evidence", "methods",
    "expected_output", "deliverable_mapping",
]

CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})

STANDARD_EXCLUSION_RULES = [
    "ads", "brand marketing", "sponsored content",
    "coupons", "retail promotions", "spam", "bot content",
]


# ─── Response parsing ────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Pull the first valid JSON object from LLM output."""
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
                return json.loads(text[brace_start : i + 1])

    return json.loads(text[brace_start:])


# ─── Validation ──────────────────────────────────────────────────────────────

class ValidationError:
    def __init__(self, field: str, message: str, severity: str = "error"):
        self.field = field
        self.message = message
        self.severity = severity

    def __repr__(self) -> str:
        return f"[{self.severity.upper()}] {self.field}: {self.message}"


def validate_plan(plan: dict, spec: dict) -> list[ValidationError]:
    """Run all validation checks on a Research Plan."""
    errors: list[ValidationError] = []

    if not plan.get("plan_summary"):
        errors.append(ValidationError(
            "plan_summary", "Missing plan summary"))

    objectives = plan.get("research_objectives", [])
    if not objectives:
        errors.append(ValidationError(
            "research_objectives",
            "No research objectives defined"))
        return errors

    _validate_objective_structure(objectives, errors)
    _validate_question_coverage(plan, spec, errors)
    _validate_no_duplicates(objectives, errors)
    _validate_scope_compliance(plan, spec, errors)
    _validate_excluded_items(plan, spec, errors)
    _validate_platform_justification(objectives, errors)
    _validate_method_support(objectives, errors)
    _validate_deliverable_traceability(objectives, errors)

    return errors


def _validate_objective_structure(
    objectives: list, errors: list[ValidationError]
) -> None:
    seen_ids = set()
    for i, obj in enumerate(objectives):
        if not isinstance(obj, dict):
            errors.append(ValidationError(
                f"research_objectives[{i}]",
                "Objective must be a structured object"))
            continue

        oid = obj.get("objective_id", "")
        if not oid:
            errors.append(ValidationError(
                f"research_objectives[{i}].objective_id",
                "Missing objective_id"))
        elif oid in seen_ids:
            errors.append(ValidationError(
                f"research_objectives[{i}].objective_id",
                f"Duplicate objective_id '{oid}'"))
        else:
            seen_ids.add(oid)

        if not obj.get("objective"):
            errors.append(ValidationError(
                f"research_objectives[{i}].objective",
                "Missing objective description"))

        if not obj.get("business_question_ids"):
            errors.append(ValidationError(
                f"research_objectives[{i}].business_question_ids",
                "Objective must map to at least one research question"))

        prio = obj.get("priority", "")
        if prio and prio not in CONFIDENCE_LEVELS:
            errors.append(ValidationError(
                f"research_objectives[{i}].priority",
                f"Priority must be high/medium/low, got '{prio}'",
                severity="warning"))


def _validate_question_coverage(
    plan: dict, spec: dict, errors: list[ValidationError]
) -> None:
    spec_rq_ids = set()
    for rq in spec.get("research_questions", []):
        if isinstance(rq, dict):
            spec_rq_ids.add(rq.get("question_id", ""))

    covered_rq_ids = set()
    for obj in plan.get("research_objectives", []):
        for qid in obj.get("business_question_ids", []):
            covered_rq_ids.add(qid)

    uncovered = spec_rq_ids - covered_rq_ids
    for rq_id in sorted(uncovered):
        errors.append(ValidationError(
            "question_coverage",
            f"Research question '{rq_id}' has no corresponding objective"))


def _validate_no_duplicates(
    objectives: list, errors: list[ValidationError]
) -> None:
    for i, obj_a in enumerate(objectives):
        for j, obj_b in enumerate(objectives):
            if i >= j:
                continue
            text_a = obj_a.get("objective", "").lower()
            text_b = obj_b.get("objective", "").lower()
            words_a = set(w for w in text_a.split() if len(w) > 3)
            words_b = set(w for w in text_b.split() if len(w) > 3)
            if len(words_a) >= 3 and len(words_b) >= 3:
                overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
                if overlap > 0.75:
                    errors.append(ValidationError(
                        "duplicate_check",
                        f"Objectives '{obj_a.get('objective_id', i)}' and "
                        f"'{obj_b.get('objective_id', j)}' may overlap "
                        f"({overlap:.0%} word overlap)",
                        severity="warning"))


def _validate_scope_compliance(
    plan: dict, spec: dict, errors: list[ValidationError]
) -> None:
    spec_platforms = set(
        p.lower() for p in
        spec.get("included_scope", {}).get("platforms", []))
    social_only = any("social" in p for p in spec_platforms)

    non_social = {"news", "blogs", "forums", "editorial", "news sites",
                  "print", "broadcast", "trade publications"}

    for i, obj in enumerate(plan.get("research_objectives", [])):
        for plat in obj.get("platforms", []):
            pname = (plat.get("name", "") if isinstance(plat, dict)
                     else str(plat)).lower()
            if social_only and pname in non_social:
                errors.append(ValidationError(
                    f"research_objectives[{i}].platforms",
                    f"'{pname}' is not social media — spec restricts to "
                    f"social media only"))


def _validate_excluded_items(
    plan: dict, spec: dict, errors: list[ValidationError]
) -> None:
    excluded_items = set()
    for entry in spec.get("excluded_scope", []):
        if isinstance(entry, dict):
            excluded_items.add(entry.get("item", "").lower())
        elif isinstance(entry, str):
            excluded_items.add(entry.lower())

    all_excluded = excluded_items | EXCLUDED_ANALYSIS_KEYWORDS

    for i, obj in enumerate(plan.get("research_objectives", [])):
        fields_to_check = [
            ("methods", obj.get("methods", [])),
            ("search_concepts", obj.get("search_concepts", [])),
        ]
        for field_name, values in fields_to_check:
            for val in values:
                val_lower = val.lower() if isinstance(val, str) else ""
                for excl in all_excluded:
                    if excl in val_lower:
                        errors.append(ValidationError(
                            f"research_objectives[{i}].{field_name}",
                            f"'{val}' references excluded item '{excl}'"))

        obj_text = obj.get("objective", "").lower()
        for excl in all_excluded:
            if excl in obj_text:
                errors.append(ValidationError(
                    f"research_objectives[{i}].objective",
                    f"Objective text references excluded item '{excl}'"))

        output_text = obj.get("expected_output", "").lower()
        for excl in all_excluded:
            if excl in output_text:
                errors.append(ValidationError(
                    f"research_objectives[{i}].expected_output",
                    f"Expected output references excluded item '{excl}'",
                    severity="warning"))


def _validate_platform_justification(
    objectives: list, errors: list[ValidationError]
) -> None:
    for i, obj in enumerate(objectives):
        platforms = obj.get("platforms", [])
        if not platforms:
            errors.append(ValidationError(
                f"research_objectives[{i}].platforms",
                "No platforms recommended — at least one required"))
        for j, plat in enumerate(platforms):
            if isinstance(plat, str):
                errors.append(ValidationError(
                    f"research_objectives[{i}].platforms[{j}]",
                    "Platform must be {name, justification}, not a string",
                    severity="warning"))
            elif isinstance(plat, dict) and not plat.get("justification"):
                errors.append(ValidationError(
                    f"research_objectives[{i}].platforms[{j}].justification",
                    "Missing platform justification",
                    severity="warning"))


def _validate_method_support(
    objectives: list, errors: list[ValidationError]
) -> None:
    for i, obj in enumerate(objectives):
        methods = obj.get("methods", [])
        if not methods:
            errors.append(ValidationError(
                f"research_objectives[{i}].methods",
                "No analytical methods specified",
                severity="warning"))
        for method in methods:
            ml = method.lower()
            if ml not in VALID_METHODS:
                matched = any(
                    v in ml or ml in v for v in VALID_METHODS)
                if not matched:
                    errors.append(ValidationError(
                        f"research_objectives[{i}].methods",
                        f"Unrecognized method '{method}'",
                        severity="warning"))


def _validate_deliverable_traceability(
    objectives: list, errors: list[ValidationError]
) -> None:
    for i, obj in enumerate(objectives):
        dm = obj.get("deliverable_mapping")
        if not dm:
            errors.append(ValidationError(
                f"research_objectives[{i}].deliverable_mapping",
                "Missing deliverable mapping — objective must trace "
                "to a client deliverable",
                severity="warning"))
        elif isinstance(dm, dict) and not dm.get("supports"):
            errors.append(ValidationError(
                f"research_objectives[{i}].deliverable_mapping.supports",
                "Missing 'supports' — what insight does this feed?",
                severity="warning"))


# ─── Post-processing ─────────────────────────────────────────────────────────

def _apply_objective_defaults(plan: dict) -> None:
    if "research_objectives" not in plan:
        plan["research_objectives"] = []
    for obj in plan["research_objectives"]:
        if not isinstance(obj, dict):
            continue
        obj.setdefault("business_question_ids", [])
        obj.setdefault("priority", "medium")
        obj.setdefault("reason", "")
        obj.setdefault("platforms", [])
        obj.setdefault("search_concepts", [])
        ev = obj.get("evidence")
        if isinstance(ev, list):
            obj["evidence"] = {"mandatory": ev, "optional": []}
        elif not isinstance(ev, dict):
            obj["evidence"] = {"mandatory": [], "optional": []}
        else:
            ev.setdefault("mandatory", [])
            ev.setdefault("optional", [])
        obj.setdefault("inclusion_rules", [])
        obj.setdefault("exclusion_rules", [])
        obj.setdefault("methods", [])
        obj.setdefault("secondary_research", "none")
        obj.setdefault("expected_output", "")
        obj.setdefault("deliverable_mapping", {})
        obj.setdefault("dependencies", [])
        obj.setdefault("confidence_target", "medium")
        obj.setdefault("estimated_complexity", "medium")


def _normalize_platforms(plan: dict) -> None:
    for obj in plan.get("research_objectives", []):
        normalized = []
        for plat in obj.get("platforms", []):
            if isinstance(plat, str):
                name = PLATFORM_ALIASES.get(plat.lower(), plat)
                normalized.append({
                    "name": name,
                    "justification": "Platform recommended for this objective",
                })
            elif isinstance(plat, dict):
                name = plat.get("name", "")
                name = PLATFORM_ALIASES.get(name.lower(), name)
                plat["name"] = name
                normalized.append(plat)
        obj["platforms"] = normalized


def _normalize_methods(plan: dict) -> None:
    for obj in plan.get("research_objectives", []):
        normalized = []
        seen = set()
        for method in obj.get("methods", []):
            canonical = CANONICAL_METHOD_NAMES.get(method.lower())
            if not canonical:
                for key, val in CANONICAL_METHOD_NAMES.items():
                    if key in method.lower() or method.lower() in key:
                        canonical = val
                        break
            result = canonical or method
            if result.lower() not in seen:
                seen.add(result.lower())
                normalized.append(result)
        obj["methods"] = normalized


def _ensure_exclusion_rules(plan: dict, spec: dict) -> None:
    for obj in plan.get("research_objectives", []):
        existing = set(r.lower() for r in obj.get("exclusion_rules", []))
        for rule in STANDARD_EXCLUSION_RULES:
            if rule not in existing:
                obj["exclusion_rules"].append(rule)


def _ensure_question_coverage(plan: dict, spec: dict) -> None:
    spec_rqs = {}
    for rq in spec.get("research_questions", []):
        if isinstance(rq, dict):
            spec_rqs[rq.get("question_id", "")] = rq

    covered = set()
    for obj in plan.get("research_objectives", []):
        for qid in obj.get("business_question_ids", []):
            covered.add(qid)

    objectives = plan["research_objectives"]
    counter = len(objectives) + 1

    for rq_id in sorted(set(spec_rqs) - covered):
        rq = spec_rqs[rq_id]
        objectives.append({
            "objective_id": f"RO{counter}",
            "business_question_ids": [rq_id],
            "objective": rq.get("question", f"Address {rq_id}"),
            "priority": rq.get("priority", "primary"),
            "reason": f"Directly addresses research question {rq_id}",
            "platforms": [
                {"name": "Reddit",
                 "justification": "Long-form discussions likely relevant"},
                {"name": "Facebook",
                 "justification": "Community groups with parent discussions"},
            ],
            "search_concepts": [],
            "evidence": {
                "mandatory": ["relevant discussions and verbatims"],
                "optional": ["supporting secondary research"],
            },
            "inclusion_rules": ["personal experience", "discussions"],
            "exclusion_rules": list(STANDARD_EXCLUSION_RULES),
            "methods": ["Thematic Analysis"],
            "secondary_research": "none",
            "expected_output": f"Thematic findings for {rq_id}",
            "deliverable_mapping": {
                "supports": f"Insight section addressing {rq_id}",
                "evidence_type": "consumer verbatims and themes",
                "recommended_visual": "theme summary",
            },
            "dependencies": [],
            "confidence_target": "medium",
            "estimated_complexity": "medium",
        })
        counter += 1


def _remove_excluded_from_plan(plan: dict, spec: dict) -> None:
    """Scrub any excluded items that leaked into methods or search concepts."""
    excluded_lower = set()
    for entry in spec.get("excluded_scope", []):
        if isinstance(entry, dict):
            excluded_lower.add(entry.get("item", "").lower())
        elif isinstance(entry, str):
            excluded_lower.add(entry.lower())

    all_excluded = excluded_lower | EXCLUDED_ANALYSIS_KEYWORDS

    for obj in plan.get("research_objectives", []):
        obj["methods"] = [
            m for m in obj.get("methods", [])
            if not any(excl in m.lower() for excl in all_excluded)
        ]
        obj["search_concepts"] = [
            c for c in obj.get("search_concepts", [])
            if not any(excl in c.lower() for excl in all_excluded)
        ]


# ─── Agent runner ─────────────────────────────────────────────────────────────

def run(
    spec: dict,
    client: OllamaClient,
    emit: Optional[EventFn] = None,
    max_retries: int = 2,
) -> dict:
    """Execute the Research Planner Agent.

    Returns a dict with keys:
      plan: the validated Research Plan
      validation_errors: list of remaining warnings
      attempts: how many LLM calls were made
      elapsed_seconds: wall-clock time
    """
    if emit is None:
        emit = lambda event_type, payload: None

    start = time.time()
    rq_count = len(spec.get("research_questions", []))
    client_name = spec.get("commissioning_brand", {}).get("name", "Unknown")

    emit("research_planner_started", {
        "research_questions": rq_count,
        "client": client_name,
    })

    user_message = _build_user_prompt(spec)

    plan = None
    all_errors: list[ValidationError] = []
    attempt = 0

    for attempt in range(1, max_retries + 2):
        emit("research_planner_attempt", {"attempt": attempt})

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        if attempt > 1 and all_errors:
            correction = _build_correction_prompt(all_errors)
            messages.append({"role": "assistant", "content": json.dumps(plan)})
            messages.append({"role": "user", "content": correction})

        emit("research_planner_reasoning", {
            "status": "LLM designing research strategy..."})

        try:
            raw_response = client.chat(
                messages,
                on_token=lambda t: None,
                format_json=True,
            )
        except Exception as e:
            emit("research_planner_error", {
                "error": f"LLM call failed: {e}"})
            continue

        try:
            plan = _extract_json(raw_response)
        except (json.JSONDecodeError, ValueError) as e:
            emit("research_planner_error", {
                "error": f"JSON parse failed: {e}"})
            continue

        _apply_objective_defaults(plan)
        _normalize_platforms(plan)
        _normalize_methods(plan)
        _remove_excluded_from_plan(plan, spec)
        _ensure_exclusion_rules(plan, spec)
        _ensure_question_coverage(plan, spec)

        all_errors = validate_plan(plan, spec)
        hard_errors = [e for e in all_errors if e.severity == "error"]

        emit("research_planner_validated", {
            "attempt": attempt,
            "objectives": len(plan.get("research_objectives", [])),
            "errors": len(hard_errors),
            "warnings": len(all_errors) - len(hard_errors),
        })

        if not hard_errors:
            break

    elapsed = round(time.time() - start, 1)

    if plan is None:
        emit("research_planner_failed", {"elapsed": elapsed})
        return {
            "plan": None,
            "validation_errors": [repr(e) for e in all_errors],
            "attempts": attempt,
            "elapsed_seconds": elapsed,
        }

    plan["_meta"] = {
        "agent": "research_planner",
        "version": "1.0.0",
        "attempts": attempt,
        "elapsed_seconds": elapsed,
        "hard_errors": len(
            [e for e in all_errors if e.severity == "error"]),
        "warnings": len(
            [e for e in all_errors if e.severity == "warning"]),
        "total_objectives": len(plan.get("research_objectives", [])),
    }

    covered_ids = set(
        qid
        for obj in plan.get("research_objectives", [])
        for qid in obj.get("business_question_ids", [])
    )

    emit("research_planner_complete", {
        "objectives": len(plan.get("research_objectives", [])),
        "questions_covered": len(covered_ids),
        "total_questions": rq_count,
        "elapsed": elapsed,
    })

    return {
        "plan": plan,
        "validation_errors": [repr(e) for e in all_errors],
        "attempts": attempt,
        "elapsed_seconds": elapsed,
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_user_prompt(spec: dict) -> str:
    parts = [
        "Create a Research Plan for this approved Project Specification.",
        "Decompose every research question into 2-5 smaller, independently "
        "researchable objectives.",
        "Every objective must trace to a client deliverable.",
        "Respect ALL excluded scope items — do not include them anywhere.\n",
    ]

    cb = spec.get("commissioning_brand", {})
    rs = spec.get("research_subject", {})
    ra = spec.get("research_audience", {})
    parts.append(f"COMMISSIONING BRAND: {cb.get('name', 'Unknown')}")
    parts.append(f"RESEARCH SUBJECT: {rs.get('description', '')}")
    parts.append(f"RESEARCH AUDIENCE: {ra.get('description', '')}")
    parts.append(f"BUSINESS OBJECTIVE: {spec.get('business_objective', '')}")
    meth = spec.get("recommended_methodology", {})
    parts.append(f"METHODOLOGY: {meth.get('primary', '')}")

    parts.append(
        "\n--- RESEARCH QUESTIONS "
        "(decompose each into 2-5 objectives) ---")
    for rq in spec.get("research_questions", []):
        if isinstance(rq, dict):
            parts.append(
                f"  {rq.get('question_id', '?')}: "
                f"{rq.get('question', '')}")

    scope = spec.get("included_scope", {})
    parts.append("\n--- SCOPE ---")
    parts.append(f"Platforms: {', '.join(filter(None, scope.get('platforms') or []))}")
    parts.append(f"Countries: {', '.join(filter(None, scope.get('countries') or []))}")
    parts.append(f"Time Period: {scope.get('time_period', '')}")

    segments = scope.get("audience_segments", [])
    if segments:
        parts.append("Audience Segments (plan life-stage comparison):")
        for seg in segments:
            parts.append(
                f"  {seg.get('segment_id', '')}: "
                f"{seg.get('name', '')} ({seg.get('role', '')})")

    parts.append(
        "\n--- EXCLUDED SCOPE "
        "(NEVER include ANY of these in your plan) ---")
    for excl in spec.get("excluded_scope", []):
        if isinstance(excl, dict):
            parts.append(
                f"  EXCLUDED: {excl.get('item', '')} — "
                f"{excl.get('reason', '')}")
        elif isinstance(excl, str):
            parts.append(f"  EXCLUDED: {excl}")

    parts.append("\nReturn the Research Plan as JSON.")
    return "\n".join(parts)


def _build_correction_prompt(errors: list[ValidationError]) -> str:
    lines = [
        "Your Research Plan had validation errors. Fix these specific "
        "problems and return the corrected JSON:\n"
    ]
    for e in errors:
        if e.severity == "error":
            lines.append(f"  ERROR in {e.field}: {e.message}")
    lines.append("\nReturn the complete corrected JSON.")
    return "\n".join(lines)
