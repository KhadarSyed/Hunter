"""Postgres behind the small sqlite3 interface the repositories already use (execute / fetchone / fetchall /
lastrowid / rowcount / commit / close, rows readable by name and position). SQL stays written once, in the
SQLite dialect, and is translated here, so setting DATABASE_URL moves the whole app to Postgres.

Foreign keys are dropped from the translated schema on purpose: SQLite never enforced them here, and existing
code inserts child rows before (or without) their parents."""
from __future__ import annotations

import queue
import re
import threading

import psycopg

POOL_SIZE = 10

# ─── SQL translation ────────────────────────────────────────────────────────

_LITERAL = re.compile(r"('(?:[^']|'')*')")
_JSON_EXTRACT = re.compile(r"json_extract\(\s*([\w.]+)\s*,\s*'\$\.(\w+)'\s*\)", re.IGNORECASE)
_LIKE = re.compile(r"\bLIKE\b", re.IGNORECASE)
_PRAGMA = re.compile(r"^\s*PRAGMA\b", re.IGNORECASE)
_INSERT = re.compile(r"^\s*INSERT\b", re.IGNORECASE)
_RETURNING = re.compile(r"\bRETURNING\b", re.IGNORECASE)
_RESERVED = re.compile(r'(?<![\w."])(user)(?![\w"])')      # column names that are reserved words in Postgres
_COMMENT = re.compile(r"--[^\n]*")


def translate(sql: str, has_params: bool) -> str | None:
    """SQLite-dialect SQL to Postgres; None for SQLite-only settings (PRAGMA) that have no Postgres meaning."""
    if _PRAGMA.match(sql):
        return None
    sql = translate_ddl(_JSON_EXTRACT.sub(lambda m: f"({m.group(1)}::json->>'{m.group(2)}')", sql))
    parts = _LITERAL.split(sql)
    out = []
    for i, part in enumerate(parts):
        if i % 2:                                           # a quoted literal: only its % needs escaping
            out.append(part.replace("%", "%%") if has_params else part)
            continue
        part = _LIKE.sub("ILIKE", part)                     # SQLite's LIKE ignores ASCII case
        part = _RESERVED.sub(r'"\1"', part)                 # a column named user would read current_user
        if has_params:
            part = part.replace("%", "%%").replace("?", "%s")
        out.append(part)
    return "".join(out)


_FK_ACTIONS = r"(\s+ON\s+(DELETE|UPDATE)\s+(CASCADE|SET\s+NULL|RESTRICT|NO\s+ACTION))*"
_DDL = [
    (re.compile(r",\s*FOREIGN\s+KEY\s*\([\w\s,]+\)\s*REFERENCES\s+\w+\s*\([\w\s,]+\)" + _FK_ACTIONS, re.I), ""),
    # types are upper case in the schema and column names lower case, so a column named blob keeps its name
    (re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b"), "BIGSERIAL PRIMARY KEY"),
    (re.compile(r"\b(\w+)\s+INTEGER\s+PRIMARY\s+KEY\b"), r"\1 BIGSERIAL PRIMARY KEY"),
    (re.compile(r"\bREAL\b"), "DOUBLE PRECISION"),
    (re.compile(r"\bBLOB\b"), "BYTEA"),
    (re.compile(r"\bINTEGER\b"), "BIGINT"),
    (re.compile(r"\(\s*strftime\('%s',\s*'now'\)\s*\)", re.I), "(EXTRACT(EPOCH FROM now()))"),
    (re.compile(r"\s+REFERENCES\s+\w+\s*\([\w\s,]+\)" + _FK_ACTIONS, re.I), ""),
    (re.compile(r"\bADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS)", re.I), "ADD COLUMN IF NOT EXISTS "),
]


def translate_ddl(sql: str) -> str:
    if not re.match(r"^\s*(CREATE|ALTER)\b", sql, re.I):
        return sql
    for pattern, repl in _DDL:
        sql = pattern.sub(repl, sql)
    return sql


def split_script(script: str) -> list[str]:
    """Statements of a schema script (semicolons inside string literals don't split)."""
    out, buf = [], []
    for i, part in enumerate(_LITERAL.split(script)):
        if i % 2:
            buf.append(part)
            continue
        pieces = _COMMENT.sub("", part).split(";")
        buf.append(pieces[0])
        for piece in pieces[1:]:
            out.append("".join(buf))
            buf = [piece]
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


# ─── Rows, cursors, connections ─────────────────────────────────────────────


class Row:
    """sqlite3.Row lookalike: row["col"], row[0], dict(row), row.keys(), iteration over values."""
    __slots__ = ("_cols", "_index", "_vals")

    def __init__(self, cols: list[str], index: dict[str, int], vals: tuple):
        self._cols, self._index, self._vals = cols, index, vals

    def __getitem__(self, key):
        return self._vals[key] if isinstance(key, (int, slice)) else self._vals[self._index[key]]

    def keys(self) -> list[str]:
        return list(self._cols)

    def __iter__(self):
        return iter(self._vals)

    def __len__(self) -> int:
        return len(self._vals)

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._cols, self._vals))})"


def _row_factory(cursor):
    cols = [d.name for d in cursor.description] if cursor.description else []
    index = {c: i for i, c in enumerate(cols)}
    return lambda values: Row(cols, index, tuple(values))


class Cursor:
    def __init__(self, cur=None, lastrowid=None, first=None):
        self._cur, self.lastrowid, self._first = cur, lastrowid, first

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount if self._cur is not None else -1

    @property
    def description(self):
        return self._cur.description if self._cur is not None else None

    def fetchone(self):
        if self._first is not None:
            row, self._first = self._first, None
            return row
        return self._cur.fetchone() if self._cur is not None and self._cur.description else None

    def fetchall(self) -> list:
        rows = [self._first] if self._first is not None else []
        self._first = None
        return rows + (self._cur.fetchall() if self._cur is not None and self._cur.description else [])

    def __iter__(self):
        return iter(self.fetchall())


def _params(params):
    if not params:
        return None
    if isinstance(params, dict):
        return {k: int(v) if isinstance(v, bool) else v for k, v in params.items()}
    return tuple(int(p) if isinstance(p, bool) else p for p in params)   # SQLite stores booleans as integers


class Connection:
    """One pooled Postgres connection; close() hands it back to the pool."""

    def __init__(self, raw: psycopg.Connection, pool: "Pool"):
        self._raw, self._pool = raw, pool
        self.row_factory = None                               # accepted for sqlite3 compatibility, unused

    def execute(self, sql: str, params=()) -> Cursor:
        values = _params(params)
        pg = translate(sql, values is not None)
        if pg is None:
            return Cursor()
        cur = self._raw.cursor()
        insert = bool(_INSERT.match(pg)) and not _RETURNING.search(pg)
        cur.execute(pg + (" RETURNING *" if insert else ""), values)
        if not insert:
            return Cursor(cur)
        first = cur.fetchone() if cur.description else None
        lastrowid = first["id"] if first is not None and "id" in first.keys() else None
        return Cursor(cur, lastrowid, first)

    def use_schema(self, name: str) -> None:
        """Work inside schema `name` (created on first use): tests give each throwaway database its own."""
        if name not in _schemas:
            self._raw.execute(f'CREATE SCHEMA IF NOT EXISTS "{name}"')
            _schemas.add(name)
        self._raw.execute(f'SET search_path TO "{name}"')
        self._raw.commit()

    def cursor(self) -> "StatementCursor":
        return StatementCursor(self)

    def executemany(self, sql: str, seq) -> None:
        for params in seq:
            self.execute(sql, params)

    def executescript(self, script: str) -> None:
        for statement in split_script(script):
            self.execute(statement)
        self.commit()

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        if self._raw is not None:
            self._pool.give_back(self._raw)
            self._raw = None

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, exc_type, *_):                         # sqlite3 semantics: commit or roll back, stay open
        self.rollback() if exc_type else self.commit()
        return False


class StatementCursor:
    """sqlite3's conn.cursor(): execute() on it, then lastrowid / fetchone / fetchall from the last statement."""

    def __init__(self, conn: Connection):
        self._conn, self._last = conn, Cursor()

    def execute(self, sql: str, params=()) -> "StatementCursor":
        self._last = self._conn.execute(sql, params)
        return self

    def executemany(self, sql: str, seq) -> None:
        self._conn.executemany(sql, seq)

    @property
    def lastrowid(self):
        return self._last.lastrowid

    @property
    def rowcount(self) -> int:
        return self._last.rowcount

    def fetchone(self):
        return self._last.fetchone()

    def fetchall(self) -> list:
        return self._last.fetchall()

    def __iter__(self):
        return iter(self.fetchall())

    def close(self) -> None:
        pass


class Pool:
    def __init__(self, url: str, size: int = POOL_SIZE):
        self._url, self._idle = url, queue.LifoQueue(maxsize=size)

    def take(self) -> Connection:
        try:
            raw = self._idle.get_nowait()
            if raw.closed or raw.broken:
                raw = None
        except queue.Empty:
            raw = None
        if raw is None:
            raw = psycopg.connect(self._url, row_factory=_row_factory, connect_timeout=10)
        return Connection(raw, self)

    def give_back(self, raw: psycopg.Connection) -> None:
        try:
            if not raw.closed:
                raw.rollback()                                # never hand on an open or failed transaction
            self._idle.put_nowait(raw)
        except (queue.Full, psycopg.Error):
            raw.close()


_pools: dict[str, Pool] = {}
_schemas: set[str] = set()
_lock = threading.Lock()


def connect(url: str) -> Connection:
    with _lock:
        pool = _pools.get(url) or _pools.setdefault(url, Pool(url))
    return pool.take()
