"""SQLAlchemy tables for an organisation's own chat LLM providers (core/db.py migration 46: org_llm_providers;
migration 49: org_llm_state), plus the intel_projects columns read to find a project's org."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

org_llm_providers = Table(
    "org_llm_providers", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("org_id", BigInteger, nullable=False),
    Column("name", Text, nullable=False),
    Column("provider_type", Text, nullable=False),
    Column("base_url", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("api_version", Text, nullable=False),
    Column("api_key_enc", Text, nullable=False),        # Fernet token (core/secret_box)
    Column("key_hint", Text, nullable=False),
    Column("is_default", BigInteger, nullable=False),
    Column("status", Text, nullable=False),             # untested | ok | failed
    Column("last_error", Text, nullable=False),
    Column("last_tested_at", Double),
    Column("last_latency_ms", BigInteger),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
    Column("updated_by_user_id", BigInteger),
    Column("reads_images", BigInteger),                 # 1 yes, 0 no, NULL not known (migration 0006)
)

org_llm_state = Table(
    "org_llm_state", metadata,
    Column("org_id", BigInteger, primary_key=True),
    Column("acting_provider_id", BigInteger),
    Column("down_since", Double, nullable=False),
    Column("failed_calls", BigInteger, nullable=False),
    Column("notified", Text, nullable=False),
    Column("paused", BigInteger, nullable=False),
    Column("last_error", Text, nullable=False),
    Column("updated_at", Double, nullable=False),
)

# owned by the projects domain; only the columns read here
intel_projects = Table(
    "intel_projects", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("org_id", BigInteger),
)
