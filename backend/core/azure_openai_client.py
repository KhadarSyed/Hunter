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
import random
import re
import time
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)


class AzureOpenAIError(RuntimeError):
    pass


ATTEMPTS = 3
BACKOFF_S = (2, 6)                   # waits before the 2nd and 3rd attempt
# a dropped network (DNS gone for a minute, run 128) is waited out ~2 min, counted apart from server errors
CONNECTION_BACKOFF_S = (2, 6, 15, 30, 60)
_RETRY_STATUS = {500, 502, 503, 504}
# A rate limit (429) is waited out rather than given up after ~8 s: work done in parallel (enrichment batches,
# brief summaries) would otherwise come back blank. Azure says how long to wait; each wait is capped. Rate-limit
# retries are counted apart from the other retries, so neither kind ever gets fewer tries than before.
RATE_LIMIT_ATTEMPTS = 8
MAX_RATE_WAIT_S = 60.0
# A full Brief & Scope spec runs ~3.5k tokens; at 4096 a slightly longer one was cut off mid-JSON and failed to parse.
MAX_OUTPUT_TOKENS = 16384


def _rate_limit_wait(r: requests.Response, retry: int) -> float:
    """Seconds to wait after a 429: Azure's retry-after-ms / Retry-After, else exponential, plus a little jitter so
    parallel calls do not all retry at the same instant."""
    wait = None
    for header, scale in (("retry-after-ms", 0.001), ("Retry-After", 1.0)):
        try:
            wait = float(r.headers.get(header, "")) * scale
            break
        except ValueError:
            continue
    if wait is None:
        wait = 2.0 * (2 ** retry)
    return min(MAX_RATE_WAIT_S, wait) + random.uniform(0, 1.0)


def _record(model: str, kind: str, usage: dict | None, started: float, *, error: bool = False, reason: str = "") -> None:
    from ..domains.usage import service as usage_service      # lazy: domains import core
    u = usage or {}
    usage_service.record(
        "azure_openai", model, kind, input_tokens=int(u.get("prompt_tokens") or 0),
        cached_input_tokens=int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
        output_tokens=int(u.get("completion_tokens") or 0),
        latency_ms=int((time.time() - started) * 1000), error=error, reason=reason)


def _http_reason(r) -> str:
    """HTTP status plus the service's own error message (never the prompt)."""
    try:
        body = r.json()
    except ValueError:
        body = None
    err = body.get("error") if isinstance(body, dict) else None
    msg = str(err.get("message") or "") if isinstance(err, dict) else str(err or "")
    return f"HTTP {r.status_code}" + (f": {msg[:160]}" if msg else "")


def _url_model(url: str) -> str:
    m = re.search(r"/deployments/([^/?]+)", url)
    return m.group(1) if m else ""


def _post(url: str, headers: dict, payload: dict, timeout: int = 180, stream: bool = False,
          kind: str = "chat") -> requests.Response:
    """A request that survives a dropped connection (a proxy's TLS reset), a rate limit or a server hiccup: a
    long run makes hundreds of calls, and one transient failure must not fail it. With stream=True the caller
    reads (and closes) the body; a response given up on here is closed before the retry."""
    failures = rate_limited = dropped = 0
    while True:
        started = time.time()
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout, stream=stream)
        except (requests.ConnectionError, requests.Timeout) as e:
            _record(_url_model(url), kind, None, started, error=True,
                    reason=f"{type(e).__name__}" + ("" if dropped == len(CONNECTION_BACKOFF_S) else " (retried)"))
            if dropped == len(CONNECTION_BACKOFF_S):
                raise
            logger.warning("Azure OpenAI call retried after %s", type(e).__name__)
            time.sleep(CONNECTION_BACKOFF_S[dropped])
            dropped += 1
            continue
        if r.status_code == 429 and rate_limited < RATE_LIMIT_ATTEMPTS - 1:
            _record(_url_model(url), kind, None, started, error=True, reason="HTTP 429 rate limited (retried)")
            wait = _rate_limit_wait(r, rate_limited)
            logger.warning("Azure OpenAI rate limited; retrying in %.1fs (%d)", wait, rate_limited + 1)
            r.close()
            time.sleep(wait)
            rate_limited += 1
            continue
        if r.status_code not in _RETRY_STATUS or failures == ATTEMPTS - 1:
            return r
        logger.warning("Azure OpenAI call retried after HTTP %s", r.status_code)
        _record(_url_model(url), kind, None, started, error=True, reason=f"{_http_reason(r)} (retried)")
        r.close()
        time.sleep(BACKOFF_S[failures])
        failures += 1


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
        # max_completion_tokens (gpt-5 rejects max_tokens) needs 2024-09-01-preview or later
        self.api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
        self.reasoning_effort = os.getenv("AZURE_OPENAI_REASONING_EFFORT", "").strip().lower()

    def _payload(self, messages: list[dict]) -> dict:
        payload: dict = {"messages": messages, "max_completion_tokens": MAX_OUTPUT_TOKENS}
        if self.reasoning_effort:       # unset: the model's own default
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

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
        payload = self._payload(messages)
        if format_json:
            payload["response_format"] = {"type": "json_object"}

        started = time.time()
        if not on_token:
            r = _post(self._url(), headers, payload)
            if r.status_code != 200:
                _record(self.deployment, "chat", None, started, error=True, reason=_http_reason(r))
                raise AzureOpenAIError(f"Azure OpenAI chat failed: {r.status_code} {r.text[:300]}")
            try:
                body = r.json()
            except ValueError:
                _record(self.deployment, "chat", None, started, error=True, reason="Reply was not valid JSON")
                raise
            _record(body.get("model") or self.deployment, "chat", body.get("usage"), started)
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":     # raised, not returned: a cut-off reply is never cached
                raise AzureOpenAIError(f"Azure OpenAI reply cut off at max_completion_tokens={MAX_OUTPUT_TOKENS}")
            return choice["message"]["content"]

        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        full: list[str] = []
        done = cut_off = False
        model, usage = "", None
        r = _post(self._url(), headers, payload, stream=True)    # records its own failed attempts
        try:
            with r:
                if r.status_code != 200:
                    raise AzureOpenAIError(f"Azure OpenAI chat failed: {r.status_code} {r.text[:300]}")
                for line in r.iter_lines():
                    if not line or not line.startswith(b"data: "):
                        continue
                    raw = line[len(b"data: "):]
                    if raw.strip() == b"[DONE]":
                        done = True
                        break
                    chunk = json.loads(raw)
                    model = chunk.get("model") or model
                    usage = chunk.get("usage") or usage
                    choices = chunk.get("choices") or []
                    delta = choices[0].get("delta", {}).get("content", "") if choices else ""
                    if delta:
                        full.append(delta)
                        on_token(delta)
                    if choices and choices[0].get("finish_reason") == "length":
                        cut_off = True      # keep reading: the usage chunk follows, before [DONE]
        except Exception as e:
            reason = str(e)[:160] if isinstance(e, AzureOpenAIError) else f"Stream failed: {type(e).__name__}"
            _record(model or self.deployment, "chat", usage, started, error=usage is None, reason=reason)
            raise
        _record(model or self.deployment, "chat", usage, started, error=usage is None and not done,
                reason="Stream ended before [DONE]")
        if cut_off:
            raise AzureOpenAIError(f"Azure OpenAI reply cut off at max_completion_tokens={MAX_OUTPUT_TOKENS}")
        if not done:        # partial text is raised, not returned, so it is never cached as the answer
            raise AzureOpenAIError("Azure OpenAI stream ended before [DONE]")
        return "".join(full)

    def chat_tools(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        """One tool-calling turn: the reply's text and the tool calls it asks for, arguments parsed."""
        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        payload = self._payload(messages)
        if tools:
            payload.update(tools=tools, tool_choice=tool_choice)
        started = time.time()
        r = _post(self._url(), headers, payload, kind="tools")
        if r.status_code != 200:
            _record(self.deployment, "tools", None, started, error=True, reason=_http_reason(r))
            raise AzureOpenAIError(f"Azure OpenAI tool call failed: {r.status_code} {r.text[:300]}")
        try:
            body = r.json()
        except ValueError:
            _record(self.deployment, "tools", None, started, error=True, reason="Reply was not valid JSON")
            raise
        _record(body.get("model") or self.deployment, "tools", body.get("usage"), started)
        message = body["choices"][0]["message"]
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
