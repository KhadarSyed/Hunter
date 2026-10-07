"""Deck Studio stages inside a deliverable run: index the reference library, design (checklist + plan +
tokens), find assets, compose (render + creative pass), export."""
from __future__ import annotations

import json
from pathlib import Path

from . import art_director, assets, checklist, creative, exporter, indexer, planner, renderer
from .planner import PlanInput


def run_studio(run, project_id: int, llm, plan_input: PlanInput, brand_colors: list[str], brand_image: Path | None,
               logos: dict[str, Path], out_dir: Path) -> dict:
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
    rows = checklist.attach_slide_numbers(spec, rows)
    spec.tokens, source = art_director.choose_tokens(llm, brand_colors, plan_input.scope_text,
                                                     indexer.design_rules(spec.family))
    run.log(f"Design family: {spec.family} - {spec.family_reason}")
    run.log(f"Palette and fonts ({source}): {spec.tokens.title_font} / {spec.tokens.body_font}, primary #{spec.tokens.primary}")
    for s in spec.slides:
        if s.reference:
            run.log(f"{s.id}: layout from {Path(s.reference['deck']).stem} slide {s.reference['slide']} ({s.reference['why']})")
    run.stage("design", "done", spec.family)

    run.stage("assets", "running")
    used: set[str] = set()
    found = []
    mood = " ".join(spec.tokens.mood[:2])
    for k, s in enumerate(spec.slides, start=1):
        run.within("assets", k / len(spec.slides), f"Finding photos and logos for slide {k} of {len(spec.slides)}")
        if s.treatment in ("A", "C", "full") and s.image.get("query"):
            role = "panel" if s.treatment == "C" else "background"
            photo = assets.find_photo(f"{s.image['query']} {mood}".strip(), role, deck_dir / "photos", used,
                                      brand_image if s.type == "cover" else None)
            s.image["path"] = str(photo.path) if photo.path else None
            found.append({"slide": s.id, "source": photo.source_url, "licence": photo.licence})
            if photo.path:
                run.log(f"Photo for {s.id}: {photo.licence} source {photo.source_url[:90]}")
        names = [c for ch in s.charts for c in ch.get("categories", [])]
        s.logos = {n: str(logos[n]) for n in names if n in logos}
    run.stage("assets", "done", f"{sum(1 for f in found if f['licence'] != 'none')} photos")

    run.stage("compose", "running")
    html, report = creative.compose(spec, deck_dir, llm, indexer.reference_text_shingles(),
                                    progress=lambda i, n, sid: run.within("compose", i / max(1, n), f"Designing slide {i} of {n}"))
    for r in report:
        if r["reasons"] and r["reasons"][0] != "no usable creative version":
            run.log(f"{r['slide_id']}: template version kept - {r['reasons'][0]}")
        for flag in r.get("qc", []):
            run.log(f"QC flag on {r['slide_id']}: {flag}")
    renderer.inline_assets(html)
    run.stage("compose", "done", f"{sum(1 for r in report if r['source'] == 'creative')} slides restyled")
    (deck_dir / "spec.json").write_text(json.dumps(spec.to_dict(), default=str), encoding="utf-8")

    run.stage("export", "running")
    out = exporter.export_all(html, spec, deck_dir, spec.title)
    run.stage("export", "done", f"{len(out['pngs'])} slides")
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("covered", "partial", "missing")}
    return {"html": html, "pptx": out["pptx"], "pdf": out["pdf"], "family": spec.family,
            "family_reason": spec.family_reason, "checklist": rows, "scorecard": counts, "report": report,
            "assets": found, "spec": spec, "deck_dir": deck_dir}
