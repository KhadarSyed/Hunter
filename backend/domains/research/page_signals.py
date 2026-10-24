"""What a web page says about itself: when it was published, which country its publisher is in, and whether
its site lets readers in (free) or refuses / paywalls them (paid).

Used to vet search results that arrive without trustworthy metadata (SearXNG). Pages are fetched the
way article_extractor does it: plain requests first, Scrapling's StealthyFetcher (a real Playwright
browser) only when the page looks bot-blocked. Nothing is guessed: a page that declares no date, or a
site that names no country, gives "" / None.

Publisher country, from address-grade evidence only, strongest first:
  1. a country-code domain (.co.uk, .de; .io/.co/.ai and the like are generic)
  2. a structured address: JSON-LD addressCountry, microdata itemprop="addressCountry", og:country-name
  3. a postal address (US state + ZIP, UK postcode, Canadian postcode) in the footer, then on the
     Contact and About/Impressum pages; country names count only inside an <address>/itemprop="address"
Country names in free text are NOT evidence: footers list international editions ("Australia | India |
Japan"), and many sites print the visitor's own location -- checked against live pages (Britannica's
footer is a region picker). Offices in several countries tie and give no answer. A site's answer is
cached for the life of the process, since every article on it shares one publisher.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import article_extractor

logger = logging.getLogger(__name__)

STEALTH_SLOTS = 2  # concurrent real browsers; each is a full Chromium process
MAX_INFO_PAGES = 2  # About + Contact is enough; more costs time without new evidence

_stealth = threading.Semaphore(STEALTH_SLOTS)
_country_cache: dict[str, str | None] = {}
_cache_lock = threading.Lock()

# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def fetch_page(url: str) -> tuple[int | None, str]:
    """(HTTP status, HTML). Escalates to a real browser only when the plain fetch looks blocked; the status
    is the browser's then. (None, "") when the page couldn't be reached at all (network, TLS, browser)."""
    try:
        status, html = article_extractor._fetch_html(url)
        if article_extractor._looks_blocked(status, html):
            with _stealth:
                status, html = article_extractor._fetch_html_stealth(url)
        return status, html or ""
    except Exception as e:
        logger.debug("Page fetch failed for %s: %s", url, type(e).__name__)
        return None, ""


def fetch_html(url: str) -> str:
    """The page's HTML, or "" when it can't be had."""
    status, html = fetch_page(url)
    return html if status is not None and status < 400 else ""


# --------------------------------------------------------------------------
# Access: can a reader open the site's articles (free), or does it refuse / paywall them (paid)?
# --------------------------------------------------------------------------

REFUSED_STATUSES = {401, 402, 403}  # 429 is "slow down", not a paywall: it says nothing about subscriptions
# Google's paywall markup, which subscription news sites publish so search engines index paywalled text
_NOT_FREE = re.compile(r'"isAccessibleForFree"\s*:\s*"?(?:false|False)"?')
# Only phrases that mean "this article is locked" -- not "subscribe to our newsletter" or "create an account"
_PAYWALL_PHRASES = ("subscribe to continue", "subscribe to read", "you've reached your limit",
                    "free articles remaining", "this content is for subscribers")
_access_cache: dict[str, str | None] = {}


def _access_of_page(status: int | None, html: str) -> str | None:
    if status is None:
        return None  # unreachable says nothing about subscriptions
    if status in REFUSED_STATUSES or _NOT_FREE.search(html) or any(p in html.lower() for p in _PAYWALL_PHRASES):
        return "paid"
    return "free" if status < 400 else None


def access_status(url: str) -> str | None:
    """"paid" when the site refuses readers (401/402/403, even to a real browser) or marks the article
    paywalled; "free" when it opens; None when it couldn't be reached. Judged from the first article seen on
    each site and cached per site -- sites rarely mix, and checking every article would double the fetching."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return None
    with _cache_lock:
        if host in _access_cache:
            return _access_cache[host]
    access = _access_of_page(*fetch_page(url))
    if access is not None:  # an unreachable site is tried again next time, not remembered as unknown
        with _cache_lock:
            _access_cache[host] = access
    return access


# --------------------------------------------------------------------------
# Date in the link itself: /2026/10/21/ or 2026-10-21 (news sites' URL convention)
# --------------------------------------------------------------------------

_URL_DATE = re.compile(r"/(20\d{2})[/-](0[1-9]|1[0-2])[/-](0[1-9]|[12]\d|3[01])(?:/|-|$)")


def date_from_url(url: str) -> str:
    """The publish date a news link carries in its path (e.g. /news/2026/10/21/...), or ""."""
    m = _URL_DATE.search(urlparse(url).path)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


# --------------------------------------------------------------------------
# Published date
# --------------------------------------------------------------------------

_DATE_FIELDS = r"(?:article:published_time|og:published_time|datePublished|date_published|pubdate|publishdate|dc\.date)"
_PAGE_DATE = re.compile(
    rf"""(?:property|name|itemprop)=["']{_DATE_FIELDS}["'][^>]*?(?:content|datetime)=["']([^"']+)["']"""
    rf"""|(?:content|datetime)=["']([^"']+)["'][^>]*?(?:property|name|itemprop)=["']{_DATE_FIELDS}["']"""
    r"""|"datePublished"\s*:\s*"([^"]+)\"""",
    re.IGNORECASE)


def published_date(html: str) -> str:
    """The publish date a page declares (meta tag, JSON-LD or <time itemprop>), or ""."""
    m = _PAGE_DATE.search(html or "")
    return next((g for g in m.groups() if g), "").strip() if m else ""


# --------------------------------------------------------------------------
# Publisher country
# --------------------------------------------------------------------------

# Names as written in addresses. Georgia and Jersey are left out: both are also US place names.
COUNTRY_NAMES = {
    "united states": "US", "united states of america": "US", "usa": "US", "u.s.a.": "US",
    "united kingdom": "GB", "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "great britain": "GB", "canada": "CA", "australia": "AU", "new zealand": "NZ", "ireland": "IE",
    "india": "IN", "singapore": "SG", "malaysia": "MY", "philippines": "PH", "indonesia": "ID",
    "thailand": "TH", "vietnam": "VN", "japan": "JP", "south korea": "KR", "china": "CN",
    "hong kong": "HK", "taiwan": "TW", "united arab emirates": "AE", "uae": "AE", "saudi arabia": "SA",
    "qatar": "QA", "israel": "IL", "turkey": "TR", "türkiye": "TR", "egypt": "EG", "nigeria": "NG",
    "kenya": "KE", "south africa": "ZA", "germany": "DE", "deutschland": "DE", "france": "FR",
    "spain": "ES", "españa": "ES", "italy": "IT", "italia": "IT", "netherlands": "NL",
    "the netherlands": "NL", "belgium": "BE", "switzerland": "CH", "austria": "AT", "sweden": "SE",
    "norway": "NO", "denmark": "DK", "finland": "FI", "poland": "PL", "portugal": "PT",
    "czech republic": "CZ", "greece": "GR", "romania": "RO", "hungary": "HU", "ukraine": "UA",
    "russia": "RU", "brazil": "BR", "brasil": "BR", "mexico": "MX", "méxico": "MX",
    "argentina": "AR", "chile": "CL", "colombia": "CO", "peru": "PE", "pakistan": "PK",
    "bangladesh": "BD", "sri lanka": "LK",
}
_NAME_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, COUNTRY_NAMES), key=len, reverse=True)) + r")\b",
                      re.IGNORECASE)
_US_STATES = ("AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|"
              "NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY")
_POSTCODES = (
    (re.compile(rf"\b(?:{_US_STATES})\s+\d{{5}}(?:-\d{{4}})?\b"), "US"),  # "New York, NY 10001"
    (re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2}\b"), "GB"),        # "London EC2A 4NE"
    (re.compile(r"\b[A-Z]\d[A-Z]\s\d[A-Z]\d\b"), "CA"),                  # "Toronto, ON M5V 2T6"
)
_META_COUNTRY = re.compile(
    r"""(?:property|name)=["'](?:og:country-name|business:contact_data:country_name)["'][^>]*?content=["']([^"']+)""",
    re.IGNORECASE)
_GENERIC_CCTLDS = {"io", "co", "ai", "tv", "me", "ly", "fm", "gg", "to", "cc", "ws", "so", "sh", "is", "am"}
_CCTLD_COUNTRY = {"uk": "GB"}
_INFO_LINK = re.compile(r"about|contact|impressum|imprint|who-we-are|our-company|kontakt", re.IGNORECASE)


def _iso(value: str) -> str | None:
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z]{2}", value):
        return "GB" if value.upper() == "UK" else value.upper()
    return COUNTRY_NAMES.get(value.lower())


def _structured_country(soup: BeautifulSoup, html: str) -> str | None:
    """A country the page states as data: JSON-LD addressCountry (Organization, NewsMediaOrganization,
    LocalBusiness...), microdata itemprop="addressCountry", or an og:country-name meta tag."""
    for script in soup.find_all("script", type="application/ld+json"):
        found = re.findall(r'"addressCountry"\s*:\s*(?:\{[^}]*?"name"\s*:\s*)?"([^"]+)"', script.string or "")
        for value in found:
            if code := _iso(value):
                return code
    for el in soup.select('[itemprop="addressCountry"]'):
        if code := _iso(el.get("content") or el.get_text(" ", strip=True)):
            return code
    m = _META_COUNTRY.search(html)
    return _iso(m.group(1)) if m else None


def _address_votes(soup: BeautifulSoup, text: str) -> Counter:
    """Postal addresses anywhere in `text`, plus country names written inside address blocks."""
    votes: Counter = Counter()
    for pattern, code in _POSTCODES:
        votes[code] += len(pattern.findall(text))
    for block in soup.select('address, [itemprop="address"]'):
        votes.update(COUNTRY_NAMES[m.lower()] for m in _NAME_RE.findall(block.get_text(" ", strip=True)))
    return votes


def _footer_text(soup: BeautifulSoup) -> str:
    parts = soup.find_all("footer") + soup.select('[id*="footer" i], [class*="footer" i]')
    text = " ".join(p.get_text(" ", strip=True) for p in parts)
    return text or soup.get_text(" ", strip=True)[-3000:]  # no marked footer: the end of the page


def _winner(votes: Counter) -> str | None:
    """The clear leader, or None when nothing was found or two countries tie."""
    top = votes.most_common(2)
    if not top or (len(top) == 2 and top[0][1] == top[1][1]):
        return None
    return top[0][0]


def _info_links(soup: BeautifulSoup, home: str) -> list[str]:
    host = urlparse(home).netloc
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        try:
            url = urljoin(home, a["href"]).split("#")[0]
            same_site = urlparse(url).netloc == host
        except ValueError:  # malformed href, e.g. "http://[broken"
            continue
        if same_site and _INFO_LINK.search(a["href"] + " " + a.get_text(" ")) and url not in links:
            links.append(url)
    # Contact pages carry the address more often than About pages
    return sorted(links, key=lambda u: 0 if re.search(r"contact|impressum|imprint|kontakt", u, re.I) else 1)[:MAX_INFO_PAGES]


def _country_from_cctld(host: str) -> str | None:
    tld = host.rsplit(".", 1)[-1]
    if len(tld) == 2 and tld not in _GENERIC_CCTLDS:
        return _CCTLD_COUNTRY.get(tld, tld.upper())
    return None


def _find_publisher_country(host: str) -> str | None:
    if code := _country_from_cctld(host):
        return code
    home = f"https://{host}/"
    html = fetch_html(home)
    soup = BeautifulSoup(html, "lxml")
    if code := _structured_country(soup, html):
        return code
    if code := _winner(_address_votes(soup, _footer_text(soup))):
        return code
    votes: Counter = Counter()
    for url in _info_links(soup, home):
        page_html = fetch_html(url)
        page = BeautifulSoup(page_html, "lxml")
        if code := _structured_country(page, page_html):
            return code
        votes += _address_votes(page, page.get_text(" ", strip=True))
    return _winner(votes)


def publisher_country(url: str) -> str | None:
    """ISO country of the site that published `url`, or None when the site doesn't say. Cached per site."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return None
    with _cache_lock:
        if host in _country_cache:
            return _country_cache[host]
    try:
        code = _find_publisher_country(host)
    except Exception:  # one odd site must never cost the whole result set
        logger.warning("Publisher country check failed for %s", host, exc_info=True)
        code = None
    with _cache_lock:
        _country_cache[host] = code
    logger.debug("Publisher country for %s: %s", host, code)
    return code
