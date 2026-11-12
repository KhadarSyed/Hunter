"""SQLAlchemy tables for Background Research: research versions, news approvals, the brand-logo / Pexels / YouTube
lookup caches, the multi-source research items and their embeddings (core/db.py; columns checked against the live
schema)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, LargeBinary, MetaData, Table, Text, UniqueConstraint

metadata = MetaData()

intel_background_research = Table(
    "intel_background_research", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("version", BigInteger, nullable=False),          # 1, 2, ... per project
    Column("status", Text, nullable=False),
    Column("research_json", Text, nullable=False),
    Column("llm_output_json", Text),
    Column("approval_status", Text),                        # approved | revision_requested
    Column("approved_by", Text),
    Column("approved_at", Double),
    Column("notes", Text),
    Column("created_at", Double, nullable=False),
)

intel_news_approvals = Table(
    "intel_news_approvals", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("research_id", BigInteger, nullable=False),
    Column("item_index", BigInteger, nullable=False),
    Column("status", Text, nullable=False),
    Column("notes", Text),
    Column("updated_at", Double, nullable=False),
)

brand_logos = Table(
    "brand_logos", metadata,
    Column("brand_key", Text, primary_key=True),
    Column("brand_name", Text, nullable=False),
    Column("logo_url", Text),
    Column("domain", Text),
    Column("source", Text, nullable=False),
    Column("fetched_at", Double, nullable=False),
)

pexels_images = Table(
    "pexels_images", metadata,
    Column("query_key", Text, primary_key=True),
    Column("query_text", Text, nullable=False),
    Column("image_url", Text),
    Column("photographer", Text),
    Column("source_url", Text),
    Column("fetched_at", Double, nullable=False),
    Column("video_url", Text),
)

youtube_videos = Table(
    "youtube_videos", metadata,
    Column("query_key", Text, primary_key=True),
    Column("query_text", Text, nullable=False),
    Column("video_id", Text),
    Column("embed_url", Text),
    Column("title", Text),
    Column("thumbnail_url", Text),
    Column("fetched_at", Double, nullable=False),
)

intel_research_items = Table(
    "intel_research_items", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("research_id", BigInteger),
    Column("topic", Text, nullable=False),
    Column("source_api", Text, nullable=False),             # comma-joined: every source that reported the URL
    Column("platform", Text),
    Column("publication", Text),
    Column("published_date", Double, nullable=False),
    Column("title", Text),
    Column("content", Text),
    Column("url", Text, nullable=False),
    Column("created_at", Double, nullable=False),
    Column("author", Text),
    Column("thumbnail_url", Text),
    Column("access", Text),
    Column("about_brand", Double),
    Column("sentiment", Text),
    Column("sentiment_confidence", Double),
    Column("classified_for", Text),
    UniqueConstraint("project_id", "url"),
)

intel_research_item_vectors = Table(
    "intel_research_item_vectors", metadata,
    Column("item_id", BigInteger, primary_key=True),
    Column("model", Text, nullable=False),
    Column("dim", BigInteger, nullable=False),
    Column("vector", LargeBinary, nullable=False),          # float32 bytes
    Column("created_at", Double, nullable=False),
)
