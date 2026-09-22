"""Tests for Word Report Renderer: validation, theme resolution, document
generation, section rendering, job/document/metric/history store functions,
API endpoints, and edge cases."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import config
from agent.app import intelligence_store as store
from agent.app import word_renderer as wr


def _init_db():
    import time
    for attempt in range(5):
        try:
            _init_db()
            return
        except Exception:
            time.sleep(1)
    store.init_intelligence_db()


def _make_project(name="Word Renderer Test Project"):
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
                narrative="Test narrative content.", status="approved"):
    return store.create_pc_slide(
        pres_id, slide_number=slide_number, slide_purpose=purpose,
        title=title, narrative=narrative, status=status,
    )


class ValidationTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_missing_presentation(self):
        result = wr.validate_for_render(99999)
        self.assertFalse(result["valid"])
        self.assertTrue(any("not found" in i.lower() for i in result["issues"]))

    def test_valid_presentation_with_slides(self):
        pid = _make_project()
        pres_id = _make_presentation(pid)
        _make_slide(pres_id, 1, purpose="cover", title="Cover")
        _make_slide(pres_id, 2, purpose="key_finding", title="Finding 1")
        result = wr.validate_for_render(pres_id)
        self.assertTrue(result["valid"])
        self.assertEqual(result["issues"], [])

    def test_no_slides_fails(self):
        pid = _make_project("No Slides Project")
        pres_id = _make_presentation(pid, "Empty")
        result = wr.validate_for_render(pres_id)
        self.assertFalse(result["valid"])
        self.assertTrue(any("no slides" in i.lower() for i in result["issues"]))

    def test_no_cover_warning(self):
        pid = _make_project("No Cover")
        pres_id = _make_presentation(pid, "No Cover")
        _make_slide(pres_id, 1, purpose="key_finding")
        result = wr.validate_for_render(pres_id)
        self.assertTrue(result["valid"])
        self.assertTrue(any("cover" in w.lower() for w in result["warnings"]))

    def test_no_conclusion_warning(self):
        pid = _make_project("No Conclusion")
        pres_id = _make_presentation(pid, "No Conclusion")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")
        result = wr.validate_for_render(pres_id)
        self.assertTrue(result["valid"])
        self.assertTrue(any("conclusion" in w.lower() for w in result["warnings"]))

    def test_rejected_slides_warning(self):
        pid = _make_project("Rejected")
        pres_id = _make_presentation(pid, "Rejected Slides")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding", status="rejected")
        result = wr.validate_for_render(pres_id)
        self.assertTrue(result["valid"])
        self.assertTrue(any("rejected" in w.lower() for w in result["warnings"]))


class ThemeResolutionTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_default_theme_returns_dict(self):
        theme = wr._resolve_theme()
        self.assertIsInstance(theme, dict)
        self.assertIn("primary_color", theme)
        self.assertIn("font_heading", theme)

    def test_unknown_theme_falls_back(self):
        theme = wr._resolve_theme("nonexistent_theme_xyz")
        self.assertIsInstance(theme, dict)
        self.assertIn("primary_color", theme)

    def test_hex_to_rgb_valid(self):
        rgb = wr._hex_to_rgb("5B2C9D")
        self.assertEqual(rgb[0], 0x5B)
        self.assertEqual(rgb[1], 0x2C)
        self.assertEqual(rgb[2], 0x9D)

    def test_hex_to_rgb_with_hash(self):
        rgb = wr._hex_to_rgb("#FF0000")
        self.assertEqual(rgb[0], 255)
        self.assertEqual(rgb[1], 0)
        self.assertEqual(rgb[2], 0)

    def test_hex_to_rgb_invalid_falls_back(self):
        rgb = wr._hex_to_rgb("xyz")
        self.assertEqual(rgb[0], 0x33)
        self.assertEqual(rgb[1], 0x33)
        self.assertEqual(rgb[2], 0x33)


class RenderReportTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_render_full_report(self):
        pid = _make_project("Render Full")
        pres_id = _make_presentation(pid, "Full Report Test")
        _make_slide(pres_id, 1, purpose="cover", title="Cover Page")
        _make_slide(pres_id, 2, purpose="executive_summary", title="Exec Summary",
                    narrative="This is the executive summary.")
        _make_slide(pres_id, 3, purpose="key_finding", title="Finding 1",
                    narrative="Key finding details.")
        _make_slide(pres_id, 4, purpose="recommendation", title="Rec 1",
                    narrative="We recommend X.")
        _make_slide(pres_id, 5, purpose="conclusion", title="Conclusion",
                    narrative="In conclusion.")

        result = wr.render_report(pres_id)
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "completed")
        self.assertIn("job_id", result)
        self.assertIn("output_path", result)
        self.assertGreater(result["file_size_bytes"], 0)
        self.assertGreater(result["section_count"], 0)
        self.assertGreater(result["word_count"], 0)
        self.assertTrue(os.path.isfile(result["output_path"]))

    def test_render_creates_job_and_document(self):
        pid = _make_project("Job+Doc")
        pres_id = _make_presentation(pid, "Job and Doc")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")

        result = wr.render_report(pres_id)
        job = store.get_word_job(result["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "completed")

        docs = store.list_word_documents(pres_id)
        self.assertGreater(len(docs), 0)

    def test_render_creates_metrics(self):
        pid = _make_project("Metrics")
        pres_id = _make_presentation(pid, "Metrics Test")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")

        result = wr.render_report(pres_id)
        metrics = store.get_word_metrics(result["job_id"])
        self.assertGreater(len(metrics), 0)
        section_names = [m["section_name"] for m in metrics]
        self.assertIn("cover", section_names)
        self.assertIn("key_findings", section_names)

    def test_render_creates_history(self):
        pid = _make_project("History")
        pres_id = _make_presentation(pid, "History Test")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")

        result = wr.render_report(pres_id)
        history = store.get_word_history(pres_id)
        actions = [h["action"] for h in history]
        self.assertIn("render_started", actions)
        self.assertIn("render_completed", actions)

    def test_render_invalid_presentation(self):
        result = wr.render_report(99999)
        self.assertIn("error", result)

    def test_render_rejected_slides_excluded(self):
        pid = _make_project("Rejected Excl")
        pres_id = _make_presentation(pid, "Rejected Slides")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding", status="rejected")
        _make_slide(pres_id, 3, purpose="key_finding", title="Good Finding")

        result = wr.render_report(pres_id)
        self.assertEqual(result["status"], "completed")

    def test_render_version_increments(self):
        pid = _make_project("Version")
        pres_id = _make_presentation(pid, "Version Test")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")

        r1 = wr.render_report(pres_id)
        r2 = wr.render_report(pres_id)
        self.assertEqual(r1["version"], 1)
        self.assertEqual(r2["version"], 2)


class RenderSectionTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_render_single_section(self):
        pid = _make_project("Section")
        pres_id = _make_presentation(pid, "Section Test")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")

        result = wr.render_section(pres_id, "key_findings")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["section"], "key_findings")
        self.assertTrue(os.path.isfile(result["output_path"]))

    def test_render_unknown_section(self):
        pid = _make_project("Bad Section")
        pres_id = _make_presentation(pid, "Bad Section")
        _make_slide(pres_id, 1, purpose="cover")

        result = wr.render_section(pres_id, "nonexistent_section")
        self.assertIn("error", result)

    def test_render_cover_section(self):
        pid = _make_project("Cover Section")
        pres_id = _make_presentation(pid, "Cover Test")
        _make_slide(pres_id, 1, purpose="cover", title="My Cover")

        result = wr.render_section(pres_id, "cover")
        self.assertEqual(result["status"], "completed")

    def test_render_methodology_section(self):
        pid = _make_project("Meth Section")
        pres_id = _make_presentation(pid, "Meth Test")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="methodology", title="Methods",
                    narrative="Our methodology description.")

        result = wr.render_section(pres_id, "methodology")
        self.assertEqual(result["status"], "completed")

    def test_render_each_valid_section(self):
        pid = _make_project("All Sections")
        pres_id = _make_presentation(pid, "All Sections")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="executive_summary")
        _make_slide(pres_id, 3, purpose="methodology")
        _make_slide(pres_id, 4, purpose="key_finding")
        _make_slide(pres_id, 5, purpose="opportunity")
        _make_slide(pres_id, 6, purpose="recommendation")
        _make_slide(pres_id, 7, purpose="conclusion")
        _make_slide(pres_id, 8, purpose="appendix")

        for sec in wr.SECTION_ORDER:
            result = wr.render_section(pres_id, sec)
            self.assertEqual(result["status"], "completed", f"Section {sec} failed")


class StatusAndDownloadTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_get_render_status(self):
        pid = _make_project("Status")
        pres_id = _make_presentation(pid, "Status Test")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")

        result = wr.render_report(pres_id)
        status = wr.get_render_status(result["job_id"])
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "completed")

    def test_get_render_status_not_found(self):
        result = wr.get_render_status("nonexistent-job-id")
        self.assertIsNone(result)

    def test_get_download_path(self):
        pid = _make_project("Download")
        pres_id = _make_presentation(pid, "Download Test")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")

        result = wr.render_report(pres_id)
        path = wr.get_download_path(result["job_id"])
        self.assertIsNotNone(path)
        self.assertTrue(os.path.isfile(path))

    def test_get_download_path_not_found(self):
        path = wr.get_download_path("nonexistent-job-id")
        self.assertIsNone(path)


class RenderSummaryTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_summary_empty(self):
        pid = _make_project("Empty Summary")
        pres_id = _make_presentation(pid, "Empty Summary")
        _make_slide(pres_id, 1, purpose="cover")

        summary = wr.get_render_summary(pres_id)
        self.assertEqual(summary["total_renders"], 0)
        self.assertEqual(summary["total_jobs"], 0)
        self.assertIsNone(summary["latest_job"])

    def test_summary_after_render(self):
        pid = _make_project("Summary After")
        pres_id = _make_presentation(pid, "Summary After")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")

        wr.render_report(pres_id)
        summary = wr.get_render_summary(pres_id)
        self.assertEqual(summary["total_renders"], 1)
        self.assertGreaterEqual(summary["total_jobs"], 1)
        self.assertIsNotNone(summary["latest_job"])
        self.assertTrue(summary["has_download"])


class ThemesListTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_list_themes(self):
        themes = wr.list_themes()
        self.assertIsInstance(themes, list)


class ContentBlockRenderingTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_slide_with_content_blocks(self):
        pid = _make_project("Content Blocks")
        pres_id = _make_presentation(pid, "Content Blocks")
        _make_slide(pres_id, 1, purpose="cover")

        blocks = json.dumps([
            {"type": "narrative", "content": "Some narrative text."},
            {"type": "quote", "content": "A wise quote", "label": "Author"},
            {"type": "metrics", "content": "Revenue: 42%", "label": "Revenue Growth"},
            {"type": "bullets", "content": "Point A\nPoint B\nPoint C"},
            {"type": "source", "content": "Source: Research Paper 2024"},
        ])
        store.create_pc_slide(
            pres_id, slide_number=2, slide_purpose="key_finding",
            title="Rich Content", narrative="Main narrative.",
            content_blocks_json=blocks, status="approved",
        )

        result = wr.render_report(pres_id)
        self.assertEqual(result["status"], "completed")
        self.assertGreater(result["word_count"], 10)

    def test_slide_with_table_block(self):
        pid = _make_project("Table Block")
        pres_id = _make_presentation(pid, "Table Block")
        _make_slide(pres_id, 1, purpose="cover")

        table_data = json.dumps({
            "headers": ["Category", "Score", "Trend"],
            "rows": [
                ["Social Media", "85", "Up"],
                ["Traditional PR", "72", "Flat"],
                ["Digital Marketing", "91", "Up"],
            ],
        })
        blocks = json.dumps([{"type": "table", "content": table_data, "label": "Performance"}])
        store.create_pc_slide(
            pres_id, slide_number=2, slide_purpose="key_finding",
            title="Table Test", content_blocks_json=blocks, status="approved",
        )

        result = wr.render_report(pres_id)
        self.assertEqual(result["status"], "completed")

    def test_slide_with_chart_block(self):
        pid = _make_project("Chart Block")
        pres_id = _make_presentation(pid, "Chart Block")
        _make_slide(pres_id, 1, purpose="cover")

        chart_data = json.dumps({
            "chart_type": "bar",
            "categories": ["Q1", "Q2", "Q3", "Q4"],
            "values": [100, 150, 130, 180],
        })
        blocks = json.dumps([{"type": "chart", "content": chart_data, "label": "Quarterly Revenue"}])
        store.create_pc_slide(
            pres_id, slide_number=2, slide_purpose="key_finding",
            title="Chart Test", content_blocks_json=blocks, status="approved",
        )

        result = wr.render_report(pres_id)
        self.assertEqual(result["status"], "completed")

    def test_slide_with_evidence_panel(self):
        pid = _make_project("Evidence Panel")
        pres_id = _make_presentation(pid, "Evidence Panel")
        _make_slide(pres_id, 1, purpose="cover")

        blocks = json.dumps([
            {"type": "evidence_panel", "content": "Survey data from 500 respondents", "label": "Primary Research"},
        ])
        store.create_pc_slide(
            pres_id, slide_number=2, slide_purpose="key_finding",
            title="Evidence Test", content_blocks_json=blocks, status="approved",
        )

        result = wr.render_report(pres_id)
        self.assertEqual(result["status"], "completed")


class WordStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import time
        time.sleep(0.5)
        _init_db()
        cls.pid = _make_project("Store Test")
        cls.pres_id = _make_presentation(cls.pid, "Store Test Pres")

    def test_create_and_get_word_job(self):
        import uuid
        job_id = f"twj-{uuid.uuid4().hex[:8]}"
        store.create_word_job(job_id, self.pres_id, job_type="full", theme_id="hunter_default")
        job = store.get_word_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job["id"], job_id)
        self.assertEqual(job["job_type"], "full")
        self.assertEqual(job["status"], "pending")

    def test_update_word_job(self):
        import uuid
        job_id = f"twj-{uuid.uuid4().hex[:8]}"
        store.create_word_job(job_id, self.pres_id, job_type="full")
        store.update_word_job(job_id, status="running", progress_pct=50)
        job = store.get_word_job(job_id)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["progress_pct"], 50)

    def test_list_word_jobs(self):
        import uuid
        store.create_word_job(f"twj-l1-{uuid.uuid4().hex[:6]}", self.pres_id, job_type="full")
        store.create_word_job(f"twj-l2-{uuid.uuid4().hex[:6]}", self.pres_id, job_type="section")
        jobs = store.list_word_jobs(self.pres_id)
        self.assertGreaterEqual(len(jobs), 2)

    def test_create_word_document(self):
        import uuid
        doc_id = store.create_word_document(
            f"twj-d-{uuid.uuid4().hex[:6]}", self.pres_id, "/tmp/test.docx",
            version=1, output_size_bytes=1024,
            section_count=5, word_count=500,
            theme_id="hunter_default", render_duration_ms=100,
        )
        self.assertIsNotNone(doc_id)

    def test_list_word_documents(self):
        import uuid
        store.create_word_document(f"twj-ld-{uuid.uuid4().hex[:6]}", self.pres_id, "/tmp/a.docx")
        docs = store.list_word_documents(self.pres_id)
        self.assertGreaterEqual(len(docs), 1)

    def test_add_word_metric(self):
        import uuid
        jid = f"twj-m-{uuid.uuid4().hex[:6]}"
        store.add_word_metric(jid, "cover", 0, duration_ms=10)
        metrics = store.get_word_metrics(jid)
        self.assertGreaterEqual(len(metrics), 1)

    def test_add_word_history(self):
        import uuid
        store.add_word_history(self.pres_id, f"twj-h-{uuid.uuid4().hex[:6]}", "render_started",
                               actor="test", details={"x": 1})
        history = store.get_word_history(self.pres_id)
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(history[0]["action"], "render_started")


class SectionOrderTest(unittest.TestCase):
    def setUp(self):
        _init_db()

    def test_section_order_has_all(self):
        self.assertEqual(len(wr.SECTION_ORDER), 10)
        self.assertIn("cover", wr.SECTION_ORDER)
        self.assertIn("appendix", wr.SECTION_ORDER)

    def test_section_order_contains_key_sections(self):
        for sec in ["cover", "executive_summary", "key_findings", "recommendations", "conclusion"]:
            self.assertIn(sec, wr.SECTION_ORDER, f"Missing section: {sec}")

    def test_purpose_mapping(self):
        self.assertEqual(wr.PURPOSE_TO_SECTION["cover"], "cover")
        self.assertEqual(wr.PURPOSE_TO_SECTION["recommendation"], "recommendations")
        self.assertEqual(wr.PURPOSE_TO_SECTION["trend"], "key_findings")
        self.assertIsNone(wr.PURPOSE_TO_SECTION["divider"])


class HelperFunctionTest(unittest.TestCase):
    def test_extract_chart_data_empty(self):
        data = wr._extract_chart_data([], {})
        self.assertEqual(data["categories"], [])
        self.assertEqual(data["values"], [])

    def test_extract_chart_data_from_metrics(self):
        blocks = [
            {"type": "metrics", "content": "Revenue: 42"},
            {"type": "metrics", "content": "Growth: 15"},
        ]
        data = wr._extract_chart_data(blocks, {})
        self.assertEqual(len(data["categories"]), 2)
        self.assertEqual(data["categories"][0], "Revenue")
        self.assertEqual(data["values"][0], 42.0)

    def test_collect_evidence_refs(self):
        slides = [
            {"evidence_ids_json": [1, 2, 3]},
            {"evidence_ids_json": [2, 3, 4]},
        ]
        refs = wr._collect_evidence_refs(slides)
        self.assertEqual(len(refs), 4)

    def test_collect_evidence_refs_json_string(self):
        slides = [{"evidence_ids_json": json.dumps([10, 20])}]
        refs = wr._collect_evidence_refs(slides)
        self.assertEqual(len(refs), 2)

    def test_valid_job_types(self):
        self.assertIn("full", wr.VALID_JOB_TYPES)
        self.assertIn("section", wr.VALID_JOB_TYPES)

    def test_valid_job_statuses(self):
        self.assertIn("completed", wr.VALID_JOB_STATUSES)
        self.assertIn("failed", wr.VALID_JOB_STATUSES)
        self.assertIn("running", wr.VALID_JOB_STATUSES)


class APIEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from agent.app.main import app
        cls.client = TestClient(app)
        _init_db()

    def test_render_missing_presentation(self):
        r = self.client.post("/api/intel/word-renderer/render",
                             json={"presentation_id": 99999})
        self.assertEqual(r.status_code, 400)

    def test_validate_endpoint(self):
        pid = _make_project("API Validate")
        pres_id = _make_presentation(pid, "API Validate")
        _make_slide(pres_id, 1, purpose="cover")
        r = self.client.post(f"/api/intel/word-renderer/validate/{pres_id}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("valid", data)

    def test_status_not_found(self):
        r = self.client.get("/api/intel/word-renderer/status/nonexistent-id")
        self.assertEqual(r.status_code, 404)

    def test_download_not_found(self):
        r = self.client.get("/api/intel/word-renderer/download/nonexistent-id")
        self.assertEqual(r.status_code, 404)

    def test_themes_endpoint(self):
        r = self.client.get("/api/intel/word-renderer/themes")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_summary_endpoint(self):
        pid = _make_project("API Summary")
        pres_id = _make_presentation(pid, "API Summary")
        _make_slide(pres_id, 1, purpose="cover")
        r = self.client.get(f"/api/intel/word-renderer/summary/{pres_id}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("total_renders", data)

    def test_jobs_endpoint(self):
        pid = _make_project("API Jobs")
        pres_id = _make_presentation(pid, "API Jobs")
        r = self.client.get(f"/api/intel/word-renderer/jobs/{pres_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_history_endpoint(self):
        pid = _make_project("API History")
        pres_id = _make_presentation(pid, "API History")
        r = self.client.get(f"/api/intel/word-renderer/history/{pres_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_render_section_unknown(self):
        pid = _make_project("API Unknown Sec")
        pres_id = _make_presentation(pid, "API Unknown Sec")
        _make_slide(pres_id, 1, purpose="cover")
        r = self.client.post(f"/api/intel/word-renderer/render-section/{pres_id}",
                             json={"section_name": "nonexistent"})
        self.assertEqual(r.status_code, 400)

    def test_render_full_via_api(self):
        pid = _make_project("API Full")
        pres_id = _make_presentation(pid, "API Full")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding", title="F1")
        r = self.client.post("/api/intel/word-renderer/render",
                             json={"presentation_id": pres_id})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "completed")
        self.assertIn("job_id", data)

    def test_download_after_render(self):
        pid = _make_project("API Download")
        pres_id = _make_presentation(pid, "API Download")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")
        r = self.client.post("/api/intel/word-renderer/render",
                             json={"presentation_id": pres_id})
        job_id = r.json()["job_id"]
        dr = self.client.get(f"/api/intel/word-renderer/download/{job_id}")
        self.assertEqual(dr.status_code, 200)
        self.assertIn("wordprocessingml", dr.headers.get("content-type", ""))

    def test_metrics_after_render(self):
        pid = _make_project("API Metrics")
        pres_id = _make_presentation(pid, "API Metrics")
        _make_slide(pres_id, 1, purpose="cover")
        _make_slide(pres_id, 2, purpose="key_finding")
        r = self.client.post("/api/intel/word-renderer/render",
                             json={"presentation_id": pres_id})
        job_id = r.json()["job_id"]
        mr = self.client.get(f"/api/intel/word-renderer/metrics/{job_id}")
        self.assertEqual(mr.status_code, 200)
        self.assertIsInstance(mr.json(), list)
        self.assertGreater(len(mr.json()), 0)


if __name__ == "__main__":
    unittest.main()
