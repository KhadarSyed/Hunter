"""Azure OpenAI chat client.

Talks to an Azure OpenAI deployment's Chat Completions REST API directly via
`requests` (no `openai` SDK dependency needed), configured from:
  AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_MODEL (deployment name),
  AZURE_OPENAI_API_VERSION
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)


class AzureOpenAIError(RuntimeError):
    pass


ATTEMPTS = 3
BACKOFF_S = (2, 6)                   # waits before the 2nd and 3rd attempt
_RETRY_STATUS = {429, 500, 502, 503, 504}


def _post(url: str, headers: dict, payload: dict, timeout: int = 180) -> requests.Response:
    """A request that survives a dropped connection (a proxy's TLS reset), a rate limit or a server hiccup: a
    long run makes hundreds of calls, and one transient failure must not fail it."""
    for attempt in range(ATTEMPTS):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt == ATTEMPTS - 1:
                raise
            logger.warning("Azure OpenAI call retried after %s", type(e).__name__)
        else:
            if r.status_code not in _RETRY_STATUS or attempt == ATTEMPTS - 1:
                return r
            logger.warning("Azure OpenAI call retried after HTTP %s", r.status_code)
        time.sleep(BACKOFF_S[attempt])
    raise AzureOpenAIError("unreachable")


class AzureOpenAIClient:
    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_version: str | None = None,
    ):
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY", "")
        self.endpoint = (endpoint or os.getenv("AZURE_OPENAI_ENDPOINT", "")).rstrip("/")
        self.deployment = deployment or os.getenv("AZURE_OPENAI_MODEL", "")
        self.api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")

    def is_reachable(self) -> bool:
        return bool(self.api_key and self.endpoint and self.deployment)

    def _url(self) -> str:
        return (
            f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions"
            f"?api-version={self.api_version}"
        )

    def chat(
        self,
        messages: list[dict],
        on_token: Optional[Callable[[str], None]] = None,
        format_json: bool = False,
    ) -> str:
        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        payload: dict = {"messages": messages, "max_tokens": 4096}
        if format_json:
            payload["response_format"] = {"type": "json_object"}

        if not on_token:
            r = _post(self._url(), headers, payload)
            if r.status_code != 200:
                raise AzureOpenAIError(f"Azure OpenAI chat failed: {r.status_code} {r.text[:300]}")
            data = r.json()
            return data["choices"][0]["message"]["content"]

        payload["stream"] = True
        full: list[str] = []
        with requests.post(self._url(), headers=headers, json=payload, stream=True, timeout=180) as r:
            if r.status_code != 200:
                raise AzureOpenAIError(f"Azure OpenAI chat failed: {r.status_code} {r.text[:300]}")
            for line in r.iter_lines():
                if not line or not line.startswith(b"data: "):
                    continue
                raw = line[len(b"data: "):]
                if raw.strip() == b"[DONE]":
                    break
                chunk = json.loads(raw)
                choices = chunk.get("choices") or []
                delta = choices[0].get("delta", {}).get("content", "") if choices else ""
                if delta:
                    full.append(delta)
                    on_token(delta)
        return "".join(full)

    def chat_tools(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        """One tool-calling turn: the reply's text and the tool calls it asks for, arguments parsed."""
        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        payload: dict = {"messages": messages, "max_tokens": 4096}
        if tools:
            payload.update(tools=tools, tool_choice=tool_choice)
        r = _post(self._url(), headers, payload)
        if r.status_code != 200:
            raise AzureOpenAIError(f"Azure OpenAI tool call failed: {r.status_code} {r.text[:300]}")
        message = r.json()["choices"][0]["message"]
        calls = []
        for c in message.get("tool_calls") or []:
            raw = c.get("function", {}).get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {"_raw": raw}
            calls.append({"id": c.get("id", ""), "name": c.get("function", {}).get("name", ""),
                          "arguments": args if isinstance(args, dict) else {"_raw": raw}})
        return {"content": message.get("content"), "tool_calls": calls, "message": message}
