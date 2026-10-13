"""Exclusion rules and the filter every source of articles passes through: web research before it is stored,
background research before it is saved, and dataset rows before a deck or report is built."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from ...core import store

logger = logging.getLogger(__name__)

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_HOST = re.compile(r"[a-z0-9.-]+")
_TEXT_KEYS = ("title", "headline", "snippet", "summary", "text", "content", "description", "body")


@dataclass(frozen=True)
class Rules:
    domains: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.domains or self.keywords)


def normalize_domain(value: str) -> str:
    """'https://www.Example.com/news' -> 'example.com'; '' when it is not a host name."""
    text = (value or "").strip().lower()
    host = (urlparse(text if _SCHEME.match(text) else f"https://{text}").hostname or "").removeprefix("www.")
    return host if "." in host and _HOST.fullmatch(host) else ""


def normalize_keyword(value: str) -> str:
    return " ".join((value or "").split())


def org_of_project(project_id: int) -> int | None:
    """A project's organization, else its owner's (projects created before organizations have none)."""
    project = store.get_project(project_id) or {}
    if project.get("org_id") is not None:
        return project["org_id"]
    owner = store.get_user_by_id(project["owner_user_id"]) if project.get("owner_user_id") else None
    return (owner or {}).get("org_id")


def rules_for_org(org_id: int | None) -> Rules:
    rows = store.list_exclusions(org_id)
    return Rules(domains=tuple(r["value"] for r in rows if r["kind"] == "domain"),
                 keywords=tuple(r["value"] for r in rows if r["kind"] == "keyword"))


def rules_for_project(project_id: int) -> Rules:
    try:
        return rules_for_org(org_of_project(project_id))
    except Exception as e:  # the list being unreadable never stops research; it is logged loudly
        logger.error("exclusion rules unavailable for project %s: %s", project_id, e)
        return Rules()


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.") if url else ""


def excluded(rules: Rules, url: str = "", *texts: str) -> str | None:
    """Why an article is excluded ('domain example.com' / 'keyword "x"'), or None. A domain covers its subdomains;
    a keyword matches as whole words, ignoring case."""
    if not rules:
        return None
    host = _host(url)
    for d in rules.domains:
        if host and (host == d or host.endswith("." + d)):
            return f"domain {d}"
    blob = " ".join(t for t in texts if t)
    for k in rules.keywords:
        if blob and re.search(rf"(?<!\w){re.escape(k)}(?!\w)", blob, re.I):
            return f'keyword "{k}"'
    return None


RESEARCH_LISTS = ("news_items", "background_context", "social_items", "traditional_items", "sources")


def scrub_research(result: dict, rules: Rules) -> dict:
    """A background-research result with excluded articles removed from each of its article lists."""
    if not rules or not isinstance(result, dict):
        return result
    return {k: keep(v, rules) if k in RESEARCH_LISTS and isinstance(v, list) and all(isinstance(i, dict) for i in v)
            else v for k, v in result.items()}


def keep(items: list[dict], rules: Rules, url_key: str = "url") -> list[dict]:
    """The items no rule excludes (dicts with a URL and text fields)."""
    if not rules:
        return items
    out = [i for i in items if not excluded(rules, str(i.get(url_key) or ""),
                                            *(str(i.get(k) or "") for k in _TEXT_KEYS))]
    if len(out) < len(items):
        logger.info("exclusion list removed %d of %d items", len(items) - len(out), len(items))
    return out
