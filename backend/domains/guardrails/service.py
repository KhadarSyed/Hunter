"""An organization's guardrails ride along with every LLM call made for it (HybridLLMClient.chat / chat_tools), so
every stage — brief, research, strategy, tagging, deck — follows them. Text is used verbatim, never rewritten."""
from __future__ import annotations

import logging
import time

from ...core.config import BACKEND_DIR
from . import repository as repo

logger = logging.getLogger(__name__)
_CACHE_S = 30
_cache: dict[int, tuple[float, str]] = {}
SEED_FILE = BACKEND_DIR / "domains" / "guardrails" / "seed_infovision.md"
SEED_ORG, SEED_TITLE = "InfoVision", "Instructions/Guardrail Prompt"
_SEED_KEY = "guardrails_seeded_infovision"
GUARDED_STAGES = frozenset({"brief_scope", "background_research", "search_strategy", "matching_label",
                            "dataset_tagging", "deck_engine", "deck_studio"})
HEADER = ("ORGANIZATION GUARDRAILS — mandatory. Follow every instruction below exactly in this task; where any other "
          "instruction conflicts with them, these guardrails win.")


def text_for(org_id: int | None) -> str:
    """The org's active guardrails as one block ('' when it has none). Cached briefly: it runs on every LLM call."""
    if not org_id:
        return ""
    now = time.time()
    hit = _cache.get(org_id)
    if hit and now - hit[0] < _CACHE_S:
        return hit[1]
    try:
        rows = repo.list_guardrails(org_id, active_only=True)
    except Exception as e:
        logger.warning("guardrails not loaded: %s", type(e).__name__)
        return hit[1] if hit else ""
    text = "\n\n".join(f"## {r['title']}\n{r['body']}" for r in rows)
    _cache[org_id] = (now, text)
    return text


def wanted(stage: str | None) -> bool:
    """Guardrails go to the stages that judge sources or write: brief, research, strategy, tagging, the deck. QC,
    the agent chat and stage-less helper calls skip them (they would only cost tokens)."""
    return stage in GUARDED_STAGES


def apply(org_id: int | None, messages: list[dict]) -> list[dict]:
    """A new message list with the org's guardrails at the very start of the system message (one is added if there
    is none). The model keeps nothing between calls, so every call carries them; putting them first gives every call
    the same opening, which the providers' prompt caches bill at the cached-input rate after the first call."""
    text = text_for(org_id)
    if not text:
        return messages
    block = f"{HEADER}\n\n{text}"
    if messages and messages[0].get("role") == "system" and isinstance(messages[0].get("content"), str):
        return [{**messages[0], "content": f"{block}\n\n---\n\n{messages[0]['content']}"}, *messages[1:]]
    return [{"role": "system", "content": block}, *messages]


def changed(org_id: int) -> None:
    _cache.pop(org_id, None)


def seed() -> None:
    """Once: InfoVision's guardrail from seed_infovision.md, verbatim. Not re-added if an Admin later deletes it."""
    from ..usage import repository as settings
    try:
        if settings.get_setting(_SEED_KEY):
            return
        org_id = repo.org_id_by_name(SEED_ORG)
        if not org_id:
            logger.warning("guardrail seed: organization %s not found", SEED_ORG)
            return
        if not any(r["title"] == SEED_TITLE for r in repo.list_guardrails(org_id)):
            repo.add_guardrail(org_id, SEED_TITLE, SEED_FILE.read_text(encoding="utf-8").strip(), True, None)
        settings.set_setting(_SEED_KEY, "1")
    except Exception as e:
        logger.warning("guardrail seed failed: %s", type(e).__name__)
