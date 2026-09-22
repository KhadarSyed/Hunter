"""Tests for executor_service: execution lifecycle, unit sequencing, dataset
filtering, duplicate removal, method routing, evidence persistence, resume
after interruption, retry logic, cancellation, and progress tracking."""
from __future__ import annotations

import csv
import json
import os
import tempfile
import time
import pytest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import intelligence_store as store
from agent.app import config
from agent.app import executor_service


SAMPLE_SPEC = {
    "commissioning_brand": {
        "name": "TestBrand",
        "category": "Snacks",
        "products": ["Chips", "Pretzels"],
        "parent_company": "FoodCo",
    },
    "business_objective": "Understand snack preferences",
    "research_objective": "Map consumer snack behaviors",
    "research_questions": [
        {"question_id": "RQ1", "question": "What are the most popular snack occasions?", "priority": "primary"},
        {"question_id": "RQ2", "question": "How do consumers compare chip brands?", "priority": "primary"},
    ],
    "included_scope": {
        "platforms": ["Twitter/X", "Reddit"],
        "countries": ["United States"],
        "time_period": "Jan 2026 - Jun 2026",
        "languages": ["English"],
    },
    "excluded_scope": [],
}

SAMPLE_PLAN = {
    "plan_summary": "Test plan",
    "research_objectives": [
        {"objective_id": "RO1", "objective": "Snack occasions", "methods": ["Theme Clustering"]},
        {"objective_id": "RO2", "objective": "Brand comparison", "methods": ["Sentiment Analysis"]},
    ],
    "execution_units": [
        {
            "id": "EU1",
            "title": "Theme Analysis",
            "objective_id": "RO1",
            "recommended_method": "Theme Clustering",
            "required_fields": ["content", "headline"],
            "platforms": [],
            "filters_required": [],
            "evidence_target": "10 evidence items",
            "dependencies": [],
            "description": "Cluster snack occasion themes",
            "search_concepts": ["snack", "occasion"],
        },
        {
            "id": "EU2",
            "title": "Sentiment on brands",
            "objective_id": "RO2",
            "recommended_method": "Sentiment Analysis",
            "required_fields": ["content", "sentiment"],
            "platforms": [],
            "filters_required": [],
            "evidence_target": "8 evidence items",
            "dependencies": [],
            "description": "Analyse sentiment toward chip brands",
            "search_concepts": ["chips", "brand"],
        },
    ],
}

SAMPLE_PLAN_WITH_DEPS = {
    "plan_summary": "Test plan with dependencies",
    "research_objectives": [{"objective_id": "RO1", "objective": "Test", "methods": ["Theme Clustering"]}],
    "execution_units": [
        {
            "id": "EU1",
            "title": "First",
            "objective_id": "RO1",
            "recommended_method": "Theme Clustering",
            "required_fields": ["content"],
            "platforms": [],
            "filters_required": [],
            "evidence_target": "",
            "dependencies": [],
            "description": "First unit",
            "search_concepts": [],
        },
        {
            "id": "EU2",
            "title": "Second — depends on EU1",
            "objective_id": "RO1",
            "recommended_method": "Sentiment Analysis",
            "required_fields": ["content"],
            "platforms": [],
            "filters_required": [],
            "evidence_target": "",
            "dependencies": ["EU1"],
            "description": "Second unit",
            "search_concepts": [],
        },
    ],
}


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    config.MEMORY_DB_PATH = tmp_path / "test_memory.db"
    store.init_intelligence_db()
    executor_service._active_runs.clear()
    yield


def _write_sample_csv(path, rows=20):
    """Write a test CSV with Meltwater-like columns."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Headline", "URL", "Source Name", "Date", "Snippet", "Sentiment"])
        writer.writeheader()
        for i in range(rows):
            writer.writerow({
                "Headline": f"Test headline about snacks {i}",
                "URL": f"http://example.com/article-{i}",
                "Source Name": "TestSource" if i % 2 == 0 else "OtherSource",
                "Date": f"2026-03-{(i % 28) + 1:02d}",
                "Snippet": f"This is a test article about chips and snack occasions number {i}. Brand TestBrand is mentioned here.",
                "Sentiment": "positive" if i % 3 == 0 else ("negative" if i % 3 == 1 else "neutral"),
            })


def _create_full_project(tmp_path, csv_rows=20):
    """Create a project with all 5 prerequisites met and an approved plan."""
    pid = store.get_or_create_project(SAMPLE_SPEC)

    rid = store.save_background_research(pid, {"status": "completed", "web_search_executed": True}, None)
    store.approve_research(rid, "test")

    sid = store.save_search_strategy(pid, {"strategy_summary": "Test", "core_queries": [{"type": "broad", "query": '"TestBrand"'}]})
    store.approve_strategy(sid, "test")

    csv_path = str(tmp_path / "sample.csv")
    _write_sample_csv(csv_path, csv_rows)
    eid = store.save_sample_evaluation(pid, sid, "sample.csv", csv_path)
    store.update_evaluation(eid, {"status": "completed", "total_records": csv_rows, "relevant_count": csv_rows})

    plan_id = store.save_research_plan(pid, SAMPLE_PLAN, source="deterministic")
    store.approve_plan(plan_id, "test")

    return pid


# ─── Prerequisite validation ──────────────────────────────────────────────

class TestExecutorPrerequisites:
    def test_nonexistent_project(self):
        result = executor_service.validate_executor_prerequisites(9999)
        assert result["ready"] is False

    def test_incomplete_prerequisites(self):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        result = executor_service.validate_executor_prerequisites(pid)
        assert result["ready"] is False
        assert result["prerequisites"]["background_research"]["status"] == "missing"

    def test_all_prerequisites_met(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.validate_executor_prerequisites(pid)
        assert result["ready"] is True
        for v in result["prerequisites"].values():
            assert v["status"] == "approved"

    def test_unapproved_plan_blocks(self, tmp_path):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        rid = store.save_background_research(pid, {"status": "completed"}, None)
        store.approve_research(rid, "test")
        sid = store.save_search_strategy(pid, {"strategy_summary": "Test"})
        store.approve_strategy(sid, "test")
        csv_path = str(tmp_path / "sample.csv")
        _write_sample_csv(csv_path)
        eid = store.save_sample_evaluation(pid, sid, "sample.csv", csv_path)
        store.update_evaluation(eid, {"status": "completed", "total_records": 20})
        store.save_research_plan(pid, SAMPLE_PLAN, source="deterministic")
        result = executor_service.validate_executor_prerequisites(pid)
        assert result["ready"] is False
        assert result["prerequisites"]["research_plan"]["status"] == "missing"


# ─── Dataset loading ──────────────────────────────────────────────────────

class TestDatasetLoading:
    def test_load_csv(self, tmp_path):
        path = str(tmp_path / "test.csv")
        _write_sample_csv(path, 10)
        records = executor_service._load_dataset(path)
        assert len(records) == 10
        assert "headline" in records[0]
        assert "url" in records[0]
        assert "content" in records[0]

    def test_load_nonexistent(self):
        records = executor_service._load_dataset("/nonexistent/path.csv")
        assert records == []

    def test_column_normalization(self, tmp_path):
        path = str(tmp_path / "test.csv")
        _write_sample_csv(path, 5)
        records = executor_service._load_dataset(path)
        assert "source" in records[0]
        assert "date" in records[0]
        assert "sentiment" in records[0]


class TestDeduplication:
    def test_url_dedup(self):
        records = [
            {"url": "http://example.com/a", "headline": "First article about snacks and brands"},
            {"url": "http://example.com/a", "headline": "Duplicate URL article about something else entirely"},
            {"url": "http://example.com/b", "headline": "Completely different topic about weather forecasts"},
        ]
        result = executor_service._deduplicate(records)
        assert len(result) == 2

    def test_headline_similarity_dedup(self):
        records = [
            {"url": "http://example.com/1", "headline": "TestBrand launches new snack line"},
            {"url": "http://example.com/2", "headline": "TestBrand launches new snack line today"},
            {"url": "http://example.com/3", "headline": "Something completely different"},
        ]
        result = executor_service._deduplicate(records, threshold=0.85)
        assert len(result) == 2

    def test_empty_input(self):
        assert executor_service._deduplicate([]) == []

    def test_no_duplicates(self):
        records = [
            {"url": "http://a.com", "headline": "Alpha"},
            {"url": "http://b.com", "headline": "Beta"},
            {"url": "http://c.com", "headline": "Gamma"},
        ]
        assert len(executor_service._deduplicate(records)) == 3


class TestFiltering:
    def test_platform_filter(self):
        records = [
            {"source": "Twitter", "content": "a"},
            {"source": "Reddit", "content": "b"},
            {"source": "Instagram", "content": "c"},
        ]
        result = executor_service._apply_filters(records, [], ["Twitter", "Reddit"])
        assert len(result) == 2

    def test_no_filters(self):
        records = [{"source": "Twitter"}, {"source": "Reddit"}]
        result = executor_service._apply_filters(records, [], [])
        assert len(result) == 2

    def test_field_selection(self):
        records = [{"content": "text", "headline": "h", "url": "u", "sentiment": "pos", "extra": "x"}]
        result = executor_service._select_fields(records, ["content", "sentiment"])
        assert "content" in result[0]
        assert "headline" in result[0]
        assert "url" in result[0]
        assert "sentiment" in result[0]
        assert "extra" not in result[0]


# ─── Method routing ───────────────────────────────────────────────────────

class TestMethodRouting:
    def test_get_executor_theme_clustering(self):
        from agent.app.methods.registry import get_executor
        executor = get_executor("Theme Clustering")
        assert executor is not None

    def test_get_executor_sentiment(self):
        from agent.app.methods.registry import get_executor
        executor = get_executor("Sentiment Analysis")
        assert executor is not None

    def test_get_executor_case_insensitive(self):
        from agent.app.methods.registry import get_executor
        executor = get_executor("theme clustering")
        assert executor is not None

    def test_all_12_methods_registered(self):
        from agent.app.methods.registry import list_methods
        methods = list_methods()
        assert len(methods) == 12

    def test_unknown_method_returns_none(self):
        from agent.app.methods.registry import get_executor
        assert get_executor("NonexistentMethod") is None

    def test_executor_returns_evidence(self):
        from agent.app.methods.registry import get_executor
        executor = get_executor("Theme Clustering")
        records = [
            {"content": f"Test about snacks and chips number {i}", "headline": f"Snack article {i}"}
            for i in range(10)
        ]
        context = {"unit_id": "EU1", "objective_id": "RO1", "objective": "Find themes", "search_concepts": ["snack"]}
        evidence = executor.execute(records, context)
        assert isinstance(evidence, list)
        for ev in evidence:
            assert "text_excerpt" in ev
            assert "confidence" in ev
            assert ev["confidence"] in ("high", "medium", "low")


# ─── Full execution lifecycle ─────────────────────────────────────────────

class TestExecutionLifecycle:
    def test_start_execution_success(self, tmp_path):
        pid = _create_full_project(tmp_path)
        events = []
        result = executor_service.start_execution(pid, emit=lambda et, p: events.append((et, p)))
        assert result["status"] in ("completed", "completed_with_errors")
        assert result["run_id"] > 0
        assert result["total_evidence"] >= 0

    def test_start_blocked_no_prerequisites(self):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        result = executor_service.start_execution(pid)
        assert result["status"] == "blocked"
        assert "missing" in result

    def test_execution_creates_run_record(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        run = store.get_execution_run(result["run_id"])
        assert run is not None
        assert run["status"] in ("completed", "completed_with_errors")

    def test_execution_creates_unit_records(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        units = store.get_execution_units(result["run_id"])
        assert len(units) == 2

    def test_units_have_correct_statuses(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        units = store.get_execution_units(result["run_id"])
        for u in units:
            assert u["status"] in ("completed", "failed", "skipped")


# ─── Evidence persistence ─────────────────────────────────────────────────

class TestEvidencePersistence:
    def test_evidence_stored(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        evidence = store.get_evidence(result["run_id"])
        assert len(evidence) > 0

    def test_evidence_has_required_fields(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        evidence = store.get_evidence(result["run_id"])
        if evidence:
            ev = evidence[0]
            assert "unit_id" in ev
            assert "objective_id" in ev
            assert "method" in ev
            assert "text_excerpt" in ev
            assert "confidence" in ev

    def test_evidence_count_matches(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        count = store.count_evidence(result["run_id"])
        evidence = store.get_evidence(result["run_id"])
        assert count == len(evidence)

    def test_evidence_per_unit(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        ev_eu1 = store.get_evidence(result["run_id"], "EU1")
        ev_eu2 = store.get_evidence(result["run_id"], "EU2")
        assert isinstance(ev_eu1, list)
        assert isinstance(ev_eu2, list)


# ─── Execution logs ──────────────────────────────────────────────────────

class TestExecutionLogs:
    def test_logs_created(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        logs = store.get_execution_logs(result["run_id"])
        assert len(logs) > 0

    def test_log_contains_start_message(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        logs = store.get_execution_logs(result["run_id"])
        messages = [l["message"] for l in logs]
        assert any("started" in m.lower() for m in messages)


# ─── Progress tracking ───────────────────────────────────────────────────

class TestProgressTracking:
    def test_get_execution_status(self, tmp_path):
        pid = _create_full_project(tmp_path)
        executor_service.start_execution(pid)
        status = executor_service.get_execution_status(pid)
        assert status is not None
        assert "run_id" in status
        assert "units" in status
        assert "logs" in status
        assert "total_evidence" in status
        assert "elapsed_seconds" in status

    def test_no_status_for_new_project(self):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        status = executor_service.get_execution_status(pid)
        assert status is None

    def test_emit_events_fired(self, tmp_path):
        pid = _create_full_project(tmp_path)
        events = []
        executor_service.start_execution(pid, emit=lambda et, p: events.append(et))
        assert "executor_unit_start" in events
        assert "executor_unit_done" in events


# ─── Cancellation ─────────────────────────────────────────────────────────

class TestCancellation:
    def test_cancel_pending_run(self, tmp_path):
        pid = _create_full_project(tmp_path)
        plan = store.get_latest_plan(pid)
        run_id = store.create_execution_run(pid, plan["id"], 2)
        ok = executor_service.cancel_execution(run_id)
        assert ok is True
        run = store.get_execution_run(run_id)
        assert run["status"] == "cancelled"

    def test_cancel_nonexistent_run(self):
        ok = executor_service.cancel_execution(9999)
        assert ok is False


# ─── Retry logic ─────────────────────────────────────────────────────────

class TestRetry:
    def test_retry_completed_unit_rejected(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        units = store.get_execution_units(result["run_id"])
        completed_unit = next((u for u in units if u["status"] == "completed"), None)
        if completed_unit:
            retry_result = executor_service.retry_unit(pid, result["run_id"], completed_unit["unit_id"])
            assert retry_result["status"] == "error"

    def test_retry_nonexistent_unit(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.start_execution(pid)
        retry_result = executor_service.retry_unit(pid, result["run_id"], "NONEXISTENT")
        assert retry_result["status"] == "error"

    def test_retry_nonexistent_run(self, tmp_path):
        pid = _create_full_project(tmp_path)
        result = executor_service.retry_unit(pid, 9999, "EU1")
        assert result["status"] == "error"


# ─── Dependency handling ─────────────────────────────────────────────────

class TestDependencies:
    def test_unmet_dependency_skips_unit(self, tmp_path):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        rid = store.save_background_research(pid, {"status": "completed"}, None)
        store.approve_research(rid, "test")
        sid = store.save_search_strategy(pid, {"strategy_summary": "Test"})
        store.approve_strategy(sid, "test")
        csv_path = str(tmp_path / "sample.csv")
        _write_sample_csv(csv_path)
        eid = store.save_sample_evaluation(pid, sid, "sample.csv", csv_path)
        store.update_evaluation(eid, {"status": "completed", "total_records": 20})

        dep_plan = {
            "plan_summary": "Dep test",
            "research_objectives": [{"objective_id": "RO1", "objective": "Test"}],
            "execution_units": [
                {
                    "id": "EU1", "title": "First", "objective_id": "RO1",
                    "recommended_method": "Theme Clustering",
                    "required_fields": ["content"], "platforms": [],
                    "filters_required": [], "evidence_target": "",
                    "dependencies": [], "description": "First", "search_concepts": [],
                },
                {
                    "id": "EU2", "title": "Depends on phantom", "objective_id": "RO1",
                    "recommended_method": "Theme Clustering",
                    "required_fields": ["content"], "platforms": [],
                    "filters_required": [], "evidence_target": "",
                    "dependencies": ["EU_PHANTOM"],
                    "description": "Depends on a unit that doesn't exist",
                    "search_concepts": [],
                },
            ],
        }

        plan_id = store.save_research_plan(pid, dep_plan, source="deterministic")
        store.approve_plan(plan_id, "test")

        result = executor_service.start_execution(pid)
        units = store.get_execution_units(result["run_id"])
        eu2 = next(u for u in units if u["unit_id"] == "EU2")
        assert eu2["status"] == "skipped"


# ─── Execution store functions ────────────────────────────────────────────

class TestExecutionStore:
    def test_create_and_get_run(self, tmp_path):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        run_id = store.create_execution_run(pid, 1, 3)
        assert run_id > 0
        run = store.get_execution_run(run_id)
        assert run is not None
        assert run["total_units"] == 3
        assert run["status"] == "pending"

    def test_update_run(self, tmp_path):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        run_id = store.create_execution_run(pid, 1, 2)
        store.update_execution_run(run_id, status="running", completed_units=1)
        run = store.get_execution_run(run_id)
        assert run["status"] == "running"
        assert run["completed_units"] == 1

    def test_latest_run(self, tmp_path):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        store.create_execution_run(pid, 1, 2)
        run_id_2 = store.create_execution_run(pid, 1, 3)
        latest = store.get_latest_execution_run(pid)
        assert latest["id"] == run_id_2

    def test_create_and_get_units(self, tmp_path):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        run_id = store.create_execution_run(pid, 1, 2)
        store.create_execution_unit(run_id, "EU1", "RO1", "Theme Clustering")
        store.create_execution_unit(run_id, "EU2", "RO2", "Sentiment Analysis")
        units = store.get_execution_units(run_id)
        assert len(units) == 2

    def test_update_unit(self, tmp_path):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        run_id = store.create_execution_run(pid, 1, 1)
        eu_id = store.create_execution_unit(run_id, "EU1", "RO1", "Theme Clustering")
        store.update_execution_unit(eu_id, status="completed", evidence_count=5)
        eu = store.get_execution_unit_by_unit_id(run_id, "EU1")
        assert eu["status"] == "completed"
        assert eu["evidence_count"] == 5

    def test_execution_logs(self, tmp_path):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        run_id = store.create_execution_run(pid, 1, 1)
        store.add_execution_log(run_id, "Test log message")
        store.add_execution_log(run_id, "Error occurred", level="error")
        logs = store.get_execution_logs(run_id)
        assert len(logs) == 2
        levels = {l["level"] for l in logs}
        assert "info" in levels
        assert "error" in levels

    def test_save_and_get_evidence(self, tmp_path):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        run_id = store.create_execution_run(pid, 1, 1)
        store.save_evidence(
            run_id=run_id, unit_id="EU1", objective_id="RO1",
            evidence_type="finding", method="Theme Clustering",
            text_excerpt="Test excerpt", confidence="high",
            rationale="Test rationale",
        )
        evidence = store.get_evidence(run_id)
        assert len(evidence) == 1
        assert evidence[0]["text_excerpt"] == "Test excerpt"
        assert evidence[0]["confidence"] == "high"

    def test_count_evidence(self, tmp_path):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        run_id = store.create_execution_run(pid, 1, 1)
        for i in range(3):
            store.save_evidence(
                run_id=run_id, unit_id="EU1", objective_id="RO1",
                evidence_type="finding", method="Theme Clustering",
                text_excerpt=f"Excerpt {i}", confidence="medium", rationale="r",
            )
        assert store.count_evidence(run_id) == 3
        assert store.count_evidence(run_id, "EU1") == 3
        assert store.count_evidence(run_id, "EU2") == 0
