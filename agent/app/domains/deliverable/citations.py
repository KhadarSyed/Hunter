"""Global, stable citation numbering across the whole deck."""
from __future__ import annotations

from .ingest import Article


class CitationRegistry:
    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._entries: list[dict] = []

    def cite(self, article: Article) -> int:
        if article.norm_url not in self._ids:
            n = len(self._entries) + 1
            self._ids[article.norm_url] = n
            self._entries.append({"n": n, "outlet": article.outlet, "title": article.title, "url": article.url,
                                  "date": article.date.isoformat() if article.date else ""})
        return self._ids[article.norm_url]

    def entries(self) -> list[dict]:
        return list(self._entries)
