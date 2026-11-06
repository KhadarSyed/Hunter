"""Model prices: seeded defaults plus a daily sync from Microsoft's public Azure Retail Prices API."""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict

from . import repository as repo

logger = logging.getLogger(__name__)

API = "https://prices.azure.com/api/retail/prices"
FILTER = "serviceName eq 'Foundry Models' and contains(meterName,'GPT 5')"
MAX_PAGES = 20
PAGE_TIMEOUT_S = 20
SYNC_EVERY_S = 24 * 3600
SYNCED_KEY = "azure_prices_synced_at"
SKIP = re.compile(r"\b(batch|pro|codex|chat)\b", re.I)
MODEL = re.compile(r"^GPT\s*(\d+(?:\.\d+)?)(?:\s+(mini|nano)\b)?", re.I)
DEFAULTS = (
    ("azure_openai", "gpt-5", "global", 1.25, 0.125, 10.0, "2025-08-01", "default"),
    ("nvidia", "nvidia/", "", 0, 0, 0, "2025-01-01", "default"),  # prefix row: every NVIDIA model is free
)


def seed_defaults() -> None:
    for row in DEFAULTS:
        if not repo.has_price_row(row[0], row[1]):
            repo.upsert_price(*row)


def _fetch_all() -> list[dict]:
    import requests
    items: list[dict] = []
    url, params = API, {"$filter": FILTER}
    for _ in range(MAX_PAGES):
        r = requests.get(url, params=params, timeout=PAGE_TIMEOUT_S)
        r.raise_for_status()
        body = r.json()
        items += body.get("Items", [])
        url, params = body.get("NextPageLink"), None
        if not url:
            break
    return items


def _parse(item: dict) -> tuple[str, str, str, float, str] | None:
    """(model, deployment, kind, price per million tokens, effective date) or None for a meter we do not use."""
    name = item.get("meterName") or ""
    m = MODEL.match(name)
    if SKIP.search(name) or not m:
        return None
    words = set(name.lower().split())
    if words & {"cchd", "cd"}:
        kind = "cached"
    elif words & {"inpt", "inp"}:
        kind = "input"
    elif words & {"outpt", "opt"}:
        kind = "output"
    else:
        return None
    deployment = "global" if words & {"glbl", "gl"} else "datazone" if words & {"dzone", "dz"} else "regional"
    model = "gpt-" + m.group(1) + (f"-{m.group(2).lower()}" if m.group(2) else "")
    price = float(item["unitPrice"]) * (1000 if str(item.get("unitOfMeasure", "")).upper().startswith("1K") else 1)
    return model, deployment, kind, price, str(item["effectiveStartDate"])[:10]


def sync_azure(fetch=None) -> int:
    """Write one price row per model, deployment type and start date; returns rows written (0 on any failure)."""
    try:
        region = repo.get_setting("azure_price_region", "southindia")
        groups: dict[tuple, dict] = defaultdict(dict)
        for item in (fetch or _fetch_all)():
            if item.get("armRegionName") != region:
                continue
            parsed = _parse(item)
            if parsed:
                model, deployment, kind, price, day = parsed
                groups[(model, deployment, day)][kind] = price
        for (model, deployment, day), p in groups.items():
            repo.upsert_price("azure_openai", model, deployment, p.get("input", 0.0), p.get("cached", 0.0),
                              p.get("output", 0.0), day, "azure_retail")
        return len(groups)
    except Exception as e:
        logger.warning("Azure price sync failed (%s: %s)", type(e).__name__, e)
        return 0


def _sync_job() -> None:
    try:
        seed_defaults()
        last = float(repo.get_setting(SYNCED_KEY, "0") or 0)
        if time.time() - last >= SYNC_EVERY_S:
            sync_azure()
            repo.set_setting(SYNCED_KEY, str(time.time()))
    except Exception as e:
        logger.warning("price sync job failed (%s: %s)", type(e).__name__, e)


def sync_in_background() -> None:
    from ...core import jobs
    jobs.runner.submit(_sync_job, name="llm-price-sync")
