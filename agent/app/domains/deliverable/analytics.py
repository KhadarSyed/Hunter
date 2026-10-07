"""Compute stage: deterministic values for every chart and table; each value is also written as a fact."""
from __future__ import annotations

from collections import Counter

from .engine_types import RQ, EngineRow, Section
from .metrics import TOP_PEAKS, month_label

TOP_N = 8
NO_ROWS = "No articles for this question"
_NOT_A_NAME = {"unknown", "none", "n/a", "na", "not stated", "unnamed", ""}
LABEL_CHARS = 30
PEAK_GAP = 2      # labelled peaks at least two periods apart so their labels never touch


def _label(text: str) -> str:
    text = str(text).strip()
    return text if len(text) <= LABEL_CHARS else text[:LABEL_CHARS - 1].rstrip() + "…"


def _spaced_peaks(values: list[int]) -> list[int]:
    chosen: list[int] = []
    for i in sorted(range(len(values)), key=lambda i: -values[i]):
        if values[i] <= 0 or len(chosen) == TOP_PEAKS:
            break
        if all(abs(i - j) >= PEAK_GAP for j in chosen):
            chosen.append(i)
    return chosen


def _pct(n: int, base: int) -> float:
    return round(100 * n / base, 1) if base else 0.0


def _section(module: dict, rq: RQ, **kw) -> Section:
    suffix = f"-{module['entity_kind']}" if module.get("entity_kind") else ""
    return Section(id=f"{rq.id.lower()}-{module['module']}{suffix}", rq_id=rq.id, module=module["module"],
                   title=module.get("title") or module["module"], **kw)


def _share_kpi(module, rq, rows, base_n, _):
    n, share = len(rows), _pct(len(rows), base_n)
    stories = len({r.story_key for r in rows})
    return _section(module, rq, chart={"kind": "kpi", "categories": ["Share of coverage"], "values": [share],
                                       "unit": "percent", "peaks": [], "series_label": rq.id},
                    facts=[f"{rq.id}: {n} of {base_n} articles ({share}%) answer this question",
                           f"{rq.id}: {stories} unique stories ({n - stories} syndicated copies)"],
                    candidate_urls=[r.article.norm_url for r in rows[:12]])


def _months(first: str, last: str) -> list[str]:
    y, m, out = int(first[:4]), int(first[5:]), []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _trend(module, rq, rows, base_n, _):
    dated = [r for r in rows if r.article.date]
    if not dated:
        return _section(module, rq, skipped="No dated articles")
    by_month = Counter(r.article.date.strftime("%Y-%m") for r in dated)
    series = _months(min(by_month), max(by_month))
    values = [by_month.get(k, 0) for k in series]
    top = _spaced_peaks(values)
    facts, cands = [], []
    for rank, i in enumerate(top, start=1):
        drivers = [r for r in dated if r.article.date.strftime("%Y-%m") == series[i]]
        lead = max(drivers, key=lambda r: (r.copies, r.article.reach))
        facts.append(f"Peak {rank}: {month_label(series[i])} with {values[i]} articles, led by \"{lead.article.title}\"")
        cands.append(lead.article.norm_url)
    undated = len(rows) - len(dated)
    plural = "s" if undated != 1 else ""
    notes = [f"{undated} undated article{plural} not shown on the trend"] if undated else []
    facts += notes
    return _section(module, rq, chart={"kind": "line_peaks", "categories": [month_label(k) for k in series],
                                       "values": values, "peaks": sorted(top), "unit": "count", "series_label": "Articles"},
                    facts=facts, candidate_urls=cands, notes=notes)


def _outlets(module, rq, rows, base_n, _):
    top = Counter(r.article.outlet for r in rows if r.article.outlet).most_common(TOP_N)
    if not top:
        return _section(module, rq, skipped="No outlet names in the data")
    return _section(module, rq, chart={"kind": "bar", "categories": [_label(o) for o, _ in top],
                                       "values": [c for _, c in top], "unit": "count", "peaks": [],
                                       "series_label": "Articles"},
                    facts=[f"Top outlet for {rq.id}: {o} with {c} articles" for o, c in top],
                    candidate_urls=[next(r.article.norm_url for r in rows if r.article.outlet == o) for o, _ in top[:5]])


def _sentiment(module, rq, rows, base_n, _):
    labels = Counter((r.article.sentiment or "").strip().title() for r in rows)
    known = {k: labels[k] for k in ("Positive", "Neutral", "Negative") if labels.get(k)}
    total = sum(known.values())
    if not total:
        return _section(module, rq, skipped="No sentiment in the data")
    cats = list(known)
    vals = [_pct(known[k], total) for k in cats]
    return _section(module, rq, chart={"kind": "doughnut", "categories": cats, "values": vals, "unit": "percent",
                                       "peaks": [], "series_label": "Sentiment"},
                    facts=[f"{rq.id} sentiment: {known[k]} of {total} articles {k.lower()} ({v}%)" for k, v in zip(cats, vals)])


def _reach(module, rq, rows, base_n, _):
    by_outlet = Counter()
    for r in rows:
        if r.article.reach and r.article.outlet:
            by_outlet[r.article.outlet] += int(r.article.reach)
    if not by_outlet:
        return _section(module, rq, skipped="No reach in the data")
    top = by_outlet.most_common(TOP_N)
    return _section(module, rq, chart={"kind": "bar", "categories": [_label(o) for o, _ in top],
                                       "values": [v for _, v in top], "unit": "count", "peaks": [],
                                       "series_label": "Reach"},
                    facts=[f"{rq.id} total reach: {sum(by_outlet.values())}"] + [f"Reach for {o}: {v}" for o, v in top])


def _themes(module, rq, rows, base_n, _):
    display: dict[str, str] = {}
    counts: Counter = Counter()
    for r in rows:
        for key in {t.strip().lower() for t in r.themes if t and t.strip()}:   # merge case variants
            counts[key] += 1
        for t in r.themes:
            display.setdefault(t.strip().lower(), t.strip())
    top = [(display[k], c) for k, c in counts.most_common(TOP_N)]
    if not top:
        return _section(module, rq, skipped="No themes in the data")
    return _section(module, rq, chart={"kind": "treemap", "categories": [t for t, _ in top], "values": [c for _, c in top],
                                       "unit": "count", "peaks": [], "series_label": "Articles"},
                    facts=[f"Theme \"{t}\": {c} of {len(rows)} articles" for t, c in top])


def _brand_sov(module, rq, rows, base_n, _):
    counts = Counter(b for r in rows for b in {str(x).strip() for x in (r.entities or {}).get("brands") or [] if x})
    if not counts:
        return _section(module, rq, skipped="No brands named in the data")
    top, total = counts.most_common(TOP_N), sum(counts.values())
    return _section(module, rq, chart={"kind": "bar", "categories": [b for b, _ in top],
                                       "values": [_pct(c, total) for _, c in top], "unit": "percent", "peaks": [],
                                       "series_label": "Share of brand mentions"},
                    facts=[f"Brand {b}: {c} of {total} brand mentions ({_pct(c, total)}%)" for b, c in top],
                    notes=["logos"])


def _top_articles(module, rq, rows, base_n, _):
    ranked = sorted(rows, key=lambda r: (-r.article.reach, -r.copies, r.article.title))[:TOP_N]
    table_rows = [[r.article.title[:70], r.article.outlet, r.article.date.isoformat() if r.article.date else "",
                   f"{int(r.article.reach)}" if r.article.reach else "", str(r.copies)] for r in ranked]
    return _section(module, rq, table={"header": ["Headline", "Outlet", "Date", "Reach", "Copies"], "rows": table_rows,
                                       "col_widths": [5.6, 2.4, 1.4, 1.4, 1.0]},
                    facts=[f"\"{r.article.title[:70]}\" ({r.article.outlet}) reach {int(r.article.reach)}, {r.copies} copies"
                           for r in ranked],
                    candidate_urls=[r.article.norm_url for r in ranked])


def _entities(module, rq, rows, base_n, extraction):
    kind = module["entity_kind"]
    if extraction is None:
        return _section(module, rq, skipped="Entity extraction unavailable (Azure OpenAI not reachable)")
    people: dict[str, dict] = {}
    for r in rows:
        for item in extraction.get(r.article.norm_url, []):
            if item["name"].strip().lower() in _NOT_A_NAME:
                continue
            entry = people.setdefault(item["name"].lower(), {**item, "count": 0, "urls": []})
            entry["count"] += 1
            entry["urls"].append(r.article.norm_url)
    if not people:
        return _section(module, rq, skipped=f"No {kind} named in these articles")
    ranked = sorted(people.values(), key=lambda e: (-e["count"], e["name"]))
    facts = [f"{e['name']} named in {e['count']} articles" for e in ranked[:10]]
    cols = [k for k in ("expert_type", "affiliation", "brand", "role") if k in ranked[0]]
    header = ["Name"] + [c.replace("_", " ").title() for c in cols] + ["Articles"]
    rows_out = [[e["name"]] + [str(e.get(c) or "") for c in cols] + [str(e["count"])] for e in ranked[:10]]
    chart = {"kind": "bar", "categories": [_label(e["name"]) for e in ranked[:TOP_N]],
             "values": [e["count"] for e in ranked[:TOP_N]], "unit": "count", "peaks": [], "series_label": "Articles"}
    if kind == "experts":
        known = [e for e in ranked if e.get("affiliation") in ("affiliated", "independent")]
        aff = [e for e in known if e["affiliation"] == "affiliated"]
        if known:
            pct = _pct(len(aff), len(known))
            facts.append(f"{len(aff)} of {len(known)} experts with a stated affiliation are brand-affiliated ({pct}%)")
            chart = {"kind": "gauge", "categories": ["Brand-affiliated experts"], "values": [pct], "unit": "percent",
                     "peaks": [], "series_label": "Affiliation"}
        else:
            # Coverage rarely states who pays an expert: say so instead of implying a share
            facts.append(f"Brand affiliation not stated for {len(ranked)} of {len(ranked)} experts")
        if len(known) < len(ranked):
            split = Counter(e.get("affiliation") if e.get("affiliation") in ("affiliated", "independent") else "unknown"
                            for e in ranked)
            labels = {"affiliated": "Brand-affiliated", "independent": "Independent", "unknown": "Not stated"}
            cats = [labels[k] for k in ("affiliated", "independent", "unknown") if split.get(k)]
            vals = [_pct(split[k], len(ranked)) for k in ("affiliated", "independent", "unknown") if split.get(k)]
            if not known:
                chart = {"kind": "doughnut", "categories": cats, "values": vals, "unit": "percent", "peaks": [],
                         "series_label": "Affiliation"}
        types = Counter(e.get("expert_type") for e in ranked)
        facts += [f"{t.replace('_', ' ')} experts: {c}" for t, c in types.most_common() if t and t != "unknown"]
    return _section(module, rq, chart=chart, table={"header": header, "rows": rows_out,
                                                     "col_widths": [3.2] + [2.2] * len(cols) + [1.2]},
                    facts=facts, candidate_urls=[e["urls"][0] for e in ranked[:6]])


_HANDLERS = {"share_kpi": _share_kpi, "volume_trend": _trend, "outlet_ranking": _outlets,
             "sentiment_split": _sentiment, "reach": _reach, "theme_clusters": _themes, "brand_sov": _brand_sov,
             "top_articles": _top_articles, "entities": _entities}


def compute_module(module: dict, rq: RQ, rows: list[EngineRow], base_n: int,
                   extraction: dict[str, list[dict]] | None) -> Section:
    if not rows:
        return _section(module, rq, skipped=NO_ROWS)
    return _HANDLERS[module["module"]](module, rq, rows, base_n, extraction)


def overview_section(rqs: list[RQ], rows_by_rq: dict[str, list[EngineRow]], base_n: int) -> Section:
    counts = [len(rows_by_rq.get(q.id, [])) for q in rqs]
    return Section(id="overview", rq_id=None, module="overview", title="Share of coverage by question",
                   chart={"kind": "bar", "categories": [q.id for q in rqs], "values": counts, "unit": "count",
                          "peaks": [], "series_label": "Articles"},
                   facts=[f"Base: {base_n} unique articles across all questions"] +
                         [f"{q.id}: {c} of {base_n} articles ({_pct(c, base_n)}%)" for q, c in zip(rqs, counts)])
