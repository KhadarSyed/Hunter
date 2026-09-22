"""Live web research adapter using DuckDuckGo search.

Implements the WebResearchAdapter protocol from brand_intelligence.py
and provides structured brand research with citation tracking, entity
validation, date filtering, and source quality classification.
"""
from __future__ import annotations

import re
import time
import hashlib
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional
from urllib.parse import urlparse

EventFn = Callable[[str, dict], None]

# ─── Source quality tiers ────────────────────────────────────────────────────

TIER_1_DOMAINS = {
    "sec.gov", "ftc.gov", "fda.gov", "epa.gov", "usda.gov",
    "reuters.com", "apnews.com", "bloomberg.com", "wsj.com",
    "ft.com", "nytimes.com", "washingtonpost.com",
    "bbc.com", "bbc.co.uk",
}

TIER_2_DOMAINS = {
    "cnbc.com", "forbes.com", "fortune.com", "businessinsider.com",
    "theguardian.com", "techcrunch.com", "wired.com", "theverge.com",
    "marketwatch.com", "seekingalpha.com", "investopedia.com",
    "adage.com", "adweek.com", "prweek.com", "digiday.com",
    "gartner.com", "forrester.com", "mckinsey.com",
    "deloitte.com", "pwc.com", "ey.com", "kpmg.com",
    "statista.com", "emarketer.com", "nielseniq.com",
    "hbr.org", "economist.com", "morningstar.com",
    "fooddive.com", "foodbusinessnews.net", "progressivegrocer.com",
    "supermarketnews.com", "grocerydive.com", "meatpoultry.com",
    "packagingdigest.com", "newfoodmagazine.com",
}

TIER_3_DOMAINS = {
    "medium.com", "substack.com", "hubspot.com",
    "delish.com", "allrecipes.com", "foodnetwork.com",
    "buzzfeed.com", "huffpost.com", "mashable.com",
    "tastingtable.com", "eater.com", "seriouseats.com",
}

BLOCKED_DOMAINS = {
    "wikipedia.org", "wikimedia.org", "wiktionary.org", "britannica.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "pinterest.com",
    "linkedin.com", "reddit.com", "quora.com",
    "flipkart.com", "amazon.in", "myntra.com", "snapdeal.com",
    "naukri.com", "indiamart.com", "justdial.com", "zomato.com",
    "swiggy.com", "bigbasket.com", "jiomart.com", "meesho.com",
    "etsy.com", "ebay.com", "aliexpress.com",
}

BLOCKED_TLDS = {".in", ".co.in", ".org.in", ".net.in", ".ind.in"}


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host.lower()
    except Exception:
        return ""


def _is_blocked(url: str) -> bool:
    domain = _extract_domain(url)
    if any(domain == bd or domain.endswith("." + bd) for bd in BLOCKED_DOMAINS):
        return True
    if any(domain.endswith(tld) for tld in BLOCKED_TLDS):
        return True
    return False


def _classify_source_tier(url: str) -> str:
    domain = _extract_domain(url)
    if any(domain == d or domain.endswith("." + d) for d in TIER_1_DOMAINS):
        return "tier_1"
    if any(domain == d or domain.endswith("." + d) for d in TIER_2_DOMAINS):
        return "tier_2"
    if any(domain == d or domain.endswith("." + d) for d in TIER_3_DOMAINS):
        return "tier_3"
    if domain.endswith(".gov") or domain.endswith(".edu"):
        return "tier_1"
    return "tier_3"


def _parse_date(date_str: str) -> Optional[date]:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y",
                "%d %b %Y", "%d %B %Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str.strip()[:19], fmt).date()
        except (ValueError, IndexError):
            continue
    date_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
    if date_match:
        try:
            return date(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
        except ValueError:
            pass
    return None


def _deduplicate_results(results: list[dict]) -> list[dict]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[dict] = []
    for r in results:
        url = r.get("url", "")
        title_key = re.sub(r"\W+", "", (r.get("title", "")).lower())
        if url in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title_key:
            seen_titles.add(title_key)
        deduped.append(r)
    return deduped


# ─── Entity relevance validation ────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    """Normalize smart quotes and unicode punctuation to ASCII equivalents."""
    return (text
            .replace("‘", "'").replace("’", "'")
            .replace("“", '"').replace("”", '"')
            .replace("–", "-").replace("—", "-")
            .replace("â", "'"))


class EntityValidator:
    """Validates whether a search result is relevant to the target entity."""

    def __init__(self, brand_name: str, category: str, geography: str,
                 exclude_patterns: list[str] | None = None):
        self.brand_name = brand_name
        self.brand_lower = _normalize_text(brand_name.lower())
        self.category = category.lower()
        self.geography = geography.lower()
        self.exclude_patterns = [p.lower() for p in (exclude_patterns or [])]

        self._build_rejection_rules()

    def _build_rejection_rules(self):
        self.rejection_terms: list[tuple[str, str]] = []

        if "mrs" in self.brand_lower:
            self.rejection_terms.extend([
                ("mrs. doubtfire", "Movie reference, not brand"),
                ("mrs doubtfire", "Movie reference, not brand"),
                ("mrs. fields", "Different brand (Mrs. Fields Cookies)"),
                ("mrs fields", "Different brand (Mrs. Fields Cookies)"),
                ("mr. t", "Different entity (actor Mr. T)"),
                ("mr t pity", "Different entity (actor Mr. T)"),
                ("mrs. butterworth", "Different brand"),
                ("mrs butterworth", "Different brand"),
                ("dear mrs", "Honorific usage, not brand"),
                ("mrs. smith", "Generic honorific usage"),
                ("grammar", "Grammar/writing guidance"),
                ("honorific", "Linguistic reference to Mrs. title"),
                ("salutation", "Linguistic reference to Mrs. title"),
                ("etiquette", "Social etiquette, not brand"),
            ])

        for pattern in self.exclude_patterns:
            self.rejection_terms.append((pattern, f"Excluded by spec: {pattern}"))

    def validate(self, title: str, snippet: str, url: str) -> dict:
        text = _normalize_text(f"{title} {snippet}".lower())

        for term, reason in self.rejection_terms:
            if term in text:
                return {
                    "relevant": False,
                    "reason": reason,
                    "confidence": "high",
                }

        brand_mentioned = self.brand_lower in text
        brand_parts = re.split(r"[^a-z0-9]+", self.brand_lower)
        brand_parts = [p for p in brand_parts if len(p) > 2]
        partial_match = any(p in text for p in brand_parts)

        category_mentioned = any(
            kw in text for kw in self.category.split()
            if len(kw) > 3
        )

        if brand_mentioned:
            return {"relevant": True, "reason": "Brand name found in content", "confidence": "high"}

        if partial_match and category_mentioned:
            return {"relevant": True, "reason": "Partial brand match + category context", "confidence": "medium"}

        if category_mentioned:
            return {"relevant": True, "reason": "Category-relevant content", "confidence": "medium"}

        return {"relevant": False, "reason": "No brand or category relevance detected", "confidence": "medium"}


# ─── Search query families ───────────────────────────────────────────────────

def build_search_queries(
    brand_name: str,
    parent_company: str | None,
    category: str,
    products: list[str],
    geography: str,
    audience: str,
    research_questions: list[str],
    competitors: list[str] | None = None,
) -> list[dict]:
    """Generate targeted search query families per the specification."""
    year = date.today().year
    queries: list[dict] = []

    def add(family: str, query: str, use_news: bool = False):
        queries.append({"family": family, "query": query, "use_news": use_news})

    add("brand_identity", f'"{brand_name}" company about', False)
    if parent_company:
        add("parent_company", f'"{parent_company}" "{brand_name}"', False)

    for product in products[:2]:
        add("products", f'"{brand_name}" "{product}"', False)

    add("announcements", f'"{brand_name}" news announcement {year}', True)
    add("campaigns", f'"{brand_name}" campaign marketing {year}', True)
    add("partnerships", f'"{brand_name}" partnership {year}', True)
    add("leadership", f'"{brand_name}" CEO executive leadership', True)
    add("controversies", f'"{brand_name}" controversy issue {year}', True)

    if competitors:
        for comp in competitors[:5]:
            add("competitor", f'"{comp}" {category} news {year}', True)

    add("category", f'{category} trends market {year}', True)
    add("consumer_trends", f'{category} consumer trends {year}', True)

    for rq in research_questions[:2]:
        short = rq[:80] if len(rq) > 80 else rq
        add("research_question", f'{brand_name} {short}', True)

    return queries


# ─── DuckDuckGo search functions ────────────────────────────────────────────

import logging as _logging
_log = _logging.getLogger(__name__)

_DDG_DELAY = 1.5
_DDG_RETRY_DELAY = 3.0


_DDG_HTTP_TIMEOUT = 15


def _ddg_web_search(query: str, max_results: int = 8, _retries: int = 1) -> list[dict]:
    for attempt in range(_retries + 1):
        try:
            from ddgs import DDGS
            with DDGS(timeout=_DDG_HTTP_TIMEOUT) as ddgs:
                raw = list(ddgs.text(query, region="us-en", max_results=max_results))
            if raw:
                results = []
                for r in raw:
                    results.append({
                        "title": r.get("title", ""),
                        "snippet": r.get("body", "") or r.get("snippet", ""),
                        "url": r.get("href", "") or r.get("url", "") or r.get("link", ""),
                        "source": r.get("source", ""),
                        "date": r.get("date", ""),
                    })
                return results
            if attempt < _retries:
                _log.warning("DDG web search returned 0 results for %r — retrying after %.1fs", query, _DDG_RETRY_DELAY)
                time.sleep(_DDG_RETRY_DELAY)
        except Exception as e:
            _log.warning("DDG web search error (attempt %d): %s", attempt + 1, e)
            if attempt < _retries:
                time.sleep(_DDG_RETRY_DELAY)
    return []


def _ddg_news_search(query: str, max_results: int = 6, _retries: int = 1) -> list[dict]:
    for attempt in range(_retries + 1):
        try:
            from ddgs import DDGS
            with DDGS(timeout=_DDG_HTTP_TIMEOUT) as ddgs:
                raw = list(ddgs.news(query, region="us-en", max_results=max_results))
            if raw:
                results = []
                for r in raw:
                    results.append({
                        "title": r.get("title", ""),
                        "snippet": r.get("body", "") or r.get("snippet", ""),
                        "url": r.get("url", "") or r.get("href", "") or r.get("link", ""),
                        "source": r.get("source", ""),
                        "date": r.get("date", ""),
                    })
                return results
            if attempt < _retries:
                _log.warning("DDG news search returned 0 results for %r — retrying after %.1fs", query, _DDG_RETRY_DELAY)
                time.sleep(_DDG_RETRY_DELAY)
        except Exception as e:
            _log.warning("DDG news search error (attempt %d): %s", attempt + 1, e)
            if attempt < _retries:
                time.sleep(_DDG_RETRY_DELAY)
    return []


# ─── Main adapter class ─────────────────────────────────────────────────────

class LiveWebResearchAdapter:
    """Implements the WebResearchAdapter protocol using DuckDuckGo.

    Produces structured brand research with:
    - Targeted search query families
    - Entity relevance validation
    - Date range filtering
    - Source quality classification (Tier 1/2/3/Rejected)
    - Deduplication
    - Full citation tracking
    """

    def __init__(self, emit: EventFn | None = None):
        self._emit = emit or (lambda et, p: None)

    async def search(self, query: str, time_period: str) -> list[dict]:
        """Execute a single web search — satisfies the protocol."""
        results = _ddg_web_search(query, max_results=8)
        time.sleep(1.5)
        return [
            {
                "url": r["url"],
                "title": r["title"],
                "snippet": r["snippet"],
            }
            for r in results if not _is_blocked(r.get("url", ""))
        ]

    async def fetch_url(self, url: str) -> dict:
        """Fetch URL content — satisfies the protocol."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                text = resp.text[:5000]
                return {"url": url, "title": "", "text": text, "status": resp.status_code}
        except Exception as e:
            return {"url": url, "title": "", "text": "", "status": 0, "error": str(e)}

    def run_full_research(
        self,
        spec: dict,
        *,
        emit: EventFn | None = None,
    ) -> dict:
        """Execute the complete brand research workflow.

        Returns a structured dict with all sources, citations, validation
        results, and the research output ready for the frontend.
        """
        _emit = emit or self._emit
        start = time.time()

        brand_name = self._extract_brand_name(spec)
        parent_company = self._extract_parent_company(spec)
        category = self._extract_category(spec)
        products = self._extract_products(spec)
        geography = self._extract_geography(spec)
        audience = self._extract_audience(spec)
        research_questions = self._extract_rqs(spec)
        competitors = self._extract_competitors(spec)
        date_range = self._extract_date_range(spec)

        if not brand_name:
            return {
                "status": "failed",
                "error": "Could not identify brand name from specification",
                "web_search_executed": False,
            }

        _emit("research_started", {"brand": brand_name, "category": category, "competitors": competitors})

        # Build entity validator
        exclude_patterns = self._extract_exclusions(spec)
        validator = EntityValidator(brand_name, category, geography, exclude_patterns)

        # Generate search queries
        queries = build_search_queries(
            brand_name, parent_company, category, products,
            geography, audience, research_questions, competitors,
        )
        _emit("research_queries_built", {"count": len(queries)})

        # Execute searches
        all_raw: list[dict] = []
        search_log: list[dict] = []

        for i, q in enumerate(queries):
            _emit("research_searching", {
                "query": q["query"],
                "family": q["family"],
                "index": i + 1,
                "total": len(queries),
            })

            web_results = _ddg_web_search(q["query"], max_results=8, _retries=1)
            time.sleep(_DDG_DELAY)

            news_results = []
            if q.get("use_news"):
                news_results = _ddg_news_search(q["query"], max_results=6, _retries=1)
                time.sleep(_DDG_DELAY)

            for r in web_results + news_results:
                r["_family"] = q["family"]
                r["_query"] = q["query"]
                r["_search_type"] = "news" if r in news_results else "web"

            all_raw.extend(web_results)
            all_raw.extend(news_results)
            search_log.append({
                "query": q["query"],
                "family": q["family"],
                "web_count": len(web_results),
                "news_count": len(news_results),
            })

        _emit("research_filtering", {"total_raw": len(all_raw)})

        # Filter blocked domains
        filtered = [r for r in all_raw if not _is_blocked(r.get("url", ""))]

        # Deduplicate
        deduped = _deduplicate_results(filtered)
        _emit("research_deduplicating", {"before": len(filtered), "after": len(deduped)})

        # Validate entity relevance
        _emit("research_validating_entities", {"count": len(deduped)})
        validated: list[dict] = []
        rejected: list[dict] = []

        for r in deduped:
            if r.get("_family") == "competitor":
                r["_validation"] = {"relevant": True, "reason": "Competitor search result", "confidence": "high"}
                validated.append(r)
            else:
                validation = validator.validate(
                    r.get("title", ""), r.get("snippet", ""), r.get("url", "")
                )
                r["_validation"] = validation
                if validation["relevant"]:
                    validated.append(r)
                else:
                    rejected.append(r)

        _emit("research_entity_validation_complete", {
            "retained": len(validated),
            "rejected": len(rejected),
        })

        # Validate dates
        _emit("research_validating_dates", {"count": len(validated)})
        in_range: list[dict] = []
        context_only: list[dict] = []
        range_start, range_end = date_range

        for r in validated:
            pub_date = _parse_date(r.get("date", ""))
            r["_pub_date"] = pub_date.isoformat() if pub_date else None

            if pub_date is None:
                r["_date_status"] = "unknown"
                r["_date_note"] = "Publication date not available"
                in_range.append(r)
            elif range_start <= pub_date <= range_end:
                r["_date_status"] = "in_range"
                r["_date_note"] = f"Within approved range ({range_start} to {range_end})"
                in_range.append(r)
            else:
                r["_date_status"] = "out_of_range"
                r["_date_note"] = f"Outside range; retained as background context"
                context_only.append(r)

        # Classify source quality
        _emit("research_classifying_sources", {"count": len(in_range) + len(context_only)})
        all_retained = in_range + context_only

        for r in all_retained:
            url = r.get("url", "")
            r["_tier"] = _classify_source_tier(url)
            r["_domain"] = _extract_domain(url)

        # Build structured output
        sources_reviewed = len(all_raw)
        sources_retained = len(all_retained)
        sources_rejected = len(rejected) + (len(all_raw) - len(filtered))
        tier_1_count = sum(1 for r in all_retained if r["_tier"] == "tier_1")
        tier_2_count = sum(1 for r in all_retained if r["_tier"] == "tier_2")
        tier_3_count = sum(1 for r in all_retained if r["_tier"] == "tier_3")

        # Build citation records
        news_items = []
        for r in in_range:
            news_items.append({
                "headline": r.get("title", ""),
                "publisher": r.get("source", "") or r["_domain"],
                "date": r.get("_pub_date") or r.get("date", ""),
                "url": r.get("url", ""),
                "tier": r["_tier"],
                "summary": r.get("snippet", ""),
                "family": r.get("_family", ""),
                "query": r.get("_query", ""),
                "date_status": r.get("_date_status", ""),
                "date_note": r.get("_date_note", ""),
                "relevance_confidence": r.get("_validation", {}).get("confidence", ""),
                "relevance_reason": r.get("_validation", {}).get("reason", ""),
                "access_date": date.today().isoformat(),
                "approval_status": "pending",
            })

        background_context = []
        for r in context_only:
            background_context.append({
                "headline": r.get("title", ""),
                "publisher": r.get("source", "") or r["_domain"],
                "date": r.get("_pub_date") or r.get("date", ""),
                "url": r.get("url", ""),
                "tier": r["_tier"],
                "summary": r.get("snippet", ""),
                "date_note": r.get("_date_note", ""),
                "access_date": date.today().isoformat(),
            })

        rejected_records = []
        for r in rejected:
            rejected_records.append({
                "headline": r.get("title", ""),
                "url": r.get("url", ""),
                "rejection_reason": r.get("_validation", {}).get("reason", ""),
            })

        # Identify research gaps
        gaps = []
        families_covered = {r.get("_family") for r in all_retained}
        expected_families = {
            "brand_identity", "products", "positioning", "social_channels",
            "announcements", "campaigns", "partnerships", "leadership",
            "controversies", "category", "consumer_trends", "cultural",
        }
        missing_families = expected_families - families_covered
        for fam in missing_families:
            gaps.append(f"No results found for search family: {fam}")

        if tier_1_count == 0:
            gaps.append("No Tier 1 (authoritative) sources found")

        if not news_items:
            gaps.append("No recent news items found within the approved date range")

        elapsed = round(time.time() - start, 1)

        _emit("research_complete", {
            "sources_retained": sources_retained,
            "sources_rejected": sources_rejected,
            "tier_1": tier_1_count,
            "elapsed": elapsed,
        })

        return {
            "status": "completed",
            "web_search_executed": True,
            "brand_name": brand_name,
            "metadata": {
                "sources_reviewed": sources_reviewed,
                "sources_retained": sources_retained,
                "sources_rejected": sources_rejected,
                "tier_1_count": tier_1_count,
                "tier_2_count": tier_2_count,
                "tier_3_count": tier_3_count,
                "date_range_start": range_start.isoformat(),
                "date_range_end": range_end.isoformat(),
                "search_queries_executed": len(queries),
                "elapsed_seconds": elapsed,
                "execution_date": date.today().isoformat(),
            },
            "news_items": news_items,
            "background_context": background_context,
            "rejected_sources": rejected_records,
            "search_log": search_log,
            "research_gaps": gaps,
            "confidence": {
                "overall": "high" if tier_1_count >= 1 and len(news_items) >= 3 else
                           "medium" if len(news_items) >= 1 else "low",
                "brand_clarity": "high" if any(r["_family"] == "brand_identity" for r in all_retained) else "low",
                "category_clarity": "high" if any(r["_family"] == "category" for r in all_retained) else "medium",
                "news_coverage": "high" if len(news_items) >= 5 else
                                 "medium" if len(news_items) >= 2 else "low",
            },
        }

    # ─── Spec field extractors ───────────────────────────────────────────

    def _extract_brand_name(self, spec: dict) -> str:
        cb = spec.get("commissioning_brand", {})
        if isinstance(cb, dict) and cb.get("name"):
            return cb["name"]
        for ent in spec.get("validated_entities", []):
            if isinstance(ent, dict) and ent.get("type") == "brand":
                return ent.get("name", "")
        rs = spec.get("research_subject", {})
        if isinstance(rs, dict) and rs.get("description"):
            return rs["description"]
        return ""

    def _extract_parent_company(self, spec: dict) -> str | None:
        cb = spec.get("commissioning_brand", {})
        if isinstance(cb, dict):
            return cb.get("parent_company")
        return None

    def _extract_category(self, spec: dict) -> str:
        cb = spec.get("commissioning_brand", {})
        if isinstance(cb, dict) and cb.get("category"):
            return cb["category"]
        if spec.get("category"):
            return spec["category"]
        for ve in spec.get("validated_entities", []):
            if isinstance(ve, dict) and ve.get("type") == "brand" and ve.get("category"):
                return ve["category"]
        subj = spec.get("research_subject", {})
        if isinstance(subj, dict):
            desc = subj.get("description", "")
            for kw, cat in [("snack", "snack food"), ("food", "food & beverage"),
                            ("beverage", "food & beverage"), ("jerky", "meat snacks"),
                            ("meat", "meat snacks"), ("beauty", "beauty & personal care"),
                            ("tech", "technology"), ("fashion", "fashion & apparel"),
                            ("auto", "automotive"), ("health", "health & wellness")]:
                if kw in desc.lower():
                    return cat
        return "general"

    def _extract_products(self, spec: dict) -> list[str]:
        cb = spec.get("commissioning_brand", {})
        if isinstance(cb, dict) and cb.get("products"):
            return cb["products"]
        return []

    def _extract_geography(self, spec: dict) -> str:
        scope = spec.get("included_scope", {})
        if isinstance(scope, dict):
            countries = scope.get("countries", [])
            if countries:
                return countries[0]
        return "US"

    def _extract_audience(self, spec: dict) -> str:
        ra = spec.get("research_audience", {})
        if isinstance(ra, dict) and ra.get("description"):
            return ra["description"]
        return ""

    def _extract_rqs(self, spec: dict) -> list[str]:
        rqs = spec.get("research_questions", [])
        return [
            rq["question"] for rq in rqs
            if isinstance(rq, dict) and rq.get("question")
        ][:8]

    def _extract_date_range(self, spec: dict) -> tuple[date, date]:
        scope = spec.get("included_scope", {})
        time_period = ""
        if isinstance(scope, dict):
            time_period = scope.get("time_period", "")

        end = date.today()

        if "12 month" in time_period.lower() or "past year" in time_period.lower():
            start = end - timedelta(days=365)
        elif "6 month" in time_period.lower():
            start = end - timedelta(days=182)
        elif "3 month" in time_period.lower():
            start = end - timedelta(days=91)
        else:
            start = end - timedelta(days=365)

        return start, end

    def _extract_competitors(self, spec: dict) -> list[str]:
        competitors = spec.get("competitors", [])
        if not competitors:
            src = spec.get("source_spec", {})
            competitors = src.get("competitors", [])
        names = []
        for c in competitors:
            if isinstance(c, dict):
                name = c.get("name", "")
                if name:
                    names.append(name)
            elif isinstance(c, str) and c:
                names.append(c)
        if not names:
            for ve_path in [
                spec.get("validated_entities", []),
                spec.get("sections", {}).get("entities", {}).get("content", []) if isinstance(spec.get("sections", {}).get("entities"), dict) else [],
                spec.get("source_spec", {}).get("validated_entities", []),
            ]:
                if isinstance(ve_path, list):
                    for e in ve_path:
                        if isinstance(e, dict) and e.get("type") == "competitor":
                            name = e.get("name", "")
                            if name:
                                names.append(name)
                if names:
                    break
        if not names:
            raw = spec.get("raw_brief", "")
            rs = spec.get("research_subject")
            rs_desc = rs.get("description", "") if isinstance(rs, dict) else ""
            text_to_search = f"{raw}\n{rs_desc}"
            if text_to_search.strip():
                patterns = [
                    r'competitive set includes?\s+(.+?)(?:\.|,\s*while)',
                    r'competitors?\s+(?:are|include|includes)\s+(.+?)(?:\.|$)',
                    r'[Cc]ompetitors?\s*\n+(.+?)(?:\n\n|\n[A-Z]|$)',
                    r'[Cc]ompetitors?:\s*(.+?)(?:\n\n|\n[A-Z]|$)',
                ]
                for pat in patterns:
                    match = re.search(pat, text_to_search, re.DOTALL)
                    if match:
                        comp_str = match.group(1)
                        comp_str = re.sub(r'\band\b', ',', comp_str)
                        comp_str = re.sub(r'\bwhile\b.*', '', comp_str)
                        for part in comp_str.split(','):
                            part = part.strip().rstrip('.')
                            if part and len(part) > 1 and len(part) < 40:
                                names.append(part)
                        if names:
                            break
        return names[:8]

    def _extract_exclusions(self, spec: dict) -> list[str]:
        excluded = spec.get("excluded_scope", [])
        patterns = []
        if isinstance(excluded, list):
            for item in excluded:
                if isinstance(item, dict) and item.get("description"):
                    patterns.append(item["description"])
                elif isinstance(item, str):
                    patterns.append(item)
        return patterns
