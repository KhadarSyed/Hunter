"""Base class for pluggable analytical method executors.

Each analytical method (e.g. "Theme Clustering", "Sentiment Analysis") used by
the Research Executor implements this interface. Executors are deterministic:
given the same records and context they always produce the same evidence.
"""

from abc import ABC, abstractmethod


class BaseMethodExecutor(ABC):
    """Base class for all analytical method executors."""

    name: str  # e.g., "Theme Clustering"

    @abstractmethod
    def execute(self, records: list[dict], context: dict) -> list[dict]:
        """Execute the method on a filtered dataset subset.

        Args:
            records: List of data records (dicts with keys like content, headline,
                     source, date, sentiment, author, reach, engagement).
            context: Dict with execution context:
                - unit_id: str
                - objective_id: str
                - objective: str (the research question text)
                - search_concepts: list[str]
                - platforms: list[str]
                - evidence_target: str
                - brand_name: str
                - category: str

        Returns:
            List of evidence dicts, each with:
                - evidence_type: str (e.g., "theme", "sentiment_distribution", "volume_trend")
                - platform: str | None
                - source: str | None
                - date: str | None
                - text_excerpt: str (verbatim from data, max 500 chars)
                - metrics: dict (method-specific metrics)
                - confidence: "high" | "medium" | "low"
                - rationale: str (why this is evidence)
        """
        ...

    def preprocess(self, records: list[dict], required_fields: list[str]) -> list[dict]:
        """Filter records to those containing all required fields."""
        result = []
        for r in records:
            if all(r.get(f) for f in required_fields):
                result.append(r)
        return result

    def _truncate(self, text: str, max_len: int = 500) -> str:
        if not text:
            return ""
        return text[:max_len] + ("..." if len(text) > max_len else "")
