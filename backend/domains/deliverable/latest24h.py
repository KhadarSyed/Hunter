"""'Refresh last 7 days' on the Deliverables page: articles from the last 7 days about the brand and its competitors,
streamed per source over /ws, then deduped, relevance-checked, summarised (cited) and charted, and saved.

Sources (all three honour a time window at the API and every item carries a date, re-checked here to the window):
  - SerpAPI google_news: `when:7d` operator.
  - Tavily news: start_date/end_date (day granularity, so the per-item date filter does the exact cut).
  - Google News RSS: `when:168h` operator.
"""
from __future__ import annotations

import contextvars
import html
import json
import logging
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import urlparse

from ...agents.entity_grounding import is_placeholder_brand
from ...core import store
from ...core.events import broadcast
from ..exclusions.service import keep, rules_for_project
from ..research import news_search
from ..research.page_signals import _country_from_cctld, publisher_country
from ..research.web_research import _COUNTRY_ISO_CODES
from ..research.multi_source import search_brand_term
from .evidence import brand_set, mentions

logger = logging.getLogger(__name__)

WINDOW = timedelta(days=7)
REFRESH_MAX_AGE = timedelta(hours=6)   # a deck reuses a stored refresh this long, then fetches up to today again
MAX_PER_QUERY = 40
MAX_BRANDS = 6              # the brand + up to five competitors: one query each, per source
LLM_TIMEOUT_S = 60
SOURCE_LABELS = {"serpapi": "SerpAPI", "tavily": "Tavily", "google_news_rss": "Google News"}
_STOP = set("what which when where how does did have has with from that this their they about into over than "
            "the and for are was were been will would could should brand brands media coverage".split())

_TAG = re.compile(r"<!--.*?-->|<[^>]+>", re.DOTALL)
# A brand whose name is also a person, place or venue ("Chandler's Ford", "Ford Field", "Aaron Ford") needs more than
# its name: the story must also read as company or industry news, or name another brand or a product.
_COMPANY_WORDS = ("company companies firm shares stock stocks investor investors earnings ceo executive executives "
                  "sales revenue profit profits launch launches launched unveil unveils unveiled recall recalls "
                  "recalled dealer dealers dealership factory plant customers inc corp motor motors automaker "
                  "automakers automotive carmaker carmakers tariff tariffs price prices pricing").split()
# shortcut: only the automotive vocabulary is built in; add an industry's words when a non-auto brand is a common word.
_INDUSTRY_WORDS = {r"auto|vehicle|\bcars?\b|\bevs?\b": (
    "car cars vehicle vehicles truck trucks suv suvs sedan sedans pickup pickups crossover ev evs electric hybrid "
    "hybrids engine engines battery batteries charging charger chargers model models horsepower mpg range lineup "
    "trim trims autopilot self-driving robotaxi drive drives driving driver drivers owner owners miles mph crash "
    "crashes registrations deliveries mechanic warranty tire tires v6 v8 hypercar supercar").split()}
_NOT_A_PRODUCT = _STOP | set("is are be has have had says said just also gets got to on in at of for by as it its will "
                             "can may new now not no his her he she says set news".split())
_VENUE = set("field stadium arena center centre hall park parade holiday river foundation museum theatre theater "
             "obituary memorial university college school library hospital church award awards prize street avenue "
             "road county".split())
# A role before "<First name> <Brand>" makes the brand a surname ("CEO Beth Ford", "Executive Director Amy Ford"). A
# capitalised word alone does not: Title Case headlines put one before every brand ("Woman Buys Hyundai").
_ROLES = set("ceo cfo coo cto chief executive director president chair chairman chairwoman founder cofounder governor "
             "mayor senator sen rep representative congressman congresswoman councilman councilwoman minister secretary "
             "judge sheriff officer coach player quarterback actor actress singer rapper author commissioner "
             "superintendent attorney professor dr mr mrs ms".split())
# A sports outlet or section (RotoWire, a college athletics site, /sports/ on a local paper): a brand named there is a
# player, coach or sponsor ("Micah Ford", "Champion Chevrolet Athlete of the Week"), not the company.
_SPORTS = set("sport sports fantasy athletics football cfootball basketball baseball softball hockey soccer nfl nba mlb "
              "nhl ncaa rotowire espn".split())
# Outlets that state their country in their name though their site has no ccTLD ("The Korea Herald", "Times of India",
# "South China Morning Post"): whole words of the name, or the start of the site's name (koreaherald.com).
_NAME_COUNTRY = (("KR", "korea|korean"), ("JP", "japan|japanese"), ("HK", "hong ?kong|south china"),
                 ("CN", "china|chinese"), ("IN", "india|indian"), ("SG", "singapore"), ("PK", "pakistan"),
                 ("PH", "philippines?"), ("AU", "australia|australian"), ("CA", "canada|canadian"))
_HOST_COUNTRY = {"korea": "KR", "japan": "JP", "hongkong": "HK", "china": "CN", "singapore": "SG"}  # not india: indianapolis
# Pure markets items (stock moves, price targets, an investor's picks) are not reputation or media coverage: kept only
# for a finance study, or when the headline is also the brand's business news (a launch, sales, a recall).
_MARKETS = re.compile(r"\b(?:stocks?|shareholders?|investors?|investing|price target|market cap|"
                      r"upgrades?|upgraded|downgrades?|downgraded|analysts?|rally|hedge fund|etf|nasdaq|nyse|"
                      r"otcmkts|michael burry)\b|\([A-Z]{2,6}:[A-Z]+\)", re.IGNORECASE)
_BUSINESS = ("launch launches launched recall recalls recalled sales deliveries exports production factory plant "
             "unveils unveiled").split()
_FINANCE_STUDY = re.compile(r"\b(?:stocks?|share price|shareholders?|investors?|investment|financial|finance|"
                            r"valuation|market cap|equity|earnings)\b", re.IGNORECASE)
# Outlet names written in a script that belongs to one country ("조선일보" is Korean).
_SCRIPT_COUNTRY = ((r"[\uac00-\ud7af]", "KR"), (r"[\u3040-\u30ff]", "JP"), (r"[\u0e00-\u0e7f]", "TH"),
                   (r"[\u0590-\u05ff]", "IL"), (r"[\u0370-\u03ff]", "GR"))
COUNTRY_WORKERS = 8
COUNTRY_BUDGET_S = 20       # an unreadable site (a 30s browser fetch) must not hold up the refresh

_busy: set[int] = set()
_busy_lock = threading.Lock()


class RefreshBusy(RuntimeError):
    pass


# ─── Pure helpers (unit-tested) ──────────────────────────────────────────────

def parse_utc(date_str: str) -> datetime | None:
    """A source's date as an aware UTC datetime; None when unparseable. Offsets are honoured (news_search._parse_date
    drops them), which matters at the window's edge."""
    s = (date_str or "").strip()
    if not s:
        return None
    for parse in (parsedate_to_datetime, lambda v: datetime.fromisoformat(v.replace("Z", "+00:00"))):
        try:
            dt = parse(s)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    naive = news_search._parse_date(s)          # SerpAPI's "09/23/2026, 10:00 AM, +0000 UTC" form
    return naive.replace(tzinfo=timezone.utc) if naive else None


def within_window(date_str: str, now: datetime) -> bool:
    """Published in (now - WINDOW, now + 5min]: an undated item fails, a few minutes of clock skew pass."""
    dt = parse_utc(date_str)
    return dt is not None and now - WINDOW < dt <= now + timedelta(minutes=5)


def _url_key(url: str) -> str:
    p = urlparse(url or "")
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def dedupe(items: list[dict]) -> list[dict]:
    """One item per story: same URL (ignoring scheme, www, query, trailing slash) or same headline. The first copy is
    kept, with `copies` = how many sources/queries carried the story and `sources` = which."""
    out: list[dict] = []
    index: dict[str, int] = {}
    for item in items:
        keys = [k for k in (_url_key(item["url"]), _title_key(item["title"])) if k]
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            hit = len(out)
            out.append({**item, "copies": 0, "sources": []})
        kept = out[hit]
        kept["copies"] += 1
        if item["source"] not in kept["sources"]:
            kept["sources"].append(item["source"])
        for k in keys:
            index.setdefault(k, hit)
    return out


def clean_text(text: str) -> str:
    """Plain text from a source's title/snippet: tags and comments (Barron's '<!-- -->') gone, entities decoded."""
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", text or ""))).strip()


def context_pattern(spec: dict, brands: list) -> re.Pattern:
    """Words that make a brand mention company/industry news: company vocabulary, the industry's vocabulary, every
    brand's spellings and products, and the scope's products and topics."""
    industry = str((spec.get("industry") or {}).get("name") or "") if isinstance(spec.get("industry"), dict) else ""
    words = list(_COMPANY_WORDS)
    for pattern, vocab in _INDUSTRY_WORDS.items():
        if re.search(pattern, industry, re.IGNORECASE):
            words += vocab
    words += [t for b in brands for t in b.terms]
    words += [e["name"] for e in spec.get("validated_entities") or []
              if isinstance(e, dict) and e.get("name") and e.get("type") in ("product", "product_group", "topic")]
    alternation = "|".join(sorted({re.escape(w.lower()) for w in words if w}, key=len, reverse=True))
    return re.compile(rf"(?<![\w-])(?:{alternation})(?![\w-])", re.IGNORECASE)


_AUTO_INDUSTRY = next(iter(_INDUSTRY_WORDS))
# Car brands that also make motorcycles (Honda, BMW, Suzuki): a MotoGP or motorbike story is not car coverage
_MOTO = re.compile(r"\b(?:moto ?gp|moto[23]|wsbk|superbikes?|motorcycles?|motorbikes?|motocross|dirt ?bikes?|"
                   r"scooters?)\b", re.IGNORECASE)
_CAR = re.compile(r"\b(?:cars?|suvs?|sedans?|hatchbacks?|minivans?|crossovers?|pickups?|trucks?|automakers?|"
                  r"carmakers?|dealerships?)\b", re.IGNORECASE)


def car_story(article: dict, spec: dict) -> bool:
    """For a car project: a motorcycle/motorsport-bike story counts only when it also talks about cars."""
    industry = str((spec.get("industry") or {}).get("name") or "") if isinstance(spec.get("industry"), dict) else ""
    text = _text(article)
    return not re.search(_AUTO_INDUSTRY, industry, re.IGNORECASE) or not _MOTO.search(text) or bool(_CAR.search(text))


def _uses(text: str, name: str) -> list[tuple[bool, bool, re.Match | None, bool]]:
    """Each mention of `name`: (a possessive before it, as in "Chandler's Ford" or "China's BYD"; a venue word in the
    three words after it, as in 'Ford Field' or 'Ford Holiday River Parade'; those three words; a role and a first
    name before it, as in 'CEO Beth Ford' or 'Director Amy Ford': the brand as a person's surname)."""
    out = []
    for m in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.IGNORECASE):
        after = re.match(r"\s+([A-Z0-9][\w-]*)(?:\s+([A-Za-z][\w-]*))?(?:\s+([A-Za-z][\w-]*))?", text[m.end():])
        venue = bool(after and any(w and w.lower() in _VENUE for w in after.groups()))
        before = re.search(r"([A-Za-z]+)\s+[A-Z][a-z]+\s+$", text[:m.start()])
        person = bool(before and before.group(1).lower() in _ROLES)
        out.append((bool(re.search(r"\w's\s*$", text[:m.start()])), venue, after, person))
    return out


def _text(article: dict) -> str:
    return f"{article['title']}\n{article['snippet']}"


def ambiguous_brands(articles: list[dict]) -> set[str]:
    """Brands this batch shows naming a venue or a person too (Ford: 'Ford Field', 'CEO Beth Ford'): their stories need
    company/industry context. A brand never seen that way (Tesla, Rivian) is kept on its name alone."""
    return {a["brands"][0] for a in articles if len(a["brands"]) == 1
            and any(venue or person for _, venue, _, person in _uses(_text(a), a["brands"][0]))}


def sports_outlet(article: dict) -> bool:
    """A sports outlet or section: a word of its name, a part of its site's name or a path segment is a sports word."""
    url = urlparse(article.get("url") or "")
    words = re.findall(r"[a-z]+", (article.get("outlet") or "").lower()) + (url.hostname or "").split(".")
    return bool(_SPORTS & {*words, *url.path.lower().split("/")})


def in_context(article: dict, context: re.Pattern, ambiguous: set[str]) -> bool:
    """Not a sports outlet's, and an unambiguous brand, two brands, or an ambiguous one named alongside a context word
    other than its own name, or as '<Brand> <Model>' ('Ford Mustang'), rather than only as a place, venue or person
    ("Chandler's Ford", 'Ford Field', 'Micah Ford')."""
    if sports_outlet(article):
        return False
    if len(article["brands"]) > 1 or not article["brands"] or article["brands"][0] not in ambiguous:
        return True
    name, text = article["brands"][0].lower(), _text(article)
    uses = _uses(text, name)
    if all(person for *_, person in uses):
        return False
    if any(m.group(0).lower() != name for m in context.finditer(text)):
        return True
    return any(not possessive and not venue and after and after.group(1).lower() not in _NOT_A_PRODUCT
               for possessive, venue, after, _ in uses)


def about_brand(article: dict, brands: list) -> bool:
    """The story is about a tracked brand: the headline names it, other than as a person's or account's name
    ('Morgan Eos Fitness'), or the snippet opens with it. A brand only listed in the body of a roundup, a business
    digest or another company's news ('Henrico Business in Brief', a hotel group's amenities) is not."""
    title = article["title"]
    for b in brands:
        if not mentions(title, [b]):
            continue
        rest = re.findall(r"[\w'&-]+", re.sub("|".join(re.escape(t) for t in b.terms), " ", title, flags=re.I))
        if not (len(rest) == 1 and rest[0][:1].isupper() and title.startswith(rest[0])):
            return True
    opening = re.sub(r"^(?:the|a|an)\s+", "", (article.get("snippet") or "").strip(), flags=re.I).lower()
    return any(opening.startswith(t) for b in brands for t in b.terms)


def finance_study(spec: dict) -> bool:
    """The brief is about the brand's stock, investors or finances."""
    parts = [str(spec.get(k) or "") for k in ("research_type", "business_objective", "research_objective",
                                              "research_subject")]
    parts += [str(q.get("question") or "") for q in spec.get("research_questions") or [] if isinstance(q, dict)]
    return bool(_FINANCE_STUDY.search(" ".join(parts)))


def markets_item(article: dict, spec: dict) -> bool:
    """A headline about the stock or investors with nothing of the brand's business or industry in it."""
    title = article["title"]
    if not _MARKETS.search(title):
        return False
    industry = str((spec.get("industry") or {}).get("name") or "") if isinstance(spec.get("industry"), dict) else ""
    words = _BUSINESS + [w for pattern, vocab in _INDUSTRY_WORDS.items() if re.search(pattern, industry, re.IGNORECASE)
                         for w in vocab]
    return not any(re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", title, re.IGNORECASE) for w in words)


def _site(article: dict) -> str:
    """The outlet's page: the article link, or for an undecoded news.google.com link its RSS <source url>."""
    url = article["url"]
    if "news.google.com" in urlparse(url).netloc:
        url = article.get("site") or ""
    return url if url and "news.google.com" not in url else ""


def known_country(article: dict) -> str | None:
    """The country told without fetching anything: the outlet name's script, the site's ccTLD, else the country the
    outlet's name or site name states ("The Korea Herald", koreaherald.com)."""
    outlet = article.get("outlet") or ""
    for pattern, code in _SCRIPT_COUNTRY:
        if re.search(pattern, outlet):
            return code
    host = (urlparse(_site(article)).hostname or "").lower()
    cctld = _country_from_cctld(host)
    if cctld:
        return cctld
    named = next((code for code, words in _NAME_COUNTRY if re.search(rf"\b(?:{words})\b", outlet, re.IGNORECASE)), None)
    label = host.removeprefix("www.").split(".")[0]
    return named or next((code for word, code in _HOST_COUNTRY.items() if label.startswith(word)), None)


def outlet_country(article: dict) -> str | None:
    """The outlet's ISO country when it can be told: known_country, else its site's address (page_signals).
    None when unknown — an undecoded news.google.com link names no publisher."""
    site = _site(article)
    return known_country(article) or (publisher_country(site) if site else None)


def outlet_countries(articles: list[dict]) -> list[str | None]:
    """outlet_country for each article. The offline answers (script, ccTLD) come first and always count: queued
    behind slow site fetches they used to miss the budget, so 조선일보 was kept. Site lookups get COUNTRY_BUDGET_S;
    one that has not answered by then counts as unknown (kept), and goes on in the background, cached per site."""
    known = [known_country(a) for a in articles]
    pool = ThreadPoolExecutor(max_workers=COUNTRY_WORKERS)
    futures = [None if code or not _site(a) else pool.submit(publisher_country, _site(a))
               for a, code in zip(articles, known)]
    wait([f for f in futures if f], timeout=COUNTRY_BUDGET_S)
    pool.shutdown(wait=False)
    return [code or (f.result() if f and f.done() and not f.exception() else None) for code, f in zip(known, futures)]


def project_country(spec: dict) -> str:
    """The project's ISO country for the outlet filter; '' for a global or unrecognised geography (no filter)."""
    geo = str((spec.get("included_scope") or {}).get("geography") or spec.get("geography") or "").strip()
    return geo.upper() if len(geo) == 2 else _COUNTRY_ISO_CODES.get(geo.lower(), "")


def category_terms(brand: str, spec: dict) -> list[str]:
    """A category study's own words, which make category news its coverage as a brand's name makes a brand's:
    'Baby Skincare Category' with industry 'Personal Care / Baby Skincare' -> 'Baby Skincare', 'Personal Care'."""
    industry = str((spec.get("industry") or {}).get("name") or "") if isinstance(spec.get("industry"), dict) else ""
    parts = [brand, *re.split(r"\s*/\s*|\s*[()]\s*", industry)]
    return list(dict.fromkeys(t for p in parts if (t := search_brand_term(p))))


def _rank(articles: list[dict]) -> list[dict]:
    """Top stories first: carried by more sources/queries, then newer."""
    return sorted(articles, key=lambda a: (-a["copies"], -(parse_utc(a["date"]) or datetime.min.replace(
        tzinfo=timezone.utc)).timestamp()))


def build_charts(articles: list[dict], brands: list[str], now: datetime) -> dict:
    """What a week of news supports: share of coverage by brand, daily volume, top outlets (when there are a few)."""
    named = Counter(b for a in articles for b in a["brands"])
    total = sum(named.values()) or 1
    share_brands = [b for b in brands if named[b]]
    share = {"kind": "doughnut", "categories": share_brands,
             "values": [round(100 * named[b] / total, 1) for b in share_brands], "unit": "percent",
             "series_label": "Share of coverage by brand (last 7 days)", "counts": [named[b] for b in share_brands]}
    first = (now - WINDOW).date()           # the window's first (partial) day through today: every kept article is on it
    days = [first + timedelta(days=i) for i in range((now.date() - first).days + 1)]
    per_day = Counter(dt.date() for a in articles if (dt := parse_utc(a["date"])))
    values = [per_day[d] for d in days]
    peak = max(values) if values else 0
    timeline = {"kind": "line_peaks", "categories": [d.strftime("%d %b") for d in days], "values": values,
                "peaks": [i for i, v in enumerate(values) if peak and v == peak][:1], "unit": "count",
                "series_label": "Articles per day (UTC)"}
    shown: dict[str, str] = {}                  # "motor1.com" and "Motor1.com" are one outlet, shown as first seen
    for a in articles:
        if a["outlet"]:
            shown.setdefault(a["outlet"].casefold(), a["outlet"])
    outlets = [(shown[k], n) for k, n in Counter(a["outlet"].casefold() for a in articles if a["outlet"]).most_common(8)]
    # each bar / day's articles (by n), listed when the deck's chart element is clicked
    share["drill"] = {b: [a["n"] for a in articles if b in a["brands"]] for b in share_brands}
    timeline["drill"] = {d.strftime("%d %b"): [a["n"] for a in articles if (dt := parse_utc(a["date"])) and dt.date() == d]
                         for d in days}
    charts = {"share": share, "timeline": timeline}
    if len(outlets) >= 3:
        charts["outlets"] = {"kind": "bar", "categories": [o for o, _ in outlets], "values": [n for _, n in outlets],
                             "unit": "count", "series_label": "Top outlets in the last 7 days",
                             "drill": {o: [a["n"] for a in articles if (a["outlet"] or "").casefold() == o.casefold()]
                                       for o, _ in outlets}}
    return charts


ICON_OUTLETS = 60           # outlets of the top stories that get their site icon (the rest show their initial)
ICON_WORKERS = 8


def outlet_icons(articles: list[dict]) -> dict[str, str]:
    """{outlet: its site icon as a data URI}: the deck shows them inside a sandbox that loads no remote images."""
    import base64
    from ...core import config
    from .visuals import favicon_png
    sites: dict[str, str] = {}
    for a in articles:
        host = (urlparse(_site(a)).hostname or "").removeprefix("www.")
        if a["outlet"] and host and a["outlet"] not in sites and len(sites) < ICON_OUTLETS:
            sites[a["outlet"]] = host
    with ThreadPoolExecutor(max_workers=ICON_WORKERS) as pool:
        files = dict(zip(sites, pool.map(lambda h: favicon_png(h, config.ASSET_CACHE_DIR / "favicons"), sites.values())))
    return {o: "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode("ascii")
            for o, p in files.items() if p and p.is_file()}


def _hhmm(a: dict) -> str:
    dt = parse_utc(a["date"])
    return dt.strftime("%d %b %H:%M UTC") if dt else ""


def deterministic_summary(articles: list[dict], brands: list[str], questions: list[dict], now: datetime) -> list[dict]:
    """Bullets built from the counts and headlines alone; every bullet cites the articles it rests on (by `n`)."""
    if not articles:
        return []
    bullets = []
    named = Counter(b for a in articles for b in a["brands"])
    lead, lead_n = named.most_common(1)[0]
    lead_story = next(a for a in articles if lead in a["brands"])
    bullets.append({"text": f"{len(articles)} new {'article' if len(articles) == 1 else 'articles'} in the last 7 "
                            f"days; {lead} is named in {lead_n} of them, the most of any brand tracked.",
                    "citations": [lead_story["n"]]})
    for brand in brands:
        story = next((a for a in articles if brand in a["brands"]), None)
        if story:
            when = _hhmm(story)
            bullets.append({"text": f"Latest on {brand}: \"{story['title']}\" ({story['outlet'] or 'unknown outlet'}"
                                    f"{', ' + when if when else ''}).", "citations": [story["n"]]})
    daily = Counter(dt.strftime("%d %b") for a in articles if (dt := parse_utc(a["date"])))
    if daily:
        day, k = daily.most_common(1)[0]
        cites = [a["n"] for a in articles if (parse_utc(a["date"]) or now).strftime("%d %b") == day][:3]
        bullets.append({"text": f"Coverage peaked on {day} with {k} {'article' if k == 1 else 'articles'}.",
                        "citations": cites})
    for q in questions:
        words = {w for w in re.findall(r"[a-z]{4,}", q["question"].lower()) if w not in _STOP}
        words -= {w.lower() for b in brands for w in b.split()}
        hits = [a for a in articles if words & set(re.findall(r"[a-z]{4,}", f"{a['title']} {a['snippet']}".lower()))]
        if hits:
            bullets.append({"text": f"{q['id']} ({q['question']}): {len(hits)} new "
                                    f"{'story touches' if len(hits) == 1 else 'stories touch'} this question, "
                                    f"led by \"{hits[0]['title']}\".", "citations": [a["n"] for a in hits[:3]]})
    return bullets


def _llm_summary(llm, articles: list[dict], brands: list[str], questions: list[dict], headline: str) -> list[dict]:
    """The LLM's bullets, kept only when each cites articles that exist; [] means use the deterministic summary."""
    listing = "\n".join(f"[{a['n']}] {a['title']} | {a['outlet']} | {_hhmm(a)} | brands: {', '.join(a['brands'])}"
                        f" | {a['snippet'][:200]}" for a in articles[:60])
    qs = "\n".join(f"{q['id']}: {q['question']}" for q in questions) or "(none)"
    prompt = (f"Brands tracked: {', '.join(brands)}.\nDeck headline: {headline or '(none)'}\nResearch questions:\n{qs}\n\n"
              f"Articles from the last 7 days:\n{listing}\n\n"
              "Write 3-6 short bullets on what is new in the last 7 days, tied to the research questions where the "
              "articles allow. Use only facts in these articles; the articles carry no sentiment scores, so do not claim a "
              "sentiment trend. Each bullet is a plain insight sentence: never mention articles, sources or coverage "
              "of the event (no 'covered in articles [1] and [2]', no '[3] reports'), and put no article numbers in the "
              "text; list the article numbers it rests on in \"citations\" only. "
              'Return JSON: {"bullets": [{"text": "...", "citations": [1, 2]}]}')
    raw = llm.chat([{"role": "system", "content": "You are a media analyst. Answer with JSON only."},
                    {"role": "user", "content": prompt}], format_json=True)
    valid = {a["n"] for a in articles}
    out = []
    for b in (json.loads(raw).get("bullets") or []):
        cites = [int(c) for c in (b.get("citations") or []) if str(c).isdigit() and int(c) in valid]
        text = plain_bullet(str(b.get("text", "")))
        if text and cites:
            out.append({"text": text, "citations": cites})
    return out


# A sentence about where the bullet comes from ("This event is covered in articles [1] and [2].", "Article [5]
# provides details.") and inline "[1, 2]" markers: the citations show as chips, the text keeps the insight only.
_META_SENTENCE = re.compile(r"(?:(?<=[.!?])\s+|^)[^.!?]*\b(?:articles?|sources?|reports?|coverage|covered|stor(?:y|ies))"
                            r"\b[^.!?]*\[\d[^.!?]*[.!?]?", re.IGNORECASE)
_CITE_MARK = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")


def plain_bullet(text: str) -> str:
    text = _CITE_MARK.sub("", _META_SENTENCE.sub("", text.strip()))
    return re.sub(r"\s+([.,;])", r"\1", re.sub(r"\s{2,}", " ", text)).strip()


def summarize(articles: list[dict], brands: list[str], questions: list[dict], headline: str, now: datetime,
              llm=None) -> dict:
    if llm is not None and articles:
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            bullets = pool.submit(contextvars.copy_context().run, _llm_summary, llm, articles, brands, questions, headline).result(timeout=LLM_TIMEOUT_S)
            if bullets:
                return {"source": "llm", "bullets": bullets}
        except Exception as e:      # timeout, unreachable, bad JSON: the deterministic tier still writes real text
            logger.warning("latest24h LLM summary failed (%s); using the deterministic summary", e)
        finally:
            pool.shutdown(wait=False)
    return {"source": "deterministic", "bullets": deterministic_summary(articles, brands, questions, now)}


# ─── Sources ────────────────────────────────────────────────────────────────

def _serpapi(query: str, natural: str, country: str, keys: dict, ok: Callable) -> list[dict]:
    raw = news_search._search_serpapi(query, country, MAX_PER_QUERY, WINDOW.days, keys.get("serpapi"), ok)
    return [news_search._normalize_serpapi_item(i) for i in raw]


def _tavily(query: str, natural: str, country: str, keys: dict, ok: Callable) -> list[dict]:
    today = datetime.now(timezone.utc)
    raw = news_search._search_tavily(natural, country, MAX_PER_QUERY, (today - WINDOW, today), None,
                                     keys.get("tavily"), ok)
    return [news_search._normalize_tavily_item(i) for i in raw]


def _rss(query: str, natural: str, country: str, keys: dict, ok: Callable) -> list[dict]:
    raw = news_search._search_google_news_rss(query, int(WINDOW.total_seconds() // 3600), country)
    ok(True, None)              # shortcut: the RSS helper returns [] on failure too, so an RSS outage reads as 0 found
    return [news_search._normalize_rss_item(i) for i in raw[:MAX_PER_QUERY]]


FETCHERS: dict[str, Callable] = {"serpapi": _serpapi, "tavily": _tavily, "google_news_rss": _rss}


# ─── The job ────────────────────────────────────────────────────────────────

def _context(project: dict) -> dict:
    spec = project.get("spec") or {}
    brand = (spec.get("commissioning_brand") or {}).get("name") or project.get("brand") or ""
    competitors = [e["name"] for e in spec.get("validated_entities") or []
                   if isinstance(e, dict) and e.get("type") == "competitor" and e.get("name")]
    products = [e["name"] for e in spec.get("validated_entities") or []
                if isinstance(e, dict) and e.get("type") in ("product", "product_group") and e.get("name")]
    questions = [{"id": q.get("id") or f"RQ{i + 1}", "question": q.get("question", "")}
                 for i, q in enumerate(spec.get("research_questions") or []) if isinstance(q, dict) and q.get("question")]
    country = ((spec.get("included_scope") or {}).get("geography") or spec.get("geography") or "US")
    country = country if len(country) == 2 else "US"
    return {"brand": brand, "competitors": competitors, "products": products, "questions": questions,
            "country": country.upper()}


def _api_keys(project: dict) -> tuple[dict, Callable]:
    from ..datasources import repository as ds_repo, service as ds_service
    org_id = project.get("org_id")
    keys = {s: ds_repo.get_key(org_id, s) if org_id else None for s in ("serpapi", "tavily")}
    return keys, lambda source, ok, error: ds_service.record_result(org_id, source, ok, error)


def _headline(project_id: int) -> str:
    run = store.get_latest_deliverable_run(project_id)
    if not run:
        return ""
    section = next((s for s in store.list_deliverable_sections(run["id"]) if s.get("id") == "executive-summary"), {})
    return str(((section.get("takeaways") or [{}])[0] or {}).get("headline") or "")   # the deck's lead takeaway


def run_refresh(refresh_id: int, project_id: int, llm=None, now: datetime | None = None) -> dict:
    """Fetch, filter, summarise and save one refresh, broadcasting `latest24h_progress` as counts change."""
    now = now or datetime.now(timezone.utc)

    def emit(**payload) -> None:
        broadcast({"type": "latest24h_progress", "project_id": project_id, "refresh_id": refresh_id, **payload})

    counts = {s: {"label": SOURCE_LABELS[s], "status": "fetching", "found": 0} for s in FETCHERS}
    try:
        project = store.get_project(project_id) or {}
        ctx = _context(project)
        names = [n for n in [ctx["brand"], *ctx["competitors"]] if n][:MAX_BRANDS]
        if not names:
            raise ValueError("The project's specification names no brand or competitors to search for")
        keys, record = _api_keys(project)
        lock = threading.Lock()
        fetched: list[dict] = []

        def fetch_source(source: str) -> None:
            ok_seen = [False]

            def ok(good: bool, error: str | None) -> None:
                ok_seen[0] = ok_seen[0] or good
                if source != "google_news_rss":
                    record(source, good, error)
            emit(source=source, status="fetching", found=0, total=len(fetched))
            try:
                for name in names:
                    term = search_brand_term(name)
                    items = FETCHERS[source](f'"{term}"', f"{term} news", ctx["country"], keys, ok)
                    fresh = [{"title": clean_text(i["title"]) or clean_text(i["content"])[:100],
                              "url": i["published_url"], "site": i.get("publisher_url") or "",
                              "outlet": i["publisher_name"] or _url_key(i["published_url"]).split("/")[0],
                              "date": i["date"], "snippet": clean_text(i["content"])[:400], "source": source}
                             for i in items if i["published_url"] and within_window(i["date"], now)]
                    with lock:
                        fetched.extend(fresh)
                        counts[source]["found"] += len(fresh)
                        total = len(fetched)
                    emit(source=source, status="fetching", found=counts[source]["found"], total=total)
                counts[source]["status"] = "done" if ok_seen[0] or counts[source]["found"] else "failed"
            except Exception as e:
                logger.warning("latest24h %s failed: %s", source, e)
                counts[source]["status"] = "failed"
            emit(source=source, status=counts[source]["status"], found=counts[source]["found"], total=len(fetched))

        with ThreadPoolExecutor(max_workers=len(FETCHERS)) as pool:
            list(pool.map(fetch_source, FETCHERS))

        category = bool(ctx["brand"]) and is_placeholder_brand(ctx["brand"])
        brands = brand_set(names[0], names[1:], [],
                           category_terms(ctx["brand"], project.get("spec") or {}) if category
                           else ctx["products"] if ctx["brand"] else [])
        unique = dedupe(fetched)
        for a in unique:
            a["brands"] = mentions(f"{a['title']}\n{a['snippet']}", brands)
        named = [a for a in unique if a["brands"]]
        context, ambiguous = context_pattern(project.get("spec") or {}, brands), ambiguous_brands(named)
        spec = project.get("spec") or {}
        finance = finance_study(spec)
        on_topic = [a for a in named if about_brand(a, brands) and in_context(a, context, ambiguous) and car_story(a, spec)
                    and (finance or not markets_item(a, spec))]
        country = project_country(project.get("spec") or {})
        if country:
            on_topic = [a for a, c in zip(on_topic, outlet_countries(on_topic)) if c in (None, country)]
        relevant = keep(on_topic, rules_for_project(project_id))
        articles = [{**a, "n": i + 1} for i, a in enumerate(_rank(relevant))]
        emit(phase="filtered", total=len(fetched), unique=len(unique), kept=len(articles))

        brand_names = [b.name for b in brands]
        summary = summarize(articles, brand_names, ctx["questions"], _headline(project_id), now, llm)
        charts = build_charts(articles, brand_names, now) if articles else {}
        if articles:
            try:
                charts["icons"] = outlet_icons(articles)
            except Exception as e:      # icons are decoration: the refresh still saves without them
                logger.warning("latest24h outlet icons failed: %s", e)
        result = {"counts": counts, "fetched": len(fetched), "kept": len(articles), "summary": summary,
                  "charts": charts, "articles": articles}
        store.finish_latest24h_refresh(refresh_id, "completed", counts, len(fetched), len(articles),
                                       summary, charts, articles)
        emit(phase="completed", total=len(fetched), kept=len(articles))
        return result
    except Exception as e:
        logger.exception("latest24h refresh %s failed", refresh_id)
        store.finish_latest24h_refresh(refresh_id, "failed", counts, 0, 0, error=str(e))
        emit(phase="failed", error=str(e))
        return {"error": str(e)}
    finally:
        with _busy_lock:
            _busy.discard(project_id)


def start(project_id: int, *, llm=None, threaded: bool = True) -> int:
    """Start a refresh for the project; one at a time per project."""
    with _busy_lock:
        if project_id in _busy:
            raise RefreshBusy("A last-7-days refresh is already running for this project")
        _busy.add(project_id)
    try:
        refresh_id = store.create_latest24h_refresh(project_id)
    except Exception:
        with _busy_lock:
            _busy.discard(project_id)
        raise
    if threaded:
        threading.Thread(target=contextvars.copy_context().run, args=(_run_with_client, refresh_id, project_id, llm), daemon=True).start()
    else:
        run_refresh(refresh_id, project_id, llm)
    return refresh_id


def _run_with_client(refresh_id: int, project_id: int, llm=None) -> None:
    """The background thread: the LLM client is resolved here (its reachability check is a network call)."""
    if llm is None:
        from ...core.llm_provider import get_llm_client
        try:
            llm = get_llm_client()
        except Exception as e:
            logger.warning("latest24h: no LLM client (%s); deterministic summary", e)
    run_refresh(refresh_id, project_id, llm)
