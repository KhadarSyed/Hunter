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

import json
import logging
import os
import re
from typing import Callable, Optional

import numpy as np

from .config import Settings

logger = logging.getLogger(__name__)


def extract_json_object(text: str) -> dict:
    """The first JSON object in chat output, tolerating markdown fences, preamble and trailing commentary.
    Raises ValueError (json.JSONDecodeError included) when there is none."""
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
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[brace_start:i + 1])
    return json.loads(text[brace_start:])


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
    from .nvidia_embed_client import NvidiaEmbedClient
    client = NvidiaEmbedClient()
    if client.is_reachable():
        return client, "nvidia_nim"

    return None, None


class HybridLLMClient:
    def __init__(self, settings: Settings):
        self._chat_backend, chat_name = _build_chat_backend(settings)
        self._embed_backend, embed_name = _build_embed_backend()
        self._asked: set[str] = set()
        logger.info(
            "LLM provider selected — chat: %s, embed: %s",
            chat_name or "none", embed_name or "none",
        )

    def is_reachable(self) -> bool:
        """Chat reachability: the platform model, or the scoped org's own provider. (Embeddings have their own
        NVIDIA NIM check — see is_embed_reachable().)"""
        if self._chat_backend is not None:
            return True
        try:
            return self._org_backend() is not None
        except Exception:
            return True         # the org has a provider; the call itself reports why it fails

    @staticmethod
    def _org_backend():
        from ..domains.providers import service as providers     # lazy: domains import core
        return providers.backend_for_scope()

    def _backend(self) -> tuple[object, str]:
        """(chat backend, org provider name or ''): the org's default provider when the scoped org has one (never
        the platform model as a fallback), else the platform Azure OpenAI model."""
        org = self._org_backend()
        if org is not None:
            return org
        if self._chat_backend is None:
            raise NoChatProviderError(
                "No chat LLM configured — set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_MODEL")
        return self._chat_backend, ""

    @staticmethod
    def _call(org_name: str, fn, *args, **kwargs):
        if not org_name:
            return fn(*args, **kwargs)
        from ..domains.providers.service import OrgProviderError
        from .azure_openai_client import ReplyCutOff
        try:
            return fn(*args, **kwargs)
        except ReplyCutOff:
            raise           # a reply problem the caller handles (re-pack smaller), not a provider failure
        except Exception as e:
            raise OrgProviderError(f"Org provider '{org_name}' failed: {e}") from e

    def is_embed_reachable(self) -> bool:
        return self._embed_backend is not None

    def chat(
        self,
        messages: list[dict],
        on_token: Optional[Callable[[str], None]] = None,
        format_json: bool = False,
    ) -> str:
        backend, org_name = self._backend()
        from ..domains.memory import service as memory     # lazy: memory imports store, which imports core
        key = memory.llm_key(f"{getattr(backend, 'deployment', '')}:{getattr(backend, 'reasoning_effort', '')}",
                             messages, format_json)
        # the same prompt twice on one client is a retry of an answer the caller rejected: ask GPT again
        cached = memory.recall_llm(key) if key not in self._asked else None
        self._asked.add(key)
        if cached is not None:
            from ..domains.usage import service as usage_service
            usage_service.record(getattr(backend, "provider", "azure_openai"),
                                 getattr(backend, "deployment", "") or "unknown", "chat",
                                 cache_hit=True, requests=0)
            if on_token:
                on_token(cached)
            return cached
        text = self._call(org_name, backend.chat, messages, on_token=on_token, format_json=format_json)
        memory.remember_llm(key, text)
        return text

    def chat_tools(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        backend, org_name = self._backend()
        return self._call(org_name, backend.chat_tools, messages, tools, tool_choice=tool_choice)

    def embed(self, text: str) -> np.ndarray:
        if self._embed_backend is None:
            raise NoEmbedProviderError(
                "No embedding provider configured — set EMBEDDING_MODEL_API_KEY and EMBEDDING_MODEL_NAME (or NVIDIA_EMBED_API_KEY and NVIDIA_EMBED_MODEL)"
            )
        return self._embed_backend.embed(text)

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        if self._embed_backend is None:
            raise NoEmbedProviderError(
                "No embedding provider configured — set EMBEDDING_MODEL_API_KEY and EMBEDDING_MODEL_NAME (or NVIDIA_EMBED_API_KEY and NVIDIA_EMBED_MODEL)"
            )
        return self._embed_backend.embed_batch(texts)


def build_llm_client(settings: Settings) -> HybridLLMClient:
    return HybridLLMClient(settings)


def get_llm_client() -> HybridLLMClient | None:
    """The HybridLLMClient from .env settings when its chat backend is reachable, else None."""
    from dotenv import load_dotenv
    load_dotenv()

    from .config import load_settings
    client = build_llm_client(load_settings())
    if client.is_reachable():
        return client

    logger.warning("No LLM provider available")
    return None
