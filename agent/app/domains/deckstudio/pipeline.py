"""Deck Studio stages inside a deliverable run: index the reference library, design (checklist + plan +
tokens), find assets, compose (render + creative pass), export."""
from __future__ import annotations

import json
from pathlib import Path

from ...core import config
from . import validate
from . import (art_director, assets, checklist, creative, design_systems, exporter, image_brief, indexer, planner, renderer, verbatims,
               vision)
from .planner import PlanInput


def _article_urls(slide, plan_input: PlanInput) -> list[str]:
    """The articles behind a slide: its cards' citations, else the first verbatims of its question."""
    by_n = {c["n"]: c["url"] for c in plan_input.citations}
    cited = [by_n[n] for c in slide.cards for n in c.get("citations", []) if n in by_n]
    if cited:
        return cited[:assets.MAX_ARTICLES]
    rq_id = slide.id.split("-", 1)[0].upper()
    return [v["url"] for v in plan_input.verbatims_by_rq.get(rq_id, [])][:assets.MAX_ARTICLES]


def _judge(llm, subjects, label: str, checks: dict):
    """Vision check per candidate photo while the slide's and the run's budgets last; None afterwards (text gate)."""
    mine = {"n": 0}

    def judge(data: bytes):
        if checks["n"] >= assets.MAX_VISION_CHECKS or mine["n"] >= assets.VISION_PER_SLIDE:
            return None
        checks["n"] += 1
        mine["n"] += 1
        return vision.matches(llm, data, subjects, label)
    return judge


MAX_PRODUCT_TRIES = 3


def attach_product(spec, products: list[str], find) -> None:
    """The client's product beside its logo on the cover: the first brief product `find` returns a photo for."""
    for name in products[:MAX_PRODUCT_TRIES]:
        path = find(name)
        if path:
            spec.product_image, spec.product_name = str(path), name
            return


def add_chart_logos(slide, logos: dict[str, Path]) -> None:
    """Logos beside chart labels, added to what the planner already put on the slide (e.g. source icons)."""
    names = [c for ch in slide.charts for c in ch.get("categories", [])] + \
            [str(row[0]) for t in slide.tables for row in t.get("rows", []) if row]
    found = {n: _brand_logo(n, logos) for n in names}
    slide.logos = {**slide.logos, **{n: str(p) for n, p in found.items() if p}}


def _brand_logo(name: str, logos: dict[str, Path]) -> Path | None:
    """The brand's logo, else its master brand's ("Aveeno" for "Aveeno Baby")."""
    if name in logos:
        return logos[name]
    words = name.split()
    return next((logos[" ".join(words[:k])] for k in range(len(words) - 1, 0, -1) if " ".join(words[:k]) in logos), None)


def attach_logos(spec, logos: dict[str, Path], client: str, brands: list[str] | None = None) -> None:
    """A client deck carries the client's logo on the cover and every footer, and the competitive set on the
    cover (client first) -- the brief's brands only, never the outlet icons or chart-label icons also in `logos`."""
    spec.brand_logo = str(logos[client]) if client in logos else ""
    names = list(dict.fromkeys([client] + list(brands if brands is not None else logos)))
    found = {n: _brand_logo(n, logos) for n in names}
    spec.logo_strip = {n: str(p) for n, p in found.items() if p}


def run_studio(run, project_id: int, llm, plan_input: PlanInput, brand_colors: list[str], brand_image: Path | None,
               logos: dict[str, Path], out_dir: Path, on_fix=None, on_issue=None) -> dict:
    deck_dir = out_dir / "deck"
    run.stage("index", "running")
    summary = indexer.index_library(progress=lambda i, n, name: run.within("index", i / max(1, n),
                                                                           f"Reading reference deck {i} of {n}"))
    run.log(f"Reference library: {summary['indexed']} indexed, {summary['unchanged']} unchanged, "
            f"{summary['skipped']} skipped, {summary['removed']} removed")
    run.stage("index", "done")

    run.stage("design", "running")
    rows = checklist.build_checklist(plan_input.rqs, plan_input.sections_by_rq, checklist.brief_asks(project_id))
    plan_input.checklist = rows
    spec = planner.build_deck_spec(plan_input)
    attach_logos(spec, logos, plan_input.title, plan_input.brands)
    rows = checklist.attach_slide_numbers(spec, rows)
    entry, design_why = design_systems.choose(llm, plan_input.scope_text, [])
    design = {**(entry.get("design") or design_systems.load(entry["slug"])), "slug": entry["slug"]}
    spec.tokens, source = art_director.choose_tokens(llm, brand_colors, plan_input.scope_text,
                                                     indexer.design_rules(spec.family), design=design)
    run.log(f"Design system: {entry['name']} - {design_why}")
    run.log(f"Design family: {spec.family} - {spec.family_reason}")
    run.log(f"Palette and fonts ({source}): {spec.tokens.title_font} / {spec.tokens.body_font}, primary #{spec.tokens.primary}")
    for s in spec.slides:
        if s.reference:
            run.log(f"{s.id}: layout from {Path(s.reference['deck']).stem} slide {s.reference['slide']} ({s.reference['why']})")
    run.stage("design", "done", spec.family)

    run.stage("assets", "running")
    used: set[str] = set()
    found = []
    photo_slides = [s for s in spec.slides if s.treatment in ("A", "C", "full") and s.image.get("query")]
    scene_by_id = image_brief.scenes(llm, photo_slides, plan_input.brands, plan_input.products, plan_input.category)
    checks = {"n": 0}
    for k, s in enumerate(spec.slides, start=1):
        run.within("assets", 0.9 * k / len(spec.slides), f"Finding photos and logos for slide {k} of {len(spec.slides)}")
        add_chart_logos(s, logos)
        if s not in photo_slides:
            continue
        role = "panel" if s.treatment == "C" else "background"
        subjects = image_brief.subjects_for(s, plan_input.brands, plan_input.products, plan_input.category,
                                            scene_by_id.get(s.id, ""))
        label = s.question or s.title or s.kicker
        photo = assets.find_photo(" ".join(image_brief.queries(subjects)[:1]) or s.image["query"], role,
                                  deck_dir / "photos", used, brand_image if s.type == "cover" else None,
                                  subjects=subjects, article_urls=_article_urls(s, plan_input),
                                  judge=_judge(llm, subjects, label, checks))
        s.image["path"] = str(photo.path) if photo.path else None
        s.image["why"] = photo.why
        found.append({"slide": s.id, "source": photo.source_url, "licence": photo.licence, "why": photo.why})
        if photo.path:
            run.log(f"Photo for {s.id}: {photo.licence} - {photo.why} - {photo.source_url[:90]}")
        else:
            run.log(f"No relevant photo for {s.id} ({photo.why}); brand gradient kept")
    def product_photo(name: str):
        subjects = image_brief.Subjects([plan_input.title], [name], plan_input.category, f"{name} product packshot")
        return assets.find_photo(f"{plan_input.title} {name}", "panel", deck_dir / "photos", used, subjects=subjects,
                                 judge=_judge(llm, subjects, f"{name} by {plan_input.title}", checks)).path
    attach_product(spec, plan_input.brand_products, product_photo)
    if spec.product_image:
        run.log(f"Cover product: {spec.product_name}")
    walls = [s for s in spec.slides if s.type == "verbatim_wall"]
    shots: dict[str, str] = {}
    for k, s in enumerate(walls, start=1):
        run.within("assets", 0.9 + 0.1 * k / len(walls), f"Capturing article screenshots for question {k} of {len(walls)}")
        rq_id = s.id.rsplit("-verbatims", 1)[0].upper()
        got = verbatims.collect(plan_input.verbatims_by_rq.get(rq_id, []), config.DATA_DIR / "verbatims")
        s.cards = [{**c, "image": g["image"]} for c, g in zip(s.cards, got)]
        shots.update({g["url"]: g["image"] for g in got if g["image"]})
        run.log(f"Verbatims for {s.kicker or rq_id}: {sum(g['kind'] == 'screenshot' for g in got)} screenshots, "
                f"{sum(g['kind'] == 'card' for g in got)} article cards, {sum(g['kind'] == 'none' for g in got)} skipped")
        for g in got:
            run.log(f"Verbatim source: {g['url']}")
    by_n = {c["n"]: c["url"] for c in plan_input.citations}
    for s in spec.slides:
        if s.type == "verbatim_wall":
            continue
        for c in s.cards:
            first = next((by_n[n] for n in c.get("citations", []) if by_n.get(n) in shots), None)
            if first:
                c["thumb"] = shots[first]
    run.stage("assets", "done", f"{sum(1 for f in found if f['licence'] != 'none')} photos")

    run.stage("compose", "running")
    html, report = creative.compose(spec, deck_dir, llm, indexer.reference_text_shingles(),
                                    progress=lambda i, n, sid: run.within("compose", i / max(1, n), f"Designing slide {i} of {n}"),
                                    on_fix=on_fix)
    for r in report:
        if r["reasons"] and r["reasons"][0] != "no usable creative version":
            run.log(f"{r['slide_id']}: template version kept - {r['reasons'][0]}")
        for flag in r.get("qc", []):
            run.log(f"QC flag on {r['slide_id']}: {flag}")
        if r.get("repaired"):
            run.log(f"Repaired {r['slide_id']}: {', '.join(r['repaired'])}")
        if r["qc"] and on_issue:
            on_issue(r["slide_id"], r["qc"])
    renderer.inline_assets(html)
    run.stage("compose", "done", f"{sum(1 for r in report if r['source'] == 'creative')} slides restyled")
    (deck_dir / "spec.json").write_text(json.dumps(spec.to_dict(), default=str), encoding="utf-8")

    run.stage("export", "running")
    out = exporter.export_all(html, spec, deck_dir, spec.title)
    run.stage("export", "done", f"{len(out['pngs'])} slides")
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("covered", "partial", "missing")}
    checks = validate.validate_deck(spec, plan_input.rqs, rows, plan_input.brand_products,
                                    has_competitors=len(plan_input.brands) > 1,
                                    citation_brands=plan_input.citation_brands or None, pptx=out["pptx"],
                                    is_category=plan_input.is_category)
    for c in checks:
        if c["status"] != "pass":
            run.log(f"Validation {c['status']}: {c['check'][:80]} - {c['detail'][:120]}")
    run.log(f"Validation: {sum(c['status'] == 'pass' for c in checks)} of {len(checks)} checks pass")
    return {"validation": checks, "html": html, "pptx": out["pptx"], "pdf": out["pdf"], "family": spec.family,
            "family_reason": spec.family_reason,
            "design_system": entry["name"], "design_reason": design_why, "checklist": rows, "scorecard": counts, "report": report,
            "assets": found, "spec": spec, "deck_dir": deck_dir}
