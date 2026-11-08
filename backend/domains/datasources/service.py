"""Live key validation for org-managed Tavily/SerpAPI credentials.

A trivial, cheap real call to each vendor — distinct from the actual research
search calls in news_search.py, which also reactively mark status via
`record_result()` below every time they run for real during a pipeline stage.
"""
from __future__ import annotations

import requests

from . import repository as ds_repo

_TIMEOUT = 15


def _validate_tavily(api_key: str) -> tuple[bool, str | None]:
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": "test", "max_results": 1},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        # Network/timeout issues are not a key problem — treat as inconclusive (ok).
        return True, f"Could not reach Tavily to validate: {e}"
    if r.status_code in (401, 403):
        return False, f"Tavily rejected this key ({r.status_code})"
    return True, None


def _validate_serpapi(api_key: str) -> tuple[bool, str | None]:
    try:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={"engine": "google_news", "q": "test", "api_key": api_key},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        return True, f"Could not reach SerpAPI to validate: {e}"
    if r.status_code in (401, 403):
        return False, f"SerpAPI rejected this key ({r.status_code})"
    try:
        data = r.json()
    except ValueError:
        return True, None
    error = str(data.get("error") or "")
    if "api key" in error.lower() and "invalid" in error.lower():
        return False, error
    return True, None


FIRECRAWL_API = "https://api.firecrawl.dev/v2"


def check_firecrawl(api_key: str) -> tuple[str, str | None]:
    """('ok' | 'expired' (rejected) | 'quota' (out of credits / rate-limited) | 'unverified' (unreachable), message).
    One 1-result search: the cheapest real call. The key is never put in the message."""
    try:
        r = requests.post(f"{FIRECRAWL_API}/search", json={"query": "test", "limit": 1},
                          headers={"Authorization": f"Bearer {api_key}"}, timeout=_TIMEOUT)
    except requests.RequestException as e:
        return "unverified", f"Could not reach Firecrawl ({type(e).__name__}); the key is saved and checked on first use"
    if r.status_code in (401, 403):
        return "expired", "Firecrawl rejected this key (invalid or revoked)"
    if r.status_code in (402, 429):
        return "quota", "Firecrawl: no credits left or rate-limited for this key"
    if r.status_code >= 500:
        return "unverified", f"Firecrawl is unavailable right now ({r.status_code})"
    return "ok", None


def _validate_firecrawl(api_key: str) -> tuple[bool, str | None]:
    status, msg = check_firecrawl(api_key)
    return status != "expired", msg


_VALIDATORS = {"tavily": _validate_tavily, "serpapi": _validate_serpapi, "firecrawl": _validate_firecrawl}


def validate_and_record(org_id: int, source: str, api_key: str) -> tuple[str, str | None]:
    """Make one real call against the vendor, persist the resulting status, return it."""
    if source == "firecrawl":
        status, error = check_firecrawl(api_key)
    else:
        ok, error = _VALIDATORS[source](api_key)
        status = "ok" if ok else "expired"
    ds_repo.mark_status(org_id, source, status, error)
    return status, error


def record_result(org_id: int | None, source: str, ok: bool, error: str | None) -> None:
    """Called from the real research pipeline (news_search.py, via research/router.py)
    every time a search actually runs — reactive validation "every stage" the key is used,
    not just on-demand. No-op when the project has no org (e.g. legacy ungrouped projects)."""
    if org_id is None:
        return
    status = "ok" if ok else "expired"
    ds_repo.mark_status(org_id, source, status, error)
