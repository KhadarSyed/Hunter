"""SQLAlchemy tables for guardrails (core/db.py migration 51), plus the organizations columns it reads by name."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

org_guardrails = Table(
    "org_guardrails", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("org_id", BigInteger, nullable=False),
    Column("title", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("active", BigInteger, nullable=False),
    Column("updated_by", BigInteger),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
)

# owned by the auth domain; only the columns read here
organizations = Table(
    "organizations", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("name", Text),
)
