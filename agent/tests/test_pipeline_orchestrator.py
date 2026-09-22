"""Tests for Pipeline Orchestrator: dependency resolution, execution ordering,
caching, failure recovery, pause/resume/cancel, metrics, progress tracking,
pipeline status, and public API."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import config
from agent.app import intelligence_store as store
from agent.app import pipeline_orchestrator as orch


def _make_project(name="Test Project"):
    spec = {
        "project_title": name,
        "commissioning_brand": {"name": "Test Brand"},
        "research_subject": {"name": "Test Subject"},
        "research_questions": [],
    }
    return store.create_project(name, spec)


class DependencyManagerTest(unittest.TestCase):
    def test_get_dependencies(self):
        self.assertEqual(orch.get_dependencies("brief_scope"), [])
        self.assertEqual(orch.get_dependencies("background_research"), ["brief_scope"])
        self.assertIn("storyline_builder", orch.get_dependencies("presentation_composer"))
        self.assertIn("si_retrieval", orch.get_dependencies("presentation_composer"))

    def test_unknown_stage_returns_empty(self):
        self.assertEqual(orch.get_dependencies("nonexistent"), [])

    def test_get_all_upstream_brief(self):
        self.assertEqual(orch.get_all_upstream("brief_scope"), set())

    def test_get_all_upstream_pptx(self):
        up = orch.get_all_upstream("pptx_renderer")
        self.assertIn("brief_scope", up)
        self.assertIn("presentation_composer", up)
        self.assertIn("storyline_builder", up)
        self.assertNotIn("pptx_renderer", up)

    def test_get_all_upstream_si_retrieval_independent(self):
        self.assertEqual(orch.get_all_upstream("si_retrieval"), set())

    def test_get_downstream_brief(self):
        ds = orch.get_downstream("brief_scope")
        self.assertIn("background_research", ds)
        self.assertIn("pptx_renderer", ds)
        self.assertNotIn("si_retrieval", ds)

    def test_get_downstream_leaf(self):
        self.assertEqual(orch.get_downstream("pptx_renderer"), set())

    def test_get_downstream_search_strategy(self):
        ds = orch.get_downstream("search_strategy")
        self.assertIn("query_evaluation", ds)
        self.assertIn("dataset_upload", ds)
        self.assertIn("research_planner", ds)

    def test_execution_order_preserves_dependency_order(self):
        stages = ["pptx_renderer", "brief_scope", "insight_generator"]
        ordered = orch.get_execution_order(stages)
        self.assertEqual(ordered[0], "brief_scope")
        self.assertEqual(ordered[-1], "pptx_renderer")

    def test_execution_order_all_stages(self):
        ordered = orch.get_execution_order(list(orch.STAGES.keys()))
        for i in range(len(ordered) - 1):
            self.assertLessEqual(
                orch.STAGES[ordered[i]]["order"],
                orch.STAGES[ordered[i + 1]]["order"],
            )

    def test_parallel_groups_full(self):
        groups = orch.get_parallel_groups(list(orch.STAGE_ORDER))
        self.assertGreater(len(groups), 0)
        all_stages = set()
        for g in groups:
            for s in g:
                self.assertNotIn(s, all_stages)
                all_stages.add(s)
        self.assertEqual(all_stages, set(orch.STAGE_ORDER))

    def test_parallel_groups_query_dataset_parallel(self):
        groups = orch.get_parallel_groups(list(orch.STAGE_ORDER))
        for g in groups:
            if "query_evaluation" in g or "dataset_upload" in g:
                if len(g) > 1:
                    self.assertIn("query_evaluation", g)
                    self.assertIn("dataset_upload", g)
                break

    def test_parallel_groups_single(self):
        groups = orch.get_parallel_groups(["brief_scope"])
        self.assertEqual(groups, [["brief_scope"]])

    def test_parallel_groups_empty(self):
        self.assertEqual(orch.get_parallel_groups([]), [])

    def test_get_invalidated_stages(self):
        inv = orch.get_invalidated_stages("search_strategy")
        self.assertIn("query_evaluation", inv)
        self.assertIn("dataset_upload", inv)
        self.assertIn("research_planner", inv)
        self.assertNotIn("brief_scope", inv)
        self.assertNotIn("background_research", inv)

    def test_invalidated_leaf_empty(self):
        self.assertEqual(orch.get_invalidated_stages("pptx_renderer"), [])

    def test_dependency_graph_structure(self):
        graph = orch.get_dependency_graph()
        self.assertEqual(len(graph), 13)
        for sid, node in graph.items():
            self.assertIn("name", node)
            self.assertIn("order", node)
            self.assertIn("dependencies", node)
            self.assertIn("downstream", node)
            self.assertIn("requires_approval", node)

    def test_dependency_graph_consistency(self):
        graph = orch.get_dependency_graph()
        for sid, node in graph.items():
            for dep in node["dependencies"]:
                self.assertIn(sid, graph[dep]["downstream"])


class StageDefinitionTest(unittest.TestCase):
    def test_stage_count(self):
        self.assertEqual(len(orch.STAGES), 13)

    def test_stage_order_contiguous(self):
        orders = sorted(cfg["order"] for cfg in orch.STAGES.values())
        self.assertEqual(orders, list(range(1, 14)))

    def test_all_stages_have_required_keys(self):
        for sid, cfg in orch.STAGES.items():
            self.assertIn("name", cfg, f"{sid} missing name")
            self.assertIn("order", cfg, f"{sid} missing order")
            self.assertIn("dependencies", cfg, f"{sid} missing dependencies")
            self.assertIn("requires_approval", cfg, f"{sid} missing requires_approval")

    def test_dependencies_reference_valid_stages(self):
        for sid, cfg in orch.STAGES.items():
            for dep in cfg["dependencies"]:
                self.assertIn(dep, orch.STAGES,
                              f"{sid} depends on unknown stage {dep}")

    def test_no_circular_dependencies(self):
        for sid in orch.STAGES:
            upstream = orch.get_all_upstream(sid)
            self.assertNotIn(sid, upstream,
                             f"Circular dependency detected for {sid}")

    def test_stage_order_list(self):
        self.assertEqual(len(orch.STAGE_ORDER), 13)
        self.assertEqual(orch.STAGE_ORDER[0], "brief_scope")
        self.assertEqual(orch.STAGE_ORDER[-1], "pptx_renderer")

    def test_valid_statuses_defined(self):
        self.assertIn("running", orch.VALID_RUN_STATUSES)
        self.assertIn("completed", orch.VALID_RUN_STATUSES)
        self.assertIn("failed", orch.VALID_RUN_STATUSES)
        self.assertIn("paused", orch.VALID_RUN_STATUSES)
        self.assertIn("cached", orch.VALID_STAGE_STATUSES)


class CacheManagerTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orch_cache_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test.db")
        config.DATA_DIR = self._tmpdir
        store.init_intelligence_db()
        self.project_id = _make_project()

    def test_compute_input_hash_deterministic(self):
        h1 = orch._compute_input_hash(self.project_id, "brief_scope")
        h2 = orch._compute_input_hash(self.project_id, "brief_scope")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_compute_input_hash_differs_by_stage(self):
        h1 = orch._compute_input_hash(self.project_id, "brief_scope")
        h2 = orch._compute_input_hash(self.project_id, "background_research")
        self.assertNotEqual(h1, h2)

    def test_check_cache_miss(self):
        result = orch.check_cache(self.project_id, "brief_scope")
        self.assertFalse(result["hit"])
        self.assertIn("input_hash", result)

    def test_store_and_check_cache_hit(self):
        ih = orch._compute_input_hash(self.project_id, "brief_scope")
        orch.store_cache(self.project_id, "brief_scope", ih,
                         output_hash="abc123", result_summary={"ok": True})
        result = orch.check_cache(self.project_id, "brief_scope")
        self.assertTrue(result["hit"])

    def test_clear_stage_cache(self):
        ih = orch._compute_input_hash(self.project_id, "brief_scope")
        orch.store_cache(self.project_id, "brief_scope", ih)
        cleared = orch.clear_stage_cache(self.project_id, "brief_scope")
        self.assertGreaterEqual(cleared, 1)
        result = orch.check_cache(self.project_id, "brief_scope")
        self.assertFalse(result["hit"])

    def test_clear_project_cache(self):
        ih = orch._compute_input_hash(self.project_id, "brief_scope")
        orch.store_cache(self.project_id, "brief_scope", ih)
        cleared = orch.clear_project_cache(self.project_id)
        self.assertGreaterEqual(cleared, 1)

    def test_invalidate_downstream_cache(self):
        for sid in ["brief_scope", "background_research", "search_strategy"]:
            ih = orch._compute_input_hash(self.project_id, sid)
            orch.store_cache(self.project_id, sid, ih)
        invalidated = orch.invalidate_downstream_cache(
            self.project_id, "brief_scope")
        self.assertIn("background_research", invalidated)
        self.assertNotIn("brief_scope", invalidated)


class StageStatusCheckerTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orch_status_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test.db")
        config.DATA_DIR = self._tmpdir
        store.init_intelligence_db()
        self.project_id = _make_project()

    def test_brief_scope_completed(self):
        status = orch._check_stage_status(self.project_id, "brief_scope")
        self.assertEqual(status["status"], "completed")
        self.assertTrue(status["exists"])

    def test_background_research_not_started(self):
        status = orch._check_stage_status(self.project_id, "background_research")
        self.assertEqual(status["status"], "not_started")
        self.assertFalse(status["exists"])

    def test_si_retrieval_not_started(self):
        status = orch._check_stage_status(self.project_id, "si_retrieval")
        self.assertIn(status["status"], ("not_started", "completed"))

    def test_get_project_stage_statuses(self):
        statuses = orch.get_project_stage_statuses(self.project_id)
        self.assertEqual(len(statuses), 13)
        for sid, data in statuses.items():
            self.assertIn("stage_id", data)
            self.assertIn("name", data)
            self.assertIn("order", data)
            self.assertIn("status", data)

    def test_unknown_stage_returns_not_started(self):
        status = orch._check_stage_status(self.project_id, "nonexistent_stage")
        self.assertEqual(status["status"], "not_started")


class PipelineStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orch_store_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test.db")
        config.DATA_DIR = self._tmpdir
        store.init_intelligence_db()
        self.project_id = _make_project()

    def test_create_and_get_pipeline_run(self):
        run_id = "test-run-001"
        store.create_pipeline_run(
            run_id, self.project_id,
            execution_mode="full",
            remaining_stages=["brief_scope", "background_research"],
            user="tester",
        )
        run = store.get_pipeline_run(run_id)
        self.assertIsNotNone(run)
        self.assertEqual(run["id"], run_id)
        self.assertEqual(run["project_id"], self.project_id)
        self.assertEqual(run["status"], "pending")
        self.assertEqual(run["execution_mode"], "full")

    def test_update_pipeline_run(self):
        run_id = "test-run-002"
        store.create_pipeline_run(run_id, self.project_id)
        store.update_pipeline_run(run_id, status="running",
                                  current_stage="brief_scope",
                                  progress_pct=10)
        run = store.get_pipeline_run(run_id)
        self.assertEqual(run["status"], "running")

    def test_list_pipeline_runs(self):
        store.create_pipeline_run("r1", self.project_id)
        store.create_pipeline_run("r2", self.project_id)
        runs = store.list_pipeline_runs(self.project_id)
        self.assertGreaterEqual(len(runs), 2)

    def test_get_latest_pipeline_run(self):
        store.create_pipeline_run("r-a", self.project_id)
        store.create_pipeline_run("r-b", self.project_id)
        latest = store.get_latest_pipeline_run(self.project_id)
        self.assertIsNotNone(latest)

    def test_create_and_get_pipeline_stage(self):
        run_id = "test-run-003"
        store.create_pipeline_run(run_id, self.project_id)
        store.create_pipeline_stage(
            run_id, "brief_scope", "Brief & Scope",
            dependencies=[],
        )
        stages = store.get_pipeline_stages(run_id)
        self.assertGreaterEqual(len(stages), 1)
        self.assertEqual(stages[0]["stage_id"], "brief_scope")

    def test_update_pipeline_stage(self):
        run_id = "test-run-004"
        store.create_pipeline_run(run_id, self.project_id)
        store.create_pipeline_stage(run_id, "brief_scope", "Brief & Scope")
        store.update_pipeline_stage(run_id, "brief_scope", status="completed")
        stage = store.get_pipeline_stage(run_id, "brief_scope")
        self.assertIsNotNone(stage)
        self.assertEqual(stage["status"], "completed")

    def test_pipeline_cache_crud(self):
        cache_id = store.set_pipeline_cache(
            self.project_id, "brief_scope", "hash123",
            output_hash="out456",
            result_summary={"test": True},
        )
        self.assertGreater(cache_id, 0)
        cached = store.get_pipeline_cache(self.project_id, "brief_scope")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["input_hash"], "hash123")
        cleared = store.clear_pipeline_cache(self.project_id, "brief_scope")
        self.assertGreaterEqual(cleared, 1)

    def test_pipeline_logs(self):
        run_id = "test-run-005"
        store.create_pipeline_run(run_id, self.project_id)
        store.add_pipeline_log(run_id, "Test log message",
                               stage_id="brief_scope", level="info")
        store.add_pipeline_log(run_id, "Error message",
                               stage_id="brief_scope", level="error")
        logs = store.get_pipeline_logs(run_id)
        self.assertGreaterEqual(len(logs), 2)
        error_logs = store.get_pipeline_logs(run_id, stage_id="brief_scope")
        self.assertGreaterEqual(len(error_logs), 2)

    def test_pipeline_metrics(self):
        run_id = "test-run-006"
        store.create_pipeline_run(run_id, self.project_id)
        store.add_pipeline_metric(
            self.project_id, "stage_execution_time", 150,
            stage_id="brief_scope", run_id=run_id, unit="ms",
        )
        metrics = store.get_pipeline_metrics(self.project_id)
        self.assertGreaterEqual(len(metrics), 1)

    def test_pipeline_performance(self):
        perf = store.get_pipeline_performance(self.project_id)
        self.assertIn("total_runs", perf)
        self.assertIn("avg_duration_ms", perf)
        self.assertIn("cache_hit_ratio", perf)
        self.assertIn("stage_averages", perf)
        self.assertIn("cache_breakdown", perf)


class DetermineStagesTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orch_det_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test.db")
        config.DATA_DIR = self._tmpdir
        store.init_intelligence_db()
        self.project_id = _make_project()

    def test_full_mode(self):
        stages = orch._determine_stages(self.project_id, "full")
        self.assertEqual(len(stages), 13)
        self.assertEqual(stages[0], "brief_scope")
        self.assertEqual(stages[-1], "pptx_renderer")

    def test_single_mode(self):
        stages = orch._determine_stages(
            self.project_id, "single", single_stage="insight_generator")
        self.assertEqual(stages, ["insight_generator"])

    def test_from_stage_mode(self):
        stages = orch._determine_stages(
            self.project_id, "from_stage", start_stage="evidence_library")
        self.assertIn("evidence_library", stages)
        self.assertIn("pptx_renderer", stages)
        self.assertNotIn("brief_scope", stages)

    def test_changed_mode_no_cache(self):
        stages = orch._determine_stages(self.project_id, "changed")
        self.assertEqual(len(stages), 13)

    def test_changed_mode_with_cache(self):
        for sid in orch.STAGE_ORDER:
            ih = orch._compute_input_hash(self.project_id, sid)
            orch.store_cache(self.project_id, sid, ih)
        stages = orch._determine_stages(self.project_id, "changed")
        self.assertEqual(len(stages), 0)


class PublicAPITest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orch_api_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test.db")
        config.DATA_DIR = self._tmpdir
        store.init_intelligence_db()
        self.project_id = _make_project()

    def test_start_invalid_project(self):
        result = orch.start_pipeline(99999)
        self.assertIn("error", result)

    def test_start_invalid_mode(self):
        result = orch.start_pipeline(self.project_id, mode="bogus")
        self.assertIn("error", result)

    def test_pause_nonexistent(self):
        result = orch.pause_pipeline("no-such-run")
        self.assertIn("error", result)

    def test_resume_nonexistent(self):
        result = orch.resume_pipeline("no-such-run")
        self.assertIn("error", result)

    def test_cancel_nonexistent(self):
        result = orch.cancel_pipeline("no-such-run")
        self.assertIn("error", result)

    def test_retry_nonexistent(self):
        result = orch.retry_stage("no-such-run", "brief_scope")
        self.assertIn("error", result)

    def test_retry_unknown_stage(self):
        run_id = "test-retry-run"
        store.create_pipeline_run(run_id, self.project_id)
        result = orch.retry_stage(run_id, "fake_stage")
        self.assertIn("error", result)

    def test_pause_not_running(self):
        run_id = "test-pause-run"
        store.create_pipeline_run(run_id, self.project_id)
        store.update_pipeline_run(run_id, status="completed")
        result = orch.pause_pipeline(run_id)
        self.assertIn("error", result)

    def test_cancel_completed(self):
        run_id = "test-cancel-run"
        store.create_pipeline_run(run_id, self.project_id)
        store.update_pipeline_run(run_id, status="completed")
        result = orch.cancel_pipeline(run_id)
        self.assertIn("error", result)

    def test_resume_not_paused(self):
        run_id = "test-resume-run"
        store.create_pipeline_run(run_id, self.project_id)
        store.update_pipeline_run(run_id, status="running")
        result = orch.resume_pipeline(run_id)
        self.assertIn("error", result)

    def test_resume_no_remaining(self):
        run_id = "test-resume-empty"
        store.create_pipeline_run(run_id, self.project_id)
        store.update_pipeline_run(run_id, status="paused",
                                  remaining_stages=[])
        result = orch.resume_pipeline(run_id)
        self.assertIn("error", result)

    def test_resume_mode_no_resumable(self):
        result = orch.start_pipeline(self.project_id, mode="resume")
        self.assertIn("error", result)

    def test_cancel_running_pipeline(self):
        run_id = "test-cancel-active"
        store.create_pipeline_run(run_id, self.project_id)
        store.update_pipeline_run(run_id, status="running")
        result = orch.cancel_pipeline(run_id)
        self.assertEqual(result["status"], "cancelled")

    def test_pause_running_pipeline(self):
        run_id = "test-pause-active"
        store.create_pipeline_run(run_id, self.project_id)
        store.update_pipeline_run(run_id, status="running")
        result = orch.pause_pipeline(run_id)
        self.assertEqual(result["status"], "paused")


class PipelineStatusTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orch_stat_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test.db")
        config.DATA_DIR = self._tmpdir
        store.init_intelligence_db()
        self.project_id = _make_project()

    def test_get_pipeline_status_none(self):
        result = orch.get_pipeline_status("nonexistent")
        self.assertIsNone(result)

    def test_get_pipeline_status_with_stages(self):
        run_id = "status-run"
        store.create_pipeline_run(run_id, self.project_id)
        store.create_pipeline_stage(run_id, "brief_scope", "Brief & Scope")
        status = orch.get_pipeline_status(run_id)
        self.assertIsNotNone(status)
        self.assertIn("stages", status)
        self.assertGreaterEqual(len(status["stages"]), 1)

    def test_get_project_status(self):
        status = orch.get_project_status(self.project_id)
        self.assertEqual(status["project_id"], self.project_id)
        self.assertIn("stage_statuses", status)
        self.assertEqual(len(status["stage_statuses"]), 13)
        self.assertIn("performance", status)
        self.assertIn("dependency_graph", status)

    def test_get_execution_timeline_empty(self):
        timeline = orch.get_execution_timeline("no-run")
        self.assertEqual(timeline, [])

    def test_get_execution_timeline(self):
        run_id = "timeline-run"
        store.create_pipeline_run(run_id, self.project_id)
        store.create_pipeline_stage(run_id, "brief_scope", "Brief & Scope")
        store.update_pipeline_stage(run_id, "brief_scope", status="completed",
                                    execution_time_ms=100)
        timeline = orch.get_execution_timeline(run_id)
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["stage_id"], "brief_scope")
        self.assertEqual(timeline[0]["execution_time_ms"], 100)

    def test_get_pipeline_logs(self):
        run_id = "log-run"
        store.create_pipeline_run(run_id, self.project_id)
        store.add_pipeline_log(run_id, "msg1", stage_id="brief_scope")
        store.add_pipeline_log(run_id, "msg2", stage_id="background_research")
        all_logs = orch.get_pipeline_logs(run_id)
        self.assertGreaterEqual(len(all_logs), 2)
        filtered = orch.get_pipeline_logs(run_id, "brief_scope")
        self.assertGreaterEqual(len(filtered), 1)

    def test_get_performance_metrics(self):
        perf = orch.get_performance_metrics(self.project_id)
        self.assertIn("total_runs", perf)

    def test_get_cache_metrics(self):
        metrics = orch.get_cache_metrics(self.project_id)
        self.assertIn("total_entries", metrics)
        self.assertIn("entries", metrics)
        self.assertIn("stages_cached", metrics)
        self.assertEqual(metrics["total_entries"], 0)


class ExecutionEngineTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orch_exec_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test.db")
        config.DATA_DIR = self._tmpdir
        store.init_intelligence_db()
        self.project_id = _make_project()

    def test_single_stage_brief_scope(self):
        result = orch.start_pipeline(
            self.project_id, mode="single", single_stage="brief_scope")
        self.assertIn("run_id", result)
        self.assertIn(result.get("status", ""), ("completed", "cached"))

    def test_single_stage_creates_run_record(self):
        result = orch.start_pipeline(
            self.project_id, mode="single", single_stage="brief_scope")
        run = store.get_pipeline_run(result["run_id"])
        self.assertIsNotNone(run)
        self.assertEqual(run["execution_mode"], "single")

    def test_single_stage_creates_log_entries(self):
        result = orch.start_pipeline(
            self.project_id, mode="single", single_stage="brief_scope")
        logs = store.get_pipeline_logs(result["run_id"])
        self.assertGreater(len(logs), 0)

    def test_run_single_stage_convenience(self):
        result = orch.run_single_stage(self.project_id, "brief_scope")
        self.assertIn("run_id", result)

    def test_run_from_stage_convenience(self):
        result = orch.run_from_stage(self.project_id, "brief_scope")
        self.assertIn("run_id", result)


class StageExecutorIntegrationTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="orch_int_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test.db")
        config.DATA_DIR = self._tmpdir
        store.init_intelligence_db()
        self.project_id = _make_project()

    def test_all_executors_registered(self):
        for sid in orch.STAGES:
            self.assertIn(sid, orch.STAGE_EXECUTORS,
                          f"Missing executor for {sid}")

    def test_exec_brief_scope(self):
        run_id = "exec-test-run"
        store.create_pipeline_run(run_id, self.project_id)
        result = orch._exec_brief_scope(self.project_id, run_id)
        self.assertEqual(result["status"], "completed")

    def test_exec_brief_scope_missing_project(self):
        run_id = "exec-test-miss"
        store.create_pipeline_run(run_id, 99999)
        with self.assertRaises(RuntimeError):
            orch._exec_brief_scope(99999, run_id)

    def test_exec_si_retrieval_empty(self):
        run_id = "exec-test-si"
        store.create_pipeline_run(run_id, self.project_id)
        result = orch._exec_si_retrieval(self.project_id, run_id)
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
