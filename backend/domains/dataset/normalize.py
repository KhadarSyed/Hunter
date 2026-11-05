"""Export rows -> article records: channel split, link normalisation, post id, author, one shape for every file."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..deliverable.ingest import normalize_url, parse_date
from ..deliverable.rows import author_of

SOCIAL_TYPES = ("social", "twitter", "facebook", "instagram", "tiktok", "reddit", "youtube", "forum", "x ")
SOCIAL_HOSTS = ("x.com", "twitter.com", "facebook.com", "instagram.com", "tiktok.com", "reddit.com", "youtube.com",
                "threads.net", "pinterest.com", "linkedin.com")
_POST_ID = [re.compile(p, re.IGNORECASE) for p in (
    r"(?:x|twitter)\.com/[^/]+/status/(\d+)", r"instagram\.com/(?:p|reel)/([^/?#]+)", r"youtube\.com/watch\?v=([^&#]+)",
    r"youtu\.be/([^/?#]+)", r"tiktok\.com/@[^/]+/video/(\d+)", r"reddit\.com/r/[^/]+/comments/([^/]+)",
    r"facebook\.com/.+/posts/([^/?#]+)", r"linkedin\.com/.*activity[:-](\d+)")]
_KEEP_PARAMS = {"v", "id", "p", "story_fbid", "article", "q"}      # the few query params that choose the page


def _host(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].lower().removeprefix("www.")


def channel_of(media_type: str, url: str) -> str:
    """'social' or 'traditional': the export's source type when it has one, else the link's host."""
    media = (media_type or "").strip().lower()
    if media:
        return "social" if any(t in f"{media} " for t in SOCIAL_TYPES) else "traditional"
    host = _host(url or "")
    return "social" if any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS) else "traditional"


def post_id(url: str) -> str:
    for p in _POST_ID:
        m = p.search(url or "")
        if m:
            return m.group(1)
    return ""


def link_key(url: str) -> str:
    """Dedupe key: no scheme, www, fragment or tracking params (utm_*, fbclid...), lower case, no trailing slash."""
    parts = urlsplit(str(url or "").strip())
    if not parts.netloc:
        return normalize_url(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k.lower() in _KEEP_PARAMS])
    return normalize_url(urlunsplit(("", parts.netloc.removeprefix("www."), parts.path, query, ""))).lstrip("/")


def _reach(v) -> int:
    try:
        return max(int(float(str(v).replace(",", "").strip())), 0)
    except ValueError:
        return 0


def _iso(v) -> str | None:
    d = parse_date(v)
    return d.isoformat() if d else None


def _record(r: dict) -> dict | None:
    url = str(r.get("url") or "").strip()
    title = str(r.get("headline") or r.get("title") or "").strip()
    if not (url or title):
        return None
    handle = str(r.get("author_handle") or "").strip()
    name = str(r.get("author_name") or r.get("author") or "").strip()
    chan = channel_of(str(r.get("media_type") or ""), url)
    from_url = author_of({}, url) if chan == "social" else ""     # an account only a social link can name
    return {"norm_url": link_key(url) or "title:" + title.lower(), "url": url, "channel": chan, "title": title,
            "summary": str(r.get("content") or r.get("snippet") or "").strip(),
            "outlet": str(r.get("source") or r.get("source_name") or _host(url)).strip(),
            "published": _iso(r.get("date")), "country": str(r.get("country") or "").strip(),
            "reach": _reach(r.get("reach")), "author_name": name, "author_id": handle or from_url,
            "post_id": str(r.get("post_id") or r.get("post_id_") or "").strip() or post_id(url), "raw": r}


def records(raw: list[dict]) -> tuple[list[dict], str | None]:
    """(records, error): an error when no row has a link or a title, naming the columns the file does have."""
    out = [rec for rec in map(_record, raw) if rec]
    if raw and not out:
        return [], "No link or title column (columns: " + ", ".join(k for k in raw[0] if k) + ")"
    return out, None if raw else "No rows"
