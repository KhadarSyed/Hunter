"""Which chat models an organisation's calls use, failover between them, and the Test connection call.

Every chat call reads the request's or job's usage scope (domains/usage/service.SCOPE): the project's org when a
project is in scope, else the user's active org. An org with providers uses them in order: its saved default (the
newest one added, unless an admin picked another), then the others newest first. A model that is down (an outage or a
rejected key, see classify) is skipped for 2 minutes and the next one answers; when every model is down the call waits,
rechecking every 5 minutes, and continues the moment one answers, so the project resumes where it stopped. Its admins
are emailed (outage.py). Never the platform model as a fallback: that serves only a platform-model org (organizations.platform_llm,
set by a Super Admin) with no provider of its own, and calls with no org in scope. Any other org with no model
gets OrgProviderError telling its admin to add one. Embeddings always stay on the platform.
"""
from __future__ import annotations

import logging
import re
import threading
import time

from ...core import org_chat_clients, secret_box, store
from ...core.azure_openai_client import AzureOpenAIError, ReplyCutOff
from ..usage import service as usage_service
from . import repository as repo

logger = logging.getLogger(__name__)
_TTL_S = 30               # a saved change reaches running jobs within this; saves through the API apply at once
_DOWN_S = 120             # a provider that failed is skipped this long; the next call after it is the probe
_RECHECK_S = 300          # all down: the waiting call rechecks the org's models every 5 minutes
_WAIT_CAP_S = 12 * 3600   # ...and gives up after 12 hours
TEST_PROMPT = [{"role": "user", "content": "Reply with the single word OK."}]
_lock = threading.Lock()
_orgs: dict[int, tuple[float, list[dict]]] = {}
_clients: dict[tuple, object] = {}
_down: dict[int, dict] = {}     # provider id -> {until, probing, kind, reason}
_project_orgs: dict[int, tuple[float, int | None]] = {}


class OrgProviderError(RuntimeError):
    """The org's own model failed (or it has none); the call is never retried on the platform model."""


class AllModelsDown(OrgProviderError):
    """Every model of the org stayed down for the whole wait (12 hours)."""


def invalidate(org_id: int) -> None:
    with _lock:
        _orgs.pop(org_id, None)


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


def _client(row: dict):
    key = (row["id"], row["updated_at"])
    with _lock:
        hit = _clients.get(key)
    if hit is None:
        hit = client_for(row)
        with _lock:
            _clients[key] = hit
    return hit


def _rows(org_id: int) -> list[dict]:
    """The org's providers in failover order: the saved default, then the others newest first."""
    now = time.time()
    with _lock:
        hit = _orgs.get(org_id)
    if not hit or now - hit[0] >= _TTL_S:
        hit = (now, repo.list_for_org(org_id))
        with _lock:
            _orgs[org_id] = hit
    return hit[1]


def route(org_id: int | None) -> list[dict] | None:
    """The org's providers in failover order, or None for the platform model (no org in scope, or a platform-model
    org with no provider). Raises OrgProviderError for any other org with no model."""
    if org_id is None:
        return None
    rows = _rows(org_id)
    if rows:
        return rows
    if store.org_uses_platform_llm(org_id):
        return None
    org = store.get_organization_by_id(org_id) or {}
    raise OrgProviderError(f"{org.get('name') or 'This organization'} has no LLM model yet: an admin adds one in "
                           "Settings → LLM Providers")


def classify(e: BaseException) -> str | None:
    """'outage' (the provider is down: 5xx, 429, timeouts, dropped connections, an error inside a stream), 'config'
    (a rejected key, no credits or unknown model: 401/402/403/404) or None (not the provider's fault: a cut-off reply, a bad request,
    bad JSON; the caller handles it)."""
    import requests
    if isinstance(e, ReplyCutOff):
        return None
    if isinstance(e, secret_box.SecretUnreadable):
        return "config"
    if isinstance(e, (requests.ConnectionError, requests.Timeout, TimeoutError, ConnectionError)):
        return "outage"
    msg = str(e)
    code = re.search(r"\b(?:HTTP |failed: )(\d{3})\b", msg)
    if code:
        n = int(code.group(1))
        # 402: the account's credits or billing ran out — the Admin must act, like a rejected key
        return "outage" if n >= 500 or n == 429 else "config" if n in (401, 402, 403, 404) else None
    if re.search(r"not valid JSON|cut off", msg, re.I):
        return None
    if re.search(r"access|permission|api key|unauthori[sz]ed|forbidden", msg, re.I):
        return "config"
    return "outage" if isinstance(e, (org_chat_clients.ProviderCallError, AzureOpenAIError)) else None


def _claim(pid: int) -> bool:
    """May this call use the provider? Not while it is marked down; once the mark expires, one call probes it."""
    with _lock:
        d = _down.get(pid)
        if d is None:
            return True
        if d["probing"] or time.time() < d["until"]:
            return False
        d["probing"] = True
        return True


def _mark_down(row: dict, kind: str, reason: str) -> None:
    with _lock:
        _down[row["id"]] = {"until": time.time() + _DOWN_S, "probing": False, "kind": kind, "reason": reason[:200]}


def _mark_up(row: dict) -> None:
    with _lock:
        _down.pop(row["id"], None)


def down_info(pid: int) -> dict | None:
    with _lock:
        d = _down.get(pid)
        return dict(d) if d else None


def call(org_id: int, rows: list[dict], invoke):
    """invoke(client) on the org's first working model, in order. A model that is down is skipped (its admins are
    emailed); when every model is down the call waits, rechecking every 5 minutes, and continues the moment one
    answers (the project resumes where it stopped). Never the platform model."""
    from . import outage
    deadline = time.time() + _WAIT_CAP_S
    while True:
        tried = False
        for row in rows:
            if not _claim(row["id"]):
                continue
            tried = True
            try:
                result = invoke(_client(row))
            except Exception as e:
                kind = classify(e)
                if kind is None:
                    _mark_up(row)           # it answered: the problem is the request or the reply, not the model
                    if isinstance(e, ReplyCutOff):
                        raise               # the batching caller re-packs smaller
                    raise OrgProviderError(f"Org provider '{row['name']}' failed: {e}") from e
                _mark_down(row, kind, str(e))
                outage.on_failure(org_id, row, kind, str(e))
                logger.warning("Org %s: model %s is %s (%s); trying the next one", org_id, row["name"], kind,
                               str(e)[:160])
                continue
            _mark_up(row)
            outage.on_success(org_id, rows, row)
            return result
        if all(down_info(r["id"]) for r in rows):
            outage.on_all_down(org_id, rows)
        if time.time() >= deadline:
            raise AllModelsDown("Every AI model of this organization stayed down for 12 hours: "
                                + "; ".join(r["name"] for r in rows))
        time.sleep(_RECHECK_S if tried else 15)
        rows = route(org_id) or rows        # a model added or fixed while waiting is used straight away


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
