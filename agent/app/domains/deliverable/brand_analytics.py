"""Brand vs competitors: share of voice and sentiment per brand, counted on literal mentions only (a brand name used
as a figure of speech is not a mention). The primary brand's products count towards the brand."""
from __future__ import annotations

from collections import Counter

from .analytics import _label, _pct
from .engine_types import EngineRow, Section
from .evidence import Brand, row_brands

SENTIMENTS = ("Positive", "Neutral", "Negative")
CANDIDATES_PER_BRAND = 3


def _mentions(rows: list[EngineRow], brands: list[Brand]) -> list[tuple[EngineRow, list[str]]]:
    return [(r, named) for r in rows if (named := row_brands(r, brands))]


def _sov(named_rows, brands: list[Brand]) -> Section:
    counts = Counter(n for _, named in named_rows for n in named)
    if not counts:
        return Section(id="brand-sov", rq_id=None, module="brand_sov", title="Share of voice",
                       skipped="No brand named in the coverage")
    primary = next((b.name for b in brands if b.primary), "")
    order = sorted(counts, key=lambda n: (n != primary, -counts[n], n))      # the client first, then by volume
    total = sum(counts.values())
    facts = [f"Brand {n}: {counts[n]} of {total} brand mentions ({_pct(counts[n], total)}%)" for n in order]
    urls = [r.article.norm_url for n in order for r, named in named_rows if n in named][:CANDIDATES_PER_BRAND * len(order)]
    return Section(id="brand-sov", rq_id=None, module="brand_sov", title="Share of voice: brand vs competitors",
                   chart={"kind": "bar", "categories": [_label(n) for n in order],
                          "values": [_pct(counts[n], total) for n in order], "unit": "percent", "peaks": [],
                          "series_label": "Share of brand mentions"},
                   facts=facts, candidate_urls=urls, notes=["logos"])


def _sentiment(named_rows, brands: list[Brand]) -> Section:
    by_brand: dict[str, Counter] = {}
    for r, named in named_rows:
        tone = (r.article.sentiment or "").strip().title()
        for n in named:
            by_brand.setdefault(n, Counter())[tone if tone in SENTIMENTS else "Unknown"] += 1
    rated = {n: c for n, c in by_brand.items() if sum(c[s] for s in SENTIMENTS)}
    if not rated:
        return Section(id="brand-sentiment", rq_id=None, module="brand_sentiment", title="Sentiment by brand",
                       skipped="No sentiment in the data")
    primary = next((b.name for b in brands if b.primary), "")
    order = sorted(rated, key=lambda n: (n != primary, -sum(rated[n].values()), n))
    rows, facts = [], []
    for n in order:
        known = sum(rated[n][s] for s in SENTIMENTS)
        shares = [_pct(rated[n][s], known) for s in SENTIMENTS]
        rows.append([n] + [f"{v}%" for v in shares] + [str(known)])
        facts.append(f"Sentiment for {n}: {shares[0]}% positive, {shares[1]}% neutral, {shares[2]}% negative "
                     f"of {known} articles")
    return Section(id="brand-sentiment", rq_id=None, module="brand_sentiment", title="Sentiment: brand vs competitors",
                   chart={"kind": "bar", "categories": [_label(n) for n in order],
                          "values": [_pct(rated[n]["Positive"], sum(rated[n][s] for s in SENTIMENTS)) for n in order],
                          "unit": "percent", "peaks": [], "series_label": "Positive share"},
                   table={"header": ["Brand", "Positive", "Neutral", "Negative", "Articles"], "rows": rows,
                          "col_widths": [3.0, 1.6, 1.6, 1.6, 1.4]},
                   facts=facts, notes=["logos"])


def brand_sections(rows: list[EngineRow], brands: list[Brand]) -> list[Section]:
    named = _mentions(rows, brands)
    return [_sov(named, brands), _sentiment(named, brands)]
