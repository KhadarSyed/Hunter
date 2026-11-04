"""SQLite access for the reference deck library (slide types and features learned from reference decks)."""
from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn


def upsert_library_deck(path: str, digest: str, family: str, n_slides: int) -> int:
    conn = _conn()
    row = conn.execute("SELECT id FROM deck_reference_decks WHERE path = ?", (path,)).fetchone()
    if row:
        conn.execute("UPDATE deck_reference_decks SET hash = ?, family = ?, n_slides = ?, indexed_at = ? WHERE id = ?",
                     (digest, family, n_slides, time.time(), row["id"]))
        deck_id = row["id"]
    else:
        deck_id = conn.execute("INSERT INTO deck_reference_decks (path, hash, family, n_slides, indexed_at) "
                               "VALUES (?, ?, ?, ?, ?)", (path, digest, family, n_slides, time.time())).lastrowid
    conn.commit()
    conn.close()
    return deck_id


def get_library_deck(path: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM deck_reference_decks WHERE path = ?", (path,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_library_decks() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM deck_reference_decks ORDER BY path").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_library_deck(path: str) -> None:
    conn = _conn()
    row = conn.execute("SELECT id FROM deck_reference_decks WHERE path = ?", (path,)).fetchone()
    if row:
        conn.execute("DELETE FROM deck_reference_slides WHERE deck_id = ?", (row["id"],))
        conn.execute("DELETE FROM deck_reference_decks WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()


def replace_library_slides(deck_id: int, slides: list[dict]) -> None:
    conn = _conn()
    conn.execute("DELETE FROM deck_reference_slides WHERE deck_id = ?", (deck_id,))
    conn.executemany("INSERT INTO deck_reference_slides (deck_id, n, type, features_json) VALUES (?, ?, ?, ?)",
                     [(deck_id, s["n"], s["type"], json.dumps(s.get("features") or {}, default=str)) for s in slides])
    conn.commit()
    conn.close()


def list_library_slides(slide_type: str | None = None) -> list[dict]:
    conn = _conn()
    sql = ("SELECT s.deck_id, s.n, s.type, s.features_json, d.path AS deck_path, d.family "
           "FROM deck_reference_slides s JOIN deck_reference_decks d ON d.id = s.deck_id")
    rows = conn.execute(sql + (" WHERE s.type = ?" if slide_type else "") + " ORDER BY d.path, s.n",
                        (slide_type,) if slide_type else ()).fetchall()
    conn.close()
    return [{"deck_id": r["deck_id"], "deck_path": r["deck_path"], "family": r["family"], "n": r["n"],
             "type": r["type"], "features": json.loads(r["features_json"])} for r in rows]
