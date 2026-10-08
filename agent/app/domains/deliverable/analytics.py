"""Compute stage: deterministic values for every chart and table; each value is also written as a fact."""
from __future__ import annotations

from collections import Counter

from ...agents import question_dimensions as qd
from . import extract as extract_mod
from .engine_types import RQ, EngineRow, Section
from .metrics import TOP_PEAKS, month_label

TOP_N = 8
_AFFILIATION_WORDS = ("affiliat", "sponsor", "paid", "brand")
NO_ROWS = "No articles for this question"
_NOT_A_NAME = {"unknown", "none", "n/a", "na", "not stated", "unnamed", ""}
LABEL_CHARS = 30
CROSSTAB_COLUMNS = 6      # a slide table stays readable: the biggest values only
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
    kind = module.get("entity_kind") or (module.get("dimension") or {}).get("key")
    suffix = f"-{kind}" if kind else ""
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
        return _section(module, rq, skipped="Entity extraction unavailable (Azure OpenAI unreachable or refused it)")
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
    rows_out = [[e["name"]] + [_words(e.get(c)) for c in cols] + [str(e["count"])] for e in ranked[:10]]
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
        types = Counter(e.get("expert_type") for e in ranked if e.get("expert_type") not in (None, "", "unknown"))
        facts += [f"{t.replace('_', ' ')} experts: {c}" for t, c in types.most_common()]
        asks_affiliation = any(w in rq.question.lower() for w in _AFFILIATION_WORDS)
        if not known and types and not asks_affiliation:
            # An all-"Not stated" doughnut answers nothing about which experts are cited: chart the type mix
            typed = sum(types.values())
            mix = [(t.replace("_", " ").capitalize(), c) for t, c in types.most_common(TOP_N)]
            facts += [f"{name}: {c} of {typed} experts ({_pct(c, typed)}%)" for name, c in mix]
            chart = {"kind": "doughnut", "categories": [n for n, _ in mix], "values": [_pct(c, typed) for _, c in mix],
                     "unit": "percent", "peaks": [], "series_label": "Expert type"}
    sampled = min(len(rows), extract_mod.EXTRACT_SAMPLE)
    notes = [f"Named in the {sampled} most-read of {len(rows)} articles"] if len(rows) > sampled else []
    return _section(module, rq, chart=chart, table={"header": header, "rows": rows_out,
                                                     "col_widths": [3.2] + [2.2] * len(cols) + [1.2]},
                    facts=facts + notes, candidate_urls=[e["urls"][0] for e in ranked[:6]], notes=notes)


def _words(value) -> str:
    """Extraction codes as table words: other_hcp -> Other HCP, unknown -> Not stated."""
    text = str(value or "").strip()
    if text.lower() == "unknown":
        return "Not stated"
    words = ["HCP" if w.lower() == "hcp" else w for w in text.replace("_", " ").split()]
    return " ".join(words)[:1].upper() + " ".join(words)[1:] if words else ""


_SOCIAL_TYPES = ("social", "twitter", "facebook", "instagram", "tiktok", "reddit", "youtube", "forum", "x ")
_SOCIAL_HOSTS = ("x.com", "twitter.com", "facebook.com", "instagram.com", "tiktok.com", "reddit.com", "youtube.com",
                 "threads.net", "pinterest.com", "linkedin.com")


def _channel(row: EngineRow) -> str:
    """Social or Editorial from the export's source type; a row without one is judged by its address."""
    media = (row.media_type or "").strip().lower()
    if media:
        return "Social" if any(t in f"{media} " for t in _SOCIAL_TYPES) else "Editorial"
    host = row.article.url.split("//", 1)[-1].split("/", 1)[0].lower().removeprefix("www.")
    if any(host == h or host.endswith("." + h) for h in _SOCIAL_HOSTS):
        return "Social"
    return ""


def _media_split(module, rq, rows, base_n, _):
    counts = Counter(c for c in (_channel(r) for r in rows) if c)
    known = sum(counts.values())
    if not known:
        return _section(module, rq, skipped="No source type in the data")
    cats = [k for k in ("Social", "Editorial") if counts.get(k)]
    unknown = len(rows) - known
    notes = [f"{unknown} of {len(rows)} articles have no source type"] if unknown else []
    return _section(module, rq, chart={"kind": "doughnut", "categories": cats,
                                       "values": [_pct(counts[k], known) for k in cats], "unit": "percent",
                                       "peaks": [], "series_label": "Source"},
                    facts=[f"{rq.id}: {counts[k]} of {known} articles are {k.lower()} ({_pct(counts[k], known)}%)"
                           for k in cats] + notes, notes=notes)


def _values_of(row: EngineRow, dim: qd.Dimension) -> list[str]:
    """The dimension's values this article names: the LLM's enrichment tags when it tagged this dimension,
    otherwise the question's own keywords (a judged dimension has none, so untagged rows count as unknown)."""
    tagged = qd.valid_names((row.tags or {}).get(dim.key), dim)
    if tagged is not None:
        return tagged
    if dim.judged:
        return []
    return qd.tag_text(f"{row.article.title}\n{row.article.text}", [dim])[dim.key]


def _breakdown(module, rq, rows, base_n, _):
    (dim,) = qd.from_json([module["dimension"]])
    per_row = [(r, _values_of(r, dim)) for r in rows]
    counts = Counter(v for _, vals in per_row for v in vals)
    order = [v.name for v in dim.values]
    top = sorted((n for n in order if counts.get(n)), key=lambda n: -counts[n])[:TOP_N + 4]
    if not top:
        return _section(module, rq, skipped=f"No articles name a {dim.label.lower()}")
    n = len(rows)
    named = sum(1 for _, vals in per_row if vals)
    facts = [f"{rq.id} {dim.label}: {v} named in {counts[v]} of {n} articles ({_pct(counts[v], n)}%)" for v in top]
    facts.append(f"{rq.id}: {named} of {n} articles name at least one {dim.label.lower()} ({_pct(named, n)}%)")
    return _section(module, rq, chart={"kind": "bar", "categories": [_label(v) for v in top],
                                       "values": [counts[v] for v in top], "unit": "count", "peaks": [],
                                       "series_label": "Articles"},
                    facts=facts,
                    candidate_urls=[next(r.article.norm_url for r, vals in per_row if v in vals) for v in top[:5]])


def _crosstab(module, rq, rows, base_n, _):
    """Share of each column value within each row value, e.g. the injury-type mix of each sport's articles."""
    row_dim, col_dim = qd.from_json(module["dimensions"])
    per_row = [(_values_of(r, row_dim), _values_of(r, col_dim)) for r in rows]
    totals = Counter(v for rv, _ in per_row for v in rv)
    row_names = sorted((v.name for v in row_dim.values if totals.get(v.name)), key=lambda n: -totals[n])[:TOP_N]
    col_totals = Counter(c for rv, cv in per_row if rv for c in cv)
    cols = sorted((v.name for v in col_dim.values if col_totals.get(v.name)), key=lambda n: -col_totals[n])[:CROSSTAB_COLUMNS]
    if not row_names:
        return _section(module, rq, skipped=f"No articles name a {row_dim.label.lower()}")
    if not cols:                      # a table of 0.0% says nothing: no article carries both dimensions
        return _section(module, rq, skipped=f"No article names both a {row_dim.label.lower()} and a "
                                            f"{col_dim.label.lower()}")
    table_rows, facts = [], []
    for name in row_names:
        within = [cv for rv, cv in per_row if name in rv]
        counts = Counter(c for cv in within for c in cv)
        table_rows.append([name] + [f"{_pct(counts[c], len(within))}%" for c in cols] + [str(len(within))])
        facts += [f"{rq.id}: {_pct(counts[c], len(within))}% of {name} articles mention {c} ({counts[c]} of {len(within)})"
                  for c in cols if counts[c]]
    return _section(module, rq, table={"header": [row_dim.label] + cols + ["Articles"], "rows": table_rows,
                                       "col_widths": [3.0] + [1.6] * len(cols) + [1.2]},
                    facts=facts)


_HANDLERS = {"share_kpi": _share_kpi, "volume_trend": _trend, "outlet_ranking": _outlets,
             "sentiment_split": _sentiment, "reach": _reach, "theme_clusters": _themes, "brand_sov": _brand_sov,
             "top_articles": _top_articles, "entities": _entities, "question_breakdown": _breakdown,
             "dimension_crosstab": _crosstab, "media_split": _media_split}


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
