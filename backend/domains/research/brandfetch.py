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

def worth_looking_up(name: str) -> bool:
    """A name worth a paid lookup: two or more letters/digits incl. a letter, and a word that is not generic. "1234",
    "x", "--", "Inc" and "The Group" cost no Brandfetch or Google call."""
    words = [w for w in (_compact(x) for x in name.split()) if w]
    joined = "".join(words)
    return len(joined) >= 2 and any(c.isalpha() for c in joined) and any(w not in _GENERIC_WORDS for w in words)


def _leading_runs(query: str) -> set[str]:
    """The query's first word, first two words, ... joined without spaces/punctuation."""
    runs, acc = set(), ""
    for word in query.split():
        acc += _compact(word)
        if acc:
            runs.add(acc)
    return runs


def _is_plausible_match(query: str, match_name: str, domain: str) -> bool:
    """The match's name or domain stem is the whole query or its leading words, ignoring spaces/punctuation:
    "McDonald's" ~ mcdonalds.com, "MC Donald's" ~ McDonald's, "Heineken 0.0 beer" ~ Heineken. Not a piece inside a
    word ("zzqx-no-such-brand-qq" !~ nosuch.vc) nor a later word ("Lightning by Ford" !~ ford.com)."""
    runs = _leading_runs(query)
    name, stem = _compact(match_name), _compact(domain.split(".")[0])
    return any(len(t) >= MIN_TOKEN_LEN and t in runs for t in (name, stem))


def resolve_brand_domain(brand_name: str) -> str | None:
    """Brandfetch search → the first plausible match's domain, or None.
    Names with spaces are retried without them ("MC Donald's" → "MCDonald's")."""
    if not worth_looking_up(brand_name) or not is_reachable():
        return None
    saved = repository.get_brand_logo(normalize_brand(brand_name))       # the logo lookup's answer: no new search
    if saved and saved["source"] == "brandfetch" and saved["domain"] and             _is_plausible_match(brand_name, "", saved["domain"]):
        return saved["domain"]
    if saved and not saved["domain"] and time.time() - (saved["fetched_at"] or 0) < NOT_FOUND_RETRY_S:
        return None                     # searched within the week: Brandfetch had no plausible match
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


def candidate_domains(brand_name: str, hint: str = "", limit: int = 5) -> list[str]:
    """Every plausible Brandfetch match for the name, then for the name plus a hint (the project's category), in
    search order: the first match is often a namesake ("Rini" -> rini.se, not iamrini.com)."""
    if not worth_looking_up(brand_name) or not is_reachable():
        return []
    out: list[str] = []
    for query in dict.fromkeys(q for q in (brand_name.strip(), f"{brand_name.strip()} {hint}".strip()) if q):
        try:
            r = _get(f"{SEARCH_API_URL}/{requests.utils.quote(query)}", timeout=REQUEST_TIMEOUT_S,
                     headers={"Authorization": f"Bearer {_env('BRANDFETCH_API_KEY')}"},
                     params={"c": _env("BRANDFETCH_CLIENT_ID")})
            matches = r.json() if r.status_code == 200 else []
        except (requests.RequestException, ValueError) as e:
            logger.warning("Brandfetch search failed for %r: %s", query, type(e).__name__)
            continue
        for match in matches or []:
            domain = (match.get("domain") or "").removeprefix("https://").removeprefix("http://").rstrip("/")
            if domain and domain not in out and _is_plausible_match(brand_name, match.get("name") or "", domain):
                out.append(domain)
    return out[:limit]


# ─── Google Images (SerpAPI) ─────────────────────────────────────────────────

# Words that say nothing about which brand an image belongs to.
_GENERIC_WORDS = {"corp", "corporation", "company", "group", "brand", "brands", "logo", "inc",
                  "limited", "ltd", "llc", "holdings", "international", "global", "the", "and"}


def _is_plausible_image(query: str, url: str, *, strict: bool = False) -> bool:
    """The image URL contains a distinctive word of the query (e.g. heineken-logo.svg). Strict: every distinctive
    word, so "Baby Skincare Category" is not matched by a babyfaceskincarespa.com logo."""
    path = _compact(url.split("?")[0])
    words = [w for w in (_compact(x) for x in query.split()) if w not in _GENERIC_WORDS]
    if strict:
        distinctive = [w for w in words if len(w) >= 3]
        return _compact(query) in path or (bool(distinctive) and all(w in path for w in distinctive))
    return any(len(w) >= 4 and w in path for w in words + [_compact(query)])


def is_plausible_logo(brand_name: str, url: str) -> bool:
    """A Google logo URL still believable for the brand under the strict rule (cached ones are re-checked)."""
    return _is_plausible_image(brand_name, url, strict=True)


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
            if u.startswith("https://") and _is_plausible_image(brand_name, u, strict=True)]
    svg = next((u for u in urls if u.lower().split("?")[0].endswith(".svg")), None)
    return svg or (urls[0] if urls else None)


def google_logo_candidates(brand_name: str, hint: str = "", limit: int = 4) -> list[str]:
    """Plausible logo image URLs from Google Images for "<name> <hint> logo" (the hint, e.g. the project's category,
    steers away from namesakes); PNG/JPG first, since the deck cannot embed SVG. Empty when SerpAPI is unavailable."""
    if not worth_looking_up(brand_name):
        return []
    try:
        r = serp_keys.get(SERPAPI_URL, {"engine": "google_images", "q": f"{brand_name} {hint} logo".replace("  ", " ")},
                          GOOGLE_TIMEOUT_S)
        images = r.json().get("images_results", []) if r is not None and r.status_code == 200 else []
    except (requests.RequestException, ValueError) as e:
        logger.warning("Google logo search for %r unavailable: %s", brand_name, type(e).__name__)
        return []
    urls = [u for u in (i.get("original") or "" for i in images) if u.startswith("https://")
            and _is_plausible_image(brand_name, u)]
    raster = [u for u in urls if u.lower().split("?")[0].endswith((".png", ".jpg", ".jpeg"))]
    return list(dict.fromkeys(raster + urls))[:limit]


# ─── Resolver ────────────────────────────────────────────────────────────────

def resolve_logo(brand_name: str) -> dict:
    """{brand_name, logo_url, source, domain, cached}: saved table first, then Brandfetch,
    then Google. Blocking (network) — call from a worker thread."""
    name = brand_name.strip()
    key = normalize_brand(name)
    result = {"brand_name": name, "logo_url": None, "source": "none", "domain": None, "cached": False}
    if not key or not worth_looking_up(name):          # not a brand: no Brandfetch or paid Google search
        return result

    saved = repository.get_brand_logo(key)
    if saved and saved["source"] == "google" and saved["logo_url"] and not is_plausible_logo(name, saved["logo_url"]):
        saved = None  # saved under the older, looser match rule: look the brand up again
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

