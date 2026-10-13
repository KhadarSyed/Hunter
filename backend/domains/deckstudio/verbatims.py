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
GRID = 8
CAPTURE_VERSION = "6"          # bump when capture rules change: older cached shots are taken again
VIEW_W, VIEW_H = 1280, 800
CAPTURE_TIMEOUT_MS = 20000
SETTLE_MS = 1200
MAX_CONSENT_BUTTONS = 40
_resolve = socket.getaddrinfo
_CONSENT = re.compile(r"^(accept|accept all|agree|i agree|ok|got it|allow all|i accept|continue)$", re.I)
_PAYWALL = re.compile(r"subscribe to (continue|read)|to continue reading|already a subscriber", re.I)
# A page that loaded but is not the article: an error, a bot check or a block (checked on the top of the page only)
_BLOCKED = re.compile(r"\b(403 forbidden|404 not found|page not found|access denied|just a moment|attention required|"
                      r"verify you are (a )?human|are you a robot|captcha|request blocked|unusual traffic|"
                      r"enable javascript and cookies)\b", re.I)
BLOCK_CHECK_CHARS = 600
POST_SELECTOR = "article, blockquote, [data-testid='tweet'], .EmbeddedMedia, .Embed"
_TWEET = re.compile(r"(?:twitter|x)\.com/[^/]+/status/(\d+)")
_INSTA = re.compile(r"instagram\.com/(p|reel)/([\w-]+)")
_TIKTOK = re.compile(r"tiktok\.com/@[^/]+/video/(\d+)")
_BODY_TEXT_JS = "() => document.body ? document.body.innerText.slice(0, 4000) : ''"
_HEADLINE_JS = """() => { const h = document.querySelector('h1') || document.querySelector('article h2');
  if (!h) return {found: false, top: 0}; h.scrollIntoView({block: 'start'});
  return {found: true, top: Math.max(0, h.getBoundingClientRect().top)}; }"""
# The stand-in for a page that cannot be captured reads like a post: who said it, their own words, when.
_CARD = """<html><body style="margin:0;width:{w}px;height:{h}px;font-family:Arial,Helvetica,sans-serif;background:#fff">
<div class="post" style="padding:44px 48px"><div style="display:flex;align-items:center;gap:20px">
<div style="position:relative;width:72px;height:72px;border-radius:50%;background:#5B2C9D;color:#fff;font:700 34px Arial;
display:flex;align-items:center;justify-content:center;flex:none">{initial}{icon}</div><div><div style="font:700 32px Arial;color:#0f1419">{outlet}</div>
<div style="font:400 26px Arial;color:#536471">{handle}</div></div></div>
<div style="font:700 36px/1.3 Arial;color:#0f1419;margin-top:34px">{title}</div>
<div style="font:400 32px/1.45 Arial;color:#0f1419;margin-top:22px">{lead}</div>{image}
<div style="font:400 26px Arial;color:#536471;margin-top:30px">{date}</div></div></body></html>"""
_CARD_IMAGE = ('<img src="{src}" alt="" onerror="this.remove()" style="display:block;width:100%;max-height:330px;'
               'object-fit:cover;border-radius:18px;margin-top:26px">')     # a hot-link-blocked photo just goes
# The page's own headline, summary, lead photo and name (Open Graph tags, else its first h1)
_META_JS = """() => { const m = n => (document.querySelector(`meta[property="${n}"],meta[name="${n}"]`) || {}).content || '';
  const h = document.querySelector('h1');
  return {title: m('og:title') || (h ? h.innerText : ''), description: m('og:description') || m('description'),
          image: m('og:image') || m('twitter:image'), site: m('og:site_name')}; }"""
LEAD_CHARS = 280
FAVICON_URL = "https://www.google.com/s2/favicons?domain={domain}&sz=128"
_ICON = ('<img src="{src}" alt="" onerror="this.remove()" style="position:absolute;inset:0;width:72px;height:72px;'
         'border-radius:50%;background:#fff;object-fit:contain;border:1px solid #e6e6ea">')
CARD_W = 760                      # about a post's width, so a card reads like the captured posts beside it
_CARD_HEIGHT_JS = "() => document.querySelector('.post').getBoundingClientRect().height"


def pick(rows, cited_urls: list[str], limit: int = GRID, ordered: bool = False) -> list[dict]:
    """Cited articles first, then distinct outlets, then the rest; by reach, or in the given order when the rows
    are already ranked by relevance (`ordered`)."""
    by_url = {r.article.url: r for r in rows}
    chosen, seen, outlets, stories = [], set(), set(), set()

    def take(row) -> None:
        a = row.article
        story = " ".join(re.findall(r"[a-z0-9]+", (a.title or "").lower()))     # syndicated copies share it
        if a.norm_url in seen or (story and story in stories) or len(chosen) >= limit:
            return
        seen.add(a.norm_url)
        stories.add(story)
        outlets.add(a.outlet)
        chosen.append({"url": a.url, "outlet": a.outlet, "title": a.title,
                       "date": a.date.isoformat() if a.date else "", "text": (a.text or "")[:400]})

    for url in cited_urls:
        if url in by_url:
            take(by_url[url])
    ranked = list(rows) if ordered else sorted(rows, key=lambda r: -r.article.reach)
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


def _article_card(page, item: dict, url: str, out: Path) -> bool:
    """A news page drawn as a post: its headline, summary and lead photo, read from the page itself."""
    meta = page.evaluate(_META_JS) or {}
    if not meta.get("title") and not page.evaluate(_HEADLINE_JS).get("found"):
        return False
    image = meta.get("image") or ""
    page.goto("about:blank")              # a clean tab: the site's CSP would block the card's markup
    _card(page, {**item, "url": url, "title": item.get("title") or meta.get("title") or "",
                 "text": item.get("text") or meta.get("description") or "",
                 "outlet": item.get("outlet") or meta.get("site") or "",
                 "image": image if image.startswith("https://") and is_public_http(image) else ""}, out)
    return out.exists()


def _capture(page, url: str, out: Path, item: dict | None = None) -> bool:
    target = embed_url(url) or url
    if not is_public_http(target):
        return False
    try:
        page.goto(target, timeout=CAPTURE_TIMEOUT_MS, wait_until="domcontentloaded")
        page.wait_for_timeout(SETTLE_MS)
        _dismiss_consent(page)
        body = page.evaluate(_BODY_TEXT_JS) or ""
        if _PAYWALL.search(body) or _BLOCKED.search(body[:BLOCK_CHECK_CHARS]):
            return False
        if embed_url(url):                    # a social post: the post card itself, as the platform draws it
            post = page.locator(POST_SELECTOR).first
            if post.count():
                post.screenshot(path=str(out))
                return out.exists()
            page.screenshot(path=str(out))
            return out.exists()
        return _article_card(page, item or {}, url, out)
    except Exception as e:      # blocked, timed out, crashed: the article card stands in
        logger.info("screenshot fell back to a card for %s: %s", urlparse(url).hostname, type(e).__name__)
        return False


def _card(page, item: dict, out: Path) -> None:
    sentences = re.split(r"(?<=[.!?])\s+", (item.get("text") or "").strip())
    lead = " ".join(sentences[:2])[:LEAD_CHARS]
    outlet = item.get("outlet") or ""
    domain = (urlparse(item.get("url") or "").hostname or "").removeprefix("www.")
    page.set_content(_CARD.format(w=CARD_W, h=VIEW_H, outlet=html.escape(outlet), initial=html.escape(outlet[:1].upper()),
                                  handle=html.escape(f"@{domain}" if domain else ""),
                                  icon=_ICON.format(src=html.escape(FAVICON_URL.format(domain=domain), quote=True))
                                  if domain else "", title=html.escape(item.get("title") or ""),
                                  date=html.escape(item.get("date") or ""), lead=html.escape(lead),
                                  image=_CARD_IMAGE.format(src=html.escape(item["image"], quote=True))
                                  if item.get("image") else ""))
    if item.get("image"):
        page.wait_for_timeout(SETTLE_MS)          # the lead photo loads before the shot
    height = page.evaluate(_CARD_HEIGHT_JS)
    height = int(height) if isinstance(height, (int, float)) and height > 0 else VIEW_H
    page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": CARD_W, "height": height}, full_page=True)


def collect(items: list[dict], folder: Path, page_factory=None) -> list[dict]:
    folder.mkdir(parents=True, exist_ok=True)
    out: list[dict | None] = []
    todo = []
    for item in items:
        stem = hashlib.sha1(f"{CAPTURE_VERSION}|{item['url']}".encode("utf-8")).hexdigest()[:16]
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
        if _capture(page, item["url"], shot, item):
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
