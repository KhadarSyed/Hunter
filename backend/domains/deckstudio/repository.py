"""The reference deck library (slide types and features learned from reference decks), through SQLAlchemy Core."""
from __future__ import annotations

import json
import time
from typing import Optional

from sqlalchemy import delete, insert, select, update

from ...core import sa
from .models import deck_reference_decks as decks
from .models import deck_reference_slides as slides

# core/store.py star-imports this module: export only the repository functions
__all__ = ["upsert_library_deck", "get_library_deck", "list_library_decks", "delete_library_deck",
           "replace_library_slides", "list_library_slides"]


def upsert_library_deck(path: str, digest: str, family: str, n_slides: int) -> int:
    values = {"hash": digest, "family": family, "n_slides": n_slides, "indexed_at": time.time()}
    with sa.begin() as conn:
        deck_id = conn.execute(select(decks.c.id).where(decks.c.path == path)).scalar()
        if deck_id is not None:
            conn.execute(update(decks).where(decks.c.id == deck_id).values(**values))
            return deck_id
        return conn.execute(insert(decks).values(path=path, **values).returning(decks.c.id)).scalar_one()


def get_library_deck(path: str) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(select(decks).where(decks.c.path == path)).first()
    return dict(row._mapping) if row else None


def list_library_decks() -> list[dict]:
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(select(decks).order_by(decks.c.path))]


def delete_library_deck(path: str) -> None:
    with sa.begin() as conn:
        deck_id = conn.execute(select(decks.c.id).where(decks.c.path == path)).scalar()
        if deck_id is not None:
            conn.execute(delete(slides).where(slides.c.deck_id == deck_id))
            conn.execute(delete(decks).where(decks.c.id == deck_id))


def replace_library_slides(deck_id: int, deck_slides: list[dict]) -> None:
    with sa.begin() as conn:
        conn.execute(delete(slides).where(slides.c.deck_id == deck_id))
        if deck_slides:
            conn.execute(insert(slides), [{"deck_id": deck_id, "n": s["n"], "type": s["type"],
                                           "features_json": json.dumps(s.get("features") or {}, default=str)}
                                          for s in deck_slides])


def list_library_slides(slide_type: str | None = None) -> list[dict]:
    q = (select(slides.c.deck_id, slides.c.n, slides.c.type, slides.c.features_json, decks.c.path.label("deck_path"),
                decks.c.family).join(decks, decks.c.id == slides.c.deck_id).order_by(decks.c.path, slides.c.n))
    if slide_type:
        q = q.where(slides.c.type == slide_type)
    with sa.begin() as conn:
        rows = conn.execute(q).all()
    return [{"deck_id": r.deck_id, "deck_path": r.deck_path, "family": r.family, "n": r.n, "type": r.type,
             "features": json.loads(r.features_json)} for r in rows]
