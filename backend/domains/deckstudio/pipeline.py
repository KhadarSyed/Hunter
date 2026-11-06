"""Deck Studio stages inside a deliverable run: index the reference library, design (checklist + plan +
tokens), find assets, compose (render + creative pass), export."""
from __future__ import annotations


import json
from dataclasses import replace
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ...core import config
from ..research import logo_files
from . import data_tables, fixer, validate
from . import (art_director, assets, checklist, creative, design_systems, exporter, image_brief, indexer, planner, renderer, verbatims,
               vision)
from .planner import PlanInput

logger = logging.getLogger(__name__)
_BUDGET = threading.Lock()
# concurrent photo searches (more risks the photo API's and the vision model's rate limits) and verbatim walls (one
# headless browser each); a small container gets fewer, or it runs out of memory mid-run
PHOTO_WORKERS = 2 if config.low_memory() else 4
WALL_WORKERS = 1 if config.low_memory() else 3
# The automatic per-slide restyle is off: on review its versions looked worse than the template, most failed the
# safety or layout checks anyway, and it took ~5 minutes a run. Single-slide edits on request (revise.py) remain.
CREATIVE_RESTYLE = False


def reuse_photos(slides, log=lambda _m: None, fit=lambda path, _slide: path) -> None:
    """A photo slide whose search found nothing borrows the nearest slide's own photo: not the photo slide right next
    to it while another exists (no picture twice in a row), then one from its own question. `fit` crops a borrowed
    photo for this slide's shape and returns None when it would blur, so the next nearest is tried. The cover and
    closing share the client's own photo. The brand gradient stays only when no photo fits."""
    own = next((s.image["path"] for s in slides if s.image.get("path") and s.type in BRAND_BOOKENDS), None)
    lenders = [(i, s) for i, s in enumerate(slides) if s.image.get("path") and s.type not in BRAND_BOOKENDS]
    for i, s in enumerate(slides):
        if s.image.get("path"):
            continue
        if s.type in BRAND_BOOKENDS and own:
            s.image["path"] = own
            log(f"{s.id}: the client's photo from the other end of the deck")
            continue
        nearest = sorted(lenders, key=lambda f: (abs(f[0] - i) == 1, _section(f[1]) != _section(s), abs(f[0] - i)))
        near, path = next(((n, p) for _, n in nearest if (p := fit(n.image["path"], s))), (None, None))
        if path:
            s.image["path"] = str(path)
            log(f"{s.id}: no photo of its own; the nearest slide's photo, from {near.id}")
        else:
            log(f"{s.id}: no photo in the deck fits this slide; brand gradient kept")


def _section(slide) -> str:
    return slide.id.split("-", 1)[0]          # "rq1-divider" -> "rq1": the slides of one research question


def _role(slide) -> str:
    return "panel" if slide.treatment == "C" or slide.type == "objectives" else "background"


def _article_urls(slide, plan_input: PlanInput) -> list[str]:
    """The articles behind a slide: its cards' citations, else the first verbatims of its question."""
    by_n = {c["n"]: c["url"] for c in plan_input.citations}
    cited = [by_n[n] for c in slide.cards for n in c.get("citations", []) if n in by_n]
    if cited:
        return cited[:assets.MAX_ARTICLES]
    rq_id = slide.id.split("-", 1)[0].upper()
    return [v["url"] for v in plan_input.verbatims_by_rq.get(rq_id, [])][:assets.MAX_ARTICLES]


BRAND_BOOKENDS = ("cover", "closing")      # slides that wear the client: their photo must be recognisably its own


def _judge(llm, subjects, label: str, checks: dict, exact: bool = False, own_brand: str = ""):
    """Vision check per candidate photo while the slide's and the run's budgets last; None afterwards (text gate)."""
    mine = {"n": 0}

    def judge(data: bytes):
        with _BUDGET:                      # photo searches run in parallel; the run's budget is shared
            if checks["n"] >= assets.MAX_VISION_CHECKS or mine["n"] >= assets.VISION_PER_SLIDE:
                return None
            checks["n"] += 1
            mine["n"] += 1
        return vision.matches(llm, data, subjects, label, exact=exact, own_brand=own_brand)
    return judge


MAX_PRODUCT_TRIES = 3


def attach_product(spec, products: list[str], find, find_brand=None) -> None:
    """The client's product beside its logo on the cover: the first brief product `find` returns a photo for; when
    none has one, the brand's own photo from `find_brand` (no caption: the logo beside it names the brand)."""
    for name in products[:MAX_PRODUCT_TRIES]:
        path = find(name)
        if path:
            spec.product_image, spec.product_name = str(path), name
            return
    path = find_brand() if products and find_brand else None
    if path:
        spec.product_image, spec.product_name = str(path), ""


def credit_photos(spec) -> None:
    """The 'Photo credits' pages, rebuilt from the photos the deck shows now (a Fix may have swapped one): before the
    Sources, which stay last so a source the Fix finds is appended to them."""
    paths = [s.image.get("path") for s in spec.slides] + [spec.product_image]
    credits = list({c["page"]: c for p in paths if p and (c := assets.credit_of(p))}.values())
    slides = [s for s in spec.slides if not s.id.startswith(planner.CREDITS_ID)]
    at = next((i for i, s in enumerate(slides) if s.type == "citations"),
              next((i for i, s in enumerate(slides) if s.type == "closing"), len(slides)))
    spec.slides = slides[:at] + planner.photo_credits_slides(credits) + slides[at:]


UNMARKED_CHARTS = ("theme_clusters",)


def add_chart_logos(slide, logos: dict[str, Path]) -> None:
    """Logos beside chart labels, added to what the planner already put on the slide (e.g. source icons)."""
    outlet_cols = [[i for i, h in enumerate(t.get("header") or []) if str(h).strip().lower() in ("outlet", "source")]
                   for t in slide.tables]
    # themes are ideas, not organisations: a letter badge or a brand logo beside "Safety investigation" adds noise
    unmarked = any(k in slide.id for k in UNMARKED_CHARTS)
    names = [c for ch in slide.charts if not unmarked for c in ch.get("categories", [])] + \
            [s["name"] for ch in slide.charts for s in ch.get("brand_series") or []] + \
            [str(b) for ch in slide.charts if ch.get("kpis") for b in (ch.get("breakdown") or {}).get("stacks") or []] + \
            [str(row[0]) for t in slide.tables for row in t.get("rows", []) if row] + \
            [str(row[i]) for t, cols in zip(slide.tables, outlet_cols) for row in t.get("rows", []) for i in cols
             if len(row) > i and row[i]]
    found = {n: _brand_logo(n, logos) for n in names}
    slide.logos = {**slide.logos, **{n: str(p) for n, p in found.items() if p}}


def _brand_logo(name: str, logos: dict[str, Path]) -> Path | None:
    """The brand's logo, else its master brand's or its product line's (see visuals.find_logo)."""
    from ..deliverable.visuals import find_logo
    return find_logo(name, logos)


def attach_logos(spec, logos: dict[str, Path], client: str, brands: list[str] | None = None) -> None:
    """A client deck carries the client's logo on the cover and every footer, and the competitive set on the
    cover (client first) -- the brief's brands only, never the outlet icons or chart-label icons also in `logos`."""
    spec.brand_logo = str(logos[client]) if client in logos else ""
    # The emblem the app shows for the brand (Brandfetch icon, cached by logo_files) goes beside the wordmark on the
    # cover: a wordmark alone ("MAZDA" in letters) reads as the brand name typed out, not as its logo
    symbol = logo_files.logo_file(client) if client else None
    spec.brand_symbol = str(symbol[0]) if symbol and str(symbol[0]) != spec.brand_logo else ""
    names = list(dict.fromkeys([client] + list(brands if brands is not None else logos)))
    found = {n: _brand_logo(n, logos) for n in names}
    spec.logo_strip = {n: str(p) for n, p in found.items() if p}


def repair_context(plan_input: PlanInput, checklist_rows: list[dict]) -> dict:
    """The run's own context for the repair agent (fixer.py), saved beside the deck."""
    return {**plan_input.repair_context, "rqs": [{"id": q.id, "question": q.question, "query": q.query}
                                                 for q in plan_input.rqs],
            "citations": [{k: c.get(k, "") for k in ("n", "outlet", "title", "url", "date")} for c in plan_input.citations],
            "citation_brands": {str(k): v for k, v in (plan_input.citation_brands or {}).items()},
            "checklist": checklist_rows, "category": plan_input.category, "verbatims_by_rq": plan_input.verbatims_by_rq,
            "validate": {"brand_products": plan_input.brand_products, "has_competitors": len(plan_input.brands) > 1,
                         "is_category": plan_input.is_category, "mixed_media": plan_input.mixed_media,
                         "brand_share": plan_input.brand_share}}


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
    workbook = data_tables.write_workbook(plan_input, deck_dir)
    run.log(f"Data tables: {workbook.name}")
    rows = checklist.build_checklist(plan_input.rqs, plan_input.sections_by_rq, checklist.brief_asks(project_id),
                                     has_data_export=workbook.exists())
    plan_input.checklist = rows
    spec = planner.build_deck_spec(plan_input)
    attach_logos(spec, logos, plan_input.title, plan_input.brands)
    spec.brand_colors = list(brand_colors)
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
    photo_slides = [s for s in spec.slides
                    if (s.treatment in ("A", "C", "full") or s.type == "objectives") and s.image.get("query")]
    # the client's actual products (CX-50, CX-90) are what a photo can show; the scope's keyword hints ("Zoom-Zoom",
    # "Kodo design", Planet Fitness's "brand refresh") searched slogans, logos and merch, so vision rejected them and most
    # slides had no photo of their own; a brand with no products (a gym, a service) searches its brand and category
    shown = plan_input.brand_products
    scene_by_id = image_brief.scenes(llm, photo_slides, plan_input.brands, shown, plan_input.category)
    checks = {"n": 0}
    for s in spec.slides:
        add_chart_logos(s, logos)

    def photo_for(s):
        role = _role(s)
        k = photo_slides.index(s) % max(1, len(shown))      # each slide leads with the next product, so photos vary
        subjects = image_brief.subjects_for(s, plan_input.brands, shown[k:] + shown[:k], plan_input.category,
                                            scene_by_id.get(s.id, ""))
        if not subjects.brands and not plan_input.is_category:
            # a slide naming no brand (takeaways, insights) searched its own words ("Did we answer the brief")
            # and spent its vision checks on junk; the client's own brand and product are always on-topic
            subjects = replace(subjects, brands=[plan_input.title])
        rivals = [b for b in subjects.brands if b != plan_input.title]
        if rivals:
            # a slide about competitors shows one of theirs, rotating across the slide's brands; never the client's
            # product under a rival's name ("BYD Model Y" finds nothing and a Tesla photo wins every slide)
            j = photo_slides.index(s) % len(rivals)
            subjects = replace(subjects, brands=rivals[j:] + rivals[:j], products=[])
        label = s.question or s.title or s.kicker
        return assets.find_photo(" ".join(image_brief.queries(subjects)[:1]) or s.image["query"], role,
                                 deck_dir / "photos", used, brand_image if s.type == "cover" else None,
                                 subjects=subjects, article_urls=_article_urls(s, plan_input),
                                 judge=_judge(llm, subjects, label, checks,
                                              own_brand=plan_input.title if s.type in BRAND_BOOKENDS
                                              and not plan_input.is_category else ""))

    # a slide whose subject and search match an earlier run's (any project's) reuses that photo: Regenerate, and
    # another organization's deck on the same brand, spend nothing on it (shared asset table)
    def cached_photo_for(s):
        key = assets.photo_key(plan_input.title, _role(s), s.image["query"])
        photo = (assets.cached_photo(key, deck_dir / "photos", used)
                 or assets.similar_photo(plan_input.title, _role(s), s.image["query"], deck_dir / "photos", used))
        if photo is None:
            photo = photo_for(s)
            assets.remember_photo(key, photo, _role(s), plan_input.title, s.image["query"])
        return photo

    # Each slide's photo search is independent (30-75s of search and vision checks), so several run at once;
    # threads only search, the run log is written here
    photos = {}
    with ThreadPoolExecutor(max_workers=PHOTO_WORKERS) as pool:
        futures = {pool.submit(cached_photo_for, s): s for s in photo_slides}
        for k, done in enumerate(as_completed(futures), start=1):
            run.within("assets", 0.8 * k / max(1, len(photo_slides)), f"Finding photos: {k} of {len(photo_slides)}")
            try:
                photos[futures[done].id] = done.result()
            except Exception as e:         # one slide's failed search costs that slide's photo, not the deck
                logger.exception("photo search failed for %s", futures[done].id)
                photos[futures[done].id] = assets.Photo(None, "", "none", f"photo search failed ({type(e).__name__})")
    taken: set[str] = set()                # URLs and content fingerprints of the photos placed so far

    def picture(photo) -> bytes:           # the downloaded original: crops for different slide shapes differ
        raw = Path(photo.path).with_suffix(".src")
        return (raw if raw.exists() else Path(photo.path)).read_bytes()

    for s in photo_slides:                 # two slides searched at once may have picked the same picture
        photo = photos[s.id]
        if photo.path and (photo.source_url in taken or assets.is_duplicate(picture(photo), taken)):
            photo = photo_for(s)           # `used` now holds every photo chosen above (URLs and fingerprints)
            if photo.path and assets.is_duplicate(picture(photo), taken):
                photo = assets.Photo(None, "", "none", "only pictures already on other slides")
        if photo.path:
            taken.add(photo.source_url)
            assets.mark_used(picture(photo), taken)
        s.image["path"] = str(photo.path) if photo.path else None
        s.image["why"] = photo.why
        found.append({"slide": s.id, "source": photo.source_url, "licence": photo.licence, "why": photo.why})
        if photo.path:
            run.log(f"Photo for {s.id}: {photo.licence} - {photo.why} - {photo.source_url[:90]}")
        else:
            run.log(f"No relevant photo for {s.id} ({photo.why}); brand gradient kept")
    reuse_photos(photo_slides, run.log,
                 lambda path, s: assets.refit(Path(path), _role(s), deck_dir / "photos" / f"{s.id}-nearest.jpg"))

    def product_photo(name: str):
        return assets.product_photo(plan_input.title, name, plan_input.category, deck_dir / "photos", used,
                                    lambda subj: _judge(llm, subj, f"{name} by {plan_input.title}", checks, exact=True)).path

    def brand_photo():
        return None if plan_input.is_category else assets.brand_photo(
            plan_input.title, plan_input.category, deck_dir / "photos", used,
            lambda subj: _judge(llm, subj, plan_input.title, checks, own_brand=plan_input.title)).path
    attach_product(spec, plan_input.brand_products, product_photo, brand_photo)
    credit_photos(spec)
    if spec.product_image:
        run.log(f"Cover product: {spec.product_name or plan_input.title + ' (brand photo: no brief product has one)'}")
    walls = [s for s in spec.slides if s.type == "verbatim_wall"]
    shots: dict[str, str] = {}

    def wall_shots(s):                     # each wall opens its own browser, so walls capture side by side
        rq_id = s.id.rsplit("-verbatims", 1)[0].upper()
        return verbatims.collect(plan_input.verbatims_by_rq.get(rq_id, []), config.DATA_DIR / "verbatims")

    with ThreadPoolExecutor(max_workers=WALL_WORKERS) as pool:
        captured = list(pool.map(wall_shots, walls))
    for k, (s, got) in enumerate(zip(walls, captured), start=1):
        run.within("assets", 0.9 + 0.1 * k / len(walls), f"Capturing article screenshots for question {k} of {len(walls)}")
        rq_id = s.id.rsplit("-verbatims", 1)[0].upper()
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
            icon = next((m["icon"] for n in c.get("citations", [])
                         if (m := spec.citation_meta.get(str(n)) or {}).get("icon")), None)
            if first or icon:              # the article's screenshot, else its outlet's icon
                c["thumb"] = shots[first] if first else icon
    run.stage("assets", "done", f"{sum(1 for f in found if f['licence'] != 'none')} photos")

    run.stage("compose", "running")
    html, report = creative.compose(spec, deck_dir, llm if CREATIVE_RESTYLE else None,
                                    indexer.reference_text_shingles(),
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
    run.stage("export", "done", f"studio deck - {len(out['pngs'])} slides")
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("covered", "partial", "missing")}
    checks = validate.validate_deck(spec, plan_input.rqs, rows, plan_input.brand_products,
                                    has_competitors=len(plan_input.brands) > 1,
                                    citation_brands=plan_input.citation_brands or None, pptx=out["pptx"],
                                    is_category=plan_input.is_category, mixed_media=plan_input.mixed_media,
                                    brand_share=plan_input.brand_share)
    for c in checks:
        if c["status"] != "pass":
            run.log(f"Validation {c['status']}: {c['check'][:80]} - {c['detail'][:120]}")
    run.log(f"Validation: {sum(c['status'] == 'pass' for c in checks)} of {len(checks)} checks pass")

    # the validator's findings are acted on, not just listed: the repair agent fixes what it can and says why not
    run.stage("repair", "running")
    repair = fixer.Repair(spec, repair_context(plan_input, rows), llm, deck_dir, log=run.log)
    try:
        fixer.save(repair)                 # the Fix button can repair this run later from the same context
        checks, rebuilt = fixer.run_repairs(repair, checks, "all", on_fix)
        rows = repair.checklist
        counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("covered", "partial", "missing")}
        if rebuilt:
            html, out = rebuilt["html"], rebuilt
    except Exception as e:                 # the validated deck still ships; the Fix button can retry
        logger.exception("repair agent failed")
        run.log(f"Repair agent stopped: {type(e).__name__}: {e}")
    run.stage("repair", "done", f"{sum(c['status'] == 'pass' for c in checks)} of {len(checks)} checks pass")
    return {"validation": checks, "html": html, "pptx": out["pptx"], "pdf": out["pdf"], "family": spec.family,
            "family_reason": spec.family_reason,
            "design_system": entry["name"], "design_reason": design_why, "checklist": rows, "scorecard": counts, "report": report,
            "assets": found, "spec": spec, "deck_dir": deck_dir}
