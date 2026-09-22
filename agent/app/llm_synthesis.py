"""LLM-powered synthesis for the Hunter Intelligence pipeline.

Provides high-quality analytical text generation using the configured Ollama
model. Falls back to template-based output when the LLM is unavailable.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .config import load_settings
from .llm_provider import HybridLLMClient, build_llm_client
from .ollama_client import OllamaError

logger = logging.getLogger(__name__)

_client: HybridLLMClient | None = None


def _get_client() -> HybridLLMClient | None:
    global _client
    if _client is None:
        cfg = load_settings()
        _client = build_llm_client(cfg)
    if not _client.is_reachable():
        logger.warning("[llm_synthesis] No LLM provider reachable")
        return None
    return _client


_LLM_PREAMBLE_PREFIXES = (
    "Certainly!", "Sure!", "Sure,", "Of course!", "Great!", "Absolutely!",
    "Here's", "Here are", "Here is", "I'd be happy", "Let me",
)


def _strip_preamble(text: str) -> str:
    """Remove common LLM conversational preamble from output."""
    stripped = text.strip()
    for prefix in _LLM_PREAMBLE_PREFIXES:
        if stripped.startswith(prefix):
            idx = stripped.find("\n", len(prefix))
            dot_idx = stripped.find(". ", len(prefix))
            colon_idx = stripped.find(":\n", len(prefix))
            cut = -1
            if colon_idx > 0 and colon_idx < 120:
                cut = colon_idx + 2
            elif dot_idx > 0 and dot_idx < 120:
                cut = dot_idx + 2
            elif idx > 0:
                cut = idx + 1
            if cut > 0:
                stripped = stripped[cut:].strip()
            break
    return stripped


_LLM_CALL_TIMEOUT = 120


def _llm_call(system: str, user: str, format_json: bool = False) -> str | None:
    client = _get_client()
    if not client:
        return None
    try:
        import concurrent.futures
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _do_chat():
            return client.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                format_json=format_json,
            )

        future = pool.submit(_do_chat)
        try:
            result = future.result(timeout=_LLM_CALL_TIMEOUT)
        except concurrent.futures.TimeoutError:
            logger.warning("[llm_synthesis] LLM call timed out after %ss — using fallback", _LLM_CALL_TIMEOUT)
            pool.shutdown(wait=False)
            return None
        finally:
            pool.shutdown(wait=False)

        if not result:
            return None
        cleaned = result.strip()
        if not format_json:
            cleaned = _strip_preamble(cleaned)
        return cleaned if cleaned else None
    except (OllamaError, Exception) as e:
        logger.warning("[llm_synthesis] LLM call failed: %s", e)
        return None


# ─── Insight Generation ──────────────────────────────────────────────────────


def synthesize_insight(
    objective_text: str,
    insight_type: str,
    evidence_excerpts: list[str],
    platforms: list[str],
) -> dict[str, str] | None:
    """Generate executive_summary, observation, interpretation, business_impact
    from evidence using the LLM. Returns None if LLM is unavailable."""
    evidence_block = "\n".join(
        f"- {ex[:400]}" for ex in evidence_excerpts[:20]
    )
    platform_str = ", ".join(platforms) if platforms else "various sources"

    system = (
        "You are a senior research analyst at a consulting firm. "
        "Write precise, evidence-based analytical content. "
        "Be specific — cite patterns, numbers, and themes from the evidence. "
        "Never use filler phrases like 'the evidence suggests' without specifics. "
        "Write in third person, professional tone. Keep each section to 2-3 sentences."
    )

    user = f"""Analyze this evidence for the research objective: "{objective_text}"

Evidence from {platform_str} ({len(evidence_excerpts)} items):
{evidence_block}

Respond in JSON with exactly these keys:
- "title": A specific, descriptive title for this insight (max 15 words, no "Insight:" prefix)
- "executive_summary": The headline finding — what the evidence reveals (2-3 sentences)
- "observation": What patterns/themes appear in the data (2-3 sentences)
- "interpretation": Why this matters — the analytical meaning (2-3 sentences)
- "business_impact": Strategic implications for decision-makers (2-3 sentences)"""

    raw = _llm_call(system, user, format_json=True)
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
        required = {"title", "executive_summary", "observation", "interpretation", "business_impact"}
        if not required.issubset(parsed.keys()):
            return None
        return parsed
    except (json.JSONDecodeError, TypeError):
        return None


# ─── Storyline Narrative ─────────────────────────────────────────────────────


def build_narrative(
    section_type: str,
    insight_titles: list[str],
    insight_summaries: list[str],
    pattern: str,
) -> str | None:
    """Generate narrative text for a storyline node."""
    insights_block = "\n".join(
        f"- {t}: {s[:300]}" for t, s in zip(insight_titles, insight_summaries)
    )

    system = (
        "You are a narrative strategist crafting a research presentation storyline. "
        "Write clear, flowing prose that connects insights into a compelling story. "
        "Be concise — 3-4 sentences max. Professional consulting tone."
    )

    user = f"""Write the narrative for a "{section_type.replace('_', ' ')}" section in a {pattern.replace('_', ' ')} presentation.

Insights for this section:
{insights_block}

Write 3-4 sentences that weave these insights into a cohesive narrative for this section. Do not use bullet points. Do not start with "This section"."""

    return _llm_call(system, user)


def build_executive_summary(
    insight_titles: list[str],
    insight_summaries: list[str],
    pattern: str,
) -> str | None:
    """Generate the executive summary for the storyline."""
    insights_block = "\n".join(
        f"- {t}: {s[:200]}" for t, s in zip(insight_titles, insight_summaries)
    )

    system = (
        "You are a senior research director writing an executive briefing. "
        "Distill multiple findings into a sharp, actionable summary. "
        "Lead with the most important finding. 3-4 sentences max."
    )

    user = f"""Write an executive summary for a {pattern.replace('_', ' ')} covering these findings:

{insights_block}

Synthesize into 3-4 sentences. Lead with the headline finding. End with the strategic implication."""

    return _llm_call(system, user)


def build_transition(from_section: str, to_section: str) -> str | None:
    """Generate a transition between storyline sections."""
    system = "You are a presentation narrator. Write smooth, professional transitions."
    user = (
        f"Write a single transition sentence connecting a '{from_section.replace('_', ' ')}' "
        f"section to a '{to_section.replace('_', ' ')}' section in a research presentation. "
        f"One sentence only."
    )
    return _llm_call(system, user)


# ─── Presentation Content ───────────────────────────────────────────────────


def generate_key_message(
    slide_title: str,
    content_summary: str,
) -> str | None:
    """Generate a key message for a presentation slide."""
    system = (
        "You are a presentation designer. Write punchy key messages that "
        "capture the single most important takeaway from each slide. "
        "One sentence, max 20 words."
    )

    user = f"""Slide: "{slide_title}"
Content: {content_summary[:500]}

Write the key message — the one thing the audience should remember from this slide. One sentence."""

    return _llm_call(system, user)


def generate_speaker_notes(
    slide_title: str,
    content_summary: str,
    key_message: str,
) -> str | None:
    """Generate speaker notes for a presentation slide."""
    system = (
        "You are a presentation coach writing speaker notes. "
        "Include what to say, what to emphasize, and how to transition. "
        "Conversational but professional. 3-5 sentences."
    )

    user = f"""Slide: "{slide_title}"
Key message: {key_message}
Content: {content_summary[:500]}

Write speaker notes (3-5 sentences) telling the presenter what to say for this slide."""

    return _llm_call(system, user)


def generate_recommendations(
    insight_titles: list[str],
    insight_summaries: list[str],
) -> list[str] | None:
    """Generate strategic recommendations from insights."""
    insights_block = "\n".join(
        f"- {t}: {s[:200]}" for t, s in zip(insight_titles, insight_summaries)
    )

    system = (
        "You are a strategy consultant. Generate specific, actionable recommendations. "
        "Each recommendation should be concrete and measurable. "
        "Return as JSON array of strings."
    )

    user = f"""Based on these research findings:

{insights_block}

Generate 3-5 specific strategic recommendations. Each should be one sentence, starting with an action verb.
Return as a JSON array of strings."""

    raw = _llm_call(system, user, format_json=True)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(r) for r in parsed[:5]]
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return [str(r) for r in v[:5]]
        return None
    except (json.JSONDecodeError, TypeError):
        return None
