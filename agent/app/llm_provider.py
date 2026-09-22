"""Unified LLM provider selection, shared by every module that previously
constructed an `OllamaClient` directly for chat and/or embeddings.

Chat priority:       Azure OpenAI -> Anthropic -> local Ollama
Embedding priority:  NVIDIA NIM   -> local Ollama

`build_llm_client()` returns a single object exposing the interface every
call site already expects: `is_reachable()`, `chat(...)`, `embed(...)`,
`embed_batch(...)`. Cloud provider failures at call time fall back to the
local Ollama instance rather than raising, so existing callers that assume
an always-available client keep working.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

import numpy as np

from .config import Settings
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


def _build_chat_backend(settings: Settings):
    azure_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_deployment = os.getenv("AZURE_OPENAI_MODEL", "")
    if azure_key and azure_endpoint and azure_deployment:
        from .azure_openai_client import AzureOpenAIClient
        client = AzureOpenAIClient(azure_key, azure_endpoint, azure_deployment)
        if client.is_reachable():
            return client, "azure_openai"

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key and not api_key.startswith("your-"):
        from .anthropic_client import AnthropicClient
        return AnthropicClient(api_key=api_key), "anthropic"

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
        self._ollama = OllamaClient(settings.ollama_host, settings.embed_model, settings.chat_model)
        self._chat_backend, chat_name = _build_chat_backend(settings)
        self._embed_backend, embed_name = _build_embed_backend()
        logger.info(
            "LLM provider selected — chat: %s, embed: %s",
            chat_name or "ollama", embed_name or "ollama",
        )

    def is_reachable(self) -> bool:
        if self._chat_backend is not None:
            return True
        return self._ollama.is_reachable()

    def chat(
        self,
        messages: list[dict],
        on_token: Optional[Callable[[str], None]] = None,
        format_json: bool = False,
    ) -> str:
        if self._chat_backend is not None:
            try:
                return self._chat_backend.chat(messages, on_token=on_token, format_json=format_json)
            except Exception:
                logger.exception("Cloud chat provider failed — falling back to Ollama")
        return self._ollama.chat(messages, on_token=on_token, format_json=format_json)

    def embed(self, text: str) -> np.ndarray:
        if self._embed_backend is not None:
            try:
                return self._embed_backend.embed(text)
            except Exception:
                logger.exception("Cloud embedding provider failed — falling back to Ollama")
        return self._ollama.embed(text)

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        if self._embed_backend is not None:
            try:
                return self._embed_backend.embed_batch(texts)
            except Exception:
                logger.exception("Cloud embedding provider failed — falling back to Ollama")
        return self._ollama.embed_batch(texts)


def build_llm_client(settings: Settings) -> HybridLLMClient:
    return HybridLLMClient(settings)
