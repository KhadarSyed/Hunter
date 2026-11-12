"""SQLAlchemy tables for the deliverable engine (core/db.py; columns checked against the live schema): runs and their
streamed sections, the article classification cache, the reference-deck index, per-question analysis plans, the
"Refresh latest 7 days" results and a finished deck's stored files. Server defaults (e.g. counts_json, fetched, kept)
are left to Postgres."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, LargeBinary, MetaData, Table, Text

metadata = MetaData()

intel_deliverable_runs = Table(
    "intel_deliverable_runs", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("status", Text, nullable=False),                 # running | completed | failed
    Column("stage", Text),
    Column("stages_json", Text),
    Column("pptx_path", Text),
    Column("docx_path", Text),
    Column("thumbs_dir", Text),
    Column("error", Text),
    Column("created_at", Double, nullable=False),
    Column("finished_at", Double),
    Column("html_path", Text),
    Column("pdf_path", Text),
    Column("studio_pptx_path", Text),
    Column("deck_dir", Text),
)

intel_deliverable_sections = Table(
    "intel_deliverable_sections", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("run_id", BigInteger, nullable=False),
    Column("section_key", Text, nullable=False),
    Column("rq_id", Text),
    Column("module", Text),
    Column("payload_json", Text, nullable=False),
    Column("created_at", Double, nullable=False),
)

intel_article_classifications = Table(
    "intel_article_classifications", metadata,
    Column("norm_url", Text, primary_key=True),
    Column("field", Text, primary_key=True),
    Column("value_json", Text, nullable=False),
    Column("model", Text),
    Column("created_at", Double, nullable=False),
)

intel_reference_decks = Table(
    "intel_reference_decks", metadata,
    Column("path", Text, primary_key=True),
    Column("text", Text),
    Column("embedding_json", Text),
    Column("indexed_at", Double, nullable=False),
    Column("model", Text),
)

intel_deliverable_plans = Table(
    "intel_deliverable_plans", metadata,
    Column("project_id", BigInteger, primary_key=True),
    Column("rq_id", Text, primary_key=True),
    Column("signature", Text, nullable=False),
    Column("plan_json", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("updated_at", Double, nullable=False),
)

intel_latest24h_refreshes = Table(
    "intel_latest24h_refreshes", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("status", Text, nullable=False),                 # running | completed | failed
    Column("started_at", Double, nullable=False),
    Column("finished_at", Double),
    Column("counts_json", Text, nullable=False),            # server default
    Column("fetched", BigInteger, nullable=False),          # server default
    Column("kept", BigInteger, nullable=False),             # server default
    Column("summary_json", Text),
    Column("charts_json", Text),
    Column("articles_json", Text),
    Column("error", Text),
)

intel_deliverable_files = Table(
    "intel_deliverable_files", metadata,
    Column("run_id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("name", Text, primary_key=True),
    Column("part", BigInteger, primary_key=True),
    Column("gz", BigInteger, nullable=False),
    Column("content", LargeBinary, nullable=False),         # a chunk of the file (empty when it lives in S3)
    Column("created_at", Double, nullable=False),
    Column("s3_key", Text),
)
