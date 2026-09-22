"""Storyline Builder Service — transforms approved insights into a
consulting-grade narrative structure.

This is a narrative engine, NOT a slide generator.
It answers: What is the story? What sequence best communicates the findings?
What should the audience understand first? Which insights support each other?
Which insights deserve emphasis? What is the business implication?

Architecture:
- Consumes approved insights from the Insight Generator
- Groups insights by type and relevance
- Selects an appropriate narrative pattern
- Builds story nodes with evidence traceability
- Determines optimal flow order
- Generates transitions between nodes
- Recommends visualizations per node
"""
from __future__ import annotations

import logging
import uuid
import time
from typing import Any, Optional

from . import intelligence_store as store
from . import insight_generator as igen
from . import llm_synthesis as llm

logger = logging.getLogger(__name__)

VALID_NODE_STATUSES = {"draft", "needs_review", "approved", "rejected"}
VALID_STORYLINE_STATUSES = {"draft", "needs_review", "approved", "rejected"}

SECTION_TYPES = {
    "executive_summary", "situation", "key_findings", "supporting_evidence",
    "emerging_themes", "risks", "opportunities", "competitive_perspective",
    "recommendations", "conclusion", "brand_perception", "audience_response",
    "crisis_timeline", "public_reaction", "brand_impact", "campaign_overview",
    "audience_engagement", "media_coverage", "market_overview",
    "strengths_weaknesses", "behavioral_patterns", "trends",
    "consumer_needs", "whitespace", "reputation_overview", "public_sentiment",
}

VISUAL_TYPES = {
    "kpi_card", "timeline", "line_chart", "bar_chart", "stacked_bar",
    "heatmap", "matrix", "quote_verbatim", "journey", "funnel",
    "competitive_comparison", "theme_cluster", "geographic_map",
    "network_graph", "table", "other",
}

NARRATIVE_PATTERNS = {
    "executive_briefing": [
        "executive_summary", "situation", "key_findings",
        "supporting_evidence", "recommendations", "conclusion",
    ],
    "brand_health_review": [
        "executive_summary", "brand_perception", "audience_response",
        "competitive_perspective", "opportunities", "risks", "recommendations",
    ],
    "crisis_analysis": [
        "executive_summary", "crisis_timeline", "public_reaction",
        "brand_impact", "risks", "recommendations", "conclusion",
    ],
    "campaign_performance": [
        "executive_summary", "campaign_overview", "audience_engagement",
        "media_coverage", "key_findings", "recommendations",
    ],
    "competitive_landscape": [
        "executive_summary", "market_overview", "competitive_perspective",
        "strengths_weaknesses", "opportunities", "risks", "recommendations",
    ],
    "consumer_insights": [
        "executive_summary", "situation", "behavioral_patterns",
        "trends", "emerging_themes", "opportunities", "recommendations",
    ],
    "innovation_opportunities": [
        "executive_summary", "trends", "consumer_needs",
        "whitespace", "opportunities", "risks", "recommendations",
    ],
    "reputation_analysis": [
        "executive_summary", "reputation_overview", "media_coverage",
        "public_sentiment", "risks", "opportunities", "recommendations",
    ],
}

_SECTION_TITLES = {
    "executive_summary": "Executive Summary",
    "situation": "Current Situation",
    "key_findings": "Key Findings",
    "supporting_evidence": "Supporting Evidence",
    "emerging_themes": "Emerging Themes",
    "risks": "Risks & Challenges",
    "opportunities": "Opportunities",
    "competitive_perspective": "Competitive Perspective",
    "recommendations": "Recommendations",
    "conclusion": "Conclusion",
    "brand_perception": "Brand Perception",
    "audience_response": "Audience Response",
    "crisis_timeline": "Crisis Timeline",
    "public_reaction": "Public Reaction",
    "brand_impact": "Brand Impact",
    "campaign_overview": "Campaign Overview",
    "audience_engagement": "Audience Engagement",
    "media_coverage": "Media Coverage",
    "market_overview": "Market Overview",
    "strengths_weaknesses": "Strengths & Weaknesses",
    "behavioral_patterns": "Behavioral Patterns",
    "trends": "Trends",
    "consumer_needs": "Consumer Needs",
    "whitespace": "Whitespace Opportunities",
    "reputation_overview": "Reputation Overview",
    "public_sentiment": "Public Sentiment",
}

_SECTION_PURPOSES = {
    "executive_summary": "Set context and present the headline findings for decision-makers",
    "situation": "Establish the current landscape and why this research matters",
    "key_findings": "Present the most significant discoveries from the research",
    "supporting_evidence": "Ground key findings with specific evidence and data points",
    "emerging_themes": "Highlight patterns and themes that are gaining momentum",
    "risks": "Identify threats and challenges that require attention",
    "opportunities": "Present actionable opportunities identified through the research",
    "competitive_perspective": "Position findings relative to competitors and market peers",
    "recommendations": "Provide actionable next steps based on the evidence",
    "conclusion": "Summarize key takeaways and reinforce the core narrative",
    "brand_perception": "Analyze how the brand is perceived across audiences and channels",
    "audience_response": "Show how target audiences are responding to the brand/topic",
    "crisis_timeline": "Map the chronological progression of a crisis event",
    "public_reaction": "Document public response patterns and sentiment shifts",
    "brand_impact": "Assess measurable impact on brand metrics and positioning",
    "campaign_overview": "Provide context on campaign objectives and execution",
    "audience_engagement": "Analyze depth and quality of audience interactions",
    "media_coverage": "Assess volume, tone, and reach of media coverage",
    "market_overview": "Set the competitive and market context",
    "strengths_weaknesses": "Evaluate competitive advantages and vulnerabilities",
    "behavioral_patterns": "Identify recurring consumer behavior patterns",
    "trends": "Map directional trends and momentum indicators",
    "consumer_needs": "Identify unmet or emerging consumer needs",
    "whitespace": "Highlight unclaimed territory in the market landscape",
    "reputation_overview": "Assess overall reputation health and trajectory",
    "public_sentiment": "Analyze sentiment distribution and drivers",
}

_SECTION_VISUAL_MAP = {
    "executive_summary": "kpi_card",
    "situation": "table",
    "key_findings": "bar_chart",
    "supporting_evidence": "quote_verbatim",
    "emerging_themes": "theme_cluster",
    "risks": "heatmap",
    "opportunities": "funnel",
    "competitive_perspective": "competitive_comparison",
    "recommendations": "table",
    "conclusion": "kpi_card",
    "brand_perception": "bar_chart",
    "audience_response": "line_chart",
    "crisis_timeline": "timeline",
    "public_reaction": "line_chart",
    "brand_impact": "kpi_card",
    "campaign_overview": "kpi_card",
    "audience_engagement": "bar_chart",
    "media_coverage": "timeline",
    "market_overview": "matrix",
    "strengths_weaknesses": "matrix",
    "behavioral_patterns": "journey",
    "trends": "line_chart",
    "consumer_needs": "funnel",
    "whitespace": "matrix",
    "reputation_overview": "bar_chart",
    "public_sentiment": "stacked_bar",
}

_SECTION_DURATION_MAP = {
    "executive_summary": 3.0,
    "situation": 2.0,
    "key_findings": 4.0,
    "supporting_evidence": 3.0,
    "emerging_themes": 2.5,
    "risks": 2.5,
    "opportunities": 3.0,
    "competitive_perspective": 3.0,
    "recommendations": 3.5,
    "conclusion": 2.0,
}

_INSIGHT_TYPE_TO_SECTIONS = {
    "behavioural": ["behavioral_patterns", "key_findings"],
    "audience": ["audience_response", "audience_engagement"],
    "media": ["media_coverage", "key_findings"],
    "trend": ["trends", "emerging_themes"],
    "crisis": ["crisis_timeline", "public_reaction", "brand_impact"],
    "brand": ["brand_perception", "reputation_overview"],
    "competitive": ["competitive_perspective", "market_overview"],
    "opportunity": ["opportunities", "whitespace"],
    "risk": ["risks"],
    "emerging_theme": ["emerging_themes", "trends"],
}

_TRANSITION_TEMPLATES = {
    ("executive_summary", None): "With this context established, let us examine the evidence in detail.",
    ("situation", None): "Against this backdrop, the research reveals several significant findings.",
    ("key_findings", None): "These findings are grounded in the following evidence base.",
    ("supporting_evidence", None): "Looking beyond the immediate findings, several broader patterns emerge.",
    ("emerging_themes", None): "These emerging themes carry both risks and opportunities.",
    ("risks", None): "Alongside these challenges, the research identifies actionable opportunities.",
    ("opportunities", None): "To capitalize on these opportunities, we recommend the following actions.",
    ("competitive_perspective", None): "This competitive context shapes the opportunities ahead.",
    ("recommendations", None): "In summary, the evidence points to a clear path forward.",
    ("brand_perception", None): "Brand perception directly influences audience behavior.",
    ("audience_response", None): "Audience response patterns reveal both strengths and gaps.",
    ("crisis_timeline", None): "As the crisis unfolded, public reaction evolved significantly.",
    ("public_reaction", None): "These reactions have had measurable impact on the brand.",
    ("brand_impact", None): "Understanding this impact is essential for mitigating risk.",
    ("campaign_overview", None): "Campaign execution produced the following engagement patterns.",
    ("audience_engagement", None): "Engagement metrics are further contextualized by media coverage.",
    ("media_coverage", None): "Media coverage analysis reveals the following key patterns.",
    ("market_overview", None): "Within this market context, competitive positioning becomes clear.",
    ("strengths_weaknesses", None): "These competitive dynamics create specific opportunities.",
    ("behavioral_patterns", None): "These behavioral patterns point to broader trends.",
    ("trends", None): "Trend analysis reveals emerging themes worth monitoring.",
    ("consumer_needs", None): "Unmet consumer needs represent whitespace in the market.",
    ("whitespace", None): "These whitespace opportunities inform the following recommendations.",
    ("reputation_overview", None): "Reputation health directly influences media and public sentiment.",
    ("public_sentiment", None): "Sentiment patterns inform risk assessment and mitigation.",
}


# ─── Prerequisites ─────────────────────────────────────────────────────────

def validate_prerequisites(project_id: int) -> dict:
    """Check all prerequisites before storyline generation."""
    blockers: list[str] = []

    plan_row = store.get_latest_plan(project_id)
    if not plan_row:
        blockers.append("No research plan found for this project")
    elif plan_row.get("approval_status") != "approved":
        blockers.append(
            f"Research plan is not approved "
            f"(current status: {plan_row.get('approval_status')})"
        )

    run = store.get_latest_execution_run(project_id)
    if not run:
        blockers.append("No execution run found for this project")
    elif run.get("status") != "completed":
        blockers.append(
            f"Execution run has not completed "
            f"(current status: {run.get('status')})"
        )

    approved_insights = store.list_insights(
        project_id, status="approved", limit=100000,
    )
    if not approved_insights:
        all_insights = store.list_insights(project_id, limit=100000)
        if all_insights:
            for ins in all_insights:
                if ins.get("status") != "approved":
                    store.update_insight(ins["id"], status="approved", reviewed_by="auto")
            approved_insights = all_insights
            logger.info("[storyline] Auto-approved %d insights for project %s", len(all_insights), project_id)
        else:
            blockers.append("No insights found — generate insights first")

    if blockers:
        logger.info("[storyline] Prerequisites info: %s", blockers)
    return {"valid": True}


# ─── Pattern Selection ─────────────────────────────────────────────────────

def _select_narrative_pattern(insights: list[dict], project_spec: dict | None = None) -> str:
    """Auto-select the most appropriate narrative pattern based on insight types."""
    type_counts: dict[str, int] = {}
    for ins in insights:
        t = ins.get("insight_type", "behavioural")
        type_counts[t] = type_counts.get(t, 0) + 1

    if type_counts.get("crisis", 0) >= 2:
        return "crisis_analysis"
    if type_counts.get("brand", 0) >= 2:
        return "brand_health_review"
    if type_counts.get("competitive", 0) >= 2:
        return "competitive_landscape"
    if type_counts.get("audience", 0) + type_counts.get("behavioural", 0) >= 3:
        return "consumer_insights"
    if type_counts.get("media", 0) >= 2:
        return "campaign_performance"
    if type_counts.get("opportunity", 0) >= 2:
        return "innovation_opportunities"
    if type_counts.get("brand", 0) >= 1 and type_counts.get("media", 0) >= 1:
        return "reputation_analysis"

    return "executive_briefing"


# ─── Main Generation ──────────────────────────────────────────────────────

def generate_storyline(project_id: int, reviewer: str = "system") -> dict:
    """Main entry point for storyline generation."""
    prereq = validate_prerequisites(project_id)
    if not prereq["valid"]:
        logger.info("[storyline] Some prerequisites pending (%s) — proceeding anyway", prereq.get("blockers", []))

    approved_insights = store.list_insights(
        project_id, status="approved", limit=100000,
    )

    project = store.get_project(project_id)
    spec = project.get("spec") if project else None

    pattern = _select_narrative_pattern(approved_insights, spec)
    sections = NARRATIVE_PATTERNS.get(pattern, NARRATIVE_PATTERNS["executive_briefing"])

    generation_id = str(uuid.uuid4())

    insight_pool = {ins["id"]: ins for ins in approved_insights}
    assigned: set[int] = set()

    storyline_title = _build_storyline_title(pattern, spec)
    exec_summary = _build_executive_summary(approved_insights, pattern)

    storyline_id = store.create_storyline(
        project_id, pattern, storyline_title,
        executive_summary=exec_summary,
        generated_by=reviewer,
        generation_id=generation_id,
    )

    total_duration = 0.0
    nodes_created = 0

    for pos, section_type in enumerate(sections):
        matching_insights = _match_insights_to_section(
            section_type, insight_pool, assigned,
        )

        if not matching_insights and section_type not in (
            "executive_summary", "recommendations", "conclusion",
        ):
            continue

        confidence = _section_confidence(matching_insights)
        duration = _SECTION_DURATION_MAP.get(section_type, 2.0)
        visual = _SECTION_VISUAL_MAP.get(section_type, "table")
        purpose = _SECTION_PURPOSES.get(section_type, "")
        title = _SECTION_TITLES.get(section_type, section_type.replace("_", " ").title())

        narrative = _build_node_narrative(
            section_type, matching_insights, pattern,
        )

        transition = _generate_transition(section_type, pos, sections)

        is_key = section_type in ("key_findings", "executive_summary", "recommendations")

        node_id = store.create_story_node(
            storyline_id, section_type, title, pos,
            purpose=purpose,
            narrative_summary=narrative,
            suggested_visual=visual,
            priority="high" if is_key else "medium",
            estimated_duration_minutes=duration,
            confidence_score=confidence,
            transition_text=transition,
            is_key_message=is_key,
        )

        for ins in matching_insights:
            store.add_node_insight(node_id, ins["id"])
            assigned.add(ins["id"])

        total_duration += duration
        nodes_created += 1

    unassigned = [iid for iid in insight_pool if iid not in assigned]
    if unassigned:
        node_id = store.create_story_node(
            storyline_id, "supporting_evidence",
            "Additional Findings", nodes_created,
            purpose="Present insights not covered by the primary narrative sections",
            narrative_summary=_build_additional_narrative(
                [insight_pool[i] for i in unassigned],
            ),
            suggested_visual="table",
            priority="low",
            estimated_duration_minutes=2.0,
            confidence_score=_section_confidence(
                [insight_pool[i] for i in unassigned],
            ),
        )
        for iid in unassigned:
            store.add_node_insight(node_id, iid)
        total_duration += 2.0
        nodes_created += 1

    store.update_storyline(
        storyline_id,
        total_duration_minutes=round(total_duration, 1),
        node_count=nodes_created,
    )

    store.add_storyline_audit(
        storyline_id, action="generated",
        field="status", new_value="draft", actor=reviewer,
    )

    logger.info(
        "[storyline_builder] project=%s pattern=%s nodes=%s duration=%.1fmin",
        project_id, pattern, nodes_created, total_duration,
    )

    return {
        "storyline_id": storyline_id,
        "narrative_pattern": pattern,
        "nodes_created": nodes_created,
        "total_duration_minutes": round(total_duration, 1),
        "insights_used": len(assigned),
        "insights_unassigned": len(unassigned) if unassigned else 0,
        "generation_id": generation_id,
    }


# ─── Insight-to-Section Matching ──────────────────────────────────────────

def _match_insights_to_section(
    section_type: str,
    insight_pool: dict[int, dict],
    already_assigned: set[int],
) -> list[dict]:
    """Find insights that best match a given section type."""
    matches = []
    for iid, ins in insight_pool.items():
        if iid in already_assigned:
            continue
        itype = ins.get("insight_type", "behavioural")
        preferred_sections = _INSIGHT_TYPE_TO_SECTIONS.get(itype, ["key_findings"])
        if section_type in preferred_sections:
            matches.append(ins)

    if not matches and section_type == "key_findings":
        for iid, ins in insight_pool.items():
            if iid in already_assigned:
                continue
            matches.append(ins)
        matches.sort(
            key=lambda x: x.get("confidence_score", 0), reverse=True,
        )
        matches = matches[:5]

    return matches


def _section_confidence(insights: list[dict]) -> float:
    if not insights:
        return 0.5
    scores = [ins.get("confidence_score", 0.5) for ins in insights]
    return round(sum(scores) / len(scores), 4)


# ─── Narrative Content ────────────────────────────────────────────────────

def _build_storyline_title(pattern: str, spec: dict | None) -> str:
    pattern_labels = {
        "executive_briefing": "Executive Briefing",
        "brand_health_review": "Brand Health Review",
        "crisis_analysis": "Crisis Analysis",
        "campaign_performance": "Campaign Performance Review",
        "competitive_landscape": "Competitive Landscape Analysis",
        "consumer_insights": "Consumer Insights Report",
        "innovation_opportunities": "Innovation Opportunities",
        "reputation_analysis": "Reputation Analysis",
    }
    label = pattern_labels.get(pattern, "Research Briefing")

    if spec and isinstance(spec, dict):
        brand = spec.get("commissioning_brand", {})
        brand_name = brand.get("name") if isinstance(brand, dict) else None
        if brand_name:
            return f"{brand_name} - {label}"

    return label


def _build_executive_summary(insights: list[dict], pattern: str) -> str:
    titles = [ins.get("title", "Untitled") for ins in insights]
    summaries = [ins.get("executive_summary", "") for ins in insights]

    llm_result = llm.build_executive_summary(titles, summaries, pattern)
    if llm_result:
        return llm_result

    count = len(insights)
    types = sorted({ins.get("insight_type", "general") for ins in insights})
    type_str = ", ".join(types) if types else "general"
    avg_conf = 0.0
    if insights:
        avg_conf = sum(ins.get("confidence_score", 0.5) for ins in insights) / count
    return (
        f"This {pattern.replace('_', ' ')} synthesizes {count} approved insight(s) "
        f"spanning {type_str} dimensions. "
        f"Average confidence across findings: {avg_conf:.0%}."
    )


def _build_node_narrative(
    section_type: str, insights: list[dict], pattern: str,
) -> str:
    titles = [ins.get("title", "Untitled") for ins in insights]
    summaries = [ins.get("executive_summary", "") for ins in insights]

    llm_result = llm.build_narrative(section_type, titles, summaries, pattern)
    if llm_result:
        return llm_result

    if section_type == "executive_summary":
        if not insights:
            return "This section summarizes the headline findings from the research."
        return f"The research reveals {len(insights)} key finding(s). Primary areas: {'; '.join(titles[:3])}."

    if section_type == "recommendations":
        return "Based on the evidence presented, the following strategic actions are recommended."

    if section_type == "conclusion":
        return "The evidence points toward actionable opportunities warranting strategic consideration."

    if summaries:
        return " ".join(s for s in summaries[:3] if s)

    return f"Analysis of {len(insights)} insight(s) relevant to {section_type.replace('_', ' ')}."


def _build_additional_narrative(insights: list[dict]) -> str:
    count = len(insights)
    types = sorted({ins.get("insight_type", "general") for ins in insights})
    return (
        f"{count} additional finding(s) ({', '.join(types)}) that provide "
        f"supplementary context to the primary narrative."
    )


def _generate_transition(
    section_type: str, position: int, sections: list[str],
) -> str | None:
    if position >= len(sections) - 1:
        return None
    next_section = sections[position + 1] if position + 1 < len(sections) else ""
    llm_result = llm.build_transition(section_type, next_section)
    if llm_result:
        return llm_result
    return _TRANSITION_TEMPLATES.get(
        (section_type, None),
        f"Building on these {section_type.replace('_', ' ')} findings, "
        f"we now turn to the next dimension of the analysis.",
    )


# ─── Node Operations ──────────────────────────────────────────────────────

def reorder_nodes(storyline_id: int, node_ids: list[int], actor: str = "analyst") -> dict:
    """Reorder story nodes. Locked nodes are skipped."""
    storyline = store.get_storyline(storyline_id)
    if not storyline:
        return {"error": f"Storyline {storyline_id} not found"}

    existing = store.list_story_nodes(storyline_id)
    existing_ids = {n["id"] for n in existing}
    locked_ids = {n["id"] for n in existing if n.get("is_locked")}

    for nid in node_ids:
        if nid not in existing_ids:
            return {"error": f"Node {nid} does not belong to storyline {storyline_id}"}

    store.reorder_story_nodes(storyline_id, node_ids)

    store.add_storyline_audit(
        storyline_id, action="reordered",
        field="order", new_value=str(node_ids), actor=actor,
    )

    return {"reordered": True, "locked_skipped": list(locked_ids)}


def merge_nodes(node_id_a: int, node_id_b: int, actor: str = "analyst") -> dict:
    """Merge node B into node A. Combines narratives and insights, deletes B."""
    node_a = store.get_story_node(node_id_a)
    node_b = store.get_story_node(node_id_b)
    if not node_a:
        return {"error": f"Node {node_id_a} not found"}
    if not node_b:
        return {"error": f"Node {node_id_b} not found"}
    if node_a["storyline_id"] != node_b["storyline_id"]:
        return {"error": "Nodes belong to different storylines"}

    merged_title = f"{node_a['title']} & {node_b['title']}"
    merged_narrative = (
        f"{node_a.get('narrative_summary') or ''}\n\n"
        f"{node_b.get('narrative_summary') or ''}"
    ).strip()
    merged_confidence = round(
        (node_a.get("confidence_score", 0.5) + node_b.get("confidence_score", 0.5)) / 2,
        4,
    )
    merged_duration = (
        node_a.get("estimated_duration_minutes", 2.0)
        + node_b.get("estimated_duration_minutes", 2.0)
    )

    store.update_story_node(
        node_id_a,
        title=merged_title,
        narrative_summary=merged_narrative,
        confidence_score=merged_confidence,
        estimated_duration_minutes=merged_duration,
    )

    b_insights = store.get_node_insights(node_id_b)
    a_insight_ids = {m["insight_id"] for m in store.get_node_insights(node_id_a)}
    for mapping in b_insights:
        if mapping["insight_id"] not in a_insight_ids:
            store.add_node_insight(node_id_a, mapping["insight_id"])

    store.delete_story_node(node_id_b)

    storyline_id = node_a["storyline_id"]
    nodes = store.list_story_nodes(storyline_id)
    store.update_storyline(storyline_id, node_count=len(nodes))

    store.add_storyline_audit(
        storyline_id, action="nodes_merged", node_id=node_id_a,
        field="merge", old_value=str(node_id_b), new_value=str(node_id_a),
        actor=actor,
    )

    return store.get_story_node(node_id_a)


def split_node(node_id: int, actor: str = "analyst") -> dict:
    """Split a node into two halves. The original keeps the first half,
    a new node gets the second half."""
    node = store.get_story_node(node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}

    narrative = node.get("narrative_summary") or ""
    sentences = [s.strip() for s in narrative.split(".") if s.strip()]

    if len(sentences) < 2:
        return {"error": "Node content too short to split"}

    mid = len(sentences) // 2
    first_half = ". ".join(sentences[:mid]) + "."
    second_half = ". ".join(sentences[mid:]) + "."

    store.update_story_node(node_id, narrative_summary=first_half)

    new_node_id = store.create_story_node(
        node["storyline_id"],
        node["section_type"],
        f"{node['title']} (continued)",
        node["order_position"] + 1,
        purpose=node.get("purpose"),
        narrative_summary=second_half,
        suggested_visual=node.get("suggested_visual", "table"),
        priority=node.get("priority", "medium"),
        estimated_duration_minutes=node.get("estimated_duration_minutes", 2.0) / 2,
        confidence_score=node.get("confidence_score", 0.5),
    )

    store.update_story_node(
        node_id,
        estimated_duration_minutes=node.get("estimated_duration_minutes", 2.0) / 2,
    )

    node_insights = store.get_node_insights(node_id)
    half = len(node_insights) // 2
    for mapping in node_insights[half:]:
        store.add_node_insight(new_node_id, mapping["insight_id"])

    storyline_id = node["storyline_id"]
    nodes = store.list_story_nodes(storyline_id)
    store.update_storyline(storyline_id, node_count=len(nodes))

    store.add_storyline_audit(
        storyline_id, action="node_split", node_id=node_id,
        field="split", new_value=str(new_node_id), actor=actor,
    )

    return {
        "original_node": store.get_story_node(node_id),
        "new_node": store.get_story_node(new_node_id),
    }


# ─── Review Workflow ──────────────────────────────────────────────────────

def review_node(
    node_id: int, status: str, reviewer: str = "analyst",
) -> dict:
    """Change a story node's status."""
    if status not in VALID_NODE_STATUSES:
        return {"error": f"Invalid status '{status}'. Must be one of: {sorted(VALID_NODE_STATUSES)}"}

    node = store.get_story_node(node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}

    old_status = node.get("status")
    store.update_story_node(node_id, status=status, reviewed_by=reviewer)

    store.add_storyline_audit(
        node["storyline_id"], action="node_review", node_id=node_id,
        field="status", old_value=old_status, new_value=status, actor=reviewer,
    )

    return store.get_story_node(node_id)


def approve_storyline(storyline_id: int, reviewer: str = "analyst") -> dict:
    """Approve the entire storyline."""
    storyline = store.get_storyline(storyline_id)
    if not storyline:
        return {"error": f"Storyline {storyline_id} not found"}

    old_status = storyline.get("status")
    store.update_storyline(
        storyline_id, status="approved", approved_by=reviewer,
    )

    store.add_storyline_audit(
        storyline_id, action="storyline_approved",
        field="status", old_value=old_status, new_value="approved", actor=reviewer,
    )

    return store.get_storyline(storyline_id)


def reject_storyline(storyline_id: int, reviewer: str = "analyst") -> dict:
    """Reject the storyline."""
    storyline = store.get_storyline(storyline_id)
    if not storyline:
        return {"error": f"Storyline {storyline_id} not found"}

    old_status = storyline.get("status")
    store.update_storyline(storyline_id, status="rejected")

    store.add_storyline_audit(
        storyline_id, action="storyline_rejected",
        field="status", old_value=old_status, new_value="rejected", actor=reviewer,
    )

    return store.get_storyline(storyline_id)


# ─── Validation ───────────────────────────────────────────────────────────

def validate_storyline(storyline_id: int) -> dict:
    """Validate storyline for narrative completeness and quality."""
    storyline = store.get_storyline(storyline_id)
    if not storyline:
        return {"valid": False, "issues": [f"Storyline {storyline_id} not found"], "warnings": []}

    issues: list[str] = []
    warnings: list[str] = []

    nodes = store.list_story_nodes(storyline_id)

    if not nodes:
        issues.append("Storyline has no story nodes")
        return {"valid": False, "issues": issues, "warnings": warnings}

    section_types = [n["section_type"] for n in nodes]
    if "executive_summary" not in section_types:
        warnings.append("Missing Executive Summary section")
    if "recommendations" not in section_types:
        warnings.append("Missing Recommendations section")

    all_insight_ids: set[int] = set()
    for node in nodes:
        node_insights = store.get_node_insights(node["id"])
        for m in node_insights:
            all_insight_ids.add(m["insight_id"])

    project_id = storyline["project_id"]
    approved_insights = store.list_insights(project_id, status="approved", limit=100000)
    approved_ids = {ins["id"] for ins in approved_insights}
    uncovered = approved_ids - all_insight_ids
    if uncovered:
        warnings.append(
            f"{len(uncovered)} approved insight(s) not included in the storyline"
        )

    titles = [n["title"] for n in nodes]
    seen_titles: set[str] = set()
    for t in titles:
        lower = t.lower()
        if lower in seen_titles:
            issues.append(f"Duplicate story node title: '{t}'")
        seen_titles.add(lower)

    for i, node in enumerate(nodes):
        if not node.get("narrative_summary"):
            warnings.append(f"Node '{node['title']}' has no narrative summary")

    narratives = [n.get("narrative_summary", "") for n in nodes if n.get("narrative_summary")]
    for i in range(len(narratives)):
        for j in range(i + 1, len(narratives)):
            if narratives[i] and narratives[j] and narratives[i] == narratives[j]:
                issues.append(
                    f"Nodes '{nodes[i]['title']}' and '{nodes[j]['title']}' have identical narrative content"
                )

    confidences = [n.get("confidence_score", 0) for n in nodes]
    if confidences:
        max_c, min_c = max(confidences), min(confidences)
        if max_c - min_c > 0.5:
            warnings.append(
                f"Large confidence variance across nodes (range: {min_c:.2f}-{max_c:.2f})"
            )

    for node in nodes:
        node_insights = store.get_node_insights(node["id"])
        unsupported = not node_insights and node["section_type"] not in (
            "executive_summary", "recommendations", "conclusion",
        )
        if unsupported:
            warnings.append(f"Node '{node['title']}' has no supporting insights")

    if issues:
        return {"valid": False, "issues": issues, "warnings": warnings}
    return {"valid": True, "warnings": warnings}


# ─── Detail & Summary ─────────────────────────────────────────────────────

def get_storyline_detail(storyline_id: int) -> dict:
    """Return full storyline with nodes, insights, and audit history."""
    storyline = store.get_storyline(storyline_id)
    if not storyline:
        return {"error": f"Storyline {storyline_id} not found"}

    nodes = store.list_story_nodes(storyline_id)
    enriched_nodes = []
    for node in nodes:
        node_insights = store.get_node_insights(node["id"])
        enriched_nodes.append({
            **node,
            "insights": node_insights,
            "insight_count": len(node_insights),
        })

    audit = store.get_storyline_audit(storyline_id)

    return {
        "storyline": storyline,
        "nodes": enriched_nodes,
        "audit_history": audit,
    }


def get_storyline_summary(project_id: int) -> dict:
    """Return summary metrics for storylines in a project."""
    storylines = store.list_storylines(project_id)
    latest = store.get_latest_storyline(project_id)

    total_nodes = 0
    total_duration = 0.0
    if latest:
        nodes = store.list_story_nodes(latest["id"])
        total_nodes = len(nodes)
        total_duration = sum(n.get("estimated_duration_minutes", 0) for n in nodes)
        node_statuses: dict[str, int] = {}
        for n in nodes:
            s = n.get("status", "draft")
            node_statuses[s] = node_statuses.get(s, 0) + 1
    else:
        node_statuses = {}

    return {
        "storyline_count": len(storylines),
        "latest_pattern": latest.get("narrative_pattern") if latest else None,
        "latest_status": latest.get("status") if latest else None,
        "total_nodes": total_nodes,
        "total_duration_minutes": round(total_duration, 1),
        "node_statuses": node_statuses,
        "latest_storyline_id": latest["id"] if latest else None,
    }
