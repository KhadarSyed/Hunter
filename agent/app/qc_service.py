"""Core QC check engine -- runs quality checks against parsed monitoring reports."""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from . import intelligence_store as store
from . import qc_parser
from . import source_retrieval

logger = logging.getLogger(__name__)

SEVERITY_WEIGHTS = {
    "critical": 25,
    "high": 15,
    "medium": 8,
    "low": 3,
    "info": 0,
}


def run_qc(report_id: int, on_progress=None) -> dict:
    """Execute all enabled QC checks against a parsed report."""
    report = store.get_qc_report(report_id)
    if not report:
        return {"error": "Report not found"}
    if report["parse_status"] != "done":
        return {"error": "Report not fully parsed"}

    mapping = report.get("field_mapping") or {}
    if not mapping:
        return {"error": "No field mapping configured"}

    run_id = store.create_qc_run(report_id)
    store.update_qc_run(run_id, status="running", started_at=time.time())

    rows = qc_parser.get_rows_from_file(report["file_path"], mapping)
    if not rows:
        store.update_qc_run(run_id, status="failed", completed_at=time.time())
        return {"error": "No rows to check"}

    store.update_qc_run(run_id, total_rows=len(rows))

    all_findings = []
    checks_run = 0

    def _progress(msg: str, pct: int):
        if on_progress:
            on_progress(msg, pct)

    _progress("Checking field coverage...", 5)
    findings = check_field_coverage(rows, mapping)
    all_findings.extend(findings)
    checks_run += 1

    _progress("Checking required fields...", 10)
    findings = check_required_fields(rows, mapping)
    all_findings.extend(findings)
    checks_run += 1

    _progress("Validating dates...", 20)
    findings = check_dates(rows, mapping)
    all_findings.extend(findings)
    checks_run += 1

    from concurrent.futures import ThreadPoolExecutor, as_completed

    _progress("Validating URLs & summaries...", 30)

    with ThreadPoolExecutor(max_workers=4) as pool:
        future_urls = pool.submit(check_urls, rows, mapping)
        future_content = pool.submit(check_content_quality, rows, mapping)
        future_llm = pool.submit(check_summaries_with_llm, rows, mapping)
        future_dates = pool.submit(check_date_mismatch, rows, mapping)

        _progress("Detecting duplicates...", 50)
        findings = check_duplicates(rows, mapping)
        all_findings.extend(findings)
        checks_run += 1

        _progress("Waiting for URL & content checks...", 60)
        try:
            all_findings.extend(future_urls.result(timeout=120))
        except Exception as e:
            logger.error("URL check failed: %s", e, exc_info=True)
        checks_run += 1

        try:
            all_findings.extend(future_content.result(timeout=120))
        except Exception as e:
            logger.error("Content quality check failed: %s", e, exc_info=True)
        checks_run += 1

        _progress("Finishing summary analysis...", 85)
        try:
            all_findings.extend(future_llm.result(timeout=60))
        except Exception as e:
            logger.error("LLM summary check failed: %s", e, exc_info=True)
        checks_run += 1

        _progress("Checking date mismatches...", 90)
        try:
            all_findings.extend(future_dates.result(timeout=120))
        except Exception as e:
            logger.error("Date mismatch check failed: %s", e, exc_info=True)
        checks_run += 1

    _progress("Calculating scores...", 95)

    tagged = []
    for f in all_findings:
        tagged.append({
            "run_id": run_id,
            "report_id": report_id,
            **f,
        })

    count = store.add_qc_findings_batch(tagged)

    score, breakdown = calculate_scores(rows, all_findings)

    store.update_qc_run(
        run_id,
        status="completed",
        total_checks=checks_run,
        total_findings=count,
        score=score,
        score_breakdown=breakdown,
        completed_at=time.time(),
    )

    _progress("QC complete", 100)

    return {
        "run_id": run_id,
        "total_rows": len(rows),
        "total_checks": checks_run,
        "total_findings": count,
        "score": score,
        "score_breakdown": breakdown,
    }


# ─── Check: Field Coverage ─────────────────────────────────────────────────

REQUIRED_QC_FIELDS = {"headline", "url", "date", "source"}


def check_field_coverage(rows: list[dict], mapping: dict) -> list[dict]:
    """Flag when critical QC fields have no mapped column at all."""
    mapped_fields = set(mapping.values())
    findings = []
    for field in REQUIRED_QC_FIELDS:
        if field not in mapped_fields:
            severity = "critical" if field == "url" else "high"
            findings.append({
                "check_type": "field_coverage",
                "row_number": 0,
                "column_name": field,
                "severity": severity,
                "message": f"Required field '{field}' has no mapped column — cannot be verified for any row",
                "expected": f"A column mapped to '{field}'",
                "actual": "(unmapped)",
            })
    return findings


# ─── Check: Required Fields ────────────────────────────────────────────────

def check_required_fields(rows: list[dict], mapping: dict) -> list[dict]:
    mapped_fields = set(mapping.values())
    required = {"headline", "url", "date", "source"} & mapped_fields
    findings = []

    for i, row in enumerate(rows):
        headline = row.get("headline", "").strip()
        if headline.startswith("[Similar"):
            continue
        headline_short = headline[:80]
        for field in required:
            val = row.get(field, "").strip()
            if not val:
                label = f" — {headline_short}" if headline_short and field != "headline" else ""
                findings.append({
                    "check_type": "required_fields",
                    "row_number": i + 2,
                    "column_name": field,
                    "severity": "critical" if field in ("headline", "url") else "high",
                    "message": f"Missing required field: {field}{label}",
                    "expected": "Non-empty value",
                    "actual": "(blank)",
                })

    return findings


# ─── Check: Date Validation ────────────────────────────────────────────────

DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d",
    "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%m-%d-%Y", "%d-%m-%Y",
]


def _parse_date(s: str) -> datetime | None:
    s = s.strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        from dateutil import parser as dateutil_parser
        return dateutil_parser.parse(s, fuzzy=True)
    except Exception:
        return None


def check_dates(rows: list[dict], mapping: dict) -> list[dict]:
    if "date" not in set(mapping.values()):
        return []

    findings = []
    now = datetime.now()
    one_year_ago = now - timedelta(days=365)

    for i, row in enumerate(rows):
        date_str = row.get("date", "").strip()
        if not date_str:
            continue

        parsed = _parse_date(date_str)
        if parsed is None:
            findings.append({
                "check_type": "date_validation",
                "row_number": i + 2,
                "column_name": "date",
                "severity": "high",
                "message": f"Unparseable date format: '{date_str}'",
                "expected": "Valid date (YYYY-MM-DD or similar)",
                "actual": date_str,
            })
            continue

        if parsed > now + timedelta(days=1):
            findings.append({
                "check_type": "date_validation",
                "row_number": i + 2,
                "column_name": "date",
                "severity": "critical",
                "message": f"Future date detected: {parsed.date()}",
                "expected": "Date not in the future",
                "actual": str(parsed.date()),
            })

        if parsed < one_year_ago:
            findings.append({
                "check_type": "date_validation",
                "row_number": i + 2,
                "column_name": "date",
                "severity": "medium",
                "message": f"Date older than 1 year: {parsed.date()}",
                "expected": "Recent date",
                "actual": str(parsed.date()),
            })

    return findings


# ─── Check: Date Mismatch (dataset date vs. actual article date) ──────────

def check_date_mismatch(rows: list[dict], mapping: dict) -> list[dict]:
    """Compare the publication date in the dataset against the date
    extracted from the actual article page.  Flags rows where the two
    dates disagree by more than 1 day."""
    mapped = set(mapping.values())
    if "date" not in mapped or "url" not in mapped:
        return []

    from concurrent.futures import ThreadPoolExecutor

    candidates = []
    for i, row in enumerate(rows):
        date_str = row.get("date", "").strip()
        url = row.get("url", "").strip()
        if not date_str or not url:
            continue
        dataset_dt = _parse_date(date_str)
        if dataset_dt is None:
            continue
        candidates.append((i, row, url, dataset_dt))

    if not candidates:
        return []

    findings: list[dict] = []

    def _check_one(item):
        idx, row, url, dataset_dt = item
        info = source_retrieval.fetch_source(url)
        page_date_str = (info or {}).get("extracted_date", "")
        if not page_date_str:
            return None
        page_dt = _parse_date(page_date_str)
        if page_dt is None:
            return None
        dataset_d = dataset_dt.date()
        page_d = page_dt.date()
        diff_days = (page_d - dataset_d).days
        if diff_days > 1:
            return {
                "check_type": "date_mismatch",
                "row_number": idx + 2,
                "column_name": "date",
                "severity": "high",
                "message": (
                    f"Date mismatch: dataset says {dataset_d}, "
                    f"but article was actually published on {page_d} "
                    f"({diff_days} day{'s' if diff_days != 1 else ''} later)"
                ),
                "expected": str(page_d),
                "actual": str(dataset_d),
                "source_url": url,
            }
        return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        for result in pool.map(_check_one, candidates):
            if result:
                findings.append(result)

    return findings


# ─── Check: URL Validation ─────────────────────────────────────────────────

def check_urls(rows: list[dict], mapping: dict) -> list[dict]:
    if "url" not in set(mapping.values()):
        return []

    import requests as req
    from concurrent.futures import ThreadPoolExecutor

    findings = []

    def _check_one(i, row):
        url = row.get("url", "").strip()
        headline = row.get("headline", "").strip()[:80]
        if not url:
            return None

        parsed = urlparse(url)
        if parsed.scheme == "file":
            return {
                "check_type": "url_validation",
                "row_number": i + 2,
                "column_name": "url",
                "severity": "critical",
                "message": f"Local file path instead of web URL — {headline}",
                "expected": "Valid web URL (https://...)",
                "actual": url[:100],
            }

        if not parsed.scheme or not parsed.netloc:
            return {
                "check_type": "url_validation",
                "row_number": i + 2,
                "column_name": "url",
                "severity": "high",
                "message": f"Malformed URL — {headline}",
                "expected": "Valid URL (https://...)",
                "actual": url[:100],
            }

        if parsed.scheme not in ("http", "https"):
            return {
                "check_type": "url_validation",
                "row_number": i + 2,
                "column_name": "url",
                "severity": "medium",
                "message": f"Non-HTTP URL scheme: {parsed.scheme} — {headline}",
                "expected": "http or https",
                "actual": parsed.scheme,
            }

        try:
            resp = req.head(url, timeout=3, allow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0 InfoVision-QC/1.0"})
            if resp.status_code == 405:
                resp = req.get(url, timeout=3, allow_redirects=True, stream=True,
                               headers={"User-Agent": "Mozilla/5.0 InfoVision-QC/1.0"})
            if resp.status_code in (401, 403):
                return None
            elif resp.status_code >= 400:
                code = resp.status_code
                if code == 404:
                    reason = "Link is broken — page not found"
                    sev = "critical"
                elif code == 429:
                    reason = "Link is rate-limited — too many requests"
                    sev = "low"
                elif code >= 500:
                    reason = "Link target server error — site may be down"
                    sev = "high"
                else:
                    reason = f"Link returned error (HTTP {code})"
                    sev = "high"
                return {
                    "check_type": "url_validation",
                    "row_number": i + 2,
                    "column_name": "url",
                    "severity": sev,
                    "message": reason,
                    "expected": "Working link",
                    "actual": url[:100],
                    "source_url": url,
                }
        except req.exceptions.Timeout:
            return {
                "check_type": "url_validation",
                "row_number": i + 2,
                "column_name": "url",
                "severity": "medium",
                "message": "Link timed out — site took too long to respond",
                "expected": "Accessible link",
                "actual": url[:100],
                "source_url": url,
            }
        except req.exceptions.RequestException as ex:
            return {
                "check_type": "url_validation",
                "row_number": i + 2,
                "column_name": "url",
                "severity": "high",
                "message": "Link is not accessible — could not connect",
                "expected": "Accessible link",
                "actual": str(ex)[:100],
                "source_url": url,
            }
        return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_check_one, i, row) for i, row in enumerate(rows)]
        for fut in futures:
            try:
                result = fut.result(timeout=10)
                if result:
                    findings.append(result)
            except Exception:
                pass

    return findings


# ─── Check: Duplicate Detection ────────────────────────────────────────────

def check_duplicates(rows: list[dict], mapping: dict) -> list[dict]:
    findings = []
    mapped_fields = set(mapping.values())

    if "headline" in mapped_fields:
        seen: dict[str, list[int]] = defaultdict(list)
        for i, row in enumerate(rows):
            headline = row.get("headline", "").strip().lower()
            if headline:
                seen[headline].append(i + 2)

        for headline, row_nums in seen.items():
            if len(row_nums) > 1:
                findings.append({
                    "check_type": "duplicate_detection",
                    "row_number": row_nums[0],
                    "column_name": "headline",
                    "severity": "high",
                    "message": f"Duplicate headline found in {len(row_nums)} rows: {row_nums}",
                    "expected": "Unique entries",
                    "actual": headline[:80],
                })

    if "url" in mapped_fields:
        seen_urls: dict[str, list[int]] = defaultdict(list)
        for i, row in enumerate(rows):
            url = row.get("url", "").strip().lower().rstrip("/")
            if url:
                seen_urls[url].append(i + 2)

        for url, row_nums in seen_urls.items():
            if len(row_nums) > 1:
                findings.append({
                    "check_type": "duplicate_detection",
                    "row_number": row_nums[0],
                    "column_name": "url",
                    "severity": "critical",
                    "message": f"Duplicate URL found in {len(row_nums)} rows: {row_nums}",
                    "expected": "Unique URLs",
                    "actual": url[:100],
                })

    return findings


# ─── Check: Headline vs Source ──────────────────────────────────────────────

def check_headlines_against_source(rows: list[dict], mapping: dict, max_rows: int = 50) -> list[dict]:
    findings = []

    for i, row in enumerate(rows[:max_rows]):
        url = row.get("url", "").strip()
        report_headline = row.get("headline", "").strip()
        if not url or not report_headline:
            continue

        source_info = source_retrieval.fetch_source(url)
        if not source_info or not source_info.get("is_accessible"):
            if source_info and source_info.get("fetch_error"):
                findings.append({
                    "check_type": "headline_match",
                    "row_number": i + 2,
                    "column_name": "url",
                    "severity": "medium",
                    "message": f"Source URL not accessible: {source_info['fetch_error']}",
                    "source_url": url,
                })
            continue

        source_headline = source_info.get("extracted_headline", "")
        if not source_headline:
            continue

        similarity = _headline_similarity(report_headline, source_headline)
        if similarity < 0.5:
            findings.append({
                "check_type": "headline_match",
                "row_number": i + 2,
                "column_name": "headline",
                "severity": "high",
                "message": f"Headline mismatch (similarity: {similarity:.0%})",
                "expected": source_headline[:120],
                "actual": report_headline[:120],
                "source_url": url,
            })

    return findings


def _headline_similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity."""
    words_a = set(re.findall(r'\w+', a.lower()))
    words_b = set(re.findall(r'\w+', b.lower()))
    if not words_a or not words_b:
        return 0.0
    overlap = words_a & words_b
    return len(overlap) / max(len(words_a), len(words_b))


# ─── Check: Summary Accuracy ───────────────────────────────────────────────

def check_summary_accuracy(rows: list[dict], mapping: dict, max_rows: int = 20) -> list[dict]:
    findings = []

    for i, row in enumerate(rows[:max_rows]):
        url = row.get("url", "").strip()
        summary = row.get("summary", "").strip()
        if not url or not summary or len(summary) < 20:
            continue

        source_info = source_retrieval.fetch_source(url)
        if not source_info or not source_info.get("is_accessible"):
            continue

        source_text = source_info.get("extracted_text", "")
        if not source_text or len(source_text) < 50:
            findings.append({
                "check_type": "summary_accuracy",
                "row_number": i + 2,
                "column_name": "summary",
                "severity": "info",
                "message": "Unable to verify summary -- source text not extractable",
                "source_url": url,
            })
            continue

        overlap = _text_overlap(summary, source_text)
        if overlap < 0.3:
            findings.append({
                "check_type": "summary_accuracy",
                "row_number": i + 2,
                "column_name": "summary",
                "severity": "medium",
                "message": f"Summary may not accurately reflect source content (overlap: {overlap:.0%})",
                "expected": "Summary derived from source article",
                "actual": summary[:120],
                "source_url": url,
            })

    return findings


def _text_overlap(summary: str, source: str) -> float:
    """Check what fraction of summary words appear in the source text."""
    summary_words = set(re.findall(r'\w{3,}', summary.lower()))
    source_words = set(re.findall(r'\w{3,}', source.lower()))
    if not summary_words:
        return 1.0
    return len(summary_words & source_words) / len(summary_words)


# ─── Helper: Fetch page and extract metadata ─────────────────────────────

_NON_PERSON_RE = re.compile(
    r'_|drupal|sso|admin|webmaster|cms|bot|system|noreply|'
    r'\b(editorial\s*team|staff|desk|bureau|newsroom|editors?|'
    r'contributor|wire\s*service|associated\s*press|reuters|agency|team)\b',
    re.IGNORECASE,
)

def _is_person_name(name: str) -> bool:
    if _NON_PERSON_RE.search(name):
        return False
    if not re.search(r'[a-zA-Z]', name):
        return False
    if len(name.split()) < 2 and not re.search(r'[A-Z][a-z]', name):
        return False
    return True


def _fetch_page(url: str) -> dict[str, str]:
    """Fetch a page once and extract author + article text."""
    import requests as req
    import json as _json

    result: dict[str, str] = {"author": "", "text": ""}
    try:
        resp = req.get(url, timeout=3, allow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0 InfoVision-QC/1.0"})
        if resp.status_code >= 400:
            return result
        html = resp.text[:80000]

        for pattern in [
            r'<meta\s+name=["\']author["\']\s+content=["\']([^"\']+)["\']',
            r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']author["\']',
            r'<meta\s+property=["\']article:author["\']\s+content=["\']([^"\']+)["\']',
            r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']article:author["\']',
        ]:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                author = m.group(1).strip()
                if author and len(author) < 100 and not author.startswith("http") and _is_person_name(author):
                    result["author"] = author
                    break

        for ld_match in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
            try:
                data = _json.loads(ld_match.group(1))
                if isinstance(data, list):
                    data = data[0]
                if not result["author"]:
                    auth = data.get("author")
                    candidate = ""
                    if isinstance(auth, dict):
                        candidate = auth.get("name", "")
                    elif isinstance(auth, list) and auth:
                        names = [a.get("name", "") if isinstance(a, dict) else str(a) for a in auth]
                        candidate = ", ".join(n for n in names if n)
                    elif isinstance(auth, str):
                        candidate = auth
                    if candidate and _is_person_name(candidate):
                        result["author"] = candidate
                body = data.get("articleBody", "")
                if isinstance(body, str) and len(body) > 50:
                    result["text"] = body
            except Exception:
                continue

        if not result["author"]:
            byline_match = re.search(r'class=["\'][^"\']*byline[^"\']*["\'][^>]*>([^<]{3,80})<', html, re.IGNORECASE)
            if byline_match:
                text = byline_match.group(1).strip()
                text = re.sub(r'^[Bb]y\s+', '', text).strip()
                if text and len(text) < 80 and _is_person_name(text):
                    result["author"] = text

        if not result["text"]:
            paragraphs = re.findall(r'<p[^>]*>([^<]{40,})</p>', html)
            result["text"] = " ".join(p.strip() for p in paragraphs[:20])

    except Exception:
        pass
    return result


# ─── Check: Content Quality ───────────────────────────────────────────────

def check_content_quality(rows: list[dict], mapping: dict) -> list[dict]:
    """Check for content quality: missing authors, summary accuracy, short summaries."""
    from concurrent.futures import ThreadPoolExecutor

    mapped = set(mapping.values())
    findings = []
    check_author = "author" in mapped
    check_summary = "summary" in mapped
    has_urls = "url" in mapped

    page_cache: dict[str, dict] = {}
    urls_to_fetch = []
    for row in rows:
        url = row.get("url", "").strip() if has_urls else ""
        headline = row.get("headline", "").strip()
        author = row.get("author", "").strip() if check_author else ""
        summary = row.get("summary", "").strip() if check_summary else ""
        if url and url.startswith("http") and check_author and not author:
            urls_to_fetch.append(url)

    if urls_to_fetch:
        unique_urls = list(set(urls_to_fetch))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda u: (u, _fetch_page(u)), unique_urls))
        for u, data in results:
            page_cache[u] = data

    for i, row in enumerate(rows):
        headline = row.get("headline", "").strip()
        if headline.startswith("[Similar"):
            continue
        headline = headline[:80]
        summary = row.get("summary", "").strip() if check_summary else ""
        author = row.get("author", "").strip() if check_author else ""
        url = row.get("url", "").strip() if has_urls else ""

        if check_summary and summary and len(summary) < 30:
            findings.append({
                "check_type": "content_quality",
                "row_number": i + 2,
                "column_name": "summary",
                "severity": "medium",
                "message": f"Summary too short ({len(summary)} chars)",
                "expected": "At least 30 characters",
                "actual": summary[:80],
            })

        page_data = page_cache.get(url, {"author": "", "text": ""})

        if check_author and not author:
            page_author = page_data["author"]
            if page_author and _is_person_name(page_author):
                findings.append({
                    "check_type": "content_quality",
                    "row_number": i + 2,
                    "column_name": "author",
                    "severity": "medium",
                    "message": f"Author missing in report but found on page: {page_author}",
                    "expected": page_author,
                    "actual": "(blank in report)",
                })

        if check_summary and summary and page_data["text"]:
            overlap = _text_overlap(summary, page_data["text"])
            if overlap < 0.3:
                findings.append({
                    "check_type": "summary_accuracy",
                    "row_number": i + 2,
                    "column_name": "summary",
                    "severity": "high",
                    "message": f"Summary may not match the actual article content (only {overlap:.0%} word overlap)",
                    "expected": "Summary that reflects the source article",
                    "actual": summary[:120],
                    "source_url": url,
                })

        if "headline" in mapped:
            headline = row.get("headline", "").strip()
            if headline and len(headline) < 10:
                findings.append({
                    "check_type": "content_quality",
                    "row_number": i + 2,
                    "column_name": "headline",
                    "severity": "medium",
                    "message": f"Headline suspiciously short ({len(headline)} chars)",
                    "expected": "Descriptive headline",
                    "actual": headline,
                })

        if "source" in mapped:
            source = row.get("source", "").strip()
            if not source:
                findings.append({
                    "check_type": "content_quality",
                    "row_number": i + 2,
                    "column_name": "source",
                    "severity": "high",
                    "message": f"Missing source/publisher — {headline}",
                    "expected": "Publisher name",
                    "actual": "(blank)",
                })

    return findings


# ─── Check: LLM Summary Validation ──────────────────────────────────────────

def check_summaries_with_llm(rows: list[dict], mapping: dict) -> list[dict]:
    """Detect summaries that don't match their headlines using keyword cross-check."""
    mapped = set(mapping.values())
    if "summary" not in mapped or "headline" not in mapped:
        return []

    articles = []
    for i, row in enumerate(rows):
        headline = row.get("headline", "").strip()
        summary = row.get("summary", "").strip()
        if headline and summary and not headline.startswith("[Similar"):
            h_words = set(re.findall(r'[a-zA-Z]{4,}', headline.lower()))
            s_words = set(re.findall(r'[a-zA-Z]{4,}', summary.lower()))
            articles.append({"index": i, "headline": headline, "summary": summary,
                            "h_words": h_words, "s_words": s_words})

    if len(articles) < 2:
        return []

    stopwords = {"this", "that", "with", "from", "have", "been", "they", "their",
                 "about", "which", "would", "could", "should", "after", "before",
                 "being", "there", "where", "what", "when", "will", "more", "some",
                 "than", "also", "into", "over", "just", "most", "only", "very",
                 "says", "said", "article", "according", "highlights", "examines",
                 "reports", "explains", "notes"}

    from collections import Counter
    h_freq = Counter()
    s_freq = Counter()
    for art in articles:
        h_freq.update(art["h_words"])
        s_freq.update(art["s_words"])
    threshold = max(3, len(articles) * 0.3)
    common_words = {w for w, c in h_freq.items() if c >= threshold}
    common_words |= {w for w, c in s_freq.items() if c >= threshold}
    ignore = stopwords | common_words

    findings = []
    for idx, art in enumerate(articles):
        own_unique = art["h_words"] - ignore
        if len(own_unique) < 2:
            continue

        own_overlap = len(own_unique & art["s_words"])
        own_ratio = own_overlap / len(own_unique)

        best_other_overlap = 0
        best_other_headline = ""
        best_other_unique = set()
        for j, other in enumerate(articles):
            if j == idx:
                continue
            other_unique = other["h_words"] - ignore
            if len(other_unique) < 2:
                continue
            other_overlap = len(other_unique & art["s_words"])
            if other_overlap > best_other_overlap:
                best_other_overlap = other_overlap
                best_other_headline = other["headline"][:80]
                best_other_unique = other_unique

        if (best_other_overlap > own_overlap + 2
                and own_ratio < 0.25
                and best_other_overlap >= 4
                and best_other_overlap / len(best_other_unique) > 0.6):
            findings.append({
                "check_type": "summary_accuracy",
                "row_number": art["index"] + 2,
                "column_name": "summary",
                "severity": "high",
                "message": f"Summary may describe a different article (closer to: \"{best_other_headline}\")",
                "expected": f"Summary about: {art['headline'][:100]}",
                "actual": art["summary"][:150],
            })

    return findings


# ─── Scoring ────────────────────────────────────────────────────────────────

def calculate_scores(rows: list[dict], findings: list[dict]) -> tuple[float, dict]:
    """Calculate row-level and report-level QC scores."""
    row_deductions: dict[int, float] = defaultdict(float)
    category_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for f in findings:
        row_num = f.get("row_number", 0)
        severity = f.get("severity", "info")
        check_type = f.get("check_type", "unknown")
        deduction = SEVERITY_WEIGHTS.get(severity, 0)
        row_deductions[row_num] += deduction
        category_counts[check_type][severity] += 1

    row_scores = []
    for i in range(len(rows)):
        row_num = i + 2
        score = max(0, 100 - row_deductions.get(row_num, 0))
        row_scores.append(score)

    overall = sum(row_scores) / len(row_scores) if row_scores else 100.0

    if overall >= 90:
        grade = "A"
    elif overall >= 75:
        grade = "B"
    elif overall >= 60:
        grade = "C"
    elif overall >= 40:
        grade = "D"
    else:
        grade = "F"

    severity_dist = defaultdict(int)
    for f in findings:
        severity_dist[f.get("severity", "info")] += 1

    breakdown = {
        "overall_score": round(overall, 1),
        "grade": grade,
        "severity_distribution": dict(severity_dist),
        "category_scores": {
            cat: dict(counts) for cat, counts in category_counts.items()
        },
        "total_rows": len(rows),
        "rows_with_issues": len(row_deductions),
        "clean_rows": len(rows) - len(row_deductions),
    }

    return round(overall, 1), breakdown
