"""Regression tests for project context isolation.

Ensures that:
- Creating a new project returns a unique ID
- Different projects have isolated data (specs, names)
- The projects API returns correct data for each project
- No cross-contamination between projects
- The list endpoint shows all projects
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import intelligence_store as store


def _init_db():
    for attempt in range(5):
        try:
            store.init_intelligence_db()
            return
        except Exception:
            time.sleep(1)
    store.init_intelligence_db()


class TestProjectCreation(unittest.TestCase):
    """Each call to create_project must return a distinct project ID."""

    @classmethod
    def setUpClass(cls):
        _init_db()

    def test_create_returns_int_id(self):
        pid = store.create_project("Test Project A", {"brief": "hello"})
        self.assertIsInstance(pid, int)
        self.assertGreater(pid, 0)

    def test_two_projects_get_different_ids(self):
        pid1 = store.create_project("Project Alpha", {"key": "alpha"})
        pid2 = store.create_project("Project Beta", {"key": "beta"})
        self.assertNotEqual(pid1, pid2)

    def test_same_name_creates_separate_projects(self):
        pid1 = store.create_project("Duplicate Name", {"version": 1})
        pid2 = store.create_project("Duplicate Name", {"version": 2})
        self.assertNotEqual(pid1, pid2)


class TestProjectIsolation(unittest.TestCase):
    """Data for one project must not leak into another."""

    @classmethod
    def setUpClass(cls):
        _init_db()
        cls.pid_a = store.create_project("Mrs. T's Moms Research", {
            "commissioning_brand": {"name": "Mrs. T's"},
            "geography": "United States",
        })
        cls.pid_b = store.create_project("Empower Campaign", {
            "commissioning_brand": {"name": "Empower"},
            "geography": "Global",
        })

    def test_project_a_has_correct_name(self):
        p = store.get_project(self.pid_a)
        self.assertEqual(p["project_name"], "Mrs. T's Moms Research")

    def test_project_b_has_correct_name(self):
        p = store.get_project(self.pid_b)
        self.assertEqual(p["project_name"], "Empower Campaign")

    def test_project_a_spec_isolated(self):
        p = store.get_project(self.pid_a)
        self.assertEqual(p["spec"]["commissioning_brand"]["name"], "Mrs. T's")

    def test_project_b_spec_isolated(self):
        p = store.get_project(self.pid_b)
        self.assertEqual(p["spec"]["commissioning_brand"]["name"], "Empower")

    def test_project_a_does_not_contain_b_data(self):
        p = store.get_project(self.pid_a)
        self.assertNotEqual(p["spec"].get("geography"), "Global")

    def test_project_b_does_not_contain_a_data(self):
        p = store.get_project(self.pid_b)
        self.assertNotEqual(p["spec"].get("geography"), "United States")

    def test_get_nonexistent_project_returns_none(self):
        p = store.get_project(999999)
        self.assertIsNone(p)


class TestProjectList(unittest.TestCase):
    """list_projects must return all created projects."""

    @classmethod
    def setUpClass(cls):
        _init_db()
        cls.pid1 = store.create_project("List Test 1", {})
        cls.pid2 = store.create_project("List Test 2", {})

    def test_list_contains_both_projects(self):
        projects = store.list_projects()
        ids = [p["id"] for p in projects]
        self.assertIn(self.pid1, ids)
        self.assertIn(self.pid2, ids)

    def test_list_returns_dicts_with_required_fields(self):
        projects = store.list_projects()
        for p in projects:
            self.assertIn("id", p)
            self.assertIn("project_name", p)
            self.assertIn("created_at", p)
            self.assertIn("updated_at", p)


class TestProjectAPIEndpoints(unittest.TestCase):
    """Test the FastAPI project endpoints via TestClient."""

    @classmethod
    def setUpClass(cls):
        _init_db()
        from fastapi.testclient import TestClient
        from agent.app.intelligence_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)

    def test_create_project_endpoint(self):
        r = self.client.post("/api/intel/projects", json={
            "project_name": "API Test Project",
            "spec": {"brief": "test brief"},
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("id", data)
        self.assertEqual(data["project_name"], "API Test Project")

    def test_get_project_endpoint(self):
        r1 = self.client.post("/api/intel/projects", json={
            "project_name": "Get Test",
            "spec": {"x": 1},
        })
        pid = r1.json()["id"]
        r2 = self.client.get(f"/api/intel/projects/{pid}")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["project_name"], "Get Test")
        self.assertEqual(r2.json()["spec"]["x"], 1)

    def test_get_nonexistent_returns_404(self):
        r = self.client.get("/api/intel/projects/999999")
        self.assertEqual(r.status_code, 404)

    def test_create_two_projects_different_ids(self):
        r1 = self.client.post("/api/intel/projects", json={
            "project_name": "First",
            "spec": {},
        })
        r2 = self.client.post("/api/intel/projects", json={
            "project_name": "Second",
            "spec": {},
        })
        self.assertNotEqual(r1.json()["id"], r2.json()["id"])

    def test_project_spec_roundtrip(self):
        spec = {
            "commissioning_brand": {"name": "TestBrand"},
            "geography": "UK",
            "research_type": "Brand Tracking",
        }
        r1 = self.client.post("/api/intel/projects", json={
            "project_name": "Roundtrip Test",
            "spec": spec,
        })
        pid = r1.json()["id"]
        r2 = self.client.get(f"/api/intel/projects/{pid}")
        returned_spec = r2.json()["spec"]
        self.assertEqual(returned_spec["commissioning_brand"]["name"], "TestBrand")
        self.assertEqual(returned_spec["geography"], "UK")
        self.assertEqual(returned_spec["research_type"], "Brand Tracking")

    def test_new_project_does_not_inherit_old_project_data(self):
        """Regression: creating project B must not return project A's data."""
        r_a = self.client.post("/api/intel/projects", json={
            "project_name": "Mrs. T's Moms Research",
            "spec": {"commissioning_brand": {"name": "Mrs. T's"}},
        })
        pid_a = r_a.json()["id"]

        r_b = self.client.post("/api/intel/projects", json={
            "project_name": "Empower Campaign",
            "spec": {"commissioning_brand": {"name": "Empower"}},
        })
        pid_b = r_b.json()["id"]

        proj_b = self.client.get(f"/api/intel/projects/{pid_b}").json()
        self.assertEqual(proj_b["project_name"], "Empower Campaign")
        self.assertNotEqual(proj_b["project_name"], "Mrs. T's Moms Research")
        self.assertEqual(proj_b["spec"]["commissioning_brand"]["name"], "Empower")
        self.assertNotEqual(proj_b["spec"]["commissioning_brand"]["name"], "Mrs. T's")

        proj_a = self.client.get(f"/api/intel/projects/{pid_a}").json()
        self.assertEqual(proj_a["project_name"], "Mrs. T's Moms Research")


class TestStaleProjectContextRegression(unittest.TestCase):
    """Regression suite: simulates the exact bug scenario.

    Scenario: User creates "Mrs. T's Moms Research" (project 1), works on it,
    then creates "Empower" (project 2). Navigating to Brief Analysis for
    project 2 must show "Empower" data, not "Mrs. T's".
    """

    @classmethod
    def setUpClass(cls):
        _init_db()
        from fastapi.testclient import TestClient
        from agent.app.intelligence_api import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)

    def test_sequential_project_creation_isolation(self):
        r1 = self.client.post("/api/intel/projects", json={
            "project_name": "Mrs. T's Moms Research",
            "spec": {
                "commissioning_brand": {"name": "Mrs. T's"},
                "geography": "United States",
                "research_type": "Social Listening",
            },
        })
        pid1 = r1.json()["id"]

        r2 = self.client.post("/api/intel/projects", json={
            "project_name": "Empower",
            "spec": {
                "commissioning_brand": {"name": "Empower"},
                "geography": "Global",
                "research_type": "Brand Tracking",
            },
        })
        pid2 = r2.json()["id"]

        self.assertNotEqual(pid1, pid2)

        proj2 = self.client.get(f"/api/intel/projects/{pid2}").json()
        self.assertEqual(proj2["project_name"], "Empower")
        self.assertEqual(proj2["spec"]["commissioning_brand"]["name"], "Empower")
        self.assertEqual(proj2["spec"]["geography"], "Global")
        self.assertNotIn("Mrs. T", proj2["project_name"])

    def test_old_project_unchanged_after_new_creation(self):
        r1 = self.client.post("/api/intel/projects", json={
            "project_name": "Original Project",
            "spec": {"key": "original_value"},
        })
        pid1 = r1.json()["id"]

        self.client.post("/api/intel/projects", json={
            "project_name": "New Project",
            "spec": {"key": "new_value"},
        })

        proj1 = self.client.get(f"/api/intel/projects/{pid1}").json()
        self.assertEqual(proj1["project_name"], "Original Project")
        self.assertEqual(proj1["spec"]["key"], "original_value")

    def test_project_ids_monotonically_increase(self):
        pids = []
        for i in range(5):
            r = self.client.post("/api/intel/projects", json={
                "project_name": f"Seq Project {i}",
                "spec": {},
            })
            pids.append(r.json()["id"])
        for i in range(1, len(pids)):
            self.assertGreater(pids[i], pids[i - 1])


class TestFrontendContextHookCoverage(unittest.TestCase):
    """Verify that all pages import from project-context (source-level check)."""

    PAGES_DIR = os.path.join(
        os.path.dirname(__file__), "..", "..", "web", "src", "pages"
    )

    PAGES_REQUIRING_PROJECT_ID = [
        "EvidenceLibrary.tsx",
        "InsightsPage.tsx",
        "StorylinePage.tsx",
        "ResearchPlan.tsx",
        "ResearchExecution.tsx",
        "PresentationComposerPage.tsx",
        "PowerPointRendererPage.tsx",
        "WordRendererPage.tsx",
        "PipelineOrchestratorPage.tsx",
        "PublishingGatewayPage.tsx",
    ]

    def test_no_hardcoded_project_id_1(self):
        """No page should contain `const projectId = 1` or `const PROJECT_ID = 1` or `useState(1)` for projectId."""
        for fname in self.PAGES_REQUIRING_PROJECT_ID:
            fpath = os.path.join(self.PAGES_DIR, fname)
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn(
                "const projectId = 1",
                content,
                f"{fname} still has hardcoded projectId = 1",
            )
            self.assertNotIn(
                "const PROJECT_ID = 1",
                content,
                f"{fname} still has hardcoded PROJECT_ID = 1",
            )

    def test_pages_import_project_context(self):
        """Every page that uses projectId must import from project-context."""
        for fname in self.PAGES_REQUIRING_PROJECT_ID:
            fpath = os.path.join(self.PAGES_DIR, fname)
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn(
                "project-context",
                content,
                f"{fname} does not import from project-context",
            )

    def test_brief_analysis_no_hardcoded_mrs_t(self):
        fpath = os.path.join(self.PAGES_DIR, "BriefAnalysis.tsx")
        if not os.path.exists(fpath):
            self.skipTest("BriefAnalysis.tsx not found")
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        hardcoded = content.count('"Mrs. T\'s Moms Research"')
        self.assertEqual(
            hardcoded, 0,
            "BriefAnalysis.tsx still has hardcoded Mrs. T's subtitle",
        )

    def test_brief_scope_review_no_hardcoded_mrs_t(self):
        fpath = os.path.join(self.PAGES_DIR, "BriefScopeReview.tsx")
        if not os.path.exists(fpath):
            self.skipTest("BriefScopeReview.tsx not found")
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        hardcoded = content.count('"Mrs. T\'s Moms Research"')
        self.assertEqual(
            hardcoded, 0,
            "BriefScopeReview.tsx still has hardcoded Mrs. T's subtitle",
        )

    def test_brief_scope_review_fetches_spec_from_api(self):
        """BriefScopeReview must load spec from API, not hardcode DEMO_SPEC."""
        fpath = os.path.join(self.PAGES_DIR, "BriefScopeReview.tsx")
        if not os.path.exists(fpath):
            self.skipTest("BriefScopeReview.tsx not found")
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("intelApi.getProject", content,
            "BriefScopeReview must fetch project spec from the API")
        self.assertIn("useActiveProjectId", content,
            "BriefScopeReview must use activeProjectId to fetch spec")
        self.assertNotIn("const s = DEMO_SPEC", content,
            "BriefScopeReview must not hardcode spec to DEMO_SPEC")

    def test_new_project_calls_create_api(self):
        fpath = os.path.join(self.PAGES_DIR, "NewProject.tsx")
        if not os.path.exists(fpath):
            self.skipTest("NewProject.tsx not found")
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("createProject", content, "NewProject must call createProject API")
        self.assertIn("setActiveProject", content, "NewProject must set active project context")

    def test_app_wraps_with_project_provider(self):
        fpath = os.path.join(self.PAGES_DIR, "..", "App.tsx")
        if not os.path.exists(fpath):
            self.skipTest("App.tsx not found")
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("<ProjectProvider>", content, "App must wrap with ProjectProvider")
        self.assertIn("ProjectDemoSync", content, "App must include ProjectDemoSync")

    def test_demo_state_has_reset_function(self):
        fpath = os.path.join(self.PAGES_DIR, "..", "lib", "demo-state.tsx")
        if not os.path.exists(fpath):
            self.skipTest("demo-state.tsx not found")
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("resetDemoState", content, "DemoState must expose resetDemoState")


if __name__ == "__main__":
    unittest.main()
