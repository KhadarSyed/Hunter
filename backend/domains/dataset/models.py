"""SQLAlchemy tables for the Data set (core/db.py migrations 37, 43, 44; columns checked against the live schema):
uploaded files, project-wide articles, one row per (article, research question), and theme titles; plus the two
columns of other domains' tables this one reads or writes (project data-set approval, active deck runs).
Server defaults (empty strings, 'pending' statuses, 0 counters) are left to Postgres."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, LargeBinary, MetaData, Table, Text

metadata = MetaData()

intel_upload_files = Table(
    "intel_upload_files", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("file_name", Text, nullable=False),
    Column("s3_key", Text),
    Column("content", LargeBinary),                 # the upload's bytes when S3 is not configured
    Column("rows_read", BigInteger, nullable=False),
    Column("added", BigInteger, nullable=False),
    Column("duplicates", BigInteger, nullable=False),
    Column("error", Text),
    Column("uploaded_by", Text),
    Column("created_at", Double, nullable=False),
)

intel_articles = Table(
    "intel_articles", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("norm_url", Text, nullable=False),        # unique per project: the dedupe key
    Column("url", Text, nullable=False),
    Column("channel", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("outlet", Text, nullable=False),
    Column("published", Text),
    Column("country", Text, nullable=False),
    Column("reach", Double, nullable=False),
    Column("author_name", Text, nullable=False),
    Column("author_id", Text, nullable=False),
    Column("post_id", Text, nullable=False),
    Column("raw_json", Text, nullable=False),
    Column("file_id", BigInteger),
    Column("content", Text, nullable=False),
    Column("content_status", Text, nullable=False),  # pending | full_text | ... | not_needed
    Column("tags_json", Text),                       # {"themes": {...}, "brands": [{"brand": ...}], ...}
    Column("tag_status", Text, nullable=False),      # pending | tagged | failed
    Column("tag_error", Text),
    Column("sentiment", Text),
    Column("sentiment_confidence", Double),
    Column("syndicated_json", Text),
    Column("similar_json", Text),
    Column("created_at", Double, nullable=False),
    Column("rq_matched", BigInteger),                # 1 matched a question, 0 Irrelevant, NULL not matched yet
    Column("copy_of", BigInteger),                   # the original of a syndicated copy
    Column("excluded_reason", Text),
    Column("keep_by", Text),
    Column("keep_at", Double),
    Column("keep_comment", Text),
)

intel_article_rq = Table(
    "intel_article_rq", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("article_id", BigInteger, nullable=False),   # unique with rq_id
    Column("rq_id", Text, nullable=False),
    Column("signature", Text, nullable=False),
    Column("matched", BigInteger, nullable=False),
    Column("match_confidence", Double),
    Column("keywords_json", Text, nullable=False),
    Column("tags_json", Text, nullable=False),
    Column("evidence_json", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("status", Text, nullable=False),             # pending | approved | irrelevant
    Column("decided_by", Text),
    Column("decided_at", Double),
    Column("decision_reason", Text),
    Column("tagged_at", Double),
    Column("query_changed", BigInteger, nullable=False),
)

intel_theme_titles = Table(
    "intel_theme_titles", metadata,
    Column("project_id", BigInteger, primary_key=True),
    Column("label_key", Text, primary_key=True),
    Column("title", Text, nullable=False),
)

# owned by the projects domain; only the data-set approval columns
intel_projects = Table(
    "intel_projects", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("dataset_approved_at", Double),
    Column("dataset_approved_by", Text),
)

# owned by the deliverable domain; only what "is a deck running" reads
intel_deliverable_runs = Table(
    "intel_deliverable_runs", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger),
    Column("status", Text),
)
