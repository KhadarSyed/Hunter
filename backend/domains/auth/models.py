"""SQLAlchemy tables for organizations, users, sessions, memberships and password resets — every column, as created
by core/db.py's migrations (checked against the live schema 2026-11-12), plus the intel_projects columns auth writes
when an org is archived or a user's projects are reassigned."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text, UniqueConstraint

metadata = MetaData()

organizations = Table(
    "organizations", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("name", Text, nullable=False),
    Column("background_image_url", Text),
    Column("created_at", Double, nullable=False),
    Column("archived_at", Double),
    Column("platform_llm", BigInteger, nullable=False),             # 1 = chat runs on the platform model
    Column("logo_url", Text),
    Column("procurement_name", Text),
    Column("procurement_email", Text),
    Column("procurement_phone", Text),
    Column("address", Text),
    Column("country", Text),
    Column("pin_code", Text),
    Column("allow_editorial_images", BigInteger, nullable=False),
)

users = Table(
    "users", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("org_id", BigInteger),                                    # NULL for a Super Admin
    Column("email", Text, nullable=False),                           # stored lower-cased and trimmed
    Column("password_hash", Text, nullable=False),                   # bcrypt
    Column("display_name", Text, nullable=False),
    Column("avatar_url", Text),
    Column("role", Text, nullable=False),                            # super_admin | admin | analyser
    Column("must_change_password", BigInteger, nullable=False),
    Column("failed_login_count", BigInteger, nullable=False),
    Column("locked_until", Double),
    Column("created_at", Double, nullable=False),
    Column("archived_at", Double),
)

sessions = Table(
    "sessions", metadata,
    Column("token", Text, primary_key=True),
    Column("user_id", BigInteger, nullable=False),
    Column("created_at", Double, nullable=False),
    Column("expires_at", Double, nullable=False),
    Column("active_org_id", BigInteger),                             # org picked in the profile menu
)

user_organizations = Table(
    "user_organizations", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("user_id", BigInteger, nullable=False),
    Column("org_id", BigInteger, nullable=False),
    Column("added_at", Double, nullable=False),
    UniqueConstraint("user_id", "org_id"),
)

password_resets = Table(
    "password_resets", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("user_id", BigInteger, nullable=False),
    Column("otp_hash", Text),                                        # SHA-256 of "<user id>:<6-digit code>"
    Column("otp_expires", Double),
    Column("attempts", BigInteger, nullable=False),
    Column("verified_at", Double),
    Column("token_hash", Text),                                      # SHA-256 of the emailed link token
    Column("token_expires", Double),
    Column("used_at", Double),
    Column("created_at", Double, nullable=False),
)

# owned by the projects domain; only the columns auth reads or writes
intel_projects = Table(
    "intel_projects", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_name", Text),
    Column("org_id", BigInteger),
    Column("owner_user_id", BigInteger),
    Column("archived_at", Double),
)
