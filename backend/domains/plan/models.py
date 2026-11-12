"""SQLAlchemy table for research plans (core/db.py: intel_research_plans; columns checked against the live schema)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

intel_research_plans = Table(
    "intel_research_plans", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("version", BigInteger, nullable=False),          # 1, 2, ... per project
    Column("status", Text, nullable=False),                 # draft
    Column("plan_json", Text, nullable=False),
    Column("source", Text, nullable=False),                 # llm | deterministic
    Column("approval_status", Text),                        # approved | rejected
    Column("approved_by", Text),
    Column("approved_at", Double),
    Column("notes", Text),
    Column("created_at", Double, nullable=False),
)
