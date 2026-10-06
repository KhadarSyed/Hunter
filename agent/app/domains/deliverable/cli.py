"""Build a reference deck from a deliverable project config.

Usage: python -m agent.app.domains.deliverable.cli agent/app/domains/deliverable/projects/baby_skincare.json
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

import io

import requests
from PIL import Image, UnidentifiedImageError
from pptx import Presentation

from ...core.anthropic_client import get_llm_client
from ..research.brandfetch import resolve_logo
from . import classify, config, deck, gauge, ingest, insights, metrics, qc
from .citations import CitationRegistry

logger = logging.getLogger("deliverable")
THEMES = ("deal", "parenting", "expert", "celebrity")
MAX_CANDIDATES = 12
LOGO_TIMEOUT_S = 20
# Brandfetch's CDN serves an HTML page to non-browser clients; a browser UA gets the image.
LOGO_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept": "image/png,image/*"}


def logo_png_url(info: dict) -> str | None:
    """PowerPoint can't embed webp/svg; ask Brandfetch's CDN for a PNG explicitly."""
    if info.get("source") == "brandfetch" and info.get("domain"):
        return f"https://cdn.brandfetch.io/{info['domain']}/w/400/h/400/logo.png?c={os.environ.get('BRANDFETCH_CLIENT_ID', '')}"
    return info.get("logo_url")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _peak_articles(t: dict, by_url: dict) -> list:
    return [by_url[u] for p in t["peaks"] for u in p["top_urls"] if u in by_url]


def _theme_facts(key: str, label: str, m: dict, cm: dict) -> list[str]:
    t = m["themes"][key]
    facts = [f"{label} share of collected coverage is {t['share']}% ({t['count']} of {m['base_n']} articles)"]
    facts += [f"Peak {p['rank']} for {label}: {metrics.month_label(p['month'])} with {p['count']} articles"
              for p in t["peaks"]]
    if t["peaks"] and t["count"]:
        top = t["peaks"][0]
        facts.append(f"{metrics.month_label(top['month'])} holds {top['count']} of {t['count']} {label} articles "
                     f"({round(100 * top['count'] / t['count'], 1)}%)")
    facts += [f"Top outlet for {label}: {o['outlet']} with {o['count']} articles" for o in t["outlets"][:5]]
    facts += [f"{k} sentiment: {v} articles" for k, v in t["sentiment"].items()]
    syn = t.get("syndication") or {}
    if syn.get("top_title_count", 0) > 1:
        facts.append(f"{syn['top_title_count']} of {t['count']} {label} articles "
                     f"({round(100 * syn['top_title_count'] / t['count'], 1)}%) share one headline: "
                     f"\"{syn['top_title']}\"")
    if key == "expert":
        e = cm["expert"]
        facts += [f"{deck.expert_label(k)} mentioned {v} times across {e['type_articles'].get(k, 0)} articles"
                  for k, v in e["type_counts"].items()]
        if e["affiliated_pct"] is not None:
            facts.append(f"{e['affiliated_pct']}% of experts with a stated affiliation are brand-affiliated "
                         f"({e['affiliated_n']} of {e['affiliation_known_n']} experts)")
    if key == "celebrity":
        facts += [f"{c['name']} featured in {c['count']} articles" for c in cm["celebrity"]["top"][:6]]
    if key == "deal":
        facts += [f"Retailer {r['retailer']} in {r['count']} deal articles" for r in cm["deal"]["retailers"][:6]]
    if key == "parenting":
        facts += [f"Topic {k.replace('_', ' ')}: {v} articles" for k, v in cm["parenting"]["topics"].items()]
    return facts


def is_real_logo(content_type: str) -> bool:
    """We request logo.png; Brandfetch answers unknown brands with a WEBP placeholder instead."""
    return content_type.split(";")[0].strip() == "image/png"


def save_logo_png(data: bytes, path: Path) -> Path | None:
    """Normalise any raster logo (webp/jpeg/png) to PNG so python-pptx can embed it; None if not an image."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        return None
    img.convert("RGBA").save(path, format="PNG")
    return path


def _download_logos(brands: list[dict], folder: Path) -> dict[str, Path | None]:
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path | None] = {}
    for b in brands:
        out[b["brand"]] = None
        url = logo_png_url(resolve_logo(b["brand"]))
        if not url:
            continue
        try:
            r = requests.get(url, headers=LOGO_HEADERS, timeout=LOGO_TIMEOUT_S)
        except requests.RequestException as e:
            logger.warning("logo download failed for %s: %s", b["brand"], e)
            continue
        if r.ok and is_real_logo(r.headers.get("content-type", "")):
            out[b["brand"]] = save_logo_png(r.content, folder / (re.sub(r"[^a-z0-9]+", "_", b["brand"].lower()) + ".png"))
    return out


_NAME_TOKEN = re.compile(r"^[A-Z][a-zA-Z'.-]+$")
_CREDENTIALS = {"MD", "PHD", "DO", "RN", "FAAD", "DR", "DR."}


def is_named_person(name: str) -> bool:
    """True for 'Dr. Neha Chandan' / 'Linda Stein Gold, MD'; False for generic roles like 'NICU nurses'."""
    tokens = [t for t in re.split(r"[\s,]+", name.strip()) if t and t.upper() not in _CREDENTIALS]
    return sum(1 for t in tokens if _NAME_TOKEN.match(t) and not t.isupper()) >= 2


def topic_cell(topics: list[dict]) -> str:
    names = [t["topic"].replace("_", " ") for t in topics if t.get("topic") not in (None, "", "unknown")]
    return ", ".join(dict.fromkeys(names)) or "not stated"


def table_rows(classified: dict, by_url: dict, registry: CitationRegistry,
               max_named: int = deck.NAMED_MAX, max_rows: int = deck.PARENTING_MAX) -> tuple[list, int, list, int]:
    """Rows for the named-expert and parenting tables, capped to what the slide shows; only shown rows are cited."""
    named_src = []
    for u, rec in classified["expert"].items():
        for e in rec.get("experts", []):
            if not is_named_person(e["name"]):
                continue
            if e["affiliation"] == "affiliated":
                aff = f"affiliated ({e['brand']})" if e["brand"] else "affiliated"
            else:
                aff = "not stated" if e["affiliation"] == "unknown" else e["affiliation"]
            named_src.append(([e["name"], deck.expert_label(e["expert_type"]), aff, by_url[u].outlet], by_url[u]))
    parenting_src = [([by_url[u].title[:60], topic_cell(rec.get("topics", [])), by_url[u].outlet], by_url[u])
                     for u, rec in classified.get("parenting", {}).items()]
    named = [cells + [f"[{registry.cite(a)}]"] for cells, a in named_src[:max_named]]
    rows = [cells + [f"[{registry.cite(a)}]"] for cells, a in parenting_src[:max_rows]]
    return named, len(named_src), rows, len(parenting_src)


def driver_facts(m: dict, cm: dict) -> list[str]:
    """Celebrity facts first (they make informative backfill cards); sentiment as one combined fact,
    since the slide's doughnut already shows the split."""
    sent = m["themes"]["celebrity"]["sentiment"]
    order = [k for k in ("positive", "neutral", "negative") if k in sent]
    return ([f"{c['name']} featured in {c['count']} articles" for c in cm["celebrity"]["top"][:6]] +
            ["Sentiment split: " + ", ".join(f"{sent[k]} {k} articles" for k in order)])


def driver_candidates(arts: list, n: int) -> list:
    """Highest-reach positive and negative articles, interleaved, so sentiment drivers see both sides."""
    by_sent = {s: sorted((a for a in arts if a.sentiment == s), key=lambda a: -a.reach) for s in ("positive", "negative")}
    out = []
    for pos, neg in zip(by_sent["positive"], by_sent["negative"]):
        out += [pos, neg]
    rest = by_sent["positive"][len(out) // 2:] + by_sent["negative"][len(out) // 2:]
    return (out + rest)[:n]


def metrics_payload(m: dict, cm: dict) -> dict:
    """Everything a slide number can come from, in one JSON (spec §8); table rows are presentation, not metrics."""
    classified = {k: ({kk: vv for kk, vv in v.items() if kk not in ("named", "rows")} if isinstance(v, dict) else v)
                  for k, v in cm.items()}
    return {**m, "classified": classified}


def exec_backfill(m: dict, cm: dict, labels: dict, cites: dict[str, list[int]]) -> list[dict]:
    """One deterministic, cited answer per brief question, so the exec summary never depends on the LLM."""
    def share(k: str) -> str:
        t = m["themes"][k]
        return f"{labels[k]} coverage is {t['share']}% of collected coverage ({t['count']} of {m['base_n']} articles)."

    e = cm["expert"]
    expert_text = share("expert")
    if e.get("type_counts"):
        top = max(e["type_counts"], key=e["type_counts"].get)
        expert_text += (f" {deck.expert_label(top)} is the most-cited expert type "
                        f"({e['type_counts'][top]} mentions across {e.get('type_articles', {}).get(top, 0)} articles).")
    if e.get("affiliated_pct") is not None:
        expert_text += (f" {e['affiliated_pct']}% of experts with a stated affiliation are brand-affiliated "
                        f"({e['affiliated_n']} of {e['affiliation_known_n']}).")
    texts = {"deal": share("deal"), "parenting": share("parenting"), "expert": expert_text,
             "celebrity": share("celebrity")}
    return [{"headline": f"Q{i}: {labels[k]}", "text": texts[k], "citations": cites.get(k, [])}
            for i, k in enumerate(("deal", "parenting", "expert", "celebrity"), start=1)]


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = config.load_config(argv[0])
    out_dir = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    llm = get_llm_client()
    if llm is None:
        logger.error("Azure OpenAI chat is not configured/reachable — stopping (spec: no invented labels).")
        return 2

    articles, ingest_stats = ingest.load_articles(cfg)
    by_url = {a.norm_url: a for a in articles}
    m = metrics.compute_metrics(articles, list(THEMES))
    m["ingest"] = ingest_stats
    _write_json(out_dir / "metrics.json", m)
    logger.info("Ingested %d unique articles %s", m["base_n"], ingest_stats)

    cache_path = out_dir / "classifications.json"
    cache = _load_json(cache_path)
    classified = {}
    for key in THEMES:
        classified[key] = classify.classify_theme([a for a in articles if key in a.themes], key, llm, cache)
        _write_json(cache_path, cache)
        logger.info("Classified %s: %d articles", key, len(classified[key]))
    cm = metrics.compute_classified_metrics(classified)

    registry = CitationRegistry()
    labels = {t["key"]: t["label"] for t in cfg["themes"]}
    ins: dict[str, list[dict]] = {}
    all_facts: list[str] = []
    for key in THEMES:
        facts = _theme_facts(key, labels[key], m, cm)
        all_facts += facts
        cands = (_peak_articles(m["themes"][key], by_url) or [a for a in articles if key in a.themes])[:MAX_CANDIDATES]
        ins[key] = insights.draft_section(labels[key], facts, cands, registry, llm,
                                          n_insights=4)
    ins["celebrity_drivers"] = insights.draft_section(
        "Celebrity-led coverage: what drives positive vs negative sentiment", driver_facts(m, cm),
        driver_candidates([a for a in articles if "celebrity" in a.themes], MAX_CANDIDATES), registry, llm, 5)
    exec_cands = [a for k in THEMES for a in _peak_articles(m["themes"][k], by_url)[:2]]
    ins["exec"] = exec_backfill(m, cm, labels, {k: [registry.cite(a) for a in _peak_articles(m["themes"][k], by_url)[:1]]
                                                for k in THEMES})
    ins["mix"] = insights.draft_section("Coverage mix across themes", all_facts, exec_cands, registry, llm, 3)
    brand_facts = [f"{b['brand']} mentioned in {b['count']} articles" for b in cm["brands"]]
    brand_cands = [by_url[u] for k in THEMES for u, rec in classified[k].items() if rec.get("brands")][:MAX_CANDIDATES]
    ins["brands"] = insights.draft_section("Brands in the conversation", brand_facts, brand_cands, registry, llm, 3)
    ins["takeaways"] = insights.draft_section("Key takeaways", all_facts + brand_facts, exec_cands, registry, llm, 6)
    ins["implications"] = insights.draft_section("Implications for consumer intent, messaging and whitespace",
                                                 all_facts + brand_facts, exec_cands, registry, llm, 4)
    (cm["expert"]["named"], cm["expert"]["named_total"],
     cm["parenting"]["rows"], cm["parenting"]["rows_total"]) = table_rows(classified, by_url, registry)
    _write_json(out_dir / "metrics.json", metrics_payload(m, cm))
    _write_json(out_dir / "insights.json", {"insights": ins, "citations": registry.entries()})

    logos = _download_logos(cm["brands"][:8], out_dir / "logos")
    gauge_png = None
    if cm["expert"]["affiliated_pct"] is not None:
        gauge_png = gauge.render_gauge_png(cm["expert"]["affiliated_pct"], "Brand-affiliated experts",
                                           out_dir / "gauge_affiliation.png")

    out = deck.build_deck(cfg, m, cm, ins, registry, by_url, logos, gauge_png, out_dir / cfg["output_name"])
    last = len(Presentation(out).slides)
    issues = qc.check_layout(out, skip={1, last})   # inherited Hunter cover + closing slides
    _write_json(out_dir / "qc_issues.json", issues)
    pngs = qc.export_pngs(out, out_dir / "qc_png")
    logger.info("Deck: %s | slides exported: %d | QC issues: %d", out, len(pngs), len(issues))
    for i in issues:
        logger.warning("QC slide %s %s: %s", i["slide"], i["kind"], i["detail"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
