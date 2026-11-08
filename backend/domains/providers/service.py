"""Which chat backend an organisation's calls use, and the Test connection call.

Every chat call reads the request's or job's usage scope (domains/usage/service.SCOPE): the project's org when a
project is in scope, else the user's active org. An org with a default provider (the newest one added, unless an
admin picked another) sends every chat call there and never falls back to the platform model (a failure raises
OrgProviderError naming the provider). The platform Azure OpenAI model serves only a platform-model org
(InfoVision, organizations.platform_llm) without a provider of its own, and calls with no org in scope. Any other
org without a provider gets OrgProviderError telling its admin to add one. Embeddings always stay on the platform.
"""
from __future__ import annotations

import logging
import threading
import time

from ...core import org_chat_clients, secret_box, store
from ..usage import service as usage_service
from . import repository as repo

logger = logging.getLogger(__name__)
_TTL_S = 30          # a saved change reaches running jobs within this; saves through the API apply at once
TEST_PROMPT = [{"role": "user", "content": "Reply with the single word OK."}]
_lock = threading.Lock()
_backends: dict[int, tuple[float, object | None, str]] = {}
_project_orgs: dict[int, tuple[float, int | None]] = {}


_NO_MODEL = object()      # cached: the org is not on the platform model and has no provider


class OrgProviderError(RuntimeError):
    """The org's own provider failed; the call is not retried on the platform model."""


def invalidate(org_id: int) -> None:
    with _lock:
        _backends.pop(org_id, None)


def _project_org(project_id: int) -> int | None:
    now = time.time()
    with _lock:
        hit = _project_orgs.get(project_id)
    if hit and now - hit[0] < _TTL_S:
        return hit[1]
    org = repo.project_org(project_id)
    with _lock:
        _project_orgs[project_id] = (now, org)
    return org


def scope_org() -> int | None:
    s = usage_service.current()
    if s.get("project_id"):
        return _project_org(int(s["project_id"]))
    return s.get("org_id")


def client_for(row: dict):
    return org_chat_clients.build(row["provider_type"], base_url=row["base_url"],
                                  api_key=secret_box.decrypt(row["api_key_enc"]), model=row["model"],
                                  api_version=row["api_version"])


def backend_for_org(org_id: int | None) -> tuple[object, str] | None:
    """(chat client, provider name) of the org's default provider, or None for the platform model."""
    if org_id is None:
        return None
    now = time.time()
    with _lock:
        hit = _backends.get(org_id)
    if not hit or now - hit[0] >= _TTL_S:
        row = repo.default_for_org(org_id)
        if row is None:
            hit = (now, None, "") if store.org_uses_platform_llm(org_id) else (now, _NO_MODEL, "")
        else:
            try:
                hit = (now, client_for(row), row["name"])
            except secret_box.SecretUnreadable as e:
                raise OrgProviderError(f"Org provider '{row['name']}': {e}") from e
        with _lock:
            _backends[org_id] = hit
    if hit[1] is _NO_MODEL:
        org = store.get_organization_by_id(org_id) or {}
        raise OrgProviderError(f"{org.get('name') or 'This organization'} has no LLM model yet: an admin adds one in "
                               "Settings → LLM Providers")
    return (hit[1], hit[2]) if hit[1] is not None else None


def backend_for_scope() -> tuple[object, str] | None:
    return backend_for_org(scope_org())


def reads_files_natively(org_id: int | None) -> bool:
    """Every org but a platform-model one (InfoVision) has its files read by Python, never the platform's NVIDIA."""
    return org_id is not None and not store.org_uses_platform_llm(org_id)


def test_connection(fields: dict, api_key: str) -> dict:
    """One tiny real chat call with these settings: {ok, latency_ms, reply, error}. Never raises."""
    started = time.time()
    try:
        client = org_chat_clients.build(fields["provider_type"], base_url=fields["base_url"], api_key=api_key,
                                        model=fields["model"], api_version=fields["api_version"])
        with usage_service.scope(stage="other", sub_stage="provider_test"):
            reply = client.chat(TEST_PROMPT)
        return {"ok": True, "latency_ms": int((time.time() - started) * 1000), "reply": reply.strip()[:80],
                "error": ""}
    except Exception as e:     # any failure is the answer to "does it connect"
        logger.info("Provider test failed: %s", type(e).__name__)
        return {"ok": False, "latency_ms": int((time.time() - started) * 1000), "reply": "",
                "error": (str(e) or type(e).__name__)[:300]}
