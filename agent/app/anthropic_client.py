"""Anthropic Claude API client — drop-in replacement for OllamaClient.chat()."""
from __future__ import annotations

import json
import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class AnthropicClient:
    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def is_reachable(self) -> bool:
        if not self.api_key or self.api_key.startswith("your-"):
            return False
        try:
            self._get_client()
            return True
        except Exception:
            return False

    def chat(
        self,
        messages: list[dict],
        on_token: Optional[Callable[[str], None]] = None,
        format_json: bool = False,
    ) -> str:
        client = self._get_client()

        system_text = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        if not chat_messages:
            chat_messages = [{"role": "user", "content": "Please respond."}]

        kwargs = {
            "model": self.model,
            "max_tokens": 16384,
            "messages": chat_messages,
        }
        if system_text:
            kwargs["system"] = system_text

        if on_token:
            full = []
            with client.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    full.append(text)
                    on_token(text)
            return "".join(full)
        else:
            response = client.messages.create(**kwargs)
            return response.content[0].text


def get_llm_client():
    """Return the best available LLM client: Azure OpenAI -> Anthropic -> Ollama."""
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
