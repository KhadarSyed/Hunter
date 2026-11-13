"""US spelling for a stored tag value: author_type "Organisation" -> "Organization" (the tagging agent now writes the US
form; old rows would otherwise show both in filters and charts). Plain text replace of json.dumps' exact output, so a
malformed tags_json row is left as it is instead of failing the migration.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-13
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_UK, _US = '"author_type": "Organisation"', '"author_type": "Organization"'


def _swap(old: str, new: str) -> None:
    for table in ("intel_articles", "intel_article_rq"):
        op.execute(f"UPDATE {table} SET tags_json = replace(tags_json, '{old}', '{new}') "
                   f"WHERE tags_json LIKE '%{old}%'")


def upgrade() -> None:
    _swap(_UK, _US)


def downgrade() -> None:
    _swap(_US, _UK)
