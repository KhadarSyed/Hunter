"""SQLAlchemy tables for research specifications (core/db.py; columns checked against the live schema): spec
versions, per-section approvals, clarifications and the audit trail. Server defaults (approval_status, is_locked)
are left to Postgres."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

intel_research_specifications = Table(
    "intel_research_specifications", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("version", BigInteger, nullable=False),          # 1, 2, ... per project
    Column("spec_json", Text, nullable=False),
    Column("raw_brief_text", Text),
    Column("status", Text, nullable=False),                 # draft | approved | revision_requested
    Column("readiness_status", Text, nullable=False),       # ready | not_ready
    Column("readiness_json", Text),
    Column("approval_status", Text, nullable=False),        # server default
    Column("approved_by", Text),
    Column("approved_at", Double),
    Column("rejected_reason", Text),
    Column("generation_source", Text, nullable=False),
    Column("llm_model", Text),
    Column("docx_path", Text),
    Column("docx_generated_at", Double),
    Column("notes", Text),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
)

intel_spec_section_approvals = Table(
    "intel_spec_section_approvals", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("spec_id", BigInteger, nullable=False),
    Column("section_key", Text, nullable=False),
    Column("status", Text, nullable=False),                 # draft | edited | approved
    Column("is_locked", BigInteger, nullable=False),        # server default 0
    Column("locked_by", Text),
    Column("locked_at", Double),
    Column("edited_content", Text),
    Column("analyst_note", Text),
    Column("reviewed_by", Text),
    Column("reviewed_at", Double),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
)

intel_spec_clarifications = Table(
    "intel_spec_clarifications", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("spec_id", BigInteger, nullable=False),
    Column("section_key", Text),
    Column("question", Text, nullable=False),
    Column("is_blocking", BigInteger, nullable=False),
    Column("answer", Text),
    Column("resolved_by", Text),
    Column("resolved_at", Double),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
)

intel_spec_audit = Table(
    "intel_spec_audit", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("spec_id", BigInteger, nullable=False),
    Column("action", Text, nullable=False),
    Column("section_key", Text),
    Column("field", Text),
    Column("old_value", Text),
    Column("new_value", Text),
    Column("actor", Text, nullable=False),
    Column("created_at", Double, nullable=False),
)
