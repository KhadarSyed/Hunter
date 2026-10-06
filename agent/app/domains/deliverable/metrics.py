"""Deterministic coverage metrics. No LLM, no guessing."""
from __future__ import annotations

from collections import Counter
from datetime import date

from .ingest import Article

TOP_PEAKS = 5
TOP_OUTLETS = 10


def month_label(month: str) -> str:
    y, m = month.split("-")
    return date(int(y), int(m), 1).strftime("%b-%y")


def _month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _theme_metrics(arts: list[Article], base_n: int) -> dict:
    dated = [a for a in arts if a.date]
    by_month = Counter(a.date.strftime("%Y-%m") for a in dated)
    months = _month_range(min(by_month), max(by_month)) if by_month else []
    monthly = [{"month": mo, "count": by_month.get(mo, 0)} for mo in months]
    ranked = sorted((x for x in monthly if x["count"] > 0), key=lambda x: (-x["count"], x["month"]))
    peaks = []
    for rank, x in enumerate(ranked[:TOP_PEAKS], start=1):
        in_month = [a for a in dated if a.date.strftime("%Y-%m") == x["month"]]
        in_month.sort(key=lambda a: (-a.reach, a.date, a.norm_url))
        peaks.append({"month": x["month"], "count": x["count"], "rank": rank,
                      "top_urls": [a.norm_url for a in in_month[:3]]})
    outlets = Counter(a.outlet for a in arts if a.outlet)
    sentiment = Counter(a.sentiment for a in arts if a.sentiment)
    return {
        "count": len(arts),
        "share": round(100 * len(arts) / base_n, 1) if base_n else 0.0,
        "date_min": min(a.date for a in dated).isoformat() if dated else None,
        "date_max": max(a.date for a in dated).isoformat() if dated else None,
        "monthly": monthly,
        "peaks": peaks,
        "outlets": [{"outlet": o, "count": c} for o, c in outlets.most_common(TOP_OUTLETS)],
        "sentiment": dict(sentiment),
    }


def compute_metrics(articles: list[Article], theme_keys: list[str]) -> dict:
    base_n = len(articles)
    return {
        "base_n": base_n,
        "multi_theme": sum(1 for a in articles if len(a.themes) > 1),
        "themes": {k: _theme_metrics([a for a in articles if k in a.themes], base_n) for k in theme_keys},
    }


def _top(counter: Counter, key: str, n: int = 10) -> list[dict]:
    return [{key: k, "count": c} for k, c in counter.most_common(n)]


def compute_classified_metrics(classifications: dict[str, dict[str, dict]]) -> dict:
    out: dict = {}
    expert_recs = classifications.get("expert", {})
    experts = [e for rec in expert_recs.values() for e in rec.get("experts", [])]
    known = [e for e in experts if e["affiliation"] in ("affiliated", "independent")]
    affiliated = sum(1 for e in known if e["affiliation"] == "affiliated")
    out["expert"] = {
        "articles_with_expert": sum(1 for r in expert_recs.values() if r.get("experts")),
        "experts_total": len(experts),
        "type_counts": dict(Counter(e["expert_type"] for e in experts if e["expert_type"] != "unknown")),
        "type_unknown": sum(1 for e in experts if e["expert_type"] == "unknown"),
        "affiliated_pct": round(100 * affiliated / len(known), 1) if known else None,
        "affiliated_n": affiliated,
        "affiliation_known_n": len(known),
        "affiliation_unknown": len(experts) - len(known),
        "affiliated_brands": _top(Counter(e["brand"] for e in experts
                                          if e["affiliation"] == "affiliated" and e["brand"]), "brand"),
    }
    celebs = classifications.get("celebrity", {})
    out["celebrity"] = {
        "top": _top(Counter(n for r in celebs.values()
                            for n in {c["name"] for c in r.get("celebrities", []) if c["name"]}), "name"),
        "roles": dict(Counter(c["role"] for r in celebs.values() for c in r.get("celebrities", []))),
    }
    deals = classifications.get("deal", {})
    out["deal"] = {
        "retailers": _top(Counter(d["retailer"] for r in deals.values() for d in r.get("deals", [])
                                  if d["retailer"]), "retailer"),
        "deal_types": dict(Counter(d["deal_type"] for r in deals.values() for d in r.get("deals", []))),
    }
    out["parenting"] = {"topics": dict(Counter(t["topic"] for r in classifications.get("parenting", {}).values()
                                               for t in r.get("topics", [])))}
    brand_articles: Counter = Counter()
    for theme_recs in classifications.values():
        for rec in theme_recs.values():
            brand_articles.update(set(rec.get("brands", [])))
    out["brands"] = _top(brand_articles, "brand", 12)
    return out
