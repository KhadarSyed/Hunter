"""SQLAlchemy table for small shared assets kept in Postgres (core/db.py: intel_assets). The S3-backed asset library
(intel_asset_library, library.py) stays on core/pg.py until it moves: it uses pgvector."""
from __future__ import annotations

from sqlalchemy import Column, Double, LargeBinary, MetaData, Table, Text

metadata = MetaData()

intel_assets = Table(
    "intel_assets", metadata,
    Column("kind", Text, primary_key=True),
    Column("key", Text, primary_key=True),
    Column("content", LargeBinary, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("meta_json", Text, nullable=False),
    Column("created_at", Double, nullable=False),
)
