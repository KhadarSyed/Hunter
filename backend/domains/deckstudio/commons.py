"""Wikimedia photos: their licence read from Commons before one goes on a slide. Public Domain / CC0 need nothing;
CC BY, BY-SA and BY-ND are used with a credit in the deck's appendix; NC (no commercial use) and anything unclear
(fair use, files on a single-language wiki, no licence given) are never used."""
from __future__ import annotations

import html
import logging
import re
from urllib.parse import unquote, urlparse

import requests

logger = logging.getLogger(__name__)
API = "https://commons.wikimedia.org/w/api.php"
TIMEOUT_S = 10
UA = {"User-Agent": "HunterAgent/1.0 (deck photo licence check)"}   # Wikimedia asks every API client to name itself
_TAG = re.compile(r"<[^>]+>")


def is_wikimedia(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("wikimedia.org") or host.endswith("wikipedia.org")


def _file_name(url: str) -> str | None:
    """'File:Name.jpg' from an upload URL (.../commons/a/ab/Name.jpg, or its thumb .../thumb/a/ab/Name.jpg/800px-...)
    or a file page (.../wiki/File:Name.jpg). None for files kept on one language's wiki (mostly fair use)."""
    parts = [unquote(p) for p in urlparse(url).path.split("/") if p]
    if "wiki" in parts and parts[-1].startswith("File:"):
        return parts[-1]
    if len(parts) < 4 or parts[:2] != ["wikipedia", "commons"]:
        return None
    rest = parts[2:]
    if rest[0] == "thumb":
        rest = rest[1:]
    return f"File:{rest[2]}" if len(rest) >= 3 else None


def classify(short_name: str) -> str:
    """'free' (no credit needed), 'credit' (usable when credited) or 'no' from Commons' licence short name."""
    n = short_name.lower().replace("-", " ")
    if re.search(r"\bnc\b", n):
        return "no"
    if "cc0" in n or "public domain" in n or re.match(r"pd\b", n):
        return "free"
    if re.match(r"cc by\b", n):
        return "credit"
    return "no"


_known: dict[str, dict] = {}         # answers Commons gave, for the process life; a failed lookup is asked again


def licence(url: str) -> dict:
    """{'use': free|credit|no, 'name', 'author', 'page'} for a Wikimedia photo; 'no' when Commons cannot say."""
    if url in _known:
        return _known[url]
    name = _file_name(url)
    if not name:
        return {"use": "no", "name": "not on Commons", "author": "", "page": url}
    try:
        r = requests.get(API, params={"action": "query", "titles": name, "prop": "imageinfo", "format": "json",
                                      "iiprop": "extmetadata|url"}, headers=UA, timeout=TIMEOUT_S)
        page = next(iter(r.json()["query"]["pages"].values()))
        info = page["imageinfo"][0]
    except (requests.RequestException, ValueError, KeyError, IndexError, StopIteration) as e:
        logger.warning("commons licence lookup failed for %s: %s", name, type(e).__name__)
        return {"use": "no", "name": "licence unknown", "author": "", "page": url}
    meta = info.get("extmetadata") or {}
    short = (meta.get("LicenseShortName") or {}).get("value", "")
    author = html.unescape(_TAG.sub("", (meta.get("Artist") or {}).get("value", ""))).strip()
    found = {"use": classify(short), "name": short or "no licence given", "author": author or "Unknown author",
             "page": info.get("descriptionurl") or url}
    _known[url] = found
    return found
