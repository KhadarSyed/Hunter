"""Unified LLM provider selection for chat and embeddings.

Chat:       Azure OpenAI only. No fallback — if it is not configured or a
            call fails, `chat()` raises so the caller can surface a real error
            (or use its own deterministic fallback; see e.g.
            domains/strategy/router.py's `_build_deterministic_strategy`).
Embedding:  NVIDIA NIM only. No fallback — `embed()`/`embed_batch()` raise if
            it is not configured or a call fails.

`build_llm_client()` returns a single object exposing the interface every
call site already expects: `is_reachable()`, `chat(...)`, `embed(...)`,
`embed_batch(...)`.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

import numpy as np

from .config import Settings

logger = logging.getLogger(__name__)


class NoChatProviderError(RuntimeError):
    """Raised by chat() when no chat LLM is configured or reachable."""


class NoEmbedProviderError(RuntimeError):
    """Raised by embed()/embed_batch() when no embedding provider is configured or reachable."""


def _build_chat_backend(settings: Settings):
    azure_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_deployment = os.getenv("AZURE_OPENAI_MODEL", "")
    if azure_key and azure_endpoint and azure_deployment:
        from .azure_openai_client import AzureOpenAIClient
        client = AzureOpenAIClient(azure_key, azure_endpoint, azure_deployment)
        if client.is_reachable():
            return client, "azure_openai"
    return None, None


def _build_embed_backend():
    nvidia_key = os.getenv("NVIDIA_EMBED_API_KEY", "")
    nvidia_model = os.getenv("NVIDIA_EMBED_MODEL", "")
    if nvidia_key and nvidia_model:
        from .nvidia_embed_client import NvidiaEmbedClient
        client = NvidiaEmbedClient()
        if client.is_reachable():
            return client, "nvidia_nim"

    return None, None


class HybridLLMClient:
    def __init__(self, settings: Settings):
        self._chat_backend, chat_name = _build_chat_backend(settings)
        self._embed_backend, embed_name = _build_embed_backend()
        logger.info(
            "LLM provider selected — chat: %s, embed: %s",
            chat_name or "none", embed_name or "none",
        )

    def is_reachable(self) -> bool:
        """Chat reachability. (Embeddings have their own NVIDIA NIM check —
        see is_embed_reachable().)"""
        return self._chat_backend is not None

    def is_embed_reachable(self) -> bool:
        return self._embed_backend is not None

    def chat(
        self,
        messages: list[dict],
        on_token: Optional[Callable[[str], None]] = None,
        format_json: bool = False,
    ) -> str:
        if self._chat_backend is None:
            raise NoChatProviderError(
                "No chat LLM configured — set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT "
                "and AZURE_OPENAI_MODEL"
            )
        return self._chat_backend.chat(messages, on_token=on_token, format_json=format_json)

    def chat_tools(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        if self._chat_backend is None:
            raise NoChatProviderError(
                "No chat LLM configured — set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_MODEL"
            )
        return self._chat_backend.chat_tools(messages, tools, tool_choice=tool_choice)

    def embed(self, text: str) -> np.ndarray:
        if self._embed_backend is None:
            raise NoEmbedProviderError(
                "No embedding provider configured — set NVIDIA_EMBED_API_KEY and NVIDIA_EMBED_MODEL"
            )
        return self._embed_backend.embed(text)

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        if self._embed_backend is None:
            raise NoEmbedProviderError(
                "No embedding provider configured — set NVIDIA_EMBED_API_KEY and NVIDIA_EMBED_MODEL"
            )
        return self._embed_backend.embed_batch(texts)


def build_llm_client(settings: Settings) -> HybridLLMClient:
    return HybridLLMClient(settings)
