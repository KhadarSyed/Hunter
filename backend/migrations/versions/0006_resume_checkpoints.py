"""Resume after a restart, and which models read images.

- intel_jobs.params_json: a job's inputs (and the user/org it runs for), so a job still running or queued when the
  server stopped is started again at the next startup instead of being cancelled.
- intel_checkpoints: what a job or deck run already finished (one row per step), so a resumed job continues from its
  last finished step. Owner is "job:<id>" or "deck:<run id>"; the rows are deleted when the job ends.
- org_llm_providers.reads_images: 1 yes, 0 no, NULL not known yet. A request with images skips models marked 0, and a
  model that rejects an image is marked 0 automatically.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-13
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE intel_jobs ADD COLUMN params_json TEXT")
    op.execute("""
        CREATE TABLE intel_checkpoints (
            owner TEXT NOT NULL,
            step TEXT NOT NULL,
            project_id BIGINT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (owner, step)
        )""")
    op.execute("CREATE INDEX intel_checkpoints_project ON intel_checkpoints (project_id)")
    op.execute("ALTER TABLE org_llm_providers ADD COLUMN reads_images BIGINT")


def downgrade() -> None:
    op.execute("ALTER TABLE org_llm_providers DROP COLUMN reads_images")
    op.execute("DROP TABLE intel_checkpoints")
    op.execute("ALTER TABLE intel_jobs DROP COLUMN params_json")
