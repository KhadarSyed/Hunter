"""SQLAlchemy tables for the reference deck library (core/db.py: deck_reference_decks, deck_reference_slides;
columns checked against the live schema)."""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, Double, MetaData, Table, Text

metadata = MetaData()

deck_reference_decks = Table(
    "deck_reference_decks", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("path", Text, nullable=False, unique=True),
    Column("hash", Text, nullable=False),
    Column("family", Text, nullable=False),
    Column("n_slides", BigInteger, nullable=False),
    Column("indexed_at", Double, nullable=False),
)

deck_reference_slides = Table(
    "deck_reference_slides", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("deck_id", BigInteger, nullable=False),
    Column("n", BigInteger, nullable=False),                # slide number in its deck
    Column("type", Text, nullable=False),
    Column("features_json", Text, nullable=False),
)
