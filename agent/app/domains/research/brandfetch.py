"""Brandfetch client — resolves a brand name to a logo CDN URL server-side.

Talks to Brandfetch's Brand Search API directly via `requests`, configured from:
BRANDFETCH_API_KEY, BRANDFETCH_CLIENT_ID.

API shape (confirmed against https://docs.brandfetch.com/reference/brand-search-api,
2026-09): `GET https://api.brandfetch.io/v2/search/{name}?c={clientId}` returns a JSON
array of `{icon, name, domain, claimed, brandId}`. The Search API authenticates with the
client ID as a query parameter, not a bearer token; BRANDFETCH_API_KEY is sent as an
`Authorization: Bearer` header as well since some accounts gate the Search API behind it
too — harmless to include if the endpoint only checks `c`.

BRANDFETCH_API_KEY is a secret and must never be logged, cached, or returned to a caller.
BRANDFETCH_CLIENT_ID is a public identifier (it is meant to be embedded in the CDN logo
URL returned to the frontend), safe to expose.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://api.brandfetch.io/v2/search"
CDN_BASE_URL = "https://cdn.brandfetch.io"


class BrandfetchError(RuntimeError):
    pass


# Process-lifetime cache: lowercased brand_name -> logo URL, or None for "known not found".
# Deliberately minimal/non-durable (cleared on restart) — not a database-backed cache.
_logo_cache: dict[str, str | None] = {}


def _get_api_key() -> str:
    return os.getenv("BRANDFETCH_API_KEY", "")


def _get_client_id() -> str:
    return os.getenv("BRANDFETCH_CLIENT_ID", "")


def is_reachable() -> bool:
    return bool(_get_api_key() and _get_client_id())


def resolve_brand_domain(brand_name: str) -> str | None:
    """Look up a brand name via Brandfetch's search API and return the best match's domain.

    Returns None if no match was found, or if the lookup could not be performed
    (missing config, transport error, auth error). Never raises for "brand not found".
    """
    if not brand_name or not brand_name.strip():
        return None
    if not is_reachable():
        logger.warning("Brandfetch not configured (missing BRANDFETCH_API_KEY/BRANDFETCH_CLIENT_ID)")
        return None

    client_id = _get_client_id()
    api_key = _get_api_key()
    url = f"{SEARCH_API_URL}/{requests.utils.quote(brand_name.strip())}"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"c": client_id}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.RequestException as e:
        logger.warning("Brandfetch search request failed for %r: %s", brand_name, e)
        return None

    if r.status_code != 200:
        logger.warning("Brandfetch search failed for %r: %s %s", brand_name, r.status_code, r.text[:200])
        return None

    try:
        matches = r.json()
    except ValueError:
        logger.warning("Brandfetch search returned non-JSON response for %r", brand_name)
        return None

    if not matches:
        return None

    domain = matches[0].get("domain")
    if not domain:
        return None
    return domain.removeprefix("https://").removeprefix("http://").rstrip("/")


def get_brand_logo_url(brand_name: str) -> str | None:
    """Resolve a brand name to a Brandfetch CDN logo URL, or None if not found.

    Caches results (including negative "not found" results) for the process lifetime
    so repeated lookups don't keep hitting the API.
    """
    if not brand_name or not brand_name.strip():
        return None

    cache_key = brand_name.strip().lower()
    if cache_key in _logo_cache:
        return _logo_cache[cache_key]

    domain = resolve_brand_domain(brand_name)
    if not domain:
        _logo_cache[cache_key] = None
        return None

    client_id = _get_client_id()
    logo_url = f"{CDN_BASE_URL}/{domain}?c={client_id}"
    _logo_cache[cache_key] = logo_url
    return logo_url
