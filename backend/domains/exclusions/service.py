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


# ─── bulk import: pasted text or an uploaded .xlsx / .csv / .txt / .json list ─────────────────────────────────────

MAX_IMPORT_BYTES = 2 * 1024 * 1024
_SPLIT = re.compile(r"[,;\t\r\n ]+")
_SPLIT_KEYWORDS = re.compile(r"[,;\t\r\n]+")          # keywords may contain spaces
_JSON_KEYS = ("domain", "website", "site", "url", "host", "value", "keyword")
_HEADER_WORDS = {"domain", "domains", "website", "websites", "site", "sites", "url", "urls", "host", "hosts", "value",
                 "values", "keyword", "keywords", "term", "terms", "blocked", "exclude", "exclusions", "name"}


class ImportError_(ValueError):
    """The upload cannot be read; the message is shown to the user."""


def split_values(text: str, kind: str = "domain") -> list[str]:
    return [v for v in (_SPLIT if kind == "domain" else _SPLIT_KEYWORDS).split(text or "") if v.strip()]


def _json_values(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [v for item in node for v in _json_values(item)]
    if isinstance(node, dict):
        hits = [node[k] for k in node if str(k).lower() in _JSON_KEYS]
        if hits:
            return [v for h in hits for v in _json_values(h)]
        lists = [v for v in node.values() if isinstance(v, list)]      # {"domains": [...]}, {"blocked": [...]}
        return [v for item in lists for v in _json_values(item)]
    return []


def values_from_file(filename: str, data: bytes, kind: str = "domain") -> list[str]:
    """Every value in an uploaded list. Cells and strings may themselves hold several values (comma separated)."""
    import json
    name = (filename or "").lower()
    if len(data) > MAX_IMPORT_BYTES:
        raise ImportError_("The file is larger than 2 MB")
    if name.endswith((".xlsx", ".xlsm")):
        import io
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise ImportError_("This Excel file could not be read") from e
        cells = [str(c) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for c in row if c is not None]
    elif name.endswith(".json"):
        try:
            cells = _json_values(json.loads(data.decode("utf-8-sig")))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ImportError_("This JSON file could not be read") from e
    elif name.endswith((".csv", ".txt")):
        import csv
        import io
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        cells = [c for row in csv.reader(io.StringIO(text)) for c in row]
    else:
        raise ImportError_("Upload an .xlsx, .csv, .txt or .json file")
    return [v for cell in cells for v in split_values(str(cell), kind)]


def prepare(kind: str, raw: list[str], existing: list[dict]) -> dict:
    """{'add': [...], 'duplicates': n, 'invalid': [...]}: normalised, de-duplicated against the list and the batch."""
    norm = normalize_domain if kind == "domain" else normalize_keyword
    seen = {r["value"].lower() for r in existing if r["kind"] == kind}
    add, invalid, dupes = [], [], 0
    for v in raw:
        if v.strip().lower() in _HEADER_WORDS:          # a spreadsheet's column heading, not a value
            continue
        value = norm(v)
        if not value:
            invalid.append(v.strip()[:80])
        elif value.lower() in seen:
            dupes += 1
        else:
            seen.add(value.lower())
            add.append(value)
    return {"add": add, "duplicates": dupes, "invalid": invalid}


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


# ─── analyst overrides: the organization's memory of blocked articles kept relevant ─────────────────────────────

_RULE = re.compile(r'(domain) (\S+)|(keyword) "(.+)"')
OVERRIDE_TYPE = "exclusion_override"


def _rule_of(reason: str) -> tuple[str, str] | None:
    """('domain', 'x.com') / ('keyword', 'promo') from an excluded() reason, also inside a longer sentence."""
    m = _RULE.search(reason or "")
    if not m:
        return None
    return ("domain", m.group(2).rstrip(")")) if m.group(1) else ("keyword", m.group(4))


def remember_override(project_id: int, reason: str, comment: str, by: str, url: str = "") -> None:
    """Org memory: per rule, how often analysts kept a blocked article and their latest comments. Never raises."""
    try:
        org = org_of_project(project_id)
        rule = _rule_of(reason)
        if not org or not rule:
            return
        key = f"{rule[0]}:{rule[1].lower()}"
        old = store.get_memory_item("org", str(org), OVERRIDE_TYPE, key)
        v = old["value"] if old else {"kind": rule[0], "value": rule[1], "count": 0, "notes": []}
        v["count"] = int(v.get("count", 0)) + 1
        v["notes"] = ([{"comment": comment[:300], "by": by, "url": url[:300], "project_id": project_id}]
                      + list(v.get("notes") or []))[:5]
        store.put_memory_item("org", str(org), OVERRIDE_TYPE, key, v)
        from ..guardrails import service as guardrails
        guardrails.changed(org)          # the agents' context picks it up at once
    except Exception as e:
        logger.warning("exclusion override not remembered: %s", type(e).__name__)


def overrides(org_id: int | None) -> dict[str, dict]:
    """{'domain:x.com': {kind, value, count, notes}} for the organization."""
    if not org_id:
        return {}
    try:
        return {i["key"]: i["value"] for i in store.list_memory_items("org", str(org_id), OVERRIDE_TYPE, limit=200)}
    except Exception:
        return {}


def override_context(org_id: int | None, limit: int = 10) -> str:
    """The analysts' overrides as a prompt section for the org's AI agents (empty when there are none)."""
    items = sorted(overrides(org_id).values(), key=lambda v: -int(v.get("count", 0)))[:limit]
    if not items:
        return ""
    lines = []
    for v in items:
        note = (v.get("notes") or [{}])[0].get("comment", "")
        what = f"site {v['value']}" if v["kind"] == "domain" else f'keyword "{v["value"]}"'
        lines.append(f"- {what}: blocked by the organization, but analysts kept {v['count']} article(s) as relevant"
                     + (f' — "{note}"' if note else ""))
    return ("ANALYST DECISIONS ON BLOCKED CONTENT (the block list still applies; use these only to understand the "
            "analysts' judgment):\n" + "\n".join(lines))


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
