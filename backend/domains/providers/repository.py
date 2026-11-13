"""An organisation's own chat LLM providers (org_llm_providers, migration 46) and outage state (org_llm_state),
through SQLAlchemy Core. This module's own `update`/`delete` are repository functions, so SQLAlchemy's are aliased."""
from __future__ import annotations

import time

from sqlalchemy import delete as sql_delete
from sqlalchemy import insert, select
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import sa
from .models import intel_projects, org_llm_providers as p, org_llm_state as st

FIELDS = ("name", "provider_type", "base_url", "model", "api_version", "reads_images")
_OUTAGE = ("acting_provider_id", "down_since", "failed_calls", "notified", "paused", "last_error")


def _rows(query) -> list[dict]:
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(query)]


def _first(query) -> dict | None:
    rows = _rows(query.limit(1))
    return rows[0] if rows else None


def list_for_org(org_id: int) -> list[dict]:
    """The default first, then newest first."""
    return _rows(select(p).where(p.c.org_id == org_id).order_by(p.c.is_default.desc(), p.c.id.desc()))


def orgs_using_model(provider_type: str, model: str) -> set[int]:
    """Organisations with a provider row for this model (prices are shared per provider type and model)."""
    return {r["org_id"] for r in _rows(select(p.c.org_id).distinct()
                                       .where(p.c.provider_type == provider_type, p.c.model == model))}


def newest_for_org(org_id: int) -> dict | None:
    return _first(select(p).where(p.c.org_id == org_id).order_by(p.c.id.desc()))


def get(provider_id: int) -> dict | None:
    return _first(select(p).where(p.c.id == provider_id))


def default_for_org(org_id: int) -> dict | None:
    return _first(select(p).where(p.c.org_id == org_id, p.c.is_default == 1).order_by(p.c.id))


def create(org_id: int, fields: dict, key_enc: str, key_hint: str, user_id: int) -> int:
    now = time.time()
    with sa.begin() as conn:
        return int(conn.execute(insert(p).values(
            org_id=org_id, **{f: fields[f] for f in FIELDS}, api_key_enc=key_enc, key_hint=key_hint,
            is_default=0, status="untested", last_error="", created_at=now, updated_at=now,
            updated_by_user_id=user_id).returning(p.c.id)).scalar_one())


def update(provider_id: int, fields: dict, key_enc: str | None, key_hint: str | None, user_id: int) -> None:
    """A changed connection is untested again."""
    values = {f: fields[f] for f in FIELDS}
    if key_enc is not None:
        values.update(api_key_enc=key_enc, key_hint=key_hint)
    with sa.begin() as conn:
        conn.execute(sql_update(p).where(p.c.id == provider_id).values(
            **values, status="untested", last_error="", updated_at=time.time(), updated_by_user_id=user_id))


def delete(provider_id: int) -> None:
    with sa.begin() as conn:
        conn.execute(sql_delete(p).where(p.c.id == provider_id))


def set_default(org_id: int, provider_id: int | None) -> None:
    """One default per org; None clears it (the org goes back to the platform model). One transaction."""
    with sa.begin() as conn:
        conn.execute(sql_update(p).where(p.c.org_id == org_id).values(is_default=0))
        if provider_id is not None:
            conn.execute(sql_update(p).where(p.c.id == provider_id, p.c.org_id == org_id).values(is_default=1))


def set_reads_images(provider_id: int, value: int | None) -> None:
    with sa.begin() as conn:
        conn.execute(sql_update(p).where(p.c.id == provider_id).values(reads_images=value))


def record_test(provider_id: int, ok: bool, error: str, latency_ms: int) -> None:
    with sa.begin() as conn:
        conn.execute(sql_update(p).where(p.c.id == provider_id).values(
            status="ok" if ok else "failed", last_error=error[:300], last_tested_at=time.time(),
            last_latency_ms=latency_ms))


def project_org(project_id: int) -> int | None:
    row = _first(select(intel_projects.c.org_id).where(intel_projects.c.id == project_id))
    return row["org_id"] if row else None


def get_outage(org_id: int) -> dict | None:
    row = _first(select(st).where(st.c.org_id == org_id))
    return {k: row[k] for k in _OUTAGE} if row else None


def save_outage(org_id: int, state: dict) -> None:
    stmt = pg_insert(st).values(org_id=org_id, **{k: state[k] for k in _OUTAGE}, updated_at=time.time())
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=[st.c.org_id], set_={
            c: stmt.excluded[c] for c in (*_OUTAGE, "updated_at")}))


def clear_outage(org_id: int) -> None:
    with sa.begin() as conn:
        conn.execute(sql_delete(st).where(st.c.org_id == org_id))
