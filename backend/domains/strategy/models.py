"""SQLAlchemy tables for Search Strategy (core/db.py; columns checked against the live schema): strategy versions,
query versions, uploaded datasets and their stored bytes, sample evaluations, and the per-question dimensions and
tag schemas; plus the Data set rows an RQ deletion removes (intel_article_rq, owned by the dataset domain)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, LargeBinary, MetaData, Table, Text

metadata = MetaData()

intel_search_strategies = Table(
    "intel_search_strategies", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("version", BigInteger, nullable=False),          # 1, 2, ... per project
    Column("status", Text, nullable=False),
    Column("strategy_json", Text, nullable=False),          # research_question_queries, query_versions, last_rq_number
    Column("approval_status", Text),
    Column("approved_by", Text),
    Column("approved_at", Double),
    Column("notes", Text),
    Column("created_at", Double, nullable=False),
)

intel_query_versions = Table(
    "intel_query_versions", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("strategy_id", BigInteger, nullable=False),
    Column("version_label", Text, nullable=False),
    Column("query_type", Text, nullable=False),
    Column("query_text", Text, nullable=False),
    Column("is_active", BigInteger),
    Column("created_at", Double, nullable=False),
)

intel_datasets = Table(
    "intel_datasets", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("file_name", Text, nullable=False),
    Column("file_path", Text, nullable=False),
    Column("record_count", BigInteger, nullable=False),
    Column("column_mapping_json", Text),
    Column("stats_json", Text),
    Column("preview_json", Text),
    Column("approval_status", Text),
    Column("approved_by", Text),
    Column("approved_at", Double),
    Column("created_at", Double, nullable=False),
    Column("processing_status", Text),
    Column("processing_error", Text),
    Column("research_question_id", Text),
    Column("enrichment_status", Text),
    Column("enrichment_json", Text),
    Column("enrichment_error", Text),
)

intel_dataset_files = Table(
    "intel_dataset_files", metadata,
    Column("dataset_id", BigInteger, primary_key=True),
    Column("file_name", Text, nullable=False),
    Column("content", LargeBinary, nullable=False),         # the upload's bytes (the disk may not survive a restart)
    Column("created_at", Double, nullable=False),
)

intel_sample_evaluations = Table(
    "intel_sample_evaluations", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("strategy_id", BigInteger, nullable=False),
    Column("file_name", Text, nullable=False),
    Column("file_path", Text, nullable=False),
    Column("evaluation_json", Text),
    Column("status", Text, nullable=False),                 # pending | completed
    Column("created_at", Double, nullable=False),
)

intel_question_dimensions = Table(
    "intel_question_dimensions", metadata,
    Column("project_id", BigInteger, primary_key=True),
    Column("rq_id", Text, primary_key=True),
    Column("signature", Text, nullable=False),
    Column("dimensions_json", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("updated_at", Double, nullable=False),
)

intel_question_tag_schemas = Table(
    "intel_question_tag_schemas", metadata,
    Column("project_id", BigInteger, primary_key=True),
    Column("rq_id", Text, primary_key=True),
    Column("signature", Text, nullable=False),
    Column("schema_json", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("updated_at", Double, nullable=False),
)

# owned by the dataset domain; only the columns an RQ deletion needs
intel_article_rq = Table(
    "intel_article_rq", metadata,
    Column("project_id", BigInteger),
    Column("rq_id", Text),
)
