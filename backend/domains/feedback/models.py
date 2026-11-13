"""SQLAlchemy table for analyst corrections (migration 0005)."""
from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

intel_tag_feedback = Table(
    "intel_tag_feedback", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("org_id", BigInteger),
    Column("source_project_id", BigInteger),        # not "project_id": the organization keeps it after a project goes
    Column("article_id", BigInteger),
    Column("rq_id", Text),
    Column("question", Text),
    Column("kind", Text, nullable=False),           # edit | reject | relevant | keep
    Column("before_json", Text),
    Column("after_json", Text),
    Column("comment", Text),
    Column("article_text", Text, nullable=False),   # title + opening, what the embedding was made from
    Column("embedding", Vector()),                  # untyped: the embedding model sets the dimension; None if it failed
    Column("model", Text),
    Column("created_by", Text),
    Column("created_at", Double, nullable=False),
)
