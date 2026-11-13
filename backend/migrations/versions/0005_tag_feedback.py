"""intel_tag_feedback: analysts' corrections of the AI's tags (edits, rejections, articles marked relevant), each with
the article's embedding, so later tagging in the same organization is shown the closest past corrections.
Learning belongs to the organization: source_project_id is not named project_id, so deleting a project keeps it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE intel_tag_feedback (
            id BIGSERIAL PRIMARY KEY,
            org_id BIGINT,
            source_project_id BIGINT,
            article_id BIGINT,
            rq_id TEXT,
            question TEXT,
            kind TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            comment TEXT,
            article_text TEXT NOT NULL,
            embedding vector,
            model TEXT,
            created_by TEXT,
            created_at DOUBLE PRECISION NOT NULL
        )""")
    op.execute("CREATE INDEX intel_tag_feedback_org ON intel_tag_feedback (org_id, kind)")


def downgrade() -> None:
    op.execute("DROP TABLE intel_tag_feedback")
