"""Tests for intelligence_store: SQLite persistence for the intelligence workflow."""
from __future__ import annotations

import json
import os
import tempfile
import pytest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import intelligence_store as store
from agent.app import config

@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    config.MEMORY_DB_PATH = tmp_path / "test_memory.db"
    store.init_intelligence_db()
    yield


class TestProjects:
    def test_create_and_get_project(self):
        spec = {"commissioning_brand": {"name": "TestBrand"}, "project_name": "Test"}
        pid = store.create_project("TestBrand", spec)
        assert pid > 0
        proj = store.get_project(pid)
        assert proj is not None
        assert proj["project_name"] == "TestBrand"
        assert proj["spec"]["commissioning_brand"]["name"] == "TestBrand"

    def test_get_or_create_project_idempotent(self):
        spec = {"commissioning_brand": {"name": "Brand1"}}
        pid1 = store.get_or_create_project(spec)
        pid2 = store.get_or_create_project(spec)
        assert pid1 == pid2

    def test_get_nonexistent_project(self):
        assert store.get_project(9999) is None


class TestJobs:
    def test_create_and_get_job(self):
        pid = store.create_project("P", {"project_name": "P"})
        store.create_job("job-1", pid, "background_research")
        job = store.get_job("job-1")
        assert job is not None
        assert job["status"] == "pending"
        assert job["job_type"] == "background_research"

    def test_update_job_status(self):
        pid = store.create_project("P", {})
        store.create_job("job-2", pid, "search_strategy")
        store.update_job("job-2", status="running", progress_pct=50, progress_message="Halfway")
        job = store.get_job("job-2")
        assert job["status"] == "running"
        assert job["progress_pct"] == 50
        assert job["started_at"] is not None

    def test_update_job_completed(self):
        pid = store.create_project("P", {})
        store.create_job("job-3", pid, "test")
        store.update_job("job-3", status="completed", result={"key": "value"})
        job = store.get_job("job-3")
        assert job["status"] == "completed"
        assert job["finished_at"] is not None
        assert job["result"]["key"] == "value"

    def test_list_jobs(self):
        pid = store.create_project("P", {})
        store.create_job("j1", pid, "research")
        store.create_job("j2", pid, "strategy")
        store.create_job("j3", pid, "research")
        all_jobs = store.list_jobs(pid)
        assert len(all_jobs) == 3
        research_jobs = store.list_jobs(pid, "research")
        assert len(research_jobs) == 2

    def test_get_nonexistent_job(self):
        assert store.get_job("nonexistent") is None


class TestBackgroundResearch:
    def test_save_and_get_research(self):
        pid = store.create_project("P", {})
        research = {"status": "completed", "web_search_executed": True, "news_items": []}
        rid = store.save_background_research(pid, research)
        assert rid > 0
        latest = store.get_latest_research(pid)
        assert latest is not None
        assert latest["version"] == 1
        assert latest["research"]["status"] == "completed"

    def test_versioning(self):
        pid = store.create_project("P", {})
        store.save_background_research(pid, {"v": 1})
        store.save_background_research(pid, {"v": 2})
        latest = store.get_latest_research(pid)
        assert latest["version"] == 2
        assert latest["research"]["v"] == 2

    def test_approve_research(self):
        pid = store.create_project("P", {})
        rid = store.save_background_research(pid, {"data": True})
        store.approve_research(rid, "test_reviewer")
        latest = store.get_latest_research(pid)
        assert latest["approval_status"] == "approved"
        assert latest["approved_by"] == "test_reviewer"

    def test_reject_research(self):
        pid = store.create_project("P", {})
        rid = store.save_background_research(pid, {"data": True})
        store.reject_research(rid, "needs more sources")
        latest = store.get_latest_research(pid)
        assert latest["approval_status"] == "revision_requested"

    def test_no_research(self):
        pid = store.create_project("P", {})
        assert store.get_latest_research(pid) is None


class TestSearchStrategies:
    def test_save_and_get_strategy(self):
        pid = store.create_project("P", {})
        strategy = {"core_queries": [{"type": "balanced", "query": "test"}]}
        sid = store.save_search_strategy(pid, strategy)
        assert sid > 0
        latest = store.get_latest_strategy(pid)
        assert latest is not None
        assert latest["version"] == 1
        assert latest["strategy"]["core_queries"][0]["type"] == "balanced"

    def test_approve_strategy(self):
        pid = store.create_project("P", {})
        sid = store.save_search_strategy(pid, {"data": True})
        store.approve_strategy(sid, "analyst")
        latest = store.get_latest_strategy(pid)
        assert latest["approval_status"] == "approved"

    def test_update_strategy_query(self):
        pid = store.create_project("P", {})
        strategy = {"core_queries": [{"type": "balanced", "query": "original"}]}
        sid = store.save_search_strategy(pid, strategy)
        vid = store.update_strategy_query(sid, "balanced", "updated query")
        assert vid > 0
        latest = store.get_latest_strategy(pid)
        assert latest["strategy"]["core_queries"][0]["query"] == "updated query"

    def test_get_query_versions(self):
        pid = store.create_project("P", {})
        sid = store.save_search_strategy(pid, {"core_queries": [{"type": "broad", "query": "v1"}]})
        store.update_strategy_query(sid, "broad", "v2")
        store.update_strategy_query(sid, "broad", "v3")
        versions = store.get_query_versions(sid)
        assert len(versions) == 2


class TestNewsApprovals:
    def test_update_and_get_approvals(self):
        pid = store.create_project("P", {})
        rid = store.save_background_research(pid, {"news_items": [{}, {}, {}]})
        store.update_news_approval(rid, 0, "approved", "good source")
        store.update_news_approval(rid, 1, "rejected", "irrelevant")
        approvals = store.get_news_approvals(rid)
        assert len(approvals) == 2
        assert approvals[0]["status"] == "approved"
        assert approvals[1]["status"] == "rejected"

    def test_update_existing_approval(self):
        pid = store.create_project("P", {})
        rid = store.save_background_research(pid, {})
        store.update_news_approval(rid, 0, "approved")
        store.update_news_approval(rid, 0, "rejected", "changed mind")
        approvals = store.get_news_approvals(rid)
        assert len(approvals) == 1
        assert approvals[0]["status"] == "rejected"


class TestSampleEvaluations:
    def test_save_and_get_evaluation(self):
        pid = store.create_project("P", {})
        sid = store.save_search_strategy(pid, {})
        eid = store.save_sample_evaluation(pid, sid, "test.csv", "/tmp/test.csv")
        latest = store.get_latest_evaluation(pid)
        assert latest is not None
        assert latest["file_name"] == "test.csv"
        assert latest["status"] == "pending"

    def test_update_evaluation(self):
        pid = store.create_project("P", {})
        sid = store.save_search_strategy(pid, {})
        eid = store.save_sample_evaluation(pid, sid, "test.csv", "/tmp/test.csv")
        store.update_evaluation(eid, {"precision": 0.85, "total_records": 100})
        latest = store.get_latest_evaluation(pid)
        assert latest["status"] == "completed"
        assert latest["evaluation"]["precision"] == 0.85
