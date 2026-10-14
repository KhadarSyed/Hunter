"""Global, stable citation numbering across the whole deck."""
from __future__ import annotations

import threading
from urllib.parse import urlparse

from .ingest import Article


def domain_of(url: str) -> str:
    """forbes.com from https://www.forbes.com/... (citations show the source domain icon)."""
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


class CitationRegistry:
    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._entries: list[dict] = []
        self._lock = threading.Lock()          # questions draft their insights in parallel

    @classmethod
    def seeded(cls, entries: list[dict]) -> "CitationRegistry":
        """A registry that continues a finished deck's numbering: its sources keep their numbers, new ones follow."""
        from .ingest import normalize_url
        registry = cls()
        for e in sorted(entries, key=lambda e: int(e["n"])):
            registry._ids[normalize_url(e["url"])] = int(e["n"])
            registry._entries.append({k: e.get(k, "") for k in ("n", "outlet", "title", "url", "date")})
        return registry

    def cite(self, article: Article) -> int:
        with self._lock:
            if article.norm_url not in self._ids:
                n = max(self._ids.values(), default=0) + 1
                self._ids[article.norm_url] = n
                self._entries.append({"n": n, "outlet": article.outlet, "title": article.title, "url": article.url,
                                      "date": article.date.isoformat() if article.date else ""})
            return self._ids[article.norm_url]

    def entries(self) -> list[dict]:
        return list(self._entries)
