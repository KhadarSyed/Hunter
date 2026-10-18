"""The project's logo: its client brand's own logo, else (a category study with no client brand, e.g. "Baby Skincare
Category") a web photo of the brief's main theme, so the project never shows a bare letter monogram."""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote

import requests

from ...core import serp_keys, store
from ..research import brandfetch, logo_files, pexels
from ..research import repository as research_repo

logger = logging.getLogger(__name__)

# Words that name the kind of study, not its subject: "Baby Skincare Category" -> "Baby Skincare"
_STUDY_WORDS = re.compile(r"\b(category|categories|industry|sector|market|segment|analysis|study)\b", re.I)
_PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
_NOT_PHOTOS = (".svg", ".gif")
THEME_SOURCE = "google_theme"


def _web_theme_image(theme: str) -> str | None:
    """A Google Images photo for the theme (web search), cached in brand_logos under "theme:<theme>" like a logo
    lookup: a found image is kept, "none" is retried after a week, an unavailable search is not saved."""
    key = f"theme:{brandfetch.normalize_brand(theme)}"
    saved = research_repo.get_brand_logo(key)
    if saved and (saved["logo_url"] or time.time() - saved["fetched_at"] < brandfetch.NOT_FOUND_RETRY_S):
        return saved["logo_url"]
    try:
        r = serp_keys.get(brandfetch.SERPAPI_URL, {"engine": "google_images", "q": theme}, brandfetch.GOOGLE_TIMEOUT_S)
        # no key, an exhausted or rejected key (401/403/429) or a 5xx is "could not search", not "no image": not saved
        if r is None or r.status_code != 200:
            logger.warning("Theme image search for %r unavailable: HTTP %s", theme, None if r is None else r.status_code)
            return None
        images = r.json().get("images_results", [])
    except (requests.RequestException, ValueError) as e:
        logger.warning("Theme image search for %r unavailable: %s", theme, type(e).__name__)
        return None
    urls = [u for u in (i.get("original") or "" for i in images)
            if u.startswith("https://") and not u.lower().split("?")[0].endswith(_NOT_PHOTOS)]
    url = next((u for u in urls if u.lower().split("?")[0].endswith(_PHOTO_EXTENSIONS)), urls[0] if urls else None)
    research_repo.save_brand_logo(key, theme, url, None, THEME_SOURCE)
    return url


def _client_brand(project: dict) -> str:
    spec = project.get("spec") or {}
    commissioning = spec.get("commissioning_brand")
    name = commissioning.get("name") if isinstance(commissioning, dict) else None
    return (project.get("brand") or name or spec.get("client") or "").strip()


def brief_theme(project: dict) -> str:
    """The brief's main theme as a short search phrase. A client named after the category is the theme itself
    ("Baby Skincare Category" -> "Baby Skincare"); otherwise the most specific part of the spec's industry
    ("Personal Care / Baby Skincare" -> "Baby Skincare"), else the project name without study words."""
    client = _client_brand(project)
    if _STUDY_WORDS.search(client):
        theme = " ".join(_STUDY_WORDS.sub(" ", client).split())
        if theme:
            return theme
    spec = project.get("spec") or {}
    industry = spec.get("industry")
    industry = industry.get("name") if isinstance(industry, dict) else industry
    if isinstance(industry, str) and industry.strip():
        return re.split(r"\s*[/>|]\s*", industry.strip())[-1]
    return " ".join(_STUDY_WORDS.sub(" ", project.get("project_name") or "").split())


def project_logo(project_id: int) -> dict | None:
    """{logo_url, is_light, source: brand|theme|none, brand, theme}; None when the project does not exist.
    Blocking (network on a cache miss): FastAPI runs the sync route in its threadpool."""
    project = store.get_project(project_id)
    if not project:
        return None
    brand = _client_brand(project)
    result = {"logo_url": None, "is_light": False, "source": "none", "brand": brand or None, "theme": None}
    if brand:
        logo = logo_files.public_logo(brand, f"/api/intel/brandfetch/logo/image?brand_name={quote(brand)}")
        if logo.get("logo_url"):
            return {**result, "logo_url": logo["logo_url"], "is_light": bool(logo.get("is_light")), "source": "brand"}
    theme = brief_theme(project)
    if theme:
        # web search first, Pexels' stock photos only when the search finds nothing
        image = _web_theme_image(theme) or pexels.resolve_background_image(theme).get("image_url")
        if image:
            return {**result, "logo_url": image, "source": "theme", "theme": theme}
    return {**result, "theme": theme or None}
