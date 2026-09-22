"""Tests for Publishing & Quality Gateway: validation, comparison, packaging,
versioning, approval workflow, publishing, audit trail, downloads, store CRUD,
and API endpoints."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import config
from agent.app import intelligence_store as store
from agent.app import publishing_gateway as pub


def _init_db():
    for attempt in range(5):
        try:
            store.init_intelligence_db()
            return
        except Exception:
            time.sleep(1)
    store.init_intelligence_db()


def _make_project(name="PubGateway Test Project"):
    spec = {
        "project_title": name,
        "commissioning_brand": {"name": "Test Brand"},
        "research_subject": {"name": "Test Subject"},
        "research_questions": [],
    }
    return store.create_project(name, spec)


def _make_presentation(project_id, title="Test Presentation", status="approved"):
    return store.create_pc_presentation(project_id, storyline_id=0, title=title, status=status)


def _make_slide(pres_id, slide_number, purpose="key_finding", title="Test Slide",
                narrative="Test narrative content.", status="approved",
                evidence_ids=None, content_blocks=None):
    return store.create_pc_slide(
        pres_id, slide_number=slide_number, slide_purpose=purpose,
        title=title, narrative=narrative, status=status,
        evidence_ids_json=json.dumps(evidence_ids or []),
        content_blocks_json=json.dumps(content_blocks or []),
    )


# ── Validation Tests ──────────────────────────────────────────────────

class ValidationTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_missing_presentation(self):
        pid = _make_project()
        result = pub.run_validation(pid, 99999)
        self.assertIn("error", result)

    def test_presentation_project_mismatch(self):
        pid1 = _make_project("Project A")
        pid2 = _make_project("Project B")
        pres = _make_presentation(pid1)
        result = pub.run_validation(pid2, pres)
        self.assertIn("error", result)

    def test_valid_complete_presentation(self):
        pid = _make_project()
        pres = _make_presentation(pid, title="Full Report")
        _make_slide(pres, 1, "cover", "Cover Slide")
        _make_slide(pres, 2, "executive_summary", "Executive Summary")
        _make_slide(pres, 3, "key_finding", "Finding 1", evidence_ids=[1, 2])
        _make_slide(pres, 4, "recommendation", "Rec 1", evidence_ids=[3])
        result = pub.run_validation(pid, pres)
        self.assertIn("readiness_score", result)
        self.assertIn("scores", result)
        self.assertIsInstance(result["issues"], list)
        self.assertIn("validation_id", result)

    def test_missing_cover_slide_is_critical(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "key_finding", "Finding Only")
        result = pub.run_validation(pid, pres)
        critical = [i for i in result["issues"] if i["severity"] == "critical"]
        self.assertTrue(any("cover" in i["description"].lower() for i in critical))

    def test_no_slides_is_critical(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        result = pub.run_validation(pid, pres)
        critical = [i for i in result["issues"] if i["severity"] == "critical"]
        self.assertTrue(len(critical) > 0)

    def test_missing_evidence_flagged(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "cover", "Cover")
        _make_slide(pres, 2, "key_finding", "Finding Without Evidence")
        result = pub.run_validation(pid, pres)
        evidence_issues = [i for i in result["issues"]
                          if "evidence" in i["description"].lower()]
        self.assertTrue(len(evidence_issues) > 0)

    def test_readiness_class_blocked_on_critical(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        result = pub.run_validation(pid, pres)
        self.assertEqual(result["readiness_class"], "blocked")

    def test_readiness_dimensions(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "cover", "Cover")
        _make_slide(pres, 2, "key_finding", "Finding", evidence_ids=[1])
        result = pub.run_validation(pid, pres)
        for dim in pub.VALIDATION_DIMENSIONS:
            self.assertIn(dim, result["scores"])
            self.assertGreaterEqual(result["scores"][dim], 0.0)
            self.assertLessEqual(result["scores"][dim], 1.0)

    def test_rejected_slides_excluded(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "cover", "Cover")
        _make_slide(pres, 2, "key_finding", "Rejected", status="rejected")
        _make_slide(pres, 3, "key_finding", "Active", evidence_ids=[1])
        result = pub.run_validation(pid, pres)
        self.assertIn("validation_id", result)

    def test_duplicate_title_flagged(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "cover", "Cover")
        _make_slide(pres, 2, "key_finding", "Same Title", evidence_ids=[1])
        _make_slide(pres, 3, "trend", "Same Title", evidence_ids=[2])
        result = pub.run_validation(pid, pres)
        dup_issues = [i for i in result["issues"] if "duplicate" in i["description"].lower()]
        self.assertTrue(len(dup_issues) > 0)

    def test_no_title_presentation_flagged(self):
        pid = _make_project()
        pres = _make_presentation(pid, title="Untitled Presentation")
        _make_slide(pres, 1, "cover", "Cover")
        result = pub.run_validation(pid, pres)
        brand_issues = [i for i in result["issues"] if "title" in i["description"].lower()]
        self.assertTrue(len(brand_issues) > 0)


# ── Comparison Tests ──────────────────────────────────────────────────

class ComparisonTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_compare_missing_presentation(self):
        pid = _make_project()
        result = pub.compare_outputs(pid, 99999)
        self.assertIn("error", result)

    def test_compare_identical_outputs(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "cover", "Cover")
        _make_slide(pres, 2, "key_finding", "Finding", evidence_ids=[1])
        result = pub.compare_outputs(pid, pres)
        self.assertIn("diff_id", result)
        self.assertIn("match_pct", result)
        self.assertIn("differences", result)

    def test_compare_produces_diff_report(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "cover", "Cover")
        result = pub.compare_outputs(pid, pres)
        stored = store.get_latest_diff_report(pres)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["id"], result["diff_id"])


# ── Version Tests ─────────────────────────────────────────────────────

class VersionTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_create_first_version(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        result = pub.create_version(pid, pres)
        self.assertEqual(result["version_label"], "v1.0.0")
        self.assertEqual(result["major"], 1)
        self.assertEqual(result["minor"], 0)

    def test_create_increments_minor(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.create_version(pid, pres)
        result = pub.create_version(pid, pres)
        self.assertEqual(result["version_label"], "v1.1.0")

    def test_list_versions(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.create_version(pid, pres)
        pub.create_version(pid, pres)
        versions = pub.list_versions(pres)
        self.assertEqual(len(versions), 2)

    def test_version_not_found(self):
        pid = _make_project()
        result = pub.create_version(pid, 99999)
        self.assertIn("error", result)


# ── Approval Workflow Tests ───────────────────────────────────────────

class ApprovalWorkflowTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_submit_for_review_creates_version(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        result = pub.submit_for_review(pid, pres)
        self.assertEqual(result["status"], "submitted")
        self.assertIn("version_id", result)

    def test_approve_deliverable(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.submit_for_review(pid, pres)
        result = pub.approve_deliverable(pid, pres)
        self.assertEqual(result["status"], "approved")

    def test_reject_deliverable(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.submit_for_review(pid, pres)
        result = pub.reject_deliverable(pid, pres, notes="Needs work")
        self.assertEqual(result["status"], "rejected")

    def test_request_revision(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.submit_for_review(pid, pres)
        result = pub.request_revision(pid, pres, notes="Fix slides 3-5")
        self.assertEqual(result["status"], "revision_requested")

    def test_approve_no_version_error(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        result = pub.approve_deliverable(pid, pres)
        self.assertIn("error", result)

    def test_reject_no_version_error(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        result = pub.reject_deliverable(pid, pres)
        self.assertIn("error", result)

    def test_full_workflow_submit_approve_publish(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "cover", "Cover")
        pub.submit_for_review(pid, pres)
        pub.approve_deliverable(pid, pres)
        result = pub.publish_deliverable(pid, pres)
        if "error" in result:
            self.assertIn("render", result["error"].lower())
        else:
            self.assertEqual(result["status"], "published")

    def test_publish_without_approval_error(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.submit_for_review(pid, pres)
        result = pub.publish_deliverable(pid, pres)
        self.assertIn("error", result)

    def test_archive(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.submit_for_review(pid, pres)
        result = pub.archive_deliverable(pid, pres)
        self.assertEqual(result["status"], "archived")

    def test_approval_history_tracked(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.submit_for_review(pid, pres)
        pub.approve_deliverable(pid, pres)
        approvals = store.list_pub_approvals(pres)
        self.assertEqual(len(approvals), 2)
        self.assertEqual(approvals[0]["action"], "approve")
        self.assertEqual(approvals[1]["action"], "submit_for_review")


# ── Package Builder Tests ─────────────────────────────────────────────

class PackageBuilderTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_package_no_renders_error(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        result = pub.build_package(pid, pres)
        self.assertIn("error", result)

    def test_package_missing_presentation_error(self):
        pid = _make_project()
        result = pub.build_package(pid, 99999)
        self.assertIn("error", result)


# ── Readiness Summary Tests ──────────────────────────────────────────

class ReadinessSummaryTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_empty_readiness(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        summary = pub.get_readiness_summary(pid, pres)
        self.assertEqual(summary["readiness_score"], 0)
        self.assertEqual(summary["readiness_class"], "draft")

    def test_readiness_after_validation(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "cover", "Cover")
        _make_slide(pres, 2, "key_finding", "Finding", evidence_ids=[1])
        pub.run_validation(pid, pres)
        summary = pub.get_readiness_summary(pid, pres)
        self.assertGreater(summary["readiness_score"], 0)
        self.assertIsNotNone(summary["latest_validation_id"])

    def test_readiness_with_version(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.create_version(pid, pres)
        summary = pub.get_readiness_summary(pid, pres)
        self.assertIsNotNone(summary["latest_version"])


# ── Audit Trail Tests ─────────────────────────────────────────────────

class AuditTrailTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_validation_creates_audit(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "cover", "Cover")
        pub.run_validation(pid, pres)
        audit = pub.get_audit_trail(pid)
        val_entries = [a for a in audit if a["action"] == "run_validation"]
        self.assertEqual(len(val_entries), 1)

    def test_approval_creates_audit(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.submit_for_review(pid, pres)
        pub.approve_deliverable(pid, pres)
        audit = pub.get_audit_trail(pid)
        approval_entries = [a for a in audit if a["entity_type"] == "approval"]
        self.assertGreaterEqual(len(approval_entries), 2)

    def test_version_creates_audit(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pub.create_version(pid, pres)
        audit = pub.get_audit_trail(pid)
        version_entries = [a for a in audit if a["entity_type"] == "version"]
        self.assertEqual(len(version_entries), 1)

    def test_compare_creates_audit(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        _make_slide(pres, 1, "cover", "Cover")
        pub.compare_outputs(pid, pres)
        audit = pub.get_audit_trail(pid)
        diff_entries = [a for a in audit if a["entity_type"] == "diff_report"]
        self.assertEqual(len(diff_entries), 1)


# ── Store CRUD Tests ──────────────────────────────────────────────────

class StoreValidationTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_create_and_get_validation(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        vid = store.create_pub_validation(pid, pres, status="completed",
                                          readiness_score=0.85,
                                          scores={"narrative": 0.9},
                                          issues=[{"desc": "test"}])
        fetched = store.get_pub_validation(vid)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["readiness_score"], 0.85)
        self.assertIsInstance(fetched["scores_json"], dict)

    def test_update_validation(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        vid = store.create_pub_validation(pid, pres)
        store.update_pub_validation(vid, status="completed", readiness_score=0.7)
        fetched = store.get_pub_validation(vid)
        self.assertEqual(fetched["status"], "completed")
        self.assertEqual(fetched["readiness_score"], 0.7)

    def test_list_validations(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        store.create_pub_validation(pid, pres)
        store.create_pub_validation(pid, pres)
        result = store.list_pub_validations(pres)
        self.assertEqual(len(result), 2)

    def test_latest_validation(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        store.create_pub_validation(pid, pres, readiness_score=0.5)
        store.create_pub_validation(pid, pres, readiness_score=0.8)
        latest = store.get_latest_pub_validation(pres)
        self.assertEqual(latest["readiness_score"], 0.8)


class StoreVersionTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_create_and_get_version(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        vid = store.create_pub_version(pid, pres, major=1, minor=0,
                                       version_label="v1.0.0")
        fetched = store.get_pub_version(vid)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["version_label"], "v1.0.0")

    def test_list_versions(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        store.create_pub_version(pid, pres)
        store.create_pub_version(pid, pres)
        result = store.list_pub_versions(pres)
        self.assertEqual(len(result), 2)


class StorePackageTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_create_and_get_package(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        pkg_id = store.create_pub_package(pid, pres, status="completed",
                                          manifest={"files": ["a.pptx"]},
                                          contents=[{"type": "pptx"}])
        fetched = store.get_pub_package(pkg_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["status"], "completed")
        self.assertIsInstance(fetched["manifest_json"], dict)


class StoreApprovalTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_create_and_list_approvals(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        store.create_pub_approval(pid, pres, "submit_for_review", "submitted")
        store.create_pub_approval(pid, pres, "approve", "approved")
        result = store.list_pub_approvals(pres)
        self.assertEqual(len(result), 2)


class StoreAuditTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_add_and_list_audit(self):
        pid = _make_project()
        store.add_pub_audit(pid, "validation", "run_validation",
                           details={"score": 0.85})
        result = store.list_pub_audit(pid)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["action"], "run_validation")
        self.assertIsInstance(result[0]["details_json"], dict)


class StoreDownloadTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_create_and_list_downloads(self):
        pid = _make_project()
        store.create_pub_download(pid, "pptx", "/tmp/test.pptx",
                                  file_size_bytes=1024)
        result = store.list_pub_downloads(pid)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["file_type"], "pptx")


class StoreStatsTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_stats_empty(self):
        pid = _make_project()
        stats = store.get_pub_stats(pid)
        self.assertEqual(stats["validations"], 0)
        self.assertEqual(stats["packages"], 0)

    def test_stats_counts(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        store.create_pub_validation(pid, pres)
        store.create_pub_package(pid, pres)
        store.create_pub_approval(pid, pres, "publish", "published")
        stats = store.get_pub_stats(pid)
        self.assertEqual(stats["validations"], 1)
        self.assertEqual(stats["packages"], 1)
        self.assertEqual(stats["publications"], 1)


class StoreDiffReportTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_create_and_get_diff_report(self):
        pid = _make_project()
        pres = _make_presentation(pid)
        did = store.create_pub_diff_report(0, pid, pres, status="completed",
                                           match_pct=0.95,
                                           differences=[{"field": "titles"}],
                                           summary={"total": 1})
        fetched = store.get_pub_diff_report(did)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["match_pct"], 0.95)
        self.assertIsInstance(fetched["differences_json"], list)


class StoreListProjectsTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_list_projects(self):
        _make_project("Project A")
        _make_project("Project B")
        projects = store.list_projects()
        self.assertGreaterEqual(len(projects), 2)
        names = [p["project_name"] for p in projects]
        self.assertIn("Project A", names)
        self.assertIn("Project B", names)


# ── Constants Tests ───────────────────────────────────────────────────

class ConstantsTest(unittest.TestCase):
    def test_valid_actions(self):
        self.assertEqual(len(pub.VALID_APPROVAL_ACTIONS), 6)
        self.assertIn("publish", pub.VALID_APPROVAL_ACTIONS)

    def test_readiness_classes(self):
        self.assertEqual(len(pub.READINESS_CLASSES), 4)
        self.assertIn("client_ready", pub.READINESS_CLASSES)

    def test_issue_severities(self):
        self.assertEqual(len(pub.ISSUE_SEVERITIES), 4)
        self.assertIn("critical", pub.ISSUE_SEVERITIES)

    def test_validation_dimensions(self):
        self.assertEqual(len(pub.VALIDATION_DIMENSIONS), 7)


# ── Helper Function Tests ─────────────────────────────────────────────

class HelperFunctionTest(unittest.TestCase):
    def test_compute_readiness_blocked(self):
        scores = {"narrative": 1.0, "evidence": 1.0, "design": 1.0,
                  "branding": 1.0, "completeness": 1.0, "rendering": 1.0,
                  "consistency": 1.0}
        issues = [{"severity": "critical", "description": "test"}]
        overall, cls = pub._compute_readiness(scores, issues)
        self.assertEqual(cls, "blocked")

    def test_compute_readiness_client_ready(self):
        scores = {"narrative": 0.9, "evidence": 0.9, "design": 0.9,
                  "branding": 0.9, "completeness": 0.9, "rendering": 0.9,
                  "consistency": 0.9}
        overall, cls = pub._compute_readiness(scores, [])
        self.assertEqual(cls, "client_ready")
        self.assertGreater(overall, 0.8)

    def test_compute_readiness_draft(self):
        scores = {"narrative": 0.2, "evidence": 0.3, "design": 0.2,
                  "branding": 0.4, "completeness": 0.3, "rendering": 0.2,
                  "consistency": 0.3}
        overall, cls = pub._compute_readiness(scores, [])
        self.assertEqual(cls, "draft")

    def test_compute_dimension_score_no_issues(self):
        score = pub._compute_dimension_score([], "narrative")
        self.assertEqual(score, 1.0)

    def test_compute_dimension_score_with_critical(self):
        issues = [{"description": "Missing narrative", "severity": "critical"}]
        score = pub._compute_dimension_score(issues, "narrative")
        self.assertLess(score, 1.0)

    def test_classify_dimension(self):
        self.assertEqual(pub._classify_dimension({"description": "Missing narrative"}), "narrative")
        self.assertEqual(pub._classify_dimension({"description": "No evidence"}), "evidence")
        self.assertEqual(pub._classify_dimension({"description": "No chart visual"}), "design")

    def test_compare_lists_identical(self):
        diffs = pub._compare_lists("titles", ["A", "B"], ["A", "B"])
        self.assertEqual(len(diffs), 0)

    def test_compare_lists_different(self):
        diffs = pub._compare_lists("titles", ["A", "B"], ["A", "C"])
        self.assertEqual(len(diffs), 2)


# ── Download Manager Tests ────────────────────────────────────────────

class DownloadManagerTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_download_path_no_package(self):
        path = pub.get_download_path(99999)
        self.assertIsNone(path)

    def test_pptx_download_no_render(self):
        path = pub.get_pptx_download_path(99999)
        self.assertIsNone(path)

    def test_word_download_no_render(self):
        path = pub.get_word_download_path(99999)
        self.assertIsNone(path)

    def test_record_download(self):
        pid = _make_project()
        tmp = tempfile.NamedTemporaryFile(suffix=".pptx", delete=False)
        tmp.write(b"test")
        tmp.close()
        dl_id = pub.record_download(pid, "pptx", tmp.name)
        self.assertIsInstance(dl_id, int)
        downloads = store.list_pub_downloads(pid)
        self.assertEqual(len(downloads), 1)
        os.unlink(tmp.name)


# ── API Endpoint Tests ────────────────────────────────────────────────

class APIEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _init_db()
        from agent.app.intelligence_api import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)
        cls.project_id = _make_project("API Test")
        cls.pres_id = _make_presentation(cls.project_id, "API Pres")
        _make_slide(cls.pres_id, 1, "cover", "Cover")
        _make_slide(cls.pres_id, 2, "key_finding", "Finding", evidence_ids=[1])

    def test_list_projects(self):
        r = self.client.get("/api/intel/projects")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_validate_endpoint(self):
        r = self.client.post("/api/intel/publishing/validate",
                            json={"project_id": self.project_id,
                                  "presentation_id": self.pres_id})
        self.assertEqual(r.status_code, 200)
        self.assertIn("readiness_score", r.json())

    def test_compare_endpoint(self):
        r = self.client.post("/api/intel/publishing/compare",
                            json={"project_id": self.project_id,
                                  "presentation_id": self.pres_id})
        self.assertEqual(r.status_code, 200)
        self.assertIn("match_pct", r.json())

    def test_version_endpoint(self):
        r = self.client.post("/api/intel/publishing/version",
                            json={"project_id": self.project_id,
                                  "presentation_id": self.pres_id})
        self.assertEqual(r.status_code, 200)
        self.assertIn("version_label", r.json())

    def test_submit_endpoint(self):
        r = self.client.post("/api/intel/publishing/submit",
                            json={"project_id": self.project_id,
                                  "presentation_id": self.pres_id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "submitted")

    def test_approve_endpoint(self):
        self.client.post("/api/intel/publishing/submit",
                        json={"project_id": self.project_id,
                              "presentation_id": self.pres_id})
        r = self.client.post("/api/intel/publishing/approve",
                            json={"project_id": self.project_id,
                                  "presentation_id": self.pres_id})
        self.assertIn(r.status_code, (200, 400))

    def test_readiness_endpoint(self):
        r = self.client.get(f"/api/intel/publishing/readiness/{self.project_id}/{self.pres_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("readiness_score", r.json())

    def test_versions_endpoint(self):
        r = self.client.get(f"/api/intel/publishing/versions/{self.pres_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_audit_endpoint(self):
        r = self.client.get(f"/api/intel/publishing/audit/{self.project_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_approvals_endpoint(self):
        r = self.client.get(f"/api/intel/publishing/approvals/{self.pres_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_validations_list_endpoint(self):
        r = self.client.get(f"/api/intel/publishing/validations/{self.pres_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_packages_endpoint(self):
        r = self.client.get(f"/api/intel/publishing/packages/{self.pres_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_stats_endpoint(self):
        r = self.client.get(f"/api/intel/publishing/stats/{self.project_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("validations", r.json())

    def test_downloads_endpoint(self):
        r = self.client.get(f"/api/intel/publishing/downloads/{self.project_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_diff_not_found(self):
        r = self.client.get(f"/api/intel/publishing/diff/99999")
        self.assertEqual(r.status_code, 404)

    def test_package_not_found(self):
        r = self.client.get(f"/api/intel/publishing/package/99999")
        self.assertEqual(r.status_code, 404)

    def test_validation_detail_not_found(self):
        r = self.client.get(f"/api/intel/publishing/validation/99999")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
