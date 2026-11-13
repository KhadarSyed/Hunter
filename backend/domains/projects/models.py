"""SQLAlchemy tables for projects and their background jobs (core/db.py: intel_projects, intel_jobs; columns checked
against the live schema)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

intel_projects = Table(
    "intel_projects", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_name", Text, nullable=False),
    Column("spec_json", Text, nullable=False),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
    Column("project_type", Text, nullable=False),           # server default 'research'
    Column("brand", Text),                                  # the Client name from the New Project form
    Column("org_id", BigInteger),
    Column("owner_user_id", BigInteger),
    Column("archived_at", Double),
    Column("dataset_approved_at", Double),
    Column("dataset_approved_by", Text),
)

intel_jobs = Table(
    "intel_jobs", metadata,
    Column("id", Text, primary_key=True),                   # job id chosen by the caller
    Column("project_id", BigInteger, nullable=False),
    Column("job_type", Text, nullable=False),
    Column("status", Text, nullable=False),                 # pending | running | completed | failed | cancelled
    Column("progress_pct", BigInteger),
    Column("progress_message", Text),
    Column("result_json", Text),
    Column("error", Text),
    Column("started_at", Double),
    Column("finished_at", Double),
    Column("created_at", Double, nullable=False),
    Column("params_json", Text),                            # inputs + scope, to start it again after a restart
)

intel_checkpoints = Table(                                  # migration 0006: finished steps of a job or deck run
    "intel_checkpoints", metadata,
    Column("owner", Text, primary_key=True),                # "job:<id>" | "deck:<run id>"
    Column("step", Text, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("created_at", Double, nullable=False),
)
