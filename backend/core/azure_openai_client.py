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


LOW_EFFORTS = ("low", "minimal")     # a cut-off at these is not retried


class AzureOpenAIError(RuntimeError):
    pass


class ReplyCutOff(AzureOpenAIError):
    """The model stopped at its output limit: a reply problem, not a provider failure. Callers that batch (the
    tagging agents) catch AzureOpenAIError and re-pack smaller; an org provider raises it too, unwrapped."""


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


def _record(model: str, kind: str, usage: dict | None, started: float, *, error: bool = False, reason: str = "",
            provider: str = "azure_openai") -> None:
    """One usage row from an OpenAI-shaped `usage` block (Azure, OpenAI and every OpenAI-compatible provider)."""
    from ..domains.usage import service as usage_service      # lazy: domains import core
    u = usage or {}
    usage_service.record(
        provider, model, kind, input_tokens=int(u.get("prompt_tokens") or 0),
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
          kind: str = "chat", provider: str = "azure_openai", model: str = "") -> requests.Response:
    """A request that survives a dropped connection (a proxy's TLS reset), a rate limit or a server hiccup: a
    long run makes hundreds of calls, and one transient failure must not fail it. With stream=True the caller
    reads (and closes) the body; a response given up on here is closed before the retry."""
    failures = rate_limited = dropped = 0
    while True:
        started = time.time()
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout, stream=stream)
        except (requests.ConnectionError, requests.Timeout) as e:
            _record(model or _url_model(url), kind, None, started, error=True, provider=provider,
                    reason=f"{type(e).__name__}" + ("" if dropped == len(CONNECTION_BACKOFF_S) else " (retried)"))
            if dropped == len(CONNECTION_BACKOFF_S):
                raise
            logger.warning("%s call retried after %s", provider, type(e).__name__)
            time.sleep(CONNECTION_BACKOFF_S[dropped])
            dropped += 1
            continue
        if r.status_code == 429 and rate_limited < RATE_LIMIT_ATTEMPTS - 1:
            _record(model or _url_model(url), kind, None, started, error=True, provider=provider, reason="HTTP 429 rate limited (retried)")
            wait = _rate_limit_wait(r, rate_limited)
            logger.warning("%s rate limited; retrying in %.1fs (%d)", provider, wait, rate_limited + 1)
            r.close()
            time.sleep(wait)
            rate_limited += 1
            continue
        if r.status_code not in _RETRY_STATUS or failures == ATTEMPTS - 1:
            return r
        logger.warning("%s call retried after HTTP %s", provider, r.status_code)
        _record(model or _url_model(url), kind, None, started, error=True, provider=provider, reason=f"{_http_reason(r)} (retried)")
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
        # gpt-4.x / gpt-3.5 reject reasoning_effort and verbosity (HTTP 400); a deployment whose name hides that
        # is caught on its first 400 by _post_chat and the two are dropped from then on
        self.reasoning_params = not re.match(r"gpt-(4|35|3\.5)", self.deployment.strip().lower())

    def _payload(self, messages: list[dict]) -> dict:
        from . import llm_effort
        task = llm_effort.current()            # a mechanical task asks for less thinking and a shorter reply
        payload: dict = {"messages": messages, "max_completion_tokens": task.get("max_tokens") or MAX_OUTPUT_TOKENS}
        if not self.reasoning_params:
            return payload
        effort = task.get("effort") or self.reasoning_effort
        if effort:                      # unset: the model's own default
            payload["reasoning_effort"] = effort
        if task.get("verbosity"):
            payload["verbosity"] = task["verbosity"]
        return payload

    def _post_chat(self, headers: dict, payload: dict, **kw) -> requests.Response:
        """_post, retried once without the GPT-5-only parameters when a non-reasoning model rejects them."""
        r = _post(self._url(), headers, payload, **kw)
        if r.status_code == 400 and ("reasoning_effort" in payload or "verbosity" in payload):
            text = r.text.lower()
            if "reasoning_effort" in text or "verbosity" in text or "unrecognized request argument" in text:
                logger.warning("Azure deployment %s rejects reasoning parameters; sending without them", self.deployment)
                r.close()
                self.reasoning_params = False
                payload.pop("reasoning_effort", None)
                payload.pop("verbosity", None)
                r = _post(self._url(), headers, payload, **kw)
        return r

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
        _effort: str | None = None,
    ) -> str:
        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        payload = self._payload(messages)
        if _effort and self.reasoning_params:
            payload["reasoning_effort"] = _effort
        if format_json:
            payload["response_format"] = {"type": "json_object"}

        started = time.time()
        if not on_token:
            r = self._post_chat(headers, payload)
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
                if self.reasoning_params and payload.get("reasoning_effort") not in LOW_EFFORTS:
                    # GPT-5 spent the budget thinking: ask once more with less thinking (the same fix as org models)
                    logger.warning("Azure %s reply cut off; retrying with reasoning_effort=low", self.deployment)
                    return self.chat(messages, format_json=format_json, _effort="low")
                raise ReplyCutOff(f"Azure OpenAI reply cut off at max_completion_tokens={MAX_OUTPUT_TOKENS}")
            return choice["message"]["content"]

        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        full: list[str] = []
        done = cut_off = False
        model, usage = "", None
        r = self._post_chat(headers, payload, stream=True)    # records its own failed attempts
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
            raise ReplyCutOff(f"Azure OpenAI reply cut off at max_completion_tokens={MAX_OUTPUT_TOKENS}")
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
        r = self._post_chat(headers, payload, kind="tools")
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
