"""org_llm_providers.enabled: a saved model can be switched off. A model switched off is never called, not even as a
fallback when the default is down (domains/providers/service._rows); the default is always switched on.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-14
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE org_llm_providers ADD COLUMN enabled BIGINT NOT NULL DEFAULT 1")


def downgrade() -> None:
    op.execute("ALTER TABLE org_llm_providers DROP COLUMN enabled")
