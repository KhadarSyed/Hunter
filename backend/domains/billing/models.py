"""SQLAlchemy table definitions for billing (the tables created by core/db.py migration 50), plus read-only column
subsets of other domains' tables that billing's queries join. Those subsets move to their owning domain's models.py
when that domain leaves core/pg.py. Column types mirror the Postgres schema (INTEGER→BIGINT, REAL→DOUBLE PRECISION)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

# ─── billing's own tables ───────────────────────────────────────────────────────────────────────────────────

subscription_plans = Table(
    "subscription_plans", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("name", Text, nullable=False),
    Column("max_users", BigInteger, nullable=False),
    Column("max_projects", BigInteger, nullable=False),
    Column("duration_months", BigInteger, nullable=False),
    Column("price", Double, nullable=False),
    Column("currency", Text, nullable=False),
    Column("active", BigInteger, nullable=False),
    Column("created_at", Double, nullable=False),
)

org_subscriptions = Table(
    "org_subscriptions", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("org_id", BigInteger, nullable=False),
    Column("plan_id", BigInteger, nullable=False),
    Column("status", Text, nullable=False),                 # pending_payment | active | queued | expired | cancelled
    Column("starts_at", Double),
    Column("ends_at", Double),
    Column("payment_ref", Text),
    Column("reminders", Text, nullable=False),
    Column("created_by", BigInteger),
    Column("created_at", Double, nullable=False),
)

user_token_limits = Table(
    "user_token_limits", metadata,
    Column("user_id", BigInteger, primary_key=True),
    Column("monthly_tokens", BigInteger),
    Column("notified_period", Text, nullable=False),
    Column("updated_at", Double, nullable=False),
)

# ─── other domains' tables (only the columns billing reads) ─────────────────────────────────────────────────

ORG_PROFILE_FIELDS = ("logo_url", "procurement_name", "procurement_email", "procurement_phone", "address",
                      "country", "pin_code")

organizations = Table(
    "organizations", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("name", Text),
    Column("archived_at", Double),
    Column("created_at", Double),
    *(Column(f, Text) for f in ORG_PROFILE_FIELDS),
)

users = Table(
    "users", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("org_id", BigInteger),
    Column("email", Text),
    Column("display_name", Text),
    Column("role", Text),
    Column("archived_at", Double),
    Column("created_at", Double),
)

user_organizations = Table(
    "user_organizations", metadata,
    Column("user_id", BigInteger),
    Column("org_id", BigInteger),
)

sessions = Table(
    "sessions", metadata,
    Column("user_id", BigInteger),
    Column("created_at", Double),
)

intel_projects = Table(
    "intel_projects", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_name", Text),
    Column("brand", Text),
    Column("org_id", BigInteger),
    Column("owner_user_id", BigInteger),
    Column("archived_at", Double),
    Column("created_at", Double),
    Column("updated_at", Double),
)

llm_usage = Table(
    "llm_usage", metadata,
    Column("ts", Double),
    Column("org_id", BigInteger),
    Column("project_id", BigInteger),
    Column("user_id", BigInteger),
    Column("total_tokens", BigInteger),
)
