"""SQLAlchemy tables for shared assets (core/db.py): intel_assets (small assets kept in Postgres when S3 is off) and
intel_asset_library (library.py: one row per S3-stored asset, its summary and pgvector embedding; migration 35)."""
from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Column, Double, LargeBinary, MetaData, Table, Text

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

intel_asset_library = Table(
    "intel_asset_library", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("kind", Text, nullable=False),               # unique with key
    Column("key", Text, nullable=False),
    Column("s3_key", Text),                             # None for a remembered "this source has none"
    Column("content_type", Text, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("brand", Text, nullable=False),              # lower-cased
    Column("summary", Text, nullable=False),
    Column("meta_json", Text, nullable=False),
    Column("embedding", Vector()),                      # untyped vector: the embedding model sets the dimension
    Column("missing", BigInteger, nullable=False),
    Column("use_count", BigInteger, nullable=False),    # server default 0
    Column("last_used_at", Double),
    Column("created_at", Double, nullable=False),
)
