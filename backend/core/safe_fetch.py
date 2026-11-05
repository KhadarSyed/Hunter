"""requests.get for URLs that come from client data: every redirect hop must be a public http(s) host, so a
dataset or search-result link can never make the server call into its own network (SSRF)."""
from __future__ import annotations

from urllib.parse import urljoin

import requests

MAX_REDIRECTS = 3


def safe_get(url: str, *, method: str = "GET", **kw) -> requests.Response | None:
    """The final response after at most MAX_REDIRECTS redirects, or None when a hop is not a public host (or there
    are too many hops). Request errors raise exactly as requests.get's do, so callers keep their own handling."""
    from ..domains.deckstudio.verbatims import is_public_http  # local: importing domains from core at load is circular
    kw["allow_redirects"] = False
    for _ in range(MAX_REDIRECTS + 1):
        if not is_public_http(url):
            return None
        resp = requests.request(method, url, **kw)
        if not (resp.is_redirect and resp.headers.get("location")):
            return resp
        resp.close()
        url = urljoin(url, resp.headers["location"])
    return None
