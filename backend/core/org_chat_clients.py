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

from .azure_openai_client import MAX_OUTPUT_TOKENS, AzureOpenAIClient, ReplyCutOff, _http_reason, _post, _record

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


class ProviderCallError(RuntimeError):
    """The org's provider refused or failed a call (message carries the HTTP status and the provider's reason)."""


class _RetryWithoutUsage(Exception):
    """HTTP 400 on a stream: the server may not know stream_options, or the model's limit is below max_tokens."""


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

    def _stream(self, payload: dict, kind: str, on_token: Optional[Callable[[str], None]] = None,
                usage_opt: bool = True, cap: bool = True) -> tuple[str, list[dict], str | None]:
        """One streamed call: (text, tool calls in OpenAI shape, finish_reason). Every call streams: a proxy behind
        Cloudflare cuts a silent connection at ~100 s (HTTP 524/502), and some proxies (VyceAI) only serve streams.
        An error sent inside the stream raises. Usage comes from the last chunk."""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        # same output cap as the Azure / Anthropic clients: a reasoning model left uncapped streamed one reply 30+ min
        body = {"model": self.model, **({"max_tokens": MAX_OUTPUT_TOKENS} if cap else {}), **payload, "stream": True}
        if usage_opt:
            body["stream_options"] = {"include_usage": True}
        started = time.time()
        r = _post(f"{self.base_url}/chat/completions", headers, body, stream=True, kind=kind, provider=self.provider,
                  model=self.model)
        text: list[str] = []
        calls: dict[int, dict] = {}
        usage, finish, done = None, None, False
        try:
            with r:
                if r.status_code != 200:
                    reason = _http_reason(r)
                    # a 400 may be a server without stream_options, then a model whose limit is below our cap:
                    # ask once without each
                    if r.status_code == 400 and (usage_opt or cap):
                        raise _RetryWithoutUsage(reason)
                    raise ProviderCallError(reason)
                for line in r.iter_lines():
                    if not line.startswith(b"data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == b"[DONE]":
                        done = True
                        break
                    chunk = json.loads(raw)
                    if chunk.get("error"):
                        err = chunk["error"]
                        raise ProviderCallError(str(err.get("message") if isinstance(err, dict) else err)[:200])
                    usage = chunk.get("usage") or usage
                    for ch in chunk.get("choices") or []:
                        delta = ch.get("delta") or {}
                        if delta.get("content"):
                            text.append(delta["content"])
                            if on_token:
                                on_token(delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(int(tc.get("index") or 0), {"id": "", "name": "", "args": []})
                            fn = tc.get("function") or {}
                            slot["id"] = tc.get("id") or slot["id"]
                            slot["name"] += fn.get("name") or ""
                            slot["args"].append(fn.get("arguments") or "")
                        finish = ch.get("finish_reason") or finish
        except _RetryWithoutUsage:
            if usage_opt:
                return self._stream(payload, kind, on_token, usage_opt=False, cap=cap)
            return self._stream(payload, kind, on_token, usage_opt=False, cap=False)
        except ProviderCallError as e:
            _record(self.model, kind, usage, started, error=True, reason=str(e), provider=self.provider)
            raise
        except Exception as e:
            reason = f"Stream failed: {type(e).__name__}"
            _record(self.model, kind, usage, started, error=True, reason=reason, provider=self.provider)
            raise ProviderCallError(reason) from e
        out = "".join(text)
        if usage is None:   # shortcut: ~4 characters a token when the server reports no usage; exact once it does
            usage = {"prompt_tokens": len(json.dumps(payload.get("messages", ""))) // 4,
                     "completion_tokens": len(out) // 4}
        _record(self.model, kind, usage, started, provider=self.provider)
        if not done and finish is None:     # a stream cut before its end is never returned (or cached) as an answer
            raise ProviderCallError("Stream ended before the reply finished")
        tool_calls = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": "".join(c["args"])}}
                      for _, c in sorted(calls.items())]
        return out, tool_calls, finish

    def chat(self, messages: list[dict], on_token: Optional[Callable[[str], None]] = None,
             format_json: bool = False) -> str:
        payload: dict = {"messages": messages}
        if format_json:
            payload["response_format"] = {"type": "json_object"}
        try:
            text, _, finish = self._stream(payload, "chat", on_token)
        except ProviderCallError as e:
            if not (format_json and "HTTP 400" in str(e)):
                raise
            text, _, finish = self._stream({"messages": messages}, "chat", on_token)   # no JSON mode: the prompt asks
        if finish == "length":     # raised, not returned: a cut-off reply is never cached
            raise ReplyCutOff("Reply cut off at the provider's output limit")
        return text

    def chat_tools(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        payload: dict = {"messages": messages}
        if tools:
            payload.update(tools=tools, tool_choice=tool_choice)
        text, calls, _ = self._stream(payload, "tools")
        message: dict = {"role": "assistant", "content": text or None}
        if calls:
            message["tool_calls"] = calls
        return _tool_reply(message)


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
            raise ReplyCutOff(f"Reply cut off at max_tokens={MAX_OUTPUT_TOKENS}")
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
