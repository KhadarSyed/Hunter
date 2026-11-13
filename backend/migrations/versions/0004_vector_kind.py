"""intel_research_item_vectors keyed by (kind, item_id): Background Research items ("research") and Data set
articles ("article") come from two tables whose ids overlap, so one id read and overwrote the other's vector.
Stored rows cannot be told apart and are only a cache of embeddings, so they are cleared and re-embedded on use.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM intel_research_item_vectors")
    op.execute("ALTER TABLE intel_research_item_vectors ADD COLUMN kind TEXT NOT NULL DEFAULT 'research'")
    op.execute("ALTER TABLE intel_research_item_vectors DROP CONSTRAINT intel_research_item_vectors_pkey")
    op.execute("ALTER TABLE intel_research_item_vectors ADD PRIMARY KEY (kind, item_id)")


def downgrade() -> None:
    op.execute("DELETE FROM intel_research_item_vectors WHERE kind <> 'research'")
    op.execute("ALTER TABLE intel_research_item_vectors DROP CONSTRAINT intel_research_item_vectors_pkey")
    op.execute("ALTER TABLE intel_research_item_vectors DROP COLUMN kind")
    op.execute("ALTER TABLE intel_research_item_vectors ADD PRIMARY KEY (item_id)")
