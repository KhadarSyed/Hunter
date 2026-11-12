"""Baseline: the schema as built by core/db.py on 2026-11-12 (legacy migrations 1-53), incl. the unused legacy
tables of the deleted products. Generated from pg_dump --schema-only of a fresh database; see ../baseline.sql.

Revision ID: 0001
Revises:
Create Date: 2026-11-12
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # raw driver SQL: no bind-parameter parsing of the dump's '::text' casts
    op.get_bind().exec_driver_sql((Path(__file__).resolve().parent.parent / "baseline.sql").read_text("utf-8"))


def downgrade() -> None:
    raise RuntimeError("The baseline cannot be downgraded: it is the whole schema.")
