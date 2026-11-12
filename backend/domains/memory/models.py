"""SQLAlchemy table for the agentic memory store (core/db.py migration 32: memory_items)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

memory_items = Table(
    "memory_items", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("scope", Text, nullable=False),
    Column("scope_id", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("key", Text, nullable=False),
    Column("value_json", Text, nullable=False),
    Column("hits", BigInteger, nullable=False),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
    Column("expires_at", Double),                 # NULL = never expires
)
