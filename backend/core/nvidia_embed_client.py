"""NVIDIA NIM embeddings client.

Talks to NVIDIA's OpenAI-compatible embeddings endpoint directly via `requests`,
configured from EMBEDDING_MODEL_API_KEY/BASE_URL/NAME, falling back to NVIDIA_EMBED_API_KEY/API_URL/MODEL.
"""
from __future__ import annotations

import logging
import os
import time

import numpy as np
import requests

logger = logging.getLogger(__name__)


class NvidiaEmbedError(RuntimeError):
    pass


def env_setting(*names: str, default: str = "") -> str:
    """First non-empty env var among `names`, whitespace and surrounding quotes stripped."""
    for name in names:
        value = os.getenv(name, "").strip().strip("\"'").strip()
        if value:
            return value
    return default


def embed_model_name() -> str:
    return env_setting("EMBEDDING_MODEL_NAME", "NVIDIA_EMBED_MODEL")


class NvidiaEmbedClient:
    def __init__(self, api_key: str | None = None, api_url: str | None = None, model: str | None = None):
        self.api_key = api_key or env_setting("EMBEDDING_MODEL_API_KEY", "NVIDIA_EMBED_API_KEY")
        self.api_url = (api_url or env_setting("EMBEDDING_MODEL_BASE_URL", "NVIDIA_EMBED_API_URL",
                                               default="https://integrate.api.nvidia.com/v1")).rstrip("/")
        self.model = model or embed_model_name()

    def is_reachable(self) -> bool:
        return bool(self.api_key and self.api_url and self.model)

    def _embed_texts(self, texts: list[str], input_type: str = "passage") -> list[np.ndarray]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "input": [t[:8000] for t in texts],
            "model": self.model,
            "input_type": input_type,
            "encoding_format": "float",
        }
        from ..domains.usage import service as usage_service      # lazy: domains import core
        started = time.time()
        try:
            r = requests.post(f"{self.api_url}/embeddings", headers=headers, json=payload, timeout=60)
        except requests.RequestException as e:
            usage_service.record("nvidia", self.model, "embed", error=True, reason=type(e).__name__,
                                 latency_ms=int((time.time() - started) * 1000))
            raise
        if r.status_code != 200:
            usage_service.record("nvidia", self.model, "embed", error=True, reason=f"HTTP {r.status_code}: {r.text[:120]}",
                                 latency_ms=int((time.time() - started) * 1000))
            raise NvidiaEmbedError(f"NVIDIA embeddings failed: {r.status_code} {r.text[:300]}")
        data = r.json()
        u = data.get("usage") or {}
        tokens = int(u.get("prompt_tokens") or u.get("total_tokens") or sum(len(t) for t in payload["input"]) // 4)
        usage_service.record("nvidia", data.get("model") or self.model, "embed", input_tokens=tokens, credits=1,
                             latency_ms=int((time.time() - started) * 1000))
        items = sorted(data["data"], key=lambda item: item.get("index", 0))
        return [np.array(item["embedding"], dtype=np.float32) for item in items]

    def embed(self, text: str) -> np.ndarray:
        return self._embed_texts([text], input_type="passage")[0]

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        return self._embed_texts(texts, input_type="passage")
