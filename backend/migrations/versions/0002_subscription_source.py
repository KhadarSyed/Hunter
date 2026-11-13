"""org_subscriptions.payment_ref -> source: the app takes no payments; every plan is applied by a Super Admin
("granted"). Rows from the removed test checkout keep the value "checkout".

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("org_subscriptions", "payment_ref", new_column_name="source")
    op.execute("UPDATE org_subscriptions SET source = 'checkout' WHERE source IS DISTINCT FROM 'granted'")


def downgrade() -> None:
    op.alter_column("org_subscriptions", "source", new_column_name="payment_ref")
