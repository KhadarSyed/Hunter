"""NVIDIA NIM embeddings client - drop-in replacement for OllamaClient.embed().

Talks to NVIDIA's OpenAI-compatible embeddings endpoint directly via `requests`,
configured from: NVIDIA_EMBED_API_KEY, NVIDIA_EMBED_API_URL, NVIDIA_EMBED_MODEL.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import requests

logger = logging.getLogger(__name__)


class NvidiaEmbedError(RuntimeError):
    pass


class NvidiaEmbedClient:
    def __init__(self, api_key: str | None = None, api_url: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("NVIDIA_EMBED_API_KEY", "")
        self.api_url = (api_url or os.getenv("NVIDIA_EMBED_API_URL", "https://integrate.api.nvidia.com/v1")).rstrip("/")
        self.model = model or os.getenv("NVIDIA_EMBED_MODEL", "")

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
        r = requests.post(f"{self.api_url}/embeddings", headers=headers, json=payload, timeout=60)
        if r.status_code != 200:
            raise NvidiaEmbedError(f"NVIDIA embeddings failed: {r.status_code} {r.text[:300]}")
        data = r.json()
        items = sorted(data["data"], key=lambda item: item.get("index", 0))
        return [np.array(item["embedding"], dtype=np.float32) for item in items]

    def embed(self, text: str) -> np.ndarray:
        return self._embed_texts([text], input_type="passage")[0]

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        return self._embed_texts(texts, input_type="passage")
