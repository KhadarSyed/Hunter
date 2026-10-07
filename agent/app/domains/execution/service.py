"""Research Executor Service — runs the approved Research Plan one Execution
Unit at a time against the uploaded dataset.

The Planner decides WHAT to analyse. The Executor decides HOW.

Lifecycle: pending → running → completed | failed | cancelled | paused
Each unit runs independently; a failure in one does not block the others.
"""
from __future__ import annotations

import csv
import logging
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ...core import store

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
MAX_EVIDENCE_PER_UNIT = 50

_active_runs: dict[int, dict] = {}


# ─── Prerequisites ─────────────────────────────────────────────────────────

def validate_executor_prerequisites(project_id: int) -> dict:
    """Check prerequisites — plan is auto-generated so not required upfront."""
    project = store.get_project(project_id)
    if not project:
        return {"ready": False, "error": "Project not found"}

    prereqs = {}

    spec = project.get("spec", {})
    prereqs["brief_scope"] = (
        {"status": "approved", "message": "OK"}
        if spec and spec.get("commissioning_brand")
        else {"status": "missing", "message": "No approved specification"}
    )

    research = store.get_latest_research(project_id)
    prereqs["background_research"] = (
        {"status": "approved", "message": "OK"}
        if research and research.get("approval_status") == "approved"
        else {"status": "missing", "message": "Background research not approved"}
    )

    strategy = store.get_latest_strategy(project_id)
    prereqs["search_strategy"] = (
        {"status": "approved", "message": "OK"}
        if strategy and strategy.get("approval_status") == "approved"
        else {"status": "missing", "message": "Search strategy not approved"}
    )

    # Check per-RQ datasets first, fall back to old evaluation
    all_datasets = store.get_datasets_by_project(project_id)
    has_approved_ds = any(ds.get("approval_status") == "approved" for ds in all_datasets)
    if not has_approved_ds:
        evaluation = store.get_latest_evaluation(project_id)
        has_approved_ds = evaluation and evaluation.get("status") == "completed"
    prereqs["dataset"] = (
        {"status": "approved", "message": "OK"}
        if has_approved_ds
        else {"status": "missing", "message": "No approved dataset"}
    )

    ready = all(p["status"] == "approved" for p in prereqs.values())
    return {"ready": ready, "prerequisites": prereqs}


# ─── Dataset loading ───────────────────────────────────────────────────────

MELTWATER_COLUMN_MAP = {
    "headline": ["headline", "title", "hit headline", "hit_headline"],
    "url": ["url", "hit url", "hit_url", "link"],
    "source": ["source_name", "source name", "source", "outlet", "media_outlet", "media outlet"],
    "date": ["date", "hit date", "hit_date", "publish date", "publish_date", "publication_date"],
    "author": ["author", "by", "byline", "journalist"],
    "content": ["snippet", "content", "hit sentence", "hit_sentence", "opening text", "opening_text", "summary", "body", "text"],
    "reach": ["reach", "potential_reach", "potential reach", "circulation"],
    "engagement": ["engagement", "social_engagement", "social echo", "social_echo"],
    "sentiment": ["sentiment", "tone", "polarity"],
    "language": ["language", "lang"],
    "country": ["country", "geography", "region", "location"],
    "media_type": ["media_type", "media type", "type", "medium", "document_type"],
}


def _load_dataset(file_path: str) -> list[dict]:
    """Load CSV/XLSX dataset and normalize column names."""
    path = Path(file_path)
    if not path.exists():
        logger.error("Dataset file not found: %s", file_path)
        return []

    if path.suffix.lower() in (".xlsx", ".xls"):
        return _load_xlsx(file_path)

    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc, newline="") as fh:
                reader = csv.DictReader(fh)
                raw = list(reader)
                return _normalize_columns(raw)
        except (UnicodeDecodeError, csv.Error):
            continue
    return []


def _load_xlsx(file_path: str) -> list[dict]:
    """Load XLSX using openpyxl if available, else skip."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True)
        records: list[dict] = []
        # Every sheet: an export can hold a Meltwater sheet plus a manually extracted one. Each sheet is
        # normalized on its own because their column names differ.
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if len(rows) < 2:
                continue
            header_idx = _find_header_row(rows)
            headers = [str(h or "").strip() for h in rows[header_idx]]
            sheet_records = []
            for row in rows[header_idx + 1:]:
                if all(v is None for v in row):
                    continue
                record = {}
                for i, h in enumerate(headers):
                    if h and i < len(row):
                        record[h] = str(row[i]) if row[i] is not None else ""
                sheet_records.append(record)
            records.extend(_normalize_columns(sheet_records))
        wb.close()
        return records
    except ImportError:
        logger.warning("openpyxl not installed — cannot load XLSX")
        return []


def _find_header_row(rows: list[tuple], max_scan: int = 10) -> int:
    """Find the header row in a Meltwater export (may have metadata rows above)."""
    known_headers = {"date", "url", "headline", "title", "source name", "hit sentence",
                     "sentiment", "reach", "keywords", "author name", "content"}
    best_idx, best_score = 0, 0
    for idx in range(min(max_scan, len(rows))):
        cells = [str(c or "").strip().lower() for c in rows[idx] if c is not None]
        score = sum(1 for c in cells if c in known_headers)
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def _normalize_columns(records: list[dict]) -> list[dict]:
    """Map Meltwater column names to standard field names."""
    if not records:
        return []

    raw_columns = list(records[0].keys())
    col_map = {}
    for standard, variants in MELTWATER_COLUMN_MAP.items():
        for col in raw_columns:
            if col.lower().strip() in variants:
                col_map[col] = standard
                break

    normalized = []
    for r in records:
        row = {}
        for raw_col, value in r.items():
            mapped = col_map.get(raw_col, raw_col.lower().strip().replace(" ", "_"))
            row[mapped] = value
        normalized.append(row)
    return normalized


def _convert_news_items(news_items: list[dict]) -> list[dict]:
    """Convert web research news_items to the record format the executor expects."""
    records = []
    for item in news_items:
        records.append({
            "headline": item.get("headline", ""),
            "content": item.get("summary", ""),
            "source": item.get("publisher", ""),
            "date": item.get("date") or item.get("access_date", ""),
            "url": item.get("url", ""),
            "author": "",
            "sentiment": "",
            "reach": "",
            "engagement": "",
            "media_type": "web",
            "_family": item.get("family", ""),
            "_query": item.get("query", ""),
        })
    return records


def _deduplicate(records: list[dict], threshold: float = 0.85) -> list[dict]:
    """Remove duplicate records by URL and headline similarity. Each kept record gets `_copies`: how many
    articles it stands for (itself plus the syndicated copies merged into it), for share-of-coverage."""
    by_url: dict[str, dict] = {}
    seen_headlines: list[tuple[str, dict]] = []
    unique: list[dict] = []

    for record in records:
        url = (record.get("url") or "").strip().lower()
        headline = (record.get("headline") or "").strip().lower()

        if url and url in by_url:
            by_url[url]["_copies"] += 1
            continue
        if headline:
            original = next((kept for seen_hl, kept in seen_headlines[-200:]
                             if SequenceMatcher(None, headline, seen_hl).ratio() >= threshold), None)
            if original is not None:
                original["_copies"] += 1
                continue
        kept = {**record, "_copies": 1}
        if headline:
            seen_headlines.append((headline, kept))
        if url:
            by_url[url] = kept
        unique.append(kept)

    return unique


def _is_excluded(record: dict) -> bool:
    """Rows the analyst removed in the Data Sources Review tab. Needs-review rows still count."""
    return record.get("approval_status") == "disapproved" or record.get("review_status") == "irrelevant"


def _enriched_to_record(rec: dict) -> dict:
    """An enriched Data Sources row in the executor's record shape, keeping its research question."""
    return {
        "headline": rec.get("title") or "",
        "content": rec.get("content") or rec.get("title") or "",
        "source": rec.get("source_name") or "",
        "date": rec.get("date") or "",
        "url": rec.get("url") or "",
        "author": rec.get("author") or "",
        "sentiment": rec.get("overall_sentiment") or "",
        "reach": rec.get("reach") or "",
        "engagement": "",
        "media_type": rec.get("media_type") or "",
        "country": rec.get("country") or "",
        "research_question_id": rec.get("research_question_id"),
        "document_id": rec.get("id"),
        "source_file": rec.get("dataset_file_name"),
    }


def _collect_dataset_records(project_id: int, datasets: list[dict]) -> list[dict]:
    """Rows from every approved dataset: the enriched rows (all sheets, analyst exclusions applied) where
    enrichment ran, otherwise the file itself. Each row keeps its dataset's research question."""
    approved_ids = {ds["id"] for ds in datasets}
    enriched = [r for r in store.get_enriched_records_by_project(project_id) if r.get("dataset_id") in approved_ids]
    enriched_ids = {r["dataset_id"] for r in enriched}
    records = [_enriched_to_record(r) for r in enriched if not _is_excluded(r)]
    for ds in datasets:
        fp = ds.get("file_path") or ""
        if ds["id"] in enriched_ids or not fp or not Path(fp).exists():
            continue
        rq = ds.get("research_question_id")
        records.extend({**r, "research_question_id": rq} for r in _load_dataset(fp))
    return records


def _objective_rq_map(plan: dict) -> dict[str, list[str]]:
    """objective_id -> the research questions it answers (from the plan's business_question_ids)."""
    return {o["objective_id"]: list(o.get("business_question_ids") or [])
            for o in plan.get("research_objectives") or [] if o.get("objective_id")}


def _unit_records(records: list[dict], rq_ids: list[str]) -> list[dict]:
    """The rows uploaded for a unit's research questions; every row when the unit names none or none of its
    questions has data (so a unit is never starved by a missing mapping)."""
    if not rq_ids:
        return records
    wanted = set(rq_ids)
    subset = [r for r in records if r.get("research_question_id") in wanted]
    return subset or records


def _prepare_unit_records(all_records: list[dict], rq_ids: list[str], filters: list[str],
                          platforms: list[str]) -> tuple[list[dict], int]:
    """(unique stories for the method, coverage volume). Coverage volume counts every in-scope article,
    syndicated copies included (share-of-coverage questions); the method reads unique stories so one
    syndicated piece doesn't dominate the themes."""
    in_scope = _apply_filters(_unit_records(all_records, rq_ids), filters, platforms)
    return _deduplicate(in_scope), len(in_scope)


def _apply_filters(records: list[dict], filters: list[str], platforms: list[str]) -> list[dict]:
    """Apply planner-defined filters to the dataset."""
    if not platforms:
        return records
    # Planner platforms are usually categories ("Online news sites") rather than the outlet names or media
    # types in the data, so filter only when rows actually carry one of those labels; otherwise keep all.
    plat_lower = {p.lower() for p in platforms}
    matched = [
        r for r in records
        if (r.get("source") or "").lower() in plat_lower or (r.get("media_type") or "").lower() in plat_lower
    ]
    return matched or records


def _select_fields(records: list[dict], required_fields: list[str]) -> list[dict]:
    """Select only the required fields from each record."""
    if not required_fields:
        return records
    return [
        {k: v for k, v in r.items() if k in required_fields or k in ("url", "headline", "_copies", "document_id", "source_file")}
        for r in records
    ]


# ─── Execution orchestration ──────────────────────────────────────────────

def start_execution(
    project_id: int,
    *,
    emit: Any = None,
) -> dict:
    """Start executing the Research Plan (auto-generates if needed)."""
    if emit is None:
        emit = lambda et, p: None

    project = store.get_project(project_id)
    if not project:
        return {"status": "blocked", "error": "Project not found"}

    # Auto-generate and auto-approve plan if none exists
    plan_row = store.get_latest_plan(project_id)
    if not plan_row or plan_row.get("approval_status") != "approved":
        emit("auto_plan", {"status": "generating"})
        from ..plan import service as planner_service
        plan_result = planner_service.generate_plan(project_id, emit=emit)
        if plan_result.get("status") != "completed":
            return {"status": "blocked", "error": f"Auto-plan failed: {plan_result.get('error', 'unknown')}"}
        plan_row = store.get_latest_plan(project_id)
        if plan_row and plan_row.get("approval_status") != "approved":
            store.approve_plan(plan_row["id"], reviewer="auto")

    plan = plan_row["plan"] if isinstance(plan_row.get("plan"), dict) else {}
    if not plan:
        plan_json = plan_row.get("plan_json")
        if isinstance(plan_json, str):
            import json
            plan = json.loads(plan_json)
        elif isinstance(plan_json, dict):
            plan = plan_json

    execution_units = plan.get("execution_units", [])
    if not execution_units:
        return {"status": "blocked", "error": "No execution units in the plan"}

    # Find dataset: per-RQ datasets → evaluation file → web research fallback
    dataset_path = ""
    web_research_records = None
    dataset_records: list[dict] = []
    all_datasets = store.get_datasets_by_project(project_id)
    approved_ds = [ds for ds in all_datasets
                   if ds.get("approval_status") == "approved" and (ds.get("processing_status") or "done") == "done"]
    if approved_ds:
        dataset_records = _collect_dataset_records(project_id, approved_ds)
        if dataset_records:
            dataset_path = "__approved_datasets__"
    if not dataset_path:
        evaluation = store.get_latest_evaluation(project_id)
        if evaluation:
            dataset_path = evaluation.get("file_path", "")
    if not dataset_records and (not dataset_path or not Path(dataset_path).exists()):
        research = store.get_latest_research(project_id)
        research_data = (research or {}).get("research", {})
        news_items = research_data.get("news_items", [])
        if news_items:
            web_research_records = _convert_news_items(news_items)
            dataset_path = "__web_research__"
        else:
            return {"status": "blocked", "error": "No approved dataset file found"}

    run_id = store.create_execution_run(project_id, plan_row["id"], len(execution_units))

    for unit in execution_units:
        store.create_execution_unit(
            run_id,
            unit["id"],
            unit.get("objective_id", unit["id"]),
            unit.get("recommended_method", "Theme Clustering"),
        )

    _active_runs[run_id] = {"status": "running", "cancel": False, "pause": False}

    store.update_execution_run(run_id, status="running", started_at=time.time())
    store.add_execution_log(run_id, "Execution started")

    spec = project["spec"]
    brand = spec.get("commissioning_brand", {})

    result = _run_execution(
        run_id=run_id,
        execution_units=execution_units,
        dataset_path=dataset_path,
        web_research_records=web_research_records,
        dataset_records=dataset_records,
        objective_rqs=_objective_rq_map(plan),
        spec=spec,
        brand_name=brand.get("name", ""),
        category=brand.get("category", ""),
        emit=emit,
    )

    _active_runs.pop(run_id, None)
    return result


def _run_execution(
    *,
    run_id: int,
    execution_units: list[dict],
    dataset_path: str,
    web_research_records: list[dict] | None = None,
    dataset_records: list[dict] | None = None,
    objective_rqs: dict[str, list[str]] | None = None,
    spec: dict,
    brand_name: str,
    category: str,
    emit: Any,
) -> dict:
    """Execute all units sequentially."""
    from ...methods.registry import get_executor

    if dataset_records:
        all_records = dataset_records
        by_rq: dict[str, int] = {}
        for r in all_records:
            key = r.get("research_question_id") or "unassigned"
            by_rq[key] = by_rq.get(key, 0) + 1
        store.add_execution_log(
            run_id, "Using approved datasets: " + ", ".join(f"{k} {v}" for k, v in sorted(by_rq.items())))
    elif web_research_records:
        all_records = web_research_records
        store.add_execution_log(run_id, f"Using web research data ({len(all_records)} articles)")
    else:
        store.add_execution_log(run_id, f"Loading dataset from {Path(dataset_path).name}")
        all_records = _load_dataset(dataset_path)
    if not all_records:
        store.update_execution_run(run_id, status="failed")
        store.add_execution_log(run_id, "Failed to load dataset", level="error")
        return {"status": "failed", "error": "Could not load dataset", "run_id": run_id}

    store.add_execution_log(run_id, f"Loaded {len(all_records)} records")

    # Deduplicated per unit below: the same article uploaded for two research questions belongs to both.
    objective_rqs = objective_rqs or {}

    completed = 0
    failed = 0
    skipped = 0
    total_evidence = 0

    for idx, unit in enumerate(execution_units):
        run_state = _active_runs.get(run_id, {})
        if run_state.get("cancel"):
            store.add_execution_log(run_id, "Execution cancelled by user")
            remaining = len(execution_units) - idx
            store.update_execution_run(run_id, status="cancelled", skipped_units=skipped + remaining)
            return {"status": "cancelled", "run_id": run_id}

        if run_state.get("pause"):
            store.add_execution_log(run_id, "Execution paused by user")
            store.update_execution_run(run_id, status="paused")
            return {"status": "paused", "run_id": run_id}

        unit_id = unit["id"]
        method_name = unit.get("recommended_method", "Theme Clustering")
        required_fields = unit.get("required_fields", ["content"])
        platforms = unit.get("platforms", [])
        filters = unit.get("filters_required", [])

        eu_row = store.get_execution_unit_by_unit_id(run_id, unit_id)
        if not eu_row:
            continue
        eu_db_id = eu_row["id"]

        deps = unit.get("dependencies", [])
        dep_blocked = False
        if deps:
            done_units = store.get_execution_units(run_id)
            done_ids = {u["unit_id"] for u in done_units if u["status"] == "completed"}
            missing_deps = [d for d in deps if d not in done_ids]
            if missing_deps:
                store.update_execution_unit(eu_db_id, status="skipped",
                                            error=f"Dependencies not met: {', '.join(missing_deps)}")
                store.add_execution_log(run_id, f"Unit {unit_id} skipped — unmet dependencies", unit_id=unit_id)
                skipped += 1
                dep_blocked = True

        if dep_blocked:
            continue

        store.update_execution_unit(eu_db_id, status="running", started_at=time.time())
        store.add_execution_log(run_id, f"Starting unit {unit_id}: {method_name}", unit_id=unit_id)
        emit("executor_unit_start", {"unit_id": unit_id, "method": method_name, "index": idx})

        try:
            rq_ids = objective_rqs.get(unit.get("objective_id", unit_id), [])
            subset, coverage_volume = _prepare_unit_records(all_records, rq_ids, filters, platforms)
            store.add_execution_log(
                run_id, f"Unit {unit_id}: {coverage_volume} articles for {', '.join(rq_ids) or 'all questions'}, "
                        f"{len(subset)} unique stories after merging syndicated copies",
                unit_id=unit_id)
            subset = _select_fields(subset, required_fields + ["url", "headline"])
            store.add_execution_log(run_id, f"Unit {unit_id}: {len(subset)} records after filtering", unit_id=unit_id)

            executor = get_executor(method_name)
            if not executor:
                store.add_execution_log(run_id, f"No executor for method: {method_name}", unit_id=unit_id, level="warn")
                executor = get_executor("theme clustering")

            if not executor:
                store.update_execution_unit(eu_db_id, status="failed",
                                            error=f"No executor available for {method_name}")
                store.add_execution_log(run_id, f"Unit {unit_id} failed: no executor", unit_id=unit_id, level="error")
                failed += 1
                continue

            context = {
                "unit_id": unit_id,
                "objective_id": unit.get("objective_id", unit_id),
                "objective": unit.get("description", unit.get("title", "")),
                "search_concepts": unit.get("search_concepts", []),
                "platforms": platforms,
                "evidence_target": unit.get("evidence_target", ""),
                "brand_name": brand_name,
                "category": category,
                "coverage_volume": coverage_volume,
            }

            evidence_records = executor.execute(subset, context)
            evidence_records = evidence_records[:MAX_EVIDENCE_PER_UNIT]

            for ev in evidence_records:
                store.save_evidence(
                    run_id=run_id,
                    unit_id=unit_id,
                    objective_id=context["objective_id"],
                    evidence_type=ev.get("evidence_type", "finding"),
                    method=method_name,
                    platform=ev.get("platform"),
                    source=ev.get("source"),
                    date=ev.get("date"),
                    text_excerpt=ev.get("text_excerpt", ""),
                    metrics=ev.get("metrics"),
                    confidence=ev.get("confidence", "medium"),
                    rationale=ev.get("rationale", ""),
                url=ev.get("url"), document_id=ev.get("document_id"),
                source_file=ev.get("source_file"), row_index=ev.get("row_index"),
                    dataset="meltwater_export",
                )

            unit_evidence = len(evidence_records)
            total_evidence += unit_evidence

            store.update_execution_unit(
                eu_db_id,
                status="completed",
                records_processed=len(subset),
                evidence_count=unit_evidence,
                result={"evidence_count": unit_evidence, "records_processed": len(subset),
                        "unique_stories": len(subset), "coverage_volume": coverage_volume},
                finished_at=time.time(),
            )
            store.add_execution_log(
                run_id,
                f"Unit {unit_id} completed: {unit_evidence} evidence from {len(subset)} records",
                unit_id=unit_id,
            )
            completed += 1

        except Exception as e:
            logger.error("[executor:%s] Unit %s failed: %s", run_id, unit_id, e, exc_info=True)
            store.update_execution_unit(eu_db_id, status="failed", error=str(e), finished_at=time.time())
            store.add_execution_log(run_id, f"Unit {unit_id} failed: {e}", unit_id=unit_id, level="error")
            failed += 1

        store.update_execution_run(
            run_id,
            completed_units=completed,
            failed_units=failed,
            skipped_units=skipped,
            total_evidence=total_evidence,
        )
        emit("executor_unit_done", {
            "unit_id": unit_id, "index": idx,
            "completed": completed, "failed": failed, "total": len(execution_units),
        })

    final_status = "completed" if failed == 0 and skipped == 0 else "completed_with_errors"
    if completed == 0:
        final_status = "failed"

    store.update_execution_run(run_id, status=final_status, finished_at=time.time())
    store.add_execution_log(run_id, f"Execution finished: {completed} completed, {failed} failed, {skipped} skipped")

    return {
        "status": final_status,
        "run_id": run_id,
        "completed_units": completed,
        "failed_units": failed,
        "skipped_units": skipped,
        "total_evidence": total_evidence,
    }


# ─── Run control ───────────────────────────────────────────────────────────

def pause_execution(run_id: int) -> bool:
    if run_id in _active_runs:
        _active_runs[run_id]["pause"] = True
        store.add_execution_log(run_id, "Pause requested")
        return True
    return False


def resume_execution(project_id: int, run_id: int, *, emit: Any = None) -> dict:
    """Resume a paused execution run from the first pending unit."""
    if emit is None:
        emit = lambda et, p: None

    run = store.get_execution_run(run_id)
    if not run or run["status"] not in ("paused", "completed_with_errors"):
        return {"status": "error", "error": "Run not found or not resumable"}

    plan_row = store.get_latest_plan(project_id)
    plan = plan_row.get("plan") or {}
    if not plan:
        import json
        plan = json.loads(plan_row.get("plan_json", "{}"))

    execution_units = plan.get("execution_units", [])
    existing_units = store.get_execution_units(run_id)
    completed_ids = {u["unit_id"] for u in existing_units if u["status"] == "completed"}

    remaining_units = [u for u in execution_units if u["id"] not in completed_ids]
    if not remaining_units:
        store.update_execution_run(run_id, status="completed")
        return {"status": "completed", "run_id": run_id}

    evaluation = store.get_latest_evaluation(project_id)
    dataset_path = evaluation.get("file_path", "")
    project = store.get_project(project_id)
    spec = project["spec"]
    brand = spec.get("commissioning_brand", {})

    for eu in existing_units:
        if eu["status"] in ("pending", "failed"):
            store.update_execution_unit(eu["id"], status="pending", error=None)

    _active_runs[run_id] = {"status": "running", "cancel": False, "pause": False}
    store.update_execution_run(run_id, status="running")
    store.add_execution_log(run_id, f"Resuming execution — {len(remaining_units)} units remaining")

    result = _run_execution(
        run_id=run_id,
        execution_units=remaining_units,
        dataset_path=dataset_path,
        spec=spec,
        brand_name=brand.get("name", ""),
        category=brand.get("category", ""),
        emit=emit,
    )

    _active_runs.pop(run_id, None)
    return result


def cancel_execution(run_id: int) -> bool:
    if run_id in _active_runs:
        _active_runs[run_id]["cancel"] = True
        store.add_execution_log(run_id, "Cancel requested")
        return True
    run = store.get_execution_run(run_id)
    if run and run["status"] in ("pending", "paused"):
        store.update_execution_run(run_id, status="cancelled")
        store.add_execution_log(run_id, "Execution cancelled")
        return True
    return False


def retry_unit(project_id: int, run_id: int, unit_id: str, *, emit: Any = None) -> dict:
    """Retry a single failed execution unit."""
    if emit is None:
        emit = lambda et, p: None

    from ...methods.registry import get_executor

    run = store.get_execution_run(run_id)
    if not run:
        return {"status": "error", "error": "Run not found"}

    eu = store.get_execution_unit_by_unit_id(run_id, unit_id)
    if not eu:
        return {"status": "error", "error": f"Unit {unit_id} not found"}
    if eu["status"] not in ("failed", "skipped"):
        return {"status": "error", "error": f"Unit {unit_id} is {eu['status']}, not retryable"}

    plan_row = store.get_latest_plan(project_id)
    plan = plan_row.get("plan") or {}
    if not plan:
        import json
        plan = json.loads(plan_row.get("plan_json", "{}"))

    unit_spec = None
    for u in plan.get("execution_units", []):
        if u["id"] == unit_id:
            unit_spec = u
            break
    if not unit_spec:
        return {"status": "error", "error": f"Unit {unit_id} not in plan"}

    project = store.get_project(project_id)
    spec = project["spec"]
    brand = spec.get("commissioning_brand", {})

    approved_ds = [ds for ds in store.get_datasets_by_project(project_id)
                   if ds.get("approval_status") == "approved" and (ds.get("processing_status") or "done") == "done"]
    all_records = _collect_dataset_records(project_id, approved_ds) if approved_ds else []
    if not all_records:
        evaluation = store.get_latest_evaluation(project_id) or {}
        all_records = _load_dataset(evaluation.get("file_path", "")) if evaluation.get("file_path") else []
    if not all_records:
        store.update_execution_unit(eu["id"], status="failed", error="No approved dataset records")
        return {"status": "failed", "error": "No approved dataset records"}
    rq_ids = _objective_rq_map(plan).get(unit_spec.get("objective_id", unit_id), [])

    method_name = unit_spec.get("recommended_method", "Theme Clustering")
    required_fields = unit_spec.get("required_fields", ["content"])
    platforms = unit_spec.get("platforms", [])
    filters = unit_spec.get("filters_required", [])

    store.update_execution_unit(eu["id"], status="running", error=None, started_at=time.time())
    store.add_execution_log(run_id, f"Retrying unit {unit_id}", unit_id=unit_id)

    try:
        subset, coverage_volume = _prepare_unit_records(all_records, rq_ids, filters, platforms)
        subset = _select_fields(subset, required_fields + ["url", "headline"])

        executor = get_executor(method_name)
        if not executor:
            executor = get_executor("theme clustering")
        if not executor:
            store.update_execution_unit(eu["id"], status="failed", error="No executor available")
            return {"status": "failed", "error": "No executor available"}

        context = {
            "unit_id": unit_id,
            "objective_id": unit_spec.get("objective_id", unit_id),
            "objective": unit_spec.get("description", ""),
            "search_concepts": unit_spec.get("search_concepts", []),
            "platforms": platforms,
            "evidence_target": unit_spec.get("evidence_target", ""),
            "brand_name": brand.get("name", ""),
            "category": brand.get("category", ""),
            "coverage_volume": coverage_volume,
        }

        evidence_records = executor.execute(subset, context)[:MAX_EVIDENCE_PER_UNIT]

        for ev in evidence_records:
            store.save_evidence(
                run_id=run_id,
                unit_id=unit_id,
                objective_id=context["objective_id"],
                evidence_type=ev.get("evidence_type", "finding"),
                method=method_name,
                platform=ev.get("platform"),
                source=ev.get("source"),
                date=ev.get("date"),
                text_excerpt=ev.get("text_excerpt", ""),
                metrics=ev.get("metrics"),
                confidence=ev.get("confidence", "medium"),
                rationale=ev.get("rationale", ""),
                url=ev.get("url"), document_id=ev.get("document_id"),
                source_file=ev.get("source_file"), row_index=ev.get("row_index"),
            )

        store.update_execution_unit(
            eu["id"], status="completed",
            records_processed=len(subset),
            evidence_count=len(evidence_records),
            result={"evidence_count": len(evidence_records), "records_processed": len(subset),
                    "unique_stories": len(subset), "coverage_volume": coverage_volume},
            finished_at=time.time(),
        )
        store.add_execution_log(run_id, f"Retry of {unit_id} succeeded: {len(evidence_records)} evidence", unit_id=unit_id)

        units = store.get_execution_units(run_id)
        completed = sum(1 for u in units if u["status"] == "completed")
        failed_count = sum(1 for u in units if u["status"] == "failed")
        skipped_count = sum(1 for u in units if u["status"] == "skipped")
        ev_count = store.count_evidence(run_id)
        store.update_execution_run(run_id, completed_units=completed, failed_units=failed_count,
                                   skipped_units=skipped_count, total_evidence=ev_count)

        return {"status": "completed", "evidence_count": len(evidence_records), "run_id": run_id}

    except Exception as e:
        store.update_execution_unit(eu["id"], status="failed", error=str(e), finished_at=time.time())
        store.add_execution_log(run_id, f"Retry of {unit_id} failed: {e}", unit_id=unit_id, level="error")
        return {"status": "failed", "error": str(e)}


# ─── Query helpers ─────────────────────────────────────────────────────────

def get_execution_status(project_id: int) -> dict | None:
    """Get the current execution status for a project."""
    run = store.get_latest_execution_run(project_id)
    if not run:
        return None

    units = store.get_execution_units(run["id"])
    logs = store.get_execution_logs(run["id"], limit=50)
    evidence_count = store.count_evidence(run["id"])

    elapsed = None
    if run.get("started_at"):
        end = run.get("finished_at") or time.time()
        elapsed = round(end - run["started_at"], 1)

    return {
        "run_id": run["id"],
        "project_id": run["project_id"],
        "plan_id": run["plan_id"],
        "status": run["status"],
        "total_units": run["total_units"],
        "completed_units": run["completed_units"],
        "failed_units": run["failed_units"],
        "skipped_units": run["skipped_units"],
        "total_evidence": evidence_count,
        "elapsed_seconds": elapsed,
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "units": [
            {
                "id": u["id"],
                "unit_id": u["unit_id"],
                "objective_id": u["objective_id"],
                "method": u["method"],
                "status": u["status"],
                "progress_pct": u.get("progress_pct", 0),
                "records_processed": u.get("records_processed", 0),
                "coverage_volume": u.get("coverage_volume"),
                "evidence_count": u.get("evidence_count", 0),
                "error": u.get("error"),
            }
            for u in units
        ],
        "logs": [
            {
                "level": l["level"],
                "message": l["message"],
                "unit_id": l.get("unit_id"),
                "created_at": l["created_at"],
            }
            for l in logs
        ],
    }
