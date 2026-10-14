"""One-off copy of the SQLite database (data/memory.db) into Postgres.

    python -m database.pg_migrate --url postgresql://hunter:hunter@127.0.0.1:5433/hunter
    python -m database.pg_migrate --url ... --replace        # empty the Postgres tables first

Reads SQLite only; never writes to it. Builds the Postgres schema, copies every table's shared columns with COPY,
moves each id sequence past the copied ids, and prints per-table row counts on both sides."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import psycopg

from backend.core import config


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _pg_columns(pg: psycopg.Connection, table: str) -> list[str]:
    return [r[0] for r in pg.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = "
                                     "current_schema() AND table_name = %s ORDER BY ordinal_position", (table,))]


def _reset_sequence(pg: psycopg.Connection, table: str) -> None:
    seq = pg.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,)).fetchone()[0]
    if seq:
        pg.execute(f'SELECT setval(%s, COALESCE((SELECT max(id) FROM "{table}"), 0) + 1, false)', (seq,))


def copy_all(sqlite_path: Path, url: str, replace: bool = False) -> list[tuple[str, int, int]]:
    with psycopg.connect(url, connect_timeout=10) as pg:
        if _pg_columns(pg, "schema_migrations") and not replace:
            raise SystemExit("Postgres already holds a Hunter schema; rerun with --replace to overwrite its data")
    os.environ["DATABASE_URL"] = url
    from . import db                                      # build both schemas through the app's own path
    from backend.deck import memory
    db.init_intelligence_db()
    memory.init_db()
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    report = []
    with psycopg.connect(url, connect_timeout=10) as pg:
        for table in _sqlite_tables(src):
            if table == "schema_migrations":               # the Postgres schema records its own
                continue
            target = _pg_columns(pg, table)
            if not target:
                print(f"  skip {table}: not in the Postgres schema")
                continue
            source = [r[1] for r in src.execute(f"PRAGMA table_info('{table}')")]
            cols = [c for c in source if c in target]
            pg.execute(f'TRUNCATE "{table}"')               # seed rows (e.g. Default Organization) give way to real data
            quoted = ", ".join(f'"{c}"' for c in cols)
            with pg.cursor().copy(f'COPY "{table}" ({quoted}) FROM STDIN') as copy:
                for row in src.execute(f"SELECT {', '.join(cols)} FROM \"{table}\""):
                    copy.write_row(row)
            if "id" in target:
                _reset_sequence(pg, table)
            n_src = src.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            n_dst = pg.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            report.append((table, n_src, n_dst))
        pg.commit()
    src.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="Postgres DATABASE_URL to copy into")
    parser.add_argument("--sqlite", default=str(config.MEMORY_DB_PATH), help="SQLite file to copy from")
    parser.add_argument("--replace", action="store_true", help="empty Postgres tables that already hold rows")
    args = parser.parse_args(argv)
    report = copy_all(Path(args.sqlite), args.url, args.replace)
    mismatched = [r for r in report if r[1] != r[2]]
    for table, n_src, n_dst in report:
        print(f"{'OK ' if n_src == n_dst else 'BAD'} {table:45s} sqlite={n_src:7d} postgres={n_dst:7d}")
    print(f"{len(report)} tables copied, {len(mismatched)} with mismatched counts")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
