"""Anthropic Claude API client."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_llm_client():
    """Return the HybridLLMClient (Azure OpenAI for chat, NVIDIA NIM for embeddings)."""
    from dotenv import load_dotenv
    load_dotenv()

    from .config import load_settings
    from .llm_provider import build_llm_client
    settings = load_settings()
    client = build_llm_client(settings)
    if client.is_reachable():
        return client

    logger.warning("No LLM provider available")
    return None
