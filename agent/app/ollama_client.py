"""Thin HTTP wrapper around a local Ollama server for embeddings and chat."""
from __future__ import annotations

import json
from typing import Callable, Iterator, Optional

import numpy as np
import requests


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, host: str, embed_model: str, chat_model: str):
        self.host = host.rstrip("/")
        self.embed_model = embed_model
        self.chat_model = chat_model

    def is_reachable(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def embed(self, text: str) -> np.ndarray:
        r = requests.post(
            f"{self.host}/api/embeddings",
            json={"model": self.embed_model, "prompt": text[:8000]},
            timeout=60,
        )
        if r.status_code != 200:
            raise OllamaError(f"embeddings failed: {r.status_code} {r.text[:300]}")
        data = r.json()
        vec = np.array(data["embedding"], dtype=np.float32)
        return vec

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        return [self.embed(t) for t in texts]

    def chat(
        self,
        messages: list[dict],
        on_token: Optional[Callable[[str], None]] = None,
        format_json: bool = False,
    ) -> str:
        """Streams a chat completion; returns the full text. Calls on_token per chunk."""
        payload = {
            "model": self.chat_model,
            "messages": messages,
            "stream": True,
        }
        if format_json:
            payload["format"] = "json"
        full = []
        with requests.post(f"{self.host}/api/chat", json=payload, stream=True, timeout=600) as r:
            if r.status_code != 200:
                raise OllamaError(f"chat failed: {r.status_code} {r.text[:300]}")
            for line in r.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    full.append(token)
                    if on_token:
                        on_token(token)
                if chunk.get("done"):
                    break
        return "".join(full)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)
