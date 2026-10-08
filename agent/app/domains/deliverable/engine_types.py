"""Data shapes shared by every deliverable-engine stage."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .ingest import Article


@dataclass
class EngineRow:
    article: Article
    rq_ids: set[str]
    copies: int = 1
    story_key: str = ""
    media_type: str = ""
    themes: list[str] = field(default_factory=list)
    entities: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)          # question dimension key -> values the LLM tagged
    author_type: str = ""
    brand_mention: str = ""                           # enrichment's literal / figurative / none
    dynamic_tags: dict = field(default_factory=dict)  # question-driven tags (deal_sale_led: Yes, ...)
    tag_evidence: dict = field(default_factory=dict)  # tag -> the article's own quote supporting it


@dataclass
class RQ:
    id: str
    question: str
    query: str = ""


@dataclass
class Section:
    id: str
    rq_id: str | None
    module: str
    title: str
    chart: dict | None = None
    table: dict | None = None
    facts: list[str] = field(default_factory=list)
    candidate_urls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
