"""SQLAlchemy tables for the Hunter agent (core/db.py: agent_memory, agent_events, agent_autopilots, agent_issues;
columns checked against the live schema). Columns with a server default (note, seen) are left to Postgres."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text, UniqueConstraint

metadata = MetaData()

agent_memory = Table(
    "agent_memory", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("kind", Text, nullable=False),
    Column("key", Text, nullable=False),
    Column("value_json", Text, nullable=False),
    Column("updated_at", Double, nullable=False),
    UniqueConstraint("project_id", "kind", "key"),
)

agent_events = Table(
    "agent_events", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("run_id", BigInteger),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("detail_json", Text),
    Column("at", Double, nullable=False),
)

agent_autopilots = Table(
    "agent_autopilots", metadata,
    Column("project_id", BigInteger, primary_key=True),
    Column("user_id", BigInteger, nullable=False),
    Column("status", Text, nullable=False),
    Column("note", Text, nullable=False),
    Column("attempts", BigInteger, nullable=False),
    Column("updated_at", Double, nullable=False),
)

agent_issues = Table(
    "agent_issues", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger),
    Column("source", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("detail_json", Text, nullable=False),
    Column("fingerprint", Text, nullable=False),
    Column("status", Text, nullable=False),               # open | triage | fixing | proposed | needs_llm | ...
    Column("note", Text, nullable=False),                 # server default ''
    Column("seen", BigInteger, nullable=False),           # server default 1
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
)
