"""Screenshots of the articles and posts behind each research question, for the verbatim slides and the insight-card
thumbnails. Pages that block automation, paywalls and non-public URLs get a generated article card instead."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import logging
import re
import socket
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)
GRID = 9
VIEW_W, VIEW_H = 1280, 800
CAPTURE_TIMEOUT_MS = 20000
SETTLE_MS = 1200
CROP_ABOVE_HEADLINE = 40
MAX_CONSENT_BUTTONS = 40
_resolve = socket.getaddrinfo
_CONSENT = re.compile(r"^(accept|accept all|agree|i agree|ok|got it|allow all|i accept|continue)$", re.I)
_PAYWALL = re.compile(r"subscribe to (continue|read)|to continue reading|already a subscriber", re.I)
_TWEET = re.compile(r"(?:twitter|x)\.com/[^/]+/status/(\d+)")
_INSTA = re.compile(r"instagram\.com/(p|reel)/([\w-]+)")
_TIKTOK = re.compile(r"tiktok\.com/@[^/]+/video/(\d+)")
_BODY_TEXT_JS = "() => document.body ? document.body.innerText.slice(0, 4000) : ''"
_HEADLINE_JS = """() => { const h = document.querySelector('h1') || document.querySelector('article h2');
  if (!h) return {found: false, top: 0}; h.scrollIntoView({block: 'start'});
  return {found: true, top: Math.max(0, h.getBoundingClientRect().top)}; }"""
_CARD = """<html><body style="margin:0;width:{w}px;height:{h}px;font-family:Arial;background:#fff">
<div style="padding:56px 64px"><div style="font:700 26px Arial;color:#555;letter-spacing:.08em;text-transform:uppercase">
{outlet}</div><div style="font:700 54px/1.15 Georgia;color:#111;margin-top:28px">{title}</div>
<div style="font:400 26px Arial;color:#666;margin-top:24px">{date}</div>
<div style="font:400 30px/1.45 Arial;color:#222;margin-top:36px">{lead}</div></div></body></html>"""


def pick(rows, cited_urls: list[str], limit: int = GRID) -> list[dict]:
    by_url = {r.article.url: r for r in rows}
    chosen, seen, outlets = [], set(), set()

    def take(row) -> None:
        a = row.article
        if a.norm_url in seen or len(chosen) >= limit:
            return
        seen.add(a.norm_url)
        outlets.add(a.outlet)
        chosen.append({"url": a.url, "outlet": a.outlet, "title": a.title,
                       "date": a.date.isoformat() if a.date else "", "text": (a.text or "")[:400]})

    for url in cited_urls:
        if url in by_url:
            take(by_url[url])
    ranked = sorted(rows, key=lambda r: -r.article.reach)
    for row in ranked:                        # distinct outlets first
        if row.article.outlet not in outlets:
            take(row)
    for row in ranked:
        take(row)
    return chosen


def embed_url(url: str) -> str | None:
    if m := _TWEET.search(url):
        return f"https://platform.twitter.com/embed/Tweet.html?id={m.group(1)}"
    if m := _INSTA.search(url):
        return f"https://www.instagram.com/{m.group(1)}/{m.group(2)}/embed"
    if m := _TIKTOK.search(url):
        return f"https://www.tiktok.com/embed/v2/{m.group(1)}"
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname.endswith("youtube.com") and (v := parse_qs(parsed.query).get("v")):
        return f"https://www.youtube.com/embed/{v[0]}"
    if parsed.hostname == "youtu.be" and parsed.path.strip("/"):
        return f"https://www.youtube.com/embed/{parsed.path.strip('/')}"
    return None


def is_public_http(url: str) -> bool:
    """Only public http(s) pages are opened: dataset URLs are client data, never trusted to point inside the network."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = _resolve(parsed.hostname, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return bool(infos)


@lru_cache(maxsize=2048)
def _origin_public(scheme: str, host: str) -> bool:
    return is_public_http(f"{scheme}://{host}/")


def _public(url: str) -> bool:
    if url.startswith(("data:", "blob:", "about:")):
        return True
    parsed = urlparse(url)
    return bool(parsed.hostname) and _origin_public(parsed.scheme, parsed.hostname)


def _guard_route(route, check=None) -> None:
    """Every request the screenshot browser makes, redirects included, must go to a public host."""
    if (check or _public)(route.request.url):
        route.continue_()
    else:
        route.abort()


@contextmanager
def _browser_page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": VIEW_W, "height": VIEW_H})
            page.route("**/*", lambda route, _request: _guard_route(route))   # redirects and sub-requests too
            yield page
        finally:
            browser.close()


def _dismiss_consent(page) -> None:
    buttons = page.locator("button")
    for i in range(min(buttons.count(), MAX_CONSENT_BUTTONS)):
        b = buttons.nth(i)
        if _CONSENT.match((b.inner_text() or "").strip()):
            b.click(timeout=2000)
            return


def _capture(page, url: str, out: Path) -> bool:
    target = embed_url(url) or url
    if not is_public_http(target):
        return False
    try:
        page.goto(target, timeout=CAPTURE_TIMEOUT_MS, wait_until="domcontentloaded")
        page.wait_for_timeout(SETTLE_MS)
        _dismiss_consent(page)
        if _PAYWALL.search(page.evaluate(_BODY_TEXT_JS) or ""):
            return False
        head = page.evaluate(_HEADLINE_JS)
        if not embed_url(url) and not head.get("found"):
            return False
        top = max(0, int(head.get("top", 0)) - CROP_ABOVE_HEADLINE)
        page.screenshot(path=str(out), clip={"x": 0, "y": top, "width": VIEW_W, "height": VIEW_H - top} if top else None)
        return out.exists()
    except Exception as e:      # blocked, timed out, crashed: the article card stands in
        logger.info("screenshot fell back to a card for %s: %s", urlparse(url).hostname, type(e).__name__)
        return False


def _card(page, item: dict, out: Path) -> None:
    lead = re.split(r"(?<=[.!?])\s", (item.get("text") or "").strip(), maxsplit=1)[0][:220]
    page.set_content(_CARD.format(w=VIEW_W, h=VIEW_H, outlet=html.escape(item.get("outlet") or ""),
                                  title=html.escape(item.get("title") or ""), date=html.escape(item.get("date") or ""),
                                  lead=html.escape(lead)))
    page.screenshot(path=str(out))


def collect(items: list[dict], folder: Path, page_factory=None) -> list[dict]:
    folder.mkdir(parents=True, exist_ok=True)
    out: list[dict | None] = []
    todo = []
    for item in items:
        stem = hashlib.sha1(item["url"].encode("utf-8")).hexdigest()[:16]
        meta = folder / f"{stem}.json"
        if meta.exists() and Path(json.loads(meta.read_text("utf-8"))["image"]).exists():
            out.append({**item, **json.loads(meta.read_text("utf-8"))})
            continue
        out.append(None)
        todo.append((len(out) - 1, item, folder / f"{stem}.png", folder / f"{stem}-card.png", meta))
    if todo:
        with (page_factory or _browser_page)() as page:
            for idx, item, shot, card, meta in todo:
                found = _one(page, item, shot, card)
                if found["image"]:
                    meta.write_text(json.dumps(found), encoding="utf-8")
                out[idx] = {**item, **found}
    return out


def _one(page, item: dict, shot: Path, card: Path) -> dict:
    """A screenshot, else an article card drawn on a clean tab (a visited site's CSP, e.g. Trusted Types, would block
    it), else nothing: one difficult article never stops the others."""
    try:
        if _capture(page, item["url"], shot):
            return {"image": str(shot), "kind": "screenshot"}
        try:
            page.goto("about:blank")
        except Exception:       # the card is still attempted; a failure there is handled below
            pass
        _card(page, item, card)
        return {"image": str(card), "kind": "card"}
    except Exception as e:
        logger.warning("verbatim skipped for %s: %s", urlparse(item["url"]).hostname, type(e).__name__)
        return {"image": None, "kind": "none"}
