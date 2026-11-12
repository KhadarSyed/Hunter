"""Postgres access for org-managed data source credentials (Tavily, SerpAPI, Firecrawl), through SQLAlchemy Core.

Keys are encrypted at rest with the same Fernet box as the LLM provider keys (core/secret_box). Rows written before
encryption hold the plain key; `encrypt_legacy_keys()` (startup) converts them, and reads accept either form."""
from __future__ import annotations

import json
import logging
import time

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import sa, secret_box
from .models import org_data_sources as ds

logger = logging.getLogger(__name__)
SOURCES = ("tavily", "serpapi", "firecrawl")
_FERNET_PREFIX = "gAAAA"          # every Fernet token starts with this (version byte + timestamp)


def _seal(api_key: str) -> str:
    return secret_box.encrypt(api_key)


def _open(stored: str | None) -> str | None:
    if not stored:
        return None
    if not stored.startswith(_FERNET_PREFIX):
        return stored                  # a row from before encryption; encrypt_legacy_keys() converts it
    try:
        return secret_box.decrypt(stored)
    except secret_box.SecretUnreadable:
        logger.warning("a data source key could not be decrypted (PROVIDER_SECRET_KEY changed?)")
        return None


def _plain(row) -> dict:
    out = dict(row._mapping)
    out["api_key"] = _open(out.get("api_key")) or ""
    try:
        out["settings"] = json.loads(out.get("settings_json") or "{}")
    except ValueError:
        out["settings"] = {}
    return out


def _where(org_id: int, source: str):
    return (ds.c.org_id == org_id, ds.c.source == source)


def upsert_key(org_id: int, source: str, api_key: str, user_id: int, status: str = "ok",
               error: str | None = None, settings: dict | None = None) -> dict:
    """Admin sets/replaces the org's key for a source (stored encrypted). Settings, when given, replace the old ones."""
    stmt = pg_insert(ds).values(org_id=org_id, source=source, api_key=_seal(api_key), status=status, expired_at=None,
                                last_error=error, updated_at=time.time(), updated_by_user_id=user_id,
                                settings_json=json.dumps(settings or {}))
    changed = ["api_key", "status", "expired_at", "last_error", "updated_at", "updated_by_user_id"]
    if settings is not None:
        changed.append("settings_json")
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=[ds.c.org_id, ds.c.source],
                                                set_={c: stmt.excluded[c] for c in changed}))
        return _plain(conn.execute(select(ds).where(*_where(org_id, source))).one())


def update_settings(org_id: int, source: str, settings: dict) -> dict | None:
    with sa.begin() as conn:
        conn.execute(update(ds).where(*_where(org_id, source))
                     .values(settings_json=json.dumps(settings), updated_at=time.time()))
        row = conn.execute(select(ds).where(*_where(org_id, source))).first()
    return _plain(row) if row else None


def delete_key(org_id: int, source: str) -> bool:
    with sa.begin() as conn:
        return bool(conn.execute(delete(ds).where(*_where(org_id, source))).rowcount)


def get_org_sources(org_id: int) -> list[dict]:
    """All configured sources for an org, keys decrypted (callers exposing them must mask; see schemas.py)."""
    with sa.begin() as conn:
        rows = conn.execute(select(ds).where(ds.c.org_id == org_id)).all()
    return [_plain(r) for r in rows]


def get_source(org_id: int, source: str) -> dict | None:
    with sa.begin() as conn:
        row = conn.execute(select(ds).where(*_where(org_id, source))).first()
    return _plain(row) if row else None


def get_key(org_id: int, source: str) -> str | None:
    """The decrypted key for internal use by the research pipeline; None when the org has not configured it."""
    row = get_source(org_id, source)
    return (row["api_key"] or None) if row else None


def mark_status(org_id: int, source: str, status: str, error: str | None = None) -> None:
    """Reactively flip a configured source's status after a real call succeeds/fails (no-op when not configured)."""
    now = time.time()
    with sa.begin() as conn:
        conn.execute(update(ds).where(*_where(org_id, source)).values(
            status=status, expired_at=now if status == "expired" else None, last_error=error, updated_at=now))


def encrypt_legacy_keys() -> int:
    """Startup, idempotent: plain keys saved before encryption are encrypted in place. Returns how many."""
    with sa.begin() as conn:
        legacy = [r for r in conn.execute(select(ds.c.id, ds.c.api_key)).all()
                  if r.api_key and not r.api_key.startswith(_FERNET_PREFIX)]
        for r in legacy:
            conn.execute(update(ds).where(ds.c.id == r.id).values(api_key=_seal(r.api_key)))
    return len(legacy)
