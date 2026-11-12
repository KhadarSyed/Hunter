"""SQLAlchemy tables for analyst orientation briefs and their section edits (core/db.py: intel_background_briefs,
intel_brief_section_edits; columns checked against the live schema)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

intel_background_briefs = Table(
    "intel_background_briefs", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("project_id", BigInteger, nullable=False),
    Column("research_id", BigInteger, nullable=False),
    Column("version", BigInteger, nullable=False),          # 1, 2, ... per project
    Column("brief_json", Text, nullable=False),
    Column("status", Text, nullable=False),                 # draft
    Column("approval_status", Text),                        # approved | revision_requested
    Column("approved_by", Text),
    Column("approved_at", Double),
    Column("docx_path", Text),
    Column("docx_generated_at", Double),
    Column("notes", Text),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
)

intel_brief_section_edits = Table(
    "intel_brief_section_edits", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("brief_id", BigInteger, nullable=False),
    Column("section_key", Text, nullable=False),
    Column("edited_content", Text, nullable=False),
    Column("analyst_note", Text),
    Column("edited_by", Text),
    Column("created_at", Double, nullable=False),
)
