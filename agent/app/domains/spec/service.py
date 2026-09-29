"""Research Specification Service — transforms a raw project spec (or LLM-
generated spec from brief_scope.py) into the 20-section Research Specification
format with readiness tracking and clarification identification.

This service does NOT perform research.  It structures and validates the project
understanding into an analyst-reviewable specification before downstream stages
(Background Research, Search Strategy, etc.) begin.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

from ...core import store
from .repository import FORM_FIELDS

SECTION_TITLES = {
    "project_understanding": "Project Understanding",
    "business_objective": "Business Objective",
    "research_objectives": "Research Objectives",
    "research_questions": "Research Questions",
    "scope_dimensions": "Scope Dimensions",
    "entities": "Entities",
    "audiences": "Audiences",
    "inclusions": "Inclusions",
    "exclusions": "Exclusions",
    "methodology": "Methodology",
    "question_method_mapping": "Question-to-Method Mapping",
    "data_requirements": "Data Requirements",
    "metrics": "Metrics & KPIs",
    "deliverables": "Deliverables",
    "assumptions": "Assumptions",
    "clarifications": "Clarifications",
    "risks": "Risks",
    "dependencies": "Dependencies",
    "success_criteria": "Success Criteria",
    "approval_status": "Approval Status",
}

# Fields the analyst sets on the New Project form (single definition in repository.py).
# The brief_scope LLM only sees the brief text, so it cannot know them.
_FORM_FIELDS = FORM_FIELDS
_SCOPE_FROM_FORM = {"geography": "geography", "time_period": "time_period"}  # included_scope key -> form key
# form key -> keywords identifying an LLM "missing information" item that the form answers
_ANSWERED_BY_FORM = {
    "geography": ("geograph", "country", "countries", "region", "market"),
    "time_period": ("time period", "timeframe", "time frame", "date range", "period of analysis", "time range"),
    "research_type": ("methodology", "research approach", "research method"),
}


def _apply_form_context(llm_spec: dict, form_spec: dict) -> dict:
    """Merge the analyst's form choices into an LLM-generated spec.

    Geography, Time Period and Research Type are dropdown selections the analyst made
    *before* the brief was even analysed — they are not prose for the LLM to refine, so
    the form's value always wins here (unlike free-text fields, where the LLM's reading
    of the brief is authoritative). This also fixes the LLM hedging unspecified values
    with reasoning text ("unspecified (assume most recent 12 months...)") that used to
    slip past an exact-match check and silently override the analyst's real selection.
    """
    merged = {**llm_spec, **{k: form_spec[k] for k in _FORM_FIELDS if form_spec.get(k)}}
    scope = dict(merged.get("included_scope") or {})
    for scope_key, form_key in _SCOPE_FROM_FORM.items():
        if form_spec.get(form_key):
            scope[scope_key] = form_spec[form_key]
    merged["included_scope"] = scope
    if form_spec.get("research_type"):
        # _build_methodology()/_build_question_method_mapping() read "recommended_methodology"
        # first (the LLM's actual output key) and only fall back to "methodology" if absent —
        # so the override must land on "recommended_methodology" or it's silently ignored.
        methodology = merged.get("recommended_methodology", merged.get("methodology"))
        merged["recommended_methodology"] = {**(methodology if isinstance(methodology, dict) else {}),
                                             "primary": form_spec["research_type"]}
    # The LLM lists what the brief text lacks; drop items the form already answered so the
    # analyst is not asked for geography / time period / research type they just selected.
    answered = [kws for form_key, kws in _ANSWERED_BY_FORM.items() if form_spec.get(form_key)]
    missing = merged.get("missing_information")
    if answered and isinstance(missing, list):
        def still_missing(item) -> bool:
            text = (item.get("item") or item.get("question") or "") if isinstance(item, dict) else str(item)
            return not any(kw in text.lower() for kws in answered for kw in kws)
        merged["missing_information"] = [i for i in missing if still_missing(i)]
    return merged


def generate_spec(
    project_id: int,
    raw_brief_text: str = "",
    use_llm: bool = False,
    llm_client: Any = None,
    emit: Optional[Callable[[str, dict], None]] = None,
) -> dict:
    """Generate a Research Specification from the project's stored spec.

    If the project already has a rich LLM-generated spec (from brief_scope.py),
    it is restructured into the 20-section format.  Otherwise, the basic
    NewProject spec is expanded with deterministic rules.

    When ``use_llm`` is True and ``llm_client`` is provided, the brief_scope
    agent is invoked first to produce a rich spec from the raw brief text.

    ``emit(step, payload)``, if given, is called at each stage (LLM interpretation
    attempts/validation from brief_scope.py, then "merging_form_context",
    "building_sections", "identifying_clarifications", "saving") — used by the
    /spec/generate route to stream progress to the Brief & Scope page.

    Returns ``{"spec_id": int, "spec": dict, "readiness": dict}``.
    """
    def _emit(step: str, payload: Optional[dict] = None) -> None:
        if emit:
            emit(step, payload or {})

    project = store.get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")

    project_spec = project.get("spec", {})

    if use_llm and llm_client and raw_brief_text:
        from ...agents.brief_scope import run as run_brief_scope
        result = run_brief_scope(
            raw_brief_text,
            llm_client,
            brief_filename=project.get("project_name", ""),
            max_retries=2,
            emit=emit,
        )
        if result.get("spec"):
            _emit("merging_form_context")
            project_spec = _apply_form_context(result["spec"], project_spec)
            store.update_project_spec(project_id, project_spec)
        else:
            _emit("brief_scope_incomplete", {"validation_errors": result.get("validation_errors", [])})

    _emit("building_sections")
    sections = _build_sections(project_spec, raw_brief_text or project_spec.get("raw_brief", ""))
    _emit("identifying_clarifications")
    clarifications = _identify_clarifications(project_spec, sections)

    spec_data = {
        "project_id": project_id,
        "project_name": project.get("project_name", ""),
        "section_order": list(store.SPEC_SECTION_ORDER),
        "section_titles": SECTION_TITLES,
        "sections": sections,
        "source_spec": project_spec,
        "industry": project_spec.get("industry") or {},
        "generated_at": time.time(),
    }

    generation_source = "llm" if (use_llm and llm_client) else "deterministic"
    llm_model = ""
    if use_llm and llm_client:
        llm_model = getattr(llm_client, "model", "ollama")

    _emit("saving")
    spec_id = store.save_research_spec(
        project_id=project_id,
        spec=spec_data,
        raw_brief_text=raw_brief_text or project_spec.get("raw_brief", ""),
        generation_source=generation_source,
        llm_model=llm_model,
    )

    for cq in clarifications:
        store.add_clarification(
            spec_id=spec_id,
            question=cq["question"],
            section_key=cq.get("section_key", ""),
            is_blocking=cq.get("is_blocking", True),
        )

    readiness = store.get_spec_readiness(spec_id)
    _emit("done", {"spec_id": spec_id, "completeness_pct": readiness.get("completeness_pct") if readiness else None})

    return {
        "spec_id": spec_id,
        "spec": spec_data,
        "readiness": readiness,
        "clarifications": clarifications,
    }


def regenerate_spec(
    spec_id: int,
    raw_brief_text: str = "",
    use_llm: bool = False,
    llm_client: Any = None,
    confirm_overwrite_locked: bool = False,
    emit: Optional[Callable[[str, dict], None]] = None,
) -> dict:
    """Regenerate a specification, preserving locked/edited sections unless
    ``confirm_overwrite_locked`` is True.

    ``emit`` follows the same contract as ``generate_spec`` — used by the
    ``/spec/{spec_id}/regenerate`` ("Reanalyze") route to stream progress."""
    def _emit(step: str, payload: Optional[dict] = None) -> None:
        if emit:
            emit(step, payload or {})

    existing = store.get_spec_by_id(spec_id)
    if not existing:
        raise ValueError(f"Spec {spec_id} not found")

    project_id = existing["project_id"]
    project = store.get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")

    locked_sections: dict[str, dict] = {}
    if not confirm_overwrite_locked:
        approvals = existing.get("section_approvals", {})
        old_sections = existing.get("spec", {}).get("sections", {})
        for key, sa in approvals.items():
            if sa.get("is_locked") or sa.get("status") == "approved":
                if key in old_sections:
                    locked_sections[key] = old_sections[key]

    project_spec = project.get("spec", {})
    if use_llm and llm_client and raw_brief_text:
        from ...agents.brief_scope import run as run_brief_scope
        result = run_brief_scope(
            raw_brief_text, llm_client,
            brief_filename=project.get("project_name", ""),
            max_retries=2,
            emit=emit,
        )
        if result.get("spec"):
            _emit("merging_form_context")
            project_spec = _apply_form_context(result["spec"], project_spec)
            store.update_project_spec(project_id, project_spec)
        else:
            _emit("brief_scope_incomplete", {"validation_errors": result.get("validation_errors", [])})

    _emit("building_sections")
    sections = _build_sections(project_spec, raw_brief_text or project_spec.get("raw_brief", ""))

    for key, locked in locked_sections.items():
        sections[key] = locked

    _emit("identifying_clarifications")
    clarifications = _identify_clarifications(project_spec, sections)
    # Dedupe against what's already on this spec (e.g. from the original generate, or a
    # prior reanalyze) so re-running Reanalyze doesn't pile up repeat clarification rows.
    existing_questions = {c.get("question") for c in existing.get("clarifications", [])}
    for cq in clarifications:
        if cq["question"] not in existing_questions:
            store.add_clarification(
                spec_id=spec_id,
                question=cq["question"],
                section_key=cq.get("section_key", ""),
                is_blocking=cq.get("is_blocking", True),
            )

    spec_data = {
        "project_id": project_id,
        "project_name": project.get("project_name", ""),
        "section_order": list(store.SPEC_SECTION_ORDER),
        "section_titles": SECTION_TITLES,
        "sections": sections,
        "source_spec": project_spec,
        "industry": project_spec.get("industry") or {},
        "generated_at": time.time(),
        "regenerated_from": spec_id,
    }

    _emit("saving")
    store.update_spec(spec_id, spec_data)
    readiness = store.get_spec_readiness(spec_id)
    _emit("done", {"spec_id": spec_id, "completeness_pct": readiness.get("completeness_pct") if readiness else None})

    return {
        "spec_id": spec_id,
        "spec": spec_data,
        "readiness": readiness,
    }


# ─── Section builders ─────────────────────────────────────────────────────────

def _build_sections(project_spec: dict, brief_text: str) -> dict:
    """Build all 20 sections from the project spec."""
    sections: dict[str, dict] = {}

    sections["project_understanding"] = {
        "title": SECTION_TITLES["project_understanding"],
        "content": _build_project_understanding(project_spec),
        "edited": False,
    }

    sections["business_objective"] = {
        "title": SECTION_TITLES["business_objective"],
        "content": _safe_str(project_spec.get("business_objective", "")),
        "edited": False,
    }

    sections["research_objectives"] = {
        "title": SECTION_TITLES["research_objectives"],
        "content": _build_research_objectives(project_spec),
        "edited": False,
    }

    sections["research_questions"] = {
        "title": SECTION_TITLES["research_questions"],
        "content": _build_research_questions(project_spec),
        "edited": False,
    }

    sections["scope_dimensions"] = {
        "title": SECTION_TITLES["scope_dimensions"],
        "content": _build_scope_dimensions(project_spec),
        "edited": False,
    }

    sections["entities"] = {
        "title": SECTION_TITLES["entities"],
        "content": _build_entities(project_spec),
        "edited": False,
    }

    sections["audiences"] = {
        "title": SECTION_TITLES["audiences"],
        "content": _build_audiences(project_spec),
        "edited": False,
    }

    sections["inclusions"] = {
        "title": SECTION_TITLES["inclusions"],
        "content": _build_inclusions(project_spec),
        "edited": False,
    }

    sections["exclusions"] = {
        "title": SECTION_TITLES["exclusions"],
        "content": _build_exclusions(project_spec),
        "edited": False,
    }

    sections["methodology"] = {
        "title": SECTION_TITLES["methodology"],
        "content": _build_methodology(project_spec),
        "edited": False,
    }

    sections["question_method_mapping"] = {
        "title": SECTION_TITLES["question_method_mapping"],
        "content": _build_question_method_mapping(project_spec),
        "edited": False,
    }

    sections["data_requirements"] = {
        "title": SECTION_TITLES["data_requirements"],
        "content": _build_data_requirements(project_spec),
        "edited": False,
    }

    sections["metrics"] = {
        "title": SECTION_TITLES["metrics"],
        "content": _build_metrics(project_spec),
        "edited": False,
    }

    sections["deliverables"] = {
        "title": SECTION_TITLES["deliverables"],
        "content": _build_deliverables(project_spec),
        "edited": False,
    }

    sections["assumptions"] = {
        "title": SECTION_TITLES["assumptions"],
        "content": _build_assumptions(project_spec),
        "edited": False,
    }

    sections["clarifications"] = {
        "title": SECTION_TITLES["clarifications"],
        "content": _build_clarifications_section(project_spec),
        "edited": False,
    }

    sections["risks"] = {
        "title": SECTION_TITLES["risks"],
        "content": _build_risks(project_spec),
        "edited": False,
    }

    sections["dependencies"] = {
        "title": SECTION_TITLES["dependencies"],
        "content": _build_dependencies(project_spec),
        "edited": False,
    }

    sections["success_criteria"] = {
        "title": SECTION_TITLES["success_criteria"],
        "content": _build_success_criteria(project_spec),
        "edited": False,
    }

    sections["approval_status"] = {
        "title": SECTION_TITLES["approval_status"],
        "content": _build_approval_status(),
        "edited": False,
    }

    return sections


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    return json.dumps(val)


def _build_project_understanding(spec: dict) -> str:
    parts = []
    ei = spec.get("executive_interpretation", "")
    if ei:
        parts.append(ei)

    cb = spec.get("commissioning_brand", {})
    if isinstance(cb, dict) and cb.get("name"):
        parts.append(f"\nCommissioning Brand: {cb['name']}")
        if cb.get("role"):
            parts.append(f"Role: {cb['role']}")

    rs = spec.get("research_subject", {})
    if isinstance(rs, dict) and rs.get("description"):
        parts.append(f"\nResearch Subject: {rs['description']}")
        if rs.get("is_brand_study") is not None:
            parts.append(f"Is Brand Study: {'Yes' if rs['is_brand_study'] else 'No'}")

    sa = spec.get("strategic_application", "")
    if sa:
        parts.append(f"\nStrategic Application: {sa}")

    return "\n".join(parts).strip()


def _build_research_objectives(spec: dict) -> str:
    parts = []
    ro = spec.get("research_objective", "")
    if ro:
        parts.append(ro)
    do = spec.get("deliverable_objective", "")
    if do:
        parts.append(f"\nDeliverable Objective: {do}")
    return "\n".join(parts).strip()


def _build_research_questions(spec: dict) -> list[dict]:
    rqs = spec.get("research_questions", [])
    result = []
    for rq in rqs:
        if isinstance(rq, dict):
            result.append({
                "question_id": rq.get("question_id") or rq.get("id", ""),
                "question": rq.get("question", ""),
                "source": rq.get("source", "inferred"),
                "priority": rq.get("priority", "primary"),
                "required": rq.get("required", True),
            })
        elif isinstance(rq, str):
            result.append({
                "question_id": f"RQ{len(result) + 1}",
                "question": rq,
                "source": "inferred",
                "priority": "primary",
                "required": True,
            })
    return result


def _build_scope_dimensions(spec: dict) -> dict:
    scope = spec.get("included_scope", {})
    geo = scope.get("geography", "")
    if not geo and scope.get("countries"):
        geo = ", ".join(scope["countries"]) if isinstance(scope["countries"], list) else str(scope["countries"])
    return {
        "platforms": scope.get("platforms", []),
        "geography": geo,
        "time_period": scope.get("time_period", spec.get("time_period", "")),
        "languages": scope.get("languages", ["English"]),
        "content_types": scope.get("content_types", []),
    }


def _build_entities(spec: dict) -> list[dict]:
    entities = spec.get("validated_entities", [])
    result = []
    for ent in entities:
        if isinstance(ent, dict):
            built = {
                "name": ent.get("name", ""),
                "type": ent.get("type", "brand"),
                "confidence": ent.get("confidence", "medium"),
                "reasoning": ent.get("reasoning", ""),
                "alternatives_considered": ent.get("alternatives_considered", []),
            }
            # Optional, type-specific fields (agents/brief_scope.py RULE #8/#9) — copied
            # through only when present so most entities don't carry empty placeholders.
            if ent.get("group"):
                built["group"] = ent["group"]
            if ent.get("keywords"):
                built["keywords"] = ent["keywords"]
            result.append(built)
    return result


def _build_audiences(spec: dict) -> dict:
    ra = spec.get("research_audience", {})
    scope = spec.get("included_scope", {})
    primary = scope.get("primary_audience", {})
    segments = scope.get("audience_segments", scope.get("segments", []))

    audience_name = ""
    if isinstance(primary, dict):
        audience_name = primary.get("name", "")
    if not audience_name and isinstance(ra, dict):
        audience_name = ra.get("description", "")
    if not audience_name:
        audience_name = scope.get("audience", "")

    return {
        "primary_audience": audience_name,
        "description": ra.get("description", "") if isinstance(ra, dict) else str(ra),
        "segments": segments if isinstance(segments, list) else [],
    }


def _build_inclusions(spec: dict) -> dict:
    scope = spec.get("included_scope", {})
    return {
        "brands": scope.get("brands", []),
        "platforms": scope.get("platforms", []),
        "expected_analyses": scope.get("expected_analyses", []),
        "deliverables": scope.get("deliverables", []),
    }


def _build_exclusions(spec: dict) -> list[dict]:
    excluded = spec.get("excluded_scope", [])
    result = []
    for entry in excluded:
        if isinstance(entry, dict):
            result.append({
                "item": entry.get("item", ""),
                "reason": entry.get("reason", ""),
                "severity": entry.get("severity", "hard exclusion"),
            })
        elif isinstance(entry, str):
            result.append({
                "item": entry,
                "reason": "Not requested",
                "severity": "hard exclusion",
            })
    return result


def _build_methodology(spec: dict) -> dict:
    meth = spec.get("recommended_methodology", spec.get("methodology", {}))
    if isinstance(meth, dict):
        return {
            "primary": meth.get("primary", ""),
            "reasoning": meth.get("reasoning", ""),
            "alternatives_considered": meth.get("alternatives_considered", []),
        }
    return {"primary": str(meth), "reasoning": "", "alternatives_considered": []}


def _build_question_method_mapping(spec: dict) -> list[dict]:
    rqs = spec.get("research_questions", [])
    meth = spec.get("recommended_methodology", spec.get("methodology", {}))
    primary = meth.get("primary", "Social Listening") if isinstance(meth, dict) else str(meth)
    mapping = []
    for rq in rqs:
        if isinstance(rq, dict):
            mapping.append({
                "question_id": rq.get("question_id") or rq.get("id", ""),
                "question": rq.get("question", ""),
                "method": primary,
                "rationale": f"Primary methodology applied to {rq.get('question_id') or rq.get('id', '')}",
            })
    return mapping


def _build_data_requirements(spec: dict) -> dict:
    scope = spec.get("included_scope", {})
    return {
        "data_sources": ["Meltwater social listening export"],
        "required_fields": ["headline", "URL", "source", "date", "content", "platform"],
        "sample_size": "Sufficient for statistical significance per research question",
        "time_range": scope.get("time_period", spec.get("time_period", "")),
        "geographic_filter": scope.get("geography", ""),
        "language_filter": scope.get("languages", ["English"]),
    }


def _build_metrics(spec: dict) -> list[dict]:
    ca = spec.get("confidence_assessment", spec.get("confidence", {}))
    metrics = [
        {"metric": "Research Question Coverage", "target": "100%", "description": "All research questions addressed with evidence"},
        {"metric": "Source Quality", "target": "Tier 1-2 majority", "description": "Majority of evidence from high-quality sources"},
        {"metric": "Evidence per Question", "target": "5+", "description": "Minimum evidence items per research question"},
    ]
    if isinstance(ca, dict):
        overall = ca.get("overall", "medium")
        metrics.append({
            "metric": "Specification Confidence",
            "target": overall.capitalize(),
            "description": f"Current assessed confidence level: {overall}",
        })
    return metrics


def _build_deliverables(spec: dict) -> list[dict]:
    scope = spec.get("included_scope", {})
    delivs = scope.get("deliverables", [])
    do = spec.get("deliverable_objective", "")

    result = []
    for d in delivs:
        if isinstance(d, str):
            result.append({"deliverable": d, "format": "Presentation / Report", "status": "planned"})
        elif isinstance(d, dict):
            result.append(d)

    if not result and do:
        result.append({"deliverable": do, "format": "Presentation / Report", "status": "planned"})
    if not result:
        result.append({"deliverable": "Research report", "format": "PPTX + DOCX", "status": "planned"})

    return result


def _build_assumptions(spec: dict) -> list[dict]:
    assumptions = spec.get("assumptions", [])
    result = []
    for a in assumptions:
        if isinstance(a, dict):
            result.append({
                "assumption": a.get("assumption", ""),
                "why_it_matters": a.get("why_it_matters", ""),
                "confidence": a.get("confidence", "medium"),
            })
        elif isinstance(a, str):
            result.append({"assumption": a, "why_it_matters": "", "confidence": "medium"})

    if not result:
        result.append({
            "assumption": "Brief text accurately represents the client's intent",
            "why_it_matters": "Misinterpretation could lead to off-target research",
            "confidence": "medium",
        })

    return result


def _build_clarifications_section(spec: dict) -> list[dict]:
    mi = spec.get("missing_information", [])
    result = []
    for item in mi:
        if isinstance(item, dict):
            result.append({
                "question": item.get("item", item.get("question", "")),
                "why_it_matters": item.get("why_it_matters", ""),
                "can_proceed_without": item.get("can_proceed_without", True),
                "assumption_if_missing": item.get("assumption_if_missing", ""),
            })
        elif isinstance(item, str):
            result.append({
                "question": item,
                "why_it_matters": "",
                "can_proceed_without": True,
                "assumption_if_missing": "",
            })
    return result


def _build_risks(spec: dict) -> list[dict]:
    risks = spec.get("risks", [])
    result = []
    for r in risks:
        if isinstance(r, dict):
            result.append({
                "risk": r.get("risk", ""),
                "severity": r.get("severity", "medium"),
                "mitigation": r.get("mitigation", ""),
            })
        elif isinstance(r, str):
            result.append({"risk": r, "severity": "medium", "mitigation": ""})

    if not result:
        result.append({
            "risk": "LLM timeout on CPU-only hardware may limit analysis depth",
            "severity": "medium",
            "mitigation": "Deterministic fallback pipeline provides basic results",
        })

    return result


def _build_dependencies(spec: dict) -> list[dict]:
    return [
        {
            "dependency": "Approved Research Specification",
            "required_for": "Background Research (Stage 2)",
            "status": "pending",
        },
        {
            "dependency": "Client brief text available",
            "required_for": "Specification generation",
            "status": "met" if spec.get("raw_brief") or spec.get("executive_interpretation") else "pending",
        },
    ]


def _build_success_criteria(spec: dict) -> list[str]:
    criteria = spec.get("success_criteria", [])
    if criteria:
        return [c if isinstance(c, str) else c.get("criterion", str(c)) for c in criteria]
    return [
        "All research questions have been validated and accepted by the analyst",
        "Entity disambiguation is complete with no low-confidence entities remaining",
        "Scope boundaries (inclusions and exclusions) are explicitly defined",
        "Methodology is justified and mapped to each research question",
        "Data requirements are specified with source, timeframe, and quality criteria",
    ]


def _build_approval_status() -> dict:
    return {
        "specification_approved": False,
        "approved_by": None,
        "approved_at": None,
        "gate_status": "Gate 1 — Pending",
    }


# ─── Clarification identification ─────────────────────────────────────────────

def _identify_clarifications(spec: dict, sections: dict) -> list[dict]:
    """Identify questions that should be raised as clarifications."""
    clarifications = []

    mi = spec.get("missing_information", [])
    for item in mi:
        if isinstance(item, dict):
            can_proceed = item.get("can_proceed_without", True)
            clarifications.append({
                "question": item.get("item", item.get("question", "")),
                "section_key": "clarifications",
                "is_blocking": not can_proceed,
            })

    rqs = sections.get("research_questions", {}).get("content", [])
    if isinstance(rqs, list) and len(rqs) == 0:
        clarifications.append({
            "question": "No research questions defined — what should this research answer?",
            "section_key": "research_questions",
            "is_blocking": True,
        })

    entities_content = sections.get("entities", {}).get("content", [])
    if isinstance(entities_content, list):
        for ent in entities_content:
            if isinstance(ent, dict) and ent.get("confidence") == "low":
                clarifications.append({
                    "question": f"Entity '{ent.get('name', '')}' has low confidence — please verify the interpretation: {ent.get('reasoning', '')}",
                    "section_key": "entities",
                    "is_blocking": True,
                })

    methodology = sections.get("methodology", {}).get("content", {})
    if isinstance(methodology, dict) and not methodology.get("primary"):
        clarifications.append({
            "question": "No primary methodology specified — what research approach should be used?",
            "section_key": "methodology",
            "is_blocking": True,
        })

    bo = sections.get("business_objective", {}).get("content", "")
    if not bo or not bo.strip():
        clarifications.append({
            "question": "Business objective is empty — what business problem is this research solving?",
            "section_key": "business_objective",
            "is_blocking": True,
        })

    # Non-blocking safety net: if the LLM (or the deterministic tier) came up empty on a
    # data point the analyst may still have in mind, ask rather than silently leave it
    # blank. Never blocking — the analyst can proceed and fill these in later if they apply.
    entity_types_present = {
        ent.get("type") for ent in entities_content if isinstance(ent, dict)
    } if isinstance(entities_content, list) else set()
    _ENTITY_GAP_PROMPTS = {
        "company": "No company/organization entities were identified — are there any relevant companies to track?",
        "product": "No specific products were identified — are there specific products this research should cover?",
        "person": "No named people were identified — are there executives, spokespeople, or other named individuals relevant to this research?",
        "product_group": "No product groups/lineups were identified — is there a specific product range or lineup in scope?",
        "event": "No events were identified — are there any launches, campaigns, conferences, or other events relevant to this research?",
    }
    for entity_type, question in _ENTITY_GAP_PROMPTS.items():
        if entity_type not in entity_types_present:
            clarifications.append({"question": question, "section_key": "entities", "is_blocking": False})

    if not (spec.get("industry") or {}).get("name"):
        clarifications.append({
            "question": "No industry/category classification was identified — what industry or category does this research subject operate in?",
            "section_key": "entities",
            "is_blocking": False,
        })

    return clarifications
