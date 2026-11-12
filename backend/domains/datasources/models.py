"""SQLAlchemy table for org-managed data source credentials (core/db.py: org_data_sources)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

org_data_sources = Table(
    "org_data_sources", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("org_id", BigInteger, nullable=False),
    Column("source", Text, nullable=False),             # tavily | serpapi | firecrawl
    Column("api_key", Text, nullable=False),            # Fernet token (core/secret_box); plain only in legacy rows
    Column("status", Text, nullable=False),             # ok | expired
    Column("expired_at", Double),
    Column("last_error", Text),
    Column("updated_at", Double, nullable=False),
    Column("updated_by_user_id", BigInteger),
    Column("settings_json", Text, nullable=False),
)
