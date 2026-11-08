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


def _parses(text: str) -> bool:
    """True when a JSON reply is usable: plain JSON (object or array) or an object inside fences/preamble."""
    try:
        json.loads(text)
        return True
    except (ValueError, TypeError):
        pass
    try:
        extract_json_object(text or "")
        return True
    except ValueError:
        return False


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


class TokenLimitReached(NoChatProviderError):
    """The scoped user has used this month's token allowance (domains/billing). A NoChatProviderError, so every
    caller falls to its rule-based tier exactly as when no model is configured."""


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
        """Chat reachability: the platform model, or the scoped org's own models. (Embeddings have their own
        NVIDIA NIM check — see is_embed_reachable().)"""
        if self._chat_backend is not None:
            return True
        try:
            return bool(self._route()[1])
        except Exception:
            return True         # the org has no model: the call itself says so

    @staticmethod
    def _route() -> tuple[int | None, list[dict] | None]:
        """(org, its models in failover order), or (org, None) for the platform model."""
        from ..domains.providers import service as providers     # lazy: domains import core
        org = providers.scope_org()
        return org, providers.route(org)

    def _platform(self):
        if self._chat_backend is None:
            raise NoChatProviderError(
                "No chat LLM configured — set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_MODEL")
        return self._chat_backend

    def _invoke(self, org, rows, fn):
        """fn(backend) on the platform model, or on the org's first working model (failover, never the platform)."""
        if rows is None:
            return fn(self._platform())
        from ..domains.providers import service as providers
        return providers.call(org, rows, fn)

    def is_embed_reachable(self) -> bool:
        return self._embed_backend is not None

    def chat(
        self,
        messages: list[dict],
        on_token: Optional[Callable[[str], None]] = None,
        format_json: bool = False,
    ) -> str:
        org, rows = self._route()
        messages = self._guard(org, messages)
        backend = self._platform() if rows is None else None
        model = (f"{getattr(backend, 'deployment', '')}:{getattr(backend, 'reasoning_effort', '')}" if backend
                 else f"{rows[0]['model']}:")
        from ..domains.memory import service as memory     # lazy: memory imports store, which imports core
        from ..domains.usage import service as usage
        key = memory.llm_key(model, messages, format_json, org=org if org is not None else usage.current().get("org_id"))
        # the same prompt twice on one client is a retry of an answer the caller rejected: ask GPT again
        cached = memory.recall_llm(key) if key not in self._asked else None
        self._asked.add(key)
        if cached is not None:
            from ..domains.usage import service as usage_service
            usage_service.record(getattr(backend, "provider", "azure_openai") if backend else rows[0]["provider_type"],
                                 (getattr(backend, "deployment", "") if backend else rows[0]["model"]) or "unknown",
                                 "chat",
                                 cache_hit=True, requests=0)
            if on_token:
                on_token(cached)
            return cached
        from ..domains.billing import service as billing
        billing.check_tokens()
        text = self._invoke(org, rows, lambda b: b.chat(messages, on_token=on_token, format_json=format_json))
        if not format_json or _parses(text):     # a broken JSON reply is never reused from the cache
            memory.remember_llm(key, text)
        return text

    @property
    def model(self) -> str:
        """The model that answers now (the platform deployment or the org's first model) — for records like a
        spec's llm_model; 'unknown' when no model is configured."""
        try:
            org, rows = self._route()
            if rows:
                return rows[0]["model"] or "unknown"
            return getattr(self._chat_backend, "deployment", "") or "unknown"
        except Exception:
            return "unknown"

    def chat_tools(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        org, rows = self._route()
        messages = self._guard(org, messages)
        from ..domains.billing import service as billing
        billing.check_tokens()
        return self._invoke(org, rows, lambda b: b.chat_tools(messages, tools, tool_choice=tool_choice))

    @staticmethod
    def _guard(org: int | None, messages: list[dict]) -> list[dict]:
        """The scoped org's guardrails added to the system message (before the memory key, so an edit is fresh)."""
        from ..domains.guardrails import service as guardrails
        from ..domains.usage import service as usage
        scope = usage.current()
        if not guardrails.wanted(scope.get("stage")):
            return messages
        return guardrails.apply(org if org is not None else scope.get("org_id"), messages)

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
