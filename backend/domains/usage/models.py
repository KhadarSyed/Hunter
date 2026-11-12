"""SQLAlchemy tables for LLM usage, model prices and usage settings (core/db.py: llm_usage, llm_prices, llm_settings;
sub_stage and error_reason added by migrations 41/42), plus the project/user columns the dashboards join."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

llm_usage = Table(
    "llm_usage", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("ts", Double, nullable=False),
    Column("org_id", BigInteger),
    Column("project_id", BigInteger),
    Column("stage", Text, nullable=False),
    Column("user_id", BigInteger),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("deployment_type", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("input_tokens", BigInteger, nullable=False),
    Column("cached_input_tokens", BigInteger, nullable=False),
    Column("output_tokens", BigInteger, nullable=False),
    Column("total_tokens", BigInteger, nullable=False),
    Column("requests", BigInteger, nullable=False),
    Column("credits", Double, nullable=False),
    Column("latency_ms", BigInteger, nullable=False),
    Column("cache_hit", BigInteger, nullable=False),
    Column("error", BigInteger, nullable=False),
    Column("cost_usd", Double, nullable=False),
    Column("sub_stage", Text, nullable=False),
    Column("error_reason", Text, nullable=False),
)

llm_prices = Table(
    "llm_prices", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("deployment_type", Text, nullable=False),
    Column("input_per_m", Double, nullable=False),
    Column("cached_per_m", Double, nullable=False),
    Column("output_per_m", Double, nullable=False),
    Column("effective_from", Text, nullable=False),        # YYYY-MM-DD (UTC day)
    Column("source", Text, nullable=False),
)

llm_settings = Table(
    "llm_settings", metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
)

# owned by the projects / auth domains; only the columns read here
intel_projects = Table(
    "intel_projects", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_name", Text),
    Column("org_id", BigInteger),
    Column("owner_user_id", BigInteger),
)

users = Table(
    "users", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("display_name", Text),
)
