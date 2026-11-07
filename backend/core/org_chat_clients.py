"""Chat clients for an organisation's own LLM provider (Settings → LLM Providers).

Each exposes what HybridLLMClient needs from a chat backend: `chat(messages, on_token, format_json)`,
`chat_tools(messages, tools, tool_choice)`, plus `deployment` / `reasoning_effort` for the memory cache key.
  OpenAICompatClient  POST {base}/chat/completions, Bearer key: OpenAI, any OpenAI-compatible server, and Google
                      Gemini through its OpenAI-compatible endpoint.
  AnthropicClient     POST {base}/v1/messages (Claude); messages and tool calls are mapped to and from OpenAI's shape.
Azure OpenAI uses the platform's AzureOpenAIClient with the org's endpoint, key and deployment.
Retries, rate-limit waits and usage rows reuse the Azure client's helpers. Usage is recorded under the model name
the org entered, so its price row applies.
"""
from __future__ import annotations

import json
import time
from typing import Callable, Optional

from .azure_openai_client import MAX_OUTPUT_TOKENS, AzureOpenAIClient, _http_reason, _post, _record

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
PROVIDER_TYPES = ("openai_compatible", "azure_openai", "anthropic", "gemini")


class ProviderCallError(RuntimeError):
    """The org's provider refused or failed a call (message carries the HTTP status and the provider's reason)."""


def _tool_reply(message: dict) -> dict:
    calls = []
    for c in message.get("tool_calls") or []:
        raw = c.get("function", {}).get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            args = {"_raw": raw}
        calls.append({"id": c.get("id", ""), "name": c.get("function", {}).get("name", ""),
                      "arguments": args if isinstance(args, dict) else {"_raw": raw}})
    return {"content": message.get("content"), "tool_calls": calls, "message": message}


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str, model: str, provider: str = "openai_compatible"):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.provider = provider
        self.deployment, self.reasoning_effort = model, ""

    def is_reachable(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def _send(self, payload: dict, kind: str) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        started = time.time()
        r = _post(f"{self.base_url}/chat/completions", headers, {"model": self.model, **payload}, kind=kind,
                  provider=self.provider, model=self.model)
        if r.status_code != 200:
            reason = _http_reason(r)
            _record(self.model, kind, None, started, error=True, reason=reason, provider=self.provider)
            raise ProviderCallError(reason)
        try:
            body = r.json()
        except ValueError:
            _record(self.model, kind, None, started, error=True, reason="Reply was not valid JSON",
                    provider=self.provider)
            raise ProviderCallError("Reply was not valid JSON") from None
        _record(self.model, kind, body.get("usage"), started, provider=self.provider)
        if not body.get("choices"):
            raise ProviderCallError("Reply had no choices")
        return body

    def chat(self, messages: list[dict], on_token: Optional[Callable[[str], None]] = None,
             format_json: bool = False) -> str:
        payload: dict = {"messages": messages}
        if format_json:
            payload["response_format"] = {"type": "json_object"}
        try:
            body = self._send(payload, "chat")
        except ProviderCallError as e:
            if not (format_json and "HTTP 400" in str(e)):
                raise
            body = self._send({"messages": messages}, "chat")   # a server without JSON mode: the prompt asks for JSON
        choice = body["choices"][0]
        if choice.get("finish_reason") == "length":     # raised, not returned: a cut-off reply is never cached
            raise ProviderCallError("Reply cut off at the provider's output limit")
        text = (choice.get("message") or {}).get("content") or ""
        if on_token and text:
            on_token(text)          # shortcut: one chunk, not a token stream; stream if live typing matters here
        return text

    def chat_tools(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        payload: dict = {"messages": messages}
        if tools:
            payload.update(tools=tools, tool_choice=tool_choice)
        return _tool_reply(self._send(payload, "tools")["choices"][0]["message"])


def _blocks(content) -> list[dict]:
    if isinstance(content, list):
        return list(content)
    return [{"type": "text", "text": str(content)}] if content else []


def to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """OpenAI chat messages → (system prompt, Anthropic messages); consecutive turns of one role are merged."""
    system, out = [], []
    for m in messages:
        role = m.get("role")
        if role == "system":
            system.append(str(m.get("content") or ""))
            continue
        if role == "tool":
            role, blocks = "user", [{"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""),
                                     "content": str(m.get("content") or "")}]
        elif role == "assistant":
            blocks = _blocks(m.get("content"))
            for c in m.get("tool_calls") or []:
                raw = c.get("function", {}).get("arguments") or "{}"
                try:
                    args = json.loads(raw) if isinstance(raw, str) else raw
                except json.JSONDecodeError:
                    args = {}
                blocks.append({"type": "tool_use", "id": c.get("id", ""), "name": c.get("function", {}).get("name", ""),
                               "input": args if isinstance(args, dict) else {}})
        else:
            role, blocks = "user", _blocks(m.get("content"))
        if not blocks:
            continue
        if out and out[-1]["role"] == role:
            out[-1] = {"role": role, "content": out[-1]["content"] + blocks}
        else:
            out.append({"role": role, "content": blocks})
    return "\n\n".join(s for s in system if s), out


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        self.api_key, self.model = api_key, model
        self.base_url = (base_url or ANTHROPIC_BASE_URL).rstrip("/")
        self.deployment, self.reasoning_effort = model, ""

    def is_reachable(self) -> bool:
        return bool(self.api_key and self.model)

    def _send(self, messages: list[dict], kind: str, *, tools: list[dict] | None = None, tool_choice: str = "auto",
              format_json: bool = False) -> dict:
        from ..domains.usage import service as usage_service      # lazy: domains import core
        system, conv = to_anthropic(messages)
        if format_json:
            system = (system + "\n\n" if system else "") + "Reply with one JSON object and nothing else."
        payload: dict = {"model": self.model, "max_tokens": MAX_OUTPUT_TOKENS, "messages": conv}
        if system:
            payload["system"] = system
        if tools and tool_choice != "none":
            payload["tools"] = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                                 "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
                                for t in tools]
            payload["tool_choice"] = {"type": "any" if tool_choice == "required" else "auto"}
        headers = {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION, "Content-Type": "application/json"}
        started = time.time()
        r = _post(f"{self.base_url}/v1/messages", headers, payload, kind=kind, provider=self.provider, model=self.model)
        if r.status_code != 200:
            reason = _http_reason(r)
            _record(self.model, kind, None, started, error=True, reason=reason, provider=self.provider)
            raise ProviderCallError(reason)
        try:
            body = r.json()
        except ValueError:
            _record(self.model, kind, None, started, error=True, reason="Reply was not valid JSON",
                    provider=self.provider)
            raise ProviderCallError("Reply was not valid JSON") from None
        u = body.get("usage") or {}
        cached = int(u.get("cache_read_input_tokens") or 0)
        usage_service.record(self.provider, self.model, kind,
                             input_tokens=int(u.get("input_tokens") or 0) + cached
                             + int(u.get("cache_creation_input_tokens") or 0),
                             cached_input_tokens=cached, output_tokens=int(u.get("output_tokens") or 0),
                             latency_ms=int((time.time() - started) * 1000))
        return body

    def chat(self, messages: list[dict], on_token: Optional[Callable[[str], None]] = None,
             format_json: bool = False) -> str:
        body = self._send(messages, "chat", format_json=format_json)
        if body.get("stop_reason") == "max_tokens":
            raise ProviderCallError(f"Reply cut off at max_tokens={MAX_OUTPUT_TOKENS}")
        text = "".join(b.get("text", "") for b in body.get("content") or [] if b.get("type") == "text")
        if on_token and text:
            on_token(text)
        return text

    def chat_tools(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        body = self._send(messages, "tools", tools=tools, tool_choice=tool_choice)
        blocks = body.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text") or None
        calls = [{"id": b.get("id", ""), "type": "function",
                  "function": {"name": b.get("name", ""), "arguments": json.dumps(b.get("input") or {})}}
                 for b in blocks if b.get("type") == "tool_use"]
        message: dict = {"role": "assistant", "content": text}
        if calls:
            message["tool_calls"] = calls
        return _tool_reply(message)


def build(provider_type: str, *, base_url: str, api_key: str, model: str, api_version: str = ""):
    """The chat client for one provider row (key already decrypted)."""
    if provider_type == "azure_openai":
        return AzureOpenAIClient(api_key, base_url, model, api_version or None)
    if provider_type == "anthropic":
        return AnthropicClient(api_key, model, base_url)
    if provider_type == "gemini":
        return OpenAICompatClient(base_url or GEMINI_BASE_URL, api_key, model, provider="gemini")
    if provider_type == "openai_compatible":
        return OpenAICompatClient(base_url, api_key, model)
    raise ValueError(f"Unknown provider type: {provider_type}")
