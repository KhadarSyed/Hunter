"""Tests for Slide Intelligence: extraction, classification, project boundary
detection, style analysis, template detection, retrieval, storyline matching,
recommendation engine, manual corrections, and store CRUD."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import config
from agent.app import intelligence_store as store
from agent.app import slide_extractor as extractor
from agent.app import slide_retrieval as retrieval
from agent.app import slide_intelligence as si
from agent.app import evidence_library as elib
from agent.app import insight_generator as igen
from agent.app import storyline_builder as sbuilder


DEFAULT_OBJECTIVES = [
    {"objective_id": "RO1", "objective": "Understand trends", "title": "Trends",
     "priority": "high", "platforms": ["Reddit", "Twitter/X"]},
    {"objective_id": "RO2", "objective": "Compare brands", "title": "Brand Comparison",
     "priority": "medium", "platforms": ["Reddit"]},
]
DEFAULT_UNITS = [
    {"id": "EU1", "objective_id": "RO1", "recommended_method": "Theme Clustering"},
    {"id": "EU2", "objective_id": "RO2", "recommended_method": "Sentiment Analysis"},
]


class SITestCase(unittest.TestCase):
    """Common lifecycle + fixture helpers."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="si_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test_memory.db")
        store.init_intelligence_db()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _create_pres(self, filename="test.pptx", slide_count=10):
        pid = store.create_si_presentation(filename, f"/tmp/{filename}", 1024)
        store.update_si_presentation(pid, slide_count=slide_count)
        return pid

    def _create_slide(self, pres_id, slide_num, **overrides):
        fields = {
            "all_text": f"Slide {slide_num} content about brand trends.",
            "title_text": f"Slide {slide_num} Title",
            "body_text": "Some body text.",
            "shape_count": 5,
            "text_shape_count": 3,
            "chart_count": 0,
            "table_count": 0,
            "image_count": 0,
            "has_chart": False,
            "has_table": False,
            "has_image": False,
            "slide_purpose": "key_finding",
            "layout_type": "title_body",
            "visual_type": "text_only",
            "narrative_role": "finding",
            "report_type": "unknown",
            "data_density": "medium",
            "executive_suitability": "medium",
            "visual_complexity": "low",
            "classification_confidence": 0.7,
            "status": "processed",
        }
        fields.update(overrides)
        return store.create_si_slide(pres_id, slide_num, **fields)

    def _setup_storyline(self):
        """Full pipeline through to an approved storyline with nodes."""
        spec = {"commissioning_brand": {"name": "TestBrand"}, "project_name": "TestBrand"}
        pid = store.get_or_create_project(spec)
        plan = {
            "plan_summary": "Test plan",
            "research_objectives": DEFAULT_OBJECTIVES,
            "execution_units": DEFAULT_UNITS,
        }
        plan_id = store.save_research_plan(pid, plan, source="deterministic")
        store.approve_plan(plan_id, "test")
        run_id = store.create_execution_run(pid, plan_id, 2)
        store.update_execution_run(run_id, status="completed")
        for i in range(3):
            store.save_evidence(
                run_id, unit_id="EU1", objective_id="RO1",
                evidence_type="finding", method="Theme Clustering",
                platform="Reddit", source="Reddit Post", date="2026-03-01",
                text_excerpt=f"Evidence item {i} about consumer trends finding {i}.",
                metrics={"likes": i, "url": f"http://example.com/si-{i}"},
                confidence="high", rationale="Test.",
            )
        elib.ingest_evidence(pid, run_id)
        items = store.list_library_items(pid)
        elib.bulk_review([it["id"] for it in items], "accepted", "test")
        igen.generate_insights(pid)
        for ins in store.list_insights(pid):
            igen.review_insight(ins["id"], "approved", "test")
        result = sbuilder.generate_storyline(pid)
        return pid, result["storyline_id"]


# ─── Store CRUD ────────────────────────────────────────────────────────────

class TestSIStore(SITestCase):
    def test_create_presentation(self):
        pid = self._create_pres()
        pres = store.get_si_presentation(pid)
        self.assertIsNotNone(pres)
        self.assertEqual(pres["filename"], "test.pptx")
        self.assertEqual(pres["status"], "pending")

    def test_list_presentations(self):
        self._create_pres("a.pptx")
        self._create_pres("b.pptx")
        lst = store.list_si_presentations()
        self.assertEqual(len(lst), 2)

    def test_update_presentation(self):
        pid = self._create_pres()
        store.update_si_presentation(pid, status="completed", processed_count=10)
        pres = store.get_si_presentation(pid)
        self.assertEqual(pres["status"], "completed")
        self.assertEqual(pres["processed_count"], 10)

    def test_delete_presentation_cascades(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        store.add_si_processing_log(pid, "test", "ok")
        store.delete_si_presentation(pid)
        self.assertIsNone(store.get_si_presentation(pid))
        self.assertIsNone(store.get_si_slide(sid))

    def test_create_and_get_slide(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1, has_chart=True)
        slide = store.get_si_slide(sid)
        self.assertIsNotNone(slide)
        self.assertTrue(slide["has_chart"])
        self.assertFalse(slide["is_excluded"])

    def test_list_slides_filtered(self):
        pid = self._create_pres()
        self._create_slide(pid, 1, slide_purpose="cover")
        self._create_slide(pid, 2, slide_purpose="key_finding")
        self._create_slide(pid, 3, slide_purpose="key_finding")
        covers = store.list_si_slides(pid, slide_purpose="cover")
        self.assertEqual(len(covers), 1)
        findings = store.list_si_slides(pid, slide_purpose="key_finding")
        self.assertEqual(len(findings), 2)

    def test_update_slide(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        store.update_si_slide(sid, slide_purpose="executive_summary", is_excluded=True)
        slide = store.get_si_slide(sid)
        self.assertEqual(slide["slide_purpose"], "executive_summary")
        self.assertTrue(slide["is_excluded"])

    def test_delete_slide_cascades(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        store.add_si_correction(sid, "purpose", "key_finding")
        store.delete_si_slide(sid)
        self.assertIsNone(store.get_si_slide(sid))
        self.assertEqual(len(store.get_si_corrections(sid)), 0)

    def test_count_slides(self):
        pid = self._create_pres()
        self._create_slide(pid, 1, slide_purpose="cover")
        self._create_slide(pid, 2, slide_purpose="cover")
        self._create_slide(pid, 3, slide_purpose="key_finding")
        self.assertEqual(store.count_si_slides(pid), 3)
        self.assertEqual(store.count_si_slides(pid, slide_purpose="cover"), 2)

    def test_search_slides(self):
        pid = self._create_pres()
        self._create_slide(pid, 1, all_text="Consumer trends in snacking")
        self._create_slide(pid, 2, all_text="Competitive landscape analysis")
        results = store.list_si_slides(pid, search="snacking")
        self.assertEqual(len(results), 1)


# ─── Template Families ─────────────────────────────────────────────────────

class TestTemplateStore(SITestCase):
    def test_create_template_family(self):
        fid = store.create_si_template_family("Executive Summary", "dashboard", "kpi")
        family = store.get_si_template_family(fid)
        self.assertEqual(family["family_name"], "Executive Summary")
        self.assertFalse(family["is_approved"])

    def test_add_template_member(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        fid = store.create_si_template_family("Test Family")
        mid = store.add_si_template_member(fid, sid, is_representative=True)
        members = store.get_si_template_members(fid)
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]["slide_id"], sid)

    def test_update_template_family(self):
        fid = store.create_si_template_family("Test")
        store.update_si_template_family(fid, is_approved=True, member_count=5)
        family = store.get_si_template_family(fid)
        self.assertTrue(family["is_approved"])
        self.assertEqual(family["member_count"], 5)

    def test_delete_template_family_cascades(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        fid = store.create_si_template_family("Test")
        store.add_si_template_member(fid, sid)
        store.delete_si_template_family(fid)
        self.assertIsNone(store.get_si_template_family(fid))


# ─── Detected Projects ────────────────────────────────────────────────────

class TestDetectedProjects(SITestCase):
    def test_create_detected_project(self):
        pid = self._create_pres()
        dpid = store.create_si_detected_project(pid, 1, 20,
                                                  project_name="Test",
                                                  client_name="Client A",
                                                  confidence=0.8)
        projects = store.list_si_detected_projects(pid)
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["client_name"], "Client A")

    def test_update_detected_project(self):
        pid = self._create_pres()
        dpid = store.create_si_detected_project(pid, 1, 20)
        store.update_si_detected_project(dpid, client_name="New Client", is_confirmed=True)
        projects = store.list_si_detected_projects(pid)
        self.assertEqual(projects[0]["client_name"], "New Client")


# ─── Style Patterns ───────────────────────────────────────────────────────

class TestStylePatterns(SITestCase):
    def test_add_style_pattern(self):
        pid = self._create_pres()
        spid = store.add_si_style_pattern("footer", "Footer pattern",
                                            {"pattern": "Source: |"}, pid, frequency=5)
        patterns = store.list_si_style_patterns(pid, pattern_type="footer")
        self.assertEqual(len(patterns), 1)
        self.assertIsInstance(patterns[0]["pattern_data"], dict)


# ─── Processing Logs ──────────────────────────────────────────────────────

class TestProcessingLogs(SITestCase):
    def test_add_and_get_logs(self):
        pid = self._create_pres()
        store.add_si_processing_log(pid, "extract", "ok", slide_number=1,
                                      message="Extracted slide 1", duration_ms=15.5)
        logs = store.get_si_processing_logs(pid)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["step"], "extract")


# ─── Manual Corrections ──────────────────────────────────────────────────

class TestCorrections(SITestCase):
    def test_add_correction(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        cid = store.add_si_correction(sid, "slide_purpose", "executive_summary",
                                        old_value="key_finding")
        corrections = store.get_si_corrections(sid)
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]["new_value"], "executive_summary")

    def test_update_metadata_with_correction(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1, slide_purpose="key_finding")
        result = si.update_slide_metadata(sid, {"slide_purpose": "executive_summary"})
        self.assertIn("slide_purpose", result["fields_updated"])
        corrections = store.get_si_corrections(sid)
        self.assertEqual(len(corrections), 1)


# ─── Embeddings ───────────────────────────────────────────────────────────

class TestEmbeddings(SITestCase):
    def test_save_and_get_embedding(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        blob = b"\x00" * 128
        store.save_si_embedding(sid, blob)
        retrieved = store.get_si_embedding(sid)
        self.assertEqual(retrieved, blob)

    def test_get_all_embeddings(self):
        pid = self._create_pres()
        s1 = self._create_slide(pid, 1)
        s2 = self._create_slide(pid, 2)
        store.save_si_embedding(s1, b"\x01" * 64)
        store.save_si_embedding(s2, b"\x02" * 64)
        all_emb = store.get_all_si_embeddings()
        self.assertEqual(len(all_emb), 2)


# ─── Classification ───────────────────────────────────────────────────────

class TestClassification(SITestCase):
    def test_classify_cover(self):
        data = {"title_text": "Hunter PR Research Client", "body_text": "",
                "all_text": "Hunter PR Research Client", "shape_count": 3,
                "text_shape_count": 2, "has_chart": False, "has_table": False,
                "chart_count": 0, "table_count": 0, "image_count": 0,
                "_chart_types": [], "_shape_positions": []}
        result = extractor._classify_slide(data)
        self.assertEqual(result["slide_purpose"], "cover")

    def test_classify_toc(self):
        data = {"title_text": "Table of Contents", "body_text": "Section 1\nSection 2",
                "all_text": "Table of Contents Section 1 Section 2",
                "shape_count": 4, "text_shape_count": 3,
                "has_chart": False, "has_table": False,
                "chart_count": 0, "table_count": 0, "image_count": 0,
                "_chart_types": [], "_shape_positions": []}
        result = extractor._classify_slide(data)
        self.assertEqual(result["slide_purpose"], "table_of_contents")

    def test_classify_scope(self):
        data = {"title_text": "Objective & Scope", "body_text": "Research scope details",
                "all_text": "Objective & Scope Research scope details",
                "shape_count": 5, "text_shape_count": 3,
                "has_chart": False, "has_table": False,
                "chart_count": 0, "table_count": 0, "image_count": 0,
                "_chart_types": [], "_shape_positions": []}
        result = extractor._classify_slide(data)
        self.assertEqual(result["slide_purpose"], "scope")

    def test_classify_chart_as_key_finding(self):
        data = {"title_text": "Analysis Results", "body_text": "Data shows...",
                "all_text": "Analysis Results Data shows...",
                "shape_count": 8, "text_shape_count": 4,
                "has_chart": True, "has_table": False,
                "chart_count": 1, "table_count": 0, "image_count": 0,
                "_chart_types": ["bar_chart"], "_shape_positions": []}
        result = extractor._classify_slide(data)
        self.assertEqual(result["slide_purpose"], "key_finding")
        self.assertEqual(result["visual_type"], "bar_chart")

    def test_classify_layout_dashboard(self):
        data = {"title_text": "Dashboard", "body_text": "Metrics",
                "all_text": "Dashboard Metrics", "shape_count": 15,
                "text_shape_count": 8, "has_chart": True, "has_table": True,
                "chart_count": 3, "table_count": 1, "image_count": 0,
                "_chart_types": ["bar_chart", "line_chart", "pie"],
                "_shape_positions": [(0, 0, 100, 100)] * 15}
        result = extractor._classify_slide(data)
        self.assertEqual(result["layout_type"], "dashboard")

    def test_classify_recommendation(self):
        data = {"title_text": "Recommendations", "body_text": "Next steps for the brand",
                "all_text": "Recommendations Next steps for the brand",
                "shape_count": 5, "text_shape_count": 3,
                "has_chart": False, "has_table": False,
                "chart_count": 0, "table_count": 0, "image_count": 0,
                "_chart_types": [], "_shape_positions": []}
        result = extractor._classify_slide(data)
        self.assertEqual(result["slide_purpose"], "recommendation")

    def test_classify_narrative_role(self):
        data = {"title_text": "Summary", "body_text": "", "all_text": "Summary",
                "shape_count": 3, "text_shape_count": 2,
                "slide_purpose": "executive_summary",
                "has_chart": False, "has_table": False,
                "chart_count": 0, "table_count": 0, "image_count": 0,
                "_chart_types": [], "_shape_positions": []}
        role = extractor._classify_narrative_role(data)
        self.assertEqual(role, "summary")

    def test_data_density(self):
        low = {"chart_count": 0, "table_count": 0, "text_shape_count": 2}
        high = {"chart_count": 3, "table_count": 2, "text_shape_count": 8}
        self.assertEqual(extractor._classify_data_density(low), "low")
        self.assertEqual(extractor._classify_data_density(high), "high")


# ─── Project Boundary Detection ───────────────────────────────────────────

class TestProjectBoundaries(SITestCase):
    def test_detect_boundaries(self):
        slides = [
            {"slide_number": 1, "slide_purpose": "cover", "title_text": "Rich / CarMax"},
            {"slide_number": 2, "slide_purpose": "scope", "title_text": "Objective & Scope"},
            {"slide_number": 10, "slide_purpose": "key_finding", "title_text": "Key Data"},
            {"slide_number": 11, "slide_purpose": "cover", "title_text": "Lila / Task Rabbit"},
            {"slide_number": 12, "slide_purpose": "scope", "title_text": "Objective & Scope"},
            {"slide_number": 20, "slide_purpose": "conclusion", "title_text": "Conclusion"},
        ]
        pid = self._create_pres()
        projects = extractor._detect_project_boundaries(slides, pid)
        self.assertEqual(len(projects), 2)
        self.assertEqual(projects[0]["analyst_name"], "Rich")
        self.assertEqual(projects[0]["client_name"], "CarMax")
        self.assertEqual(projects[1]["analyst_name"], "Lila")

    def test_parse_client_brand(self):
        client, brand = extractor._parse_client_brand("IRS Direct File (TurboTax)")
        self.assertEqual(client, "IRS Direct File")
        self.assertEqual(brand, "TurboTax")


# ─── Retrieval ─────────────────────────────────────────────────────────────

class TestRetrieval(SITestCase):
    def test_retrieve_for_node(self):
        _, storyline_id = self._setup_storyline()
        pid = self._create_pres()
        self._create_slide(pid, 1, slide_purpose="key_finding", layout_type="chart_led",
                           visual_type="bar_chart", all_text="Brand trends consumer analysis")
        self._create_slide(pid, 2, slide_purpose="executive_summary", layout_type="dashboard",
                           all_text="Executive summary of findings")
        self._create_slide(pid, 3, slide_purpose="recommendation", layout_type="text_led",
                           all_text="Recommendations for next steps")
        nodes = store.list_story_nodes(storyline_id)
        self.assertGreater(len(nodes), 0)
        result = retrieval.retrieve_for_node(nodes[0]["id"], top_k=5)
        self.assertNotIn("error", result)
        self.assertIn("results", result)

    def test_retrieve_nonexistent_node(self):
        result = retrieval.retrieve_for_node(99999)
        self.assertIn("error", result)

    def test_text_similarity(self):
        sim = retrieval._text_similarity("brand health consumer trends",
                                          "consumer brand perception trends")
        self.assertGreater(sim, 0.2)

    def test_diversity_selection(self):
        scored = [
            ({"slide_purpose": "key_finding", "layout_type": "chart_led", "client": "A"}, 0.9),
            ({"slide_purpose": "key_finding", "layout_type": "chart_led", "client": "A"}, 0.85),
            ({"slide_purpose": "key_finding", "layout_type": "chart_led", "client": "A"}, 0.80),
            ({"slide_purpose": "trend", "layout_type": "text_led", "client": "B"}, 0.75),
            ({"slide_purpose": "sentiment", "layout_type": "dashboard", "client": "C"}, 0.70),
        ]
        selected = retrieval._ensure_diversity(scored, 3)
        self.assertEqual(len(selected), 3)


# ─── Storyline Matching ──────────────────────────────────────────────────

class TestStorylineMatching(SITestCase):
    def test_match_storyline(self):
        _, storyline_id = self._setup_storyline()
        pid = self._create_pres()
        for i in range(5):
            self._create_slide(pid, i + 1,
                                slide_purpose=["key_finding", "executive_summary",
                                               "recommendation", "trend", "conclusion"][i],
                                all_text=f"Content about trends and analysis {i}")
        result = retrieval.match_storyline(storyline_id)
        self.assertNotIn("error", result)
        self.assertGreater(result["total_matches"], 0)
        self.assertGreater(len(result["node_results"]), 0)

    def test_match_nonexistent_storyline(self):
        result = retrieval.match_storyline(99999)
        self.assertIn("error", result)

    def test_storyline_match_store(self):
        _, storyline_id = self._setup_storyline()
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        nodes = store.list_story_nodes(storyline_id)
        mid = store.create_si_storyline_match(
            storyline_id, nodes[0]["id"], sid,
            similarity_score=0.8, match_reason="Purpose match",
            recommended_elements=["layout"], elements_not_to_reuse=["data"],
        )
        matches = store.get_si_storyline_matches(storyline_id=storyline_id)
        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0]["similarity_score"], 0.8)
        self.assertIsInstance(matches[0]["recommended_elements"], list)


# ─── Recommendation Engine ────────────────────────────────────────────────

class TestRecommendation(SITestCase):
    def test_recommend_for_node(self):
        _, storyline_id = self._setup_storyline()
        pid = self._create_pres()
        self._create_slide(pid, 1, slide_purpose="key_finding", layout_type="chart_led")
        nodes = store.list_story_nodes(storyline_id)
        result = retrieval.recommend_for_node(nodes[0]["id"])
        self.assertNotIn("error", result)
        self.assertIn("best_layout", result)
        self.assertIn("best_visual", result)
        self.assertIn("best_content_hierarchy", result)
        self.assertIsInstance(result["best_content_hierarchy"], list)
        self.assertIn("alternative_layouts", result)

    def test_recommend_nonexistent_node(self):
        result = retrieval.recommend_for_node(99999)
        self.assertIn("error", result)

    def test_content_hierarchy(self):
        h = retrieval._get_content_hierarchy("executive_summary")
        self.assertIsInstance(h, list)
        self.assertGreater(len(h), 0)

    def test_callout_style(self):
        s = retrieval._get_callout_style("executive_summary")
        self.assertIn("KPI", s)


# ─── Slide Intelligence Service ──────────────────────────────────────────

class TestSlideIntelligenceService(SITestCase):
    def test_dashboard_empty(self):
        result = si.get_dashboard()
        self.assertEqual(result["total_slides"], 0)
        self.assertEqual(result["presentation_count"], 0)

    def test_dashboard_with_data(self):
        pid = self._create_pres()
        self._create_slide(pid, 1, slide_purpose="key_finding")
        self._create_slide(pid, 2, slide_purpose="cover")
        result = si.get_dashboard()
        self.assertEqual(result["total_slides"], 2)
        self.assertEqual(result["presentation_count"], 1)
        self.assertIn("key_finding", result["purpose_distribution"])

    def test_exclude_include_slide(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        result = si.exclude_slide(sid)
        self.assertTrue(result["is_excluded"])
        slide = store.get_si_slide(sid)
        self.assertTrue(slide["is_excluded"])
        result = si.include_slide(sid)
        self.assertFalse(result["is_excluded"])

    def test_exclude_nonexistent(self):
        result = si.exclude_slide(99999)
        self.assertIn("error", result)

    def test_approve_template(self):
        fid = store.create_si_template_family("Test")
        result = si.approve_template(fid)
        self.assertTrue(result["is_approved"])

    def test_template_detail(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        fid = store.create_si_template_family("Test Family")
        store.add_si_template_member(fid, sid, is_representative=True)
        result = si.get_template_detail(fid)
        self.assertIn("family", result)
        self.assertIn("members", result)
        self.assertEqual(len(result["members"]), 1)

    def test_search_slides(self):
        pid = self._create_pres()
        self._create_slide(pid, 1, all_text="Consumer brand analysis")
        self._create_slide(pid, 2, all_text="Competitive landscape review")
        result = si.search_slides("consumer")
        self.assertEqual(result["count"], 1)

    def test_slide_detail(self):
        pid = self._create_pres()
        sid = self._create_slide(pid, 1)
        result = si.get_slide_detail(sid)
        self.assertIn("slide", result)
        self.assertIn("corrections", result)

    def test_retrieval_history(self):
        rid = store.add_si_retrieval_history("test query",
                                              [{"slide_id": 1, "score": 0.8}])
        self.assertGreater(rid, 0)


# ─── Duplicate Detection ─────────────────────────────────────────────────

class TestDuplicateDetection(SITestCase):
    def test_detect_duplicates(self):
        pid = self._create_pres()
        self._create_slide(pid, 1, all_text="This is a detailed analysis of consumer trends "
                           "in the snacking category across multiple demographics.")
        self._create_slide(pid, 2, all_text="This is a detailed analysis of consumer trends "
                           "in the snacking category across multiple demographics.")
        self._create_slide(pid, 3, all_text="Completely different content about competitive landscape.")
        result = si.detect_duplicates()
        self.assertGreaterEqual(result["total_groups"], 1)

    def test_no_duplicates(self):
        pid = self._create_pres()
        self._create_slide(pid, 1, all_text="Unique content about brand positioning alpha.")
        self._create_slide(pid, 2, all_text="Different analysis of market share beta.")
        result = si.detect_duplicates()
        self.assertEqual(result["total_groups"], 0)


if __name__ == "__main__":
    unittest.main()
