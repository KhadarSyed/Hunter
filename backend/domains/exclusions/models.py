"""SQLAlchemy table for the exclusion list (core/db.py: intel_exclusions)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

intel_exclusions = Table(
    "intel_exclusions", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("org_id", BigInteger),                 # NULL = the platform-wide list
    Column("kind", Text, nullable=False),         # domain | keyword
    Column("value", Text, nullable=False),
    Column("created_by", BigInteger),
    Column("created_at", Double, nullable=False),
)
