"""SQLite-backed memory: run history, live-feed events, the slide index, and chat.

This is the agent's persistent memory of every past run so the UI's History
sidebar can list, replay, and reopen prior work after a restart.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_filename TEXT,
    client_guess TEXT,
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL DEFAULT 'running',
    output_path TEXT
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS slide_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_path TEXT NOT NULL,
    slide_no INTEGER NOT NULL,
    title TEXT,
    body_text TEXT,
    has_chart INTEGER DEFAULT 0,
    has_picture INTEGER DEFAULT 0,
    client_guess TEXT,
    embedding_blob BLOB,
    file_mtime REAL NOT NULL,
    file_hash TEXT NOT NULL,
    UNIQUE(deck_path, slide_no)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id);
CREATE INDEX IF NOT EXISTS idx_slide_index_deck ON slide_index(deck_path);
CREATE INDEX IF NOT EXISTS idx_chat_run_id ON chat_messages(run_id);
"""


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(config.MEMORY_DB_PATH), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def _cursor():
    conn = get_conn()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    finally:
        cur.close()


# ---- runs ----

def create_run(brief_filename: str, client_guess: Optional[str]) -> int:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO runs (brief_filename, client_guess, started_at, status) VALUES (?, ?, ?, 'running')",
            (brief_filename, client_guess, time.time()),
        )
        return cur.lastrowid


def update_run_client(run_id: int, client_guess: str) -> None:
    with _cursor() as cur:
        cur.execute("UPDATE runs SET client_guess=? WHERE id=?", (client_guess, run_id))


def finish_run(run_id: int, status: str, output_path: Optional[str]) -> None:
    with _cursor() as cur:
        cur.execute(
            "UPDATE runs SET status=?, output_path=?, finished_at=? WHERE id=?",
            (status, output_path, time.time(), run_id),
        )


def mark_interrupted_runs() -> int:
    """Any run still 'running' at startup had its worker thread killed by the
    previous process exiting - mark it failed so it doesn't look stuck forever."""
    with _cursor() as cur:
        cur.execute(
            "UPDATE runs SET status='failed', finished_at=? WHERE status='running'",
            (time.time(),),
        )
        return cur.rowcount


def delete_run(run_id: int) -> None:
    with _cursor() as cur:
        cur.execute("DELETE FROM run_events WHERE run_id=?", (run_id,))
        cur.execute("DELETE FROM chat_messages WHERE run_id=?", (run_id,))
        cur.execute("DELETE FROM runs WHERE id=?", (run_id,))


def list_runs(limit: int = 100) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_run(run_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


# ---- run events (live feed + replay) ----

def add_event(run_id: int, event_type: str, payload: dict) -> dict:
    ts = time.time()
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO run_events (run_id, ts, event_type, payload_json) VALUES (?, ?, ?, ?)",
            (run_id, ts, event_type, json.dumps(payload)),
        )
    return {"run_id": run_id, "ts": ts, "event_type": event_type, "payload": payload}


def list_events(run_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT ts, event_type, payload_json FROM run_events WHERE run_id=? ORDER BY id ASC",
        (run_id,),
    ).fetchall()
    return [
        {"ts": r["ts"], "event_type": r["event_type"], "payload": json.loads(r["payload_json"])}
        for r in rows
    ]


# ---- chat ----

def add_chat_message(run_id: Optional[int], role: str, content: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO chat_messages (run_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (run_id, role, content, time.time()),
        )


def clear_chat_messages() -> None:
    with _cursor() as cur:
        cur.execute("DELETE FROM chat_messages WHERE run_id IS NULL")


def list_chat_messages(run_id: Optional[int]) -> list[dict]:
    conn = get_conn()
    if run_id is None:
        rows = conn.execute(
            "SELECT role, content, ts FROM chat_messages WHERE run_id IS NULL ORDER BY id ASC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT role, content, ts FROM chat_messages WHERE run_id=? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---- slide index ----

def upsert_slide(
    deck_path: str,
    slide_no: int,
    title: str,
    body_text: str,
    has_chart: bool,
    has_picture: bool,
    client_guess: str,
    embedding: bytes,
    file_mtime: float,
    file_hash: str,
) -> None:
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO slide_index
                (deck_path, slide_no, title, body_text, has_chart, has_picture,
                 client_guess, embedding_blob, file_mtime, file_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(deck_path, slide_no) DO UPDATE SET
                title=excluded.title,
                body_text=excluded.body_text,
                has_chart=excluded.has_chart,
                has_picture=excluded.has_picture,
                client_guess=excluded.client_guess,
                embedding_blob=excluded.embedding_blob,
                file_mtime=excluded.file_mtime,
                file_hash=excluded.file_hash
            """,
            (
                deck_path,
                slide_no,
                title,
                body_text,
                int(has_chart),
                int(has_picture),
                client_guess,
                embedding,
                file_mtime,
                file_hash,
            ),
        )


def delete_slides_for_deck(deck_path: str) -> None:
    with _cursor() as cur:
        cur.execute("DELETE FROM slide_index WHERE deck_path=?", (deck_path,))


def get_indexed_deck_hashes() -> dict[str, tuple[float, str]]:
    """deck_path -> (file_mtime, file_hash) for one representative row per deck."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT deck_path, MAX(file_mtime) as mtime, file_hash FROM slide_index GROUP BY deck_path"
    ).fetchall()
    return {r["deck_path"]: (r["mtime"], r["file_hash"]) for r in rows}


def all_slides() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, deck_path, slide_no, title, body_text, has_chart, has_picture, "
        "client_guess, embedding_blob FROM slide_index"
    ).fetchall()
    return [dict(r) for r in rows]


def slide_count() -> int:
    conn = get_conn()
    return conn.execute("SELECT COUNT(*) FROM slide_index").fetchone()[0]


def deck_count() -> int:
    conn = get_conn()
    return conn.execute("SELECT COUNT(DISTINCT deck_path) FROM slide_index").fetchone()[0]
