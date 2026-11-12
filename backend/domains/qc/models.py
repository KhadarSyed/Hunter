"""SQLAlchemy tables for the QC flow (core/db.py: qc_reports, qc_runs, qc_findings, qc_exports; columns checked
against the live schema). JSON-shaped columns hold text written with json.dumps."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

qc_reports = Table(
    "qc_reports", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("file_name", Text, nullable=False),
    Column("file_path", Text, nullable=False),              # local disk path of the upload (not kept in S3 yet)
    Column("row_count", BigInteger),
    Column("column_count", BigInteger),
    Column("columns_json", Text),
    Column("field_mapping", Text),
    Column("parse_status", Text),
    Column("parse_error", Text),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
)

qc_runs = Table(
    "qc_runs", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("report_id", BigInteger, nullable=False),
    Column("status", Text),                                 # pending | running | completed | failed
    Column("total_rows", BigInteger),
    Column("total_checks", BigInteger),
    Column("total_findings", BigInteger),
    Column("score", Double),
    Column("score_breakdown", Text),
    Column("started_at", Double),
    Column("completed_at", Double),
    Column("created_at", Double, nullable=False),
)

qc_findings = Table(
    "qc_findings", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("run_id", BigInteger, nullable=False),
    Column("report_id", BigInteger, nullable=False),
    Column("check_type", Text, nullable=False),
    Column("row_number", BigInteger),
    Column("column_name", Text),
    Column("severity", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("expected", Text),
    Column("actual", Text),
    Column("source_url", Text),
    Column("analyst_action", Text),
    Column("created_at", Double, nullable=False),
)

qc_exports = Table(
    "qc_exports", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("run_id", BigInteger, nullable=False),
    Column("file_name", Text, nullable=False),
    Column("file_path", Text, nullable=False),              # local disk path (not kept in S3 yet)
    Column("format", Text),
    Column("created_at", Double, nullable=False),
)


# the QC link checker's cache: the latest fetch of each source URL (core/db.py QC_SCHEMA; columns from the live DB)
qc_source_cache = Table(
    "qc_source_cache", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("url", Text, nullable=False),
    Column("status_code", BigInteger),
    Column("is_accessible", BigInteger),
    Column("is_paywalled", BigInteger),
    Column("extracted_headline", Text),
    Column("extracted_date", Text),
    Column("extracted_text", Text),
    Column("fetch_error", Text),
    Column("fetched_at", Double, nullable=False),
)
