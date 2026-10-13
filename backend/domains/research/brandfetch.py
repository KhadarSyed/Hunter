"""Brand / product logo resolution.

Lookup order for a brand (or product) name:
  1. brand_logos table  — every logo ever resolved is saved here and served first
  2. Brandfetch         — Brand Search API → brand domain → Brandfetch CDN logo
  3. Google Images      — via SerpAPI (SERP_API_KEY): "<name> logo svg", preferring .svg
Definite outcomes are saved, including "not found" (source="none", retried after
NOT_FOUND_RETRY_S). Transient failures (timeouts, 5xx, rate limits) are NOT saved, so
a slow API never blocks a brand.

Both Brandfetch search and Google are fuzzy — they always return *something* — so a
result is only accepted when it plausibly belongs to the queried name (_is_plausible_*).

Brandfetch Search API (docs.brandfetch.com/reference/brand-search-api, 2026-09):
`GET https://api.brandfetch.io/v2/search/{name}?c={clientId}` → JSON array of
`{icon, name, domain, claimed, brandId}`.

BRANDFETCH_API_KEY and SERP_API_KEY are secrets: never log, cache, or return them.
BRANDFETCH_CLIENT_ID is public (it is embedded in the CDN logo URL).
"""
from __future__ import annotations

import logging
import os
import time

import requests

from ...core import serp_keys
from . import repository

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://api.brandfetch.io/v2/search"
CDN_BASE_URL = "https://cdn.brandfetch.io"
SERPAPI_URL = "https://serpapi.com/search.json"
REQUEST_TIMEOUT_S = 10
GOOGLE_TIMEOUT_S = 20
NOT_FOUND_RETRY_S = 7 * 86_400  # re-check brands with no logo after a week
MIN_TOKEN_LEN = 3


class BrandfetchError(RuntimeError):
    pass


class LookupUnavailable(RuntimeError):
    """A logo source could not answer right now (timeout, 5xx, rate limit) — don't cache."""


def _env(name: str) -> str:
    return (os.getenv(name) or "").split("#")[0].strip().strip('"')


def is_reachable() -> bool:
    return bool(_env("BRANDFETCH_API_KEY") and _env("BRANDFETCH_CLIENT_ID"))


def normalize_brand(name: str) -> str:
    return " ".join(name.lower().split())


def _compact(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _get(url: str, *, timeout: int, **kwargs) -> requests.Response:
    try:
        r = requests.get(url, timeout=timeout, **kwargs)
    except requests.RequestException as e:
        raise LookupUnavailable(type(e).__name__) from e
    if r.status_code == 429 or r.status_code >= 500:
        raise LookupUnavailable(f"HTTP {r.status_code}")
    return r


# ─── Brandfetch ──────────────────────────────────────────────────────────────

def _is_plausible_match(query: str, match_name: str, domain: str) -> bool:
    """The match's name or domain stem appears in the query, ignoring spaces/punctuation:
    "McDonald's" ~ mcdonalds.com, "Heineken 0.0 beer" ~ Heineken; "Zxq Corp" !~ Corpay."""
    q = _compact(query)
    name, stem = _compact(match_name), _compact(domain.split(".")[0])
    return bool(q) and any(len(t) >= MIN_TOKEN_LEN and t in q for t in (name, stem))


def resolve_brand_domain(brand_name: str) -> str | None:
    """Brandfetch search → the first plausible match's domain, or None.
    Names with spaces are retried without them ("MC Donald's" → "MCDonald's")."""
    if not brand_name.strip() or not is_reachable():
        return None
    queries = [brand_name.strip()]
    if " " in queries[0]:
        queries.append(queries[0].replace(" ", ""))
    for query in queries:
        r = _get(f"{SEARCH_API_URL}/{requests.utils.quote(query)}", timeout=REQUEST_TIMEOUT_S,
                 headers={"Authorization": f"Bearer {_env('BRANDFETCH_API_KEY')}"},
                 params={"c": _env("BRANDFETCH_CLIENT_ID")})
        if r.status_code != 200:
            logger.warning("Brandfetch search failed for %r: HTTP %s", query, r.status_code)
            return None
        try:
            matches = r.json() or []
        except ValueError:
            return None
        for match in matches:
            domain = (match.get("domain") or "").removeprefix("https://").removeprefix("http://").rstrip("/")
            if domain and _is_plausible_match(brand_name, match.get("name") or "", domain):
                return domain
    return None


# ─── Google Images (SerpAPI) ─────────────────────────────────────────────────

# Words that say nothing about which brand an image belongs to.
_GENERIC_WORDS = {"corp", "corporation", "company", "group", "brand", "brands", "logo", "inc",
                  "limited", "ltd", "llc", "holdings", "international", "global", "the", "and"}


def _is_plausible_image(query: str, url: str) -> bool:
    """The image URL contains a distinctive word of the query (e.g. heineken-logo.svg)."""
    path = _compact(url.split("?")[0])
    words = [w for w in (_compact(x) for x in query.split()) if w not in _GENERIC_WORDS]
    return any(len(w) >= 4 and w in path for w in words + [_compact(query)])


def _google_logo(brand_name: str) -> str | None:
    """First plausible .svg for "<name> logo svg" on Google Images, else first plausible image."""
    try:
        r = serp_keys.get(SERPAPI_URL, {"engine": "google_images", "q": f"{brand_name} logo svg"}, GOOGLE_TIMEOUT_S)
    except requests.RequestException as e:
        raise LookupUnavailable(type(e).__name__) from e
    if r is None:
        return None
    if r.status_code == 429 or r.status_code >= 500:
        raise LookupUnavailable(f"HTTP {r.status_code}")
    try:
        images = r.json().get("images_results", []) if r.status_code == 200 else []
    except ValueError:
        return None
    urls = [u for u in (i.get("original") or "" for i in images)
            if u.startswith("https://") and _is_plausible_image(brand_name, u)]
    svg = next((u for u in urls if u.lower().split("?")[0].endswith(".svg")), None)
    return svg or (urls[0] if urls else None)


# ─── Resolver ────────────────────────────────────────────────────────────────

def resolve_logo(brand_name: str) -> dict:
    """{brand_name, logo_url, source, domain, cached}: saved table first, then Brandfetch,
    then Google. Blocking (network) — call from a worker thread."""
    name = brand_name.strip()
    key = normalize_brand(name)
    result = {"brand_name": name, "logo_url": None, "source": "none", "domain": None, "cached": False}
    if not key:
        return result

    saved = repository.get_brand_logo(key)
    if saved and (saved["logo_url"] or time.time() - saved["fetched_at"] < NOT_FOUND_RETRY_S):
        return {**result, "logo_url": saved["logo_url"], "source": saved["source"],
                "domain": saved["domain"], "cached": True}

    try:
        domain = resolve_brand_domain(name)
        if domain:
            result.update(logo_url=f"{CDN_BASE_URL}/{domain}?c={_env('BRANDFETCH_CLIENT_ID')}",
                          source="brandfetch", domain=domain)
        else:
            logo_url = _google_logo(name)
            if logo_url:
                result.update(logo_url=logo_url, source="google")
    except LookupUnavailable as e:
        logger.warning("Logo lookup for %r unavailable (%s); not cached, will retry", name, e)
        return result
    repository.save_brand_logo(key, name, result["logo_url"], result["domain"], result["source"])
    return result


def get_brand_logo_url(brand_name: str) -> str | None:
    """Backwards-compatible helper: just the logo URL (or None)."""
    return resolve_logo(brand_name)["logo_url"]
